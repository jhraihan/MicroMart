import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect } from '@playwright/test'

/*
 * Shared plumbing for the admin end-to-end specs.
 *
 * Three rules these specs are built on, and the reasons they are worth the
 * plumbing:
 *
 * 1. **Every spec makes what it needs.** These tests run against the DEV
 *    database, and they mutate it -- orders advance, products deactivate,
 *    stock moves. A spec that reached for "the first order in the list" would
 *    be fighting the other specs, the demo data and yesterday's run all at
 *    once. So each one mints its own product, order or review through
 *    `manage.py e2e_fixture`, and nothing here asserts on a global count.
 *
 * 2. **The server is the assertion.** A green screen is not proof. Every
 *    spec that changes something reads it back through the API afterwards --
 *    the order's status and its OrderStatusLog rows, the variant's ledger,
 *    the product's rating -- because the UI is a report of the truth and not
 *    the truth itself.
 *
 * 3. **Signing in is not free.** DRF throttles the `auth` scope at 10/min
 *    (config/settings/base.py), keyed on the caller's IP for an anonymous
 *    request -- which every login is. A suite that posts to /auth/login/ in
 *    each of its dozen tests spends the whole budget on plumbing and then
 *    goes red on a 429 that means nothing about the product. So the sign-in
 *    FORM is driven where signing in is the thing under test (the admin
 *    sign-in spec, the staff and customer role specs), and everywhere else a
 *    session is established from a refresh cookie the fixture command mints
 *    with the same `issue_tokens` the login view calls. The app then boots
 *    through its real `/auth/refresh/` path, which is untethered from the
 *    throttle and is the path a returning admin actually takes.
 *
 * None of the specs use `serial` mode. Every test mints what it needs, so with
 * playwright.config.js's single worker they already run one at a time -- and a
 * failure then reports the remaining tests instead of skipping them, which is
 * the whole point of a suite like this.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const BACKEND = path.resolve(HERE, '../../../backend')

// macOS/Linux layout first, Windows second. This project has lived on both
// (docs/HANDOFF.md §2) and the harness should not be what breaks when it moves.
const PYTHON = [
  path.join(BACKEND, '.venv', 'bin', 'python'),
  path.join(BACKEND, '.venv', 'Scripts', 'python.exe'),
].find(existsSync)

const FENCE_OPEN = '<<<E2E_FIXTURE_JSON'
const FENCE_CLOSE = 'E2E_FIXTURE_JSON>>>'

/** The two accounts `manage.py seed_demo` creates. */
export const SEEDED_ADMIN = { email: 'admin@example.com', password: 'ChangeMe!2026' }
export const SEEDED_CUSTOMER = {
  email: 'shopper@example.com',
  password: 'Str0ngPass!2026',
}

/** The refresh cookie's name and path (config/settings/base.py). */
const REFRESH_COOKIE = 'refresh_token'
const REFRESH_COOKIE_PATH = '/api/v1/auth/'

/**
 * Run a `manage.py e2e_fixture` subcommand and return its JSON.
 *
 * Synchronous on purpose: a fixture is a precondition, so there is nothing to
 * overlap it with, and `await`ing a child process in every `beforeAll` buys
 * nothing but noise.
 */
export function fixture(kind, args = []) {
  if (!PYTHON) {
    throw new Error(
      `No virtualenv interpreter under ${BACKEND}/.venv. ` +
        'Create it and install requirements/dev.txt (docs/HANDOFF.md §2).',
    )
  }

  let output
  try {
    output = execFileSync(PYTHON, ['manage.py', 'e2e_fixture', kind, ...args], {
      cwd: BACKEND,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  } catch (error) {
    throw new Error(
      `e2e_fixture ${kind} failed.\n${error.stderr || ''}\n${error.stdout || ''}`,
    )
  }

  // Fenced rather than "the last line", because Django is entitled to print
  // warnings on the same stream and a fixture that fails to parse would look
  // like a product defect.
  const start = output.indexOf(FENCE_OPEN)
  const end = output.indexOf(FENCE_CLOSE)
  if (start === -1 || end === -1) {
    throw new Error(`e2e_fixture ${kind} printed no fixture payload:\n${output}`)
  }
  return JSON.parse(output.slice(start + FENCE_OPEN.length, end).trim())
}

/** A real JWT for an existing account, minted the way the login view mints one. */
export function tokensFor(email) {
  return fixture('token', ['--email', email])
}

/** Authorization header for a direct API call. */
export function bearer(access) {
  return { Authorization: `Bearer ${access}` }
}

/**
 * Put a signed-in session in the browser without touching the login endpoint.
 *
 * The refresh token goes into the same HttpOnly cookie the login response
 * would set; `App.jsx` then trades it for an access token on mount through
 * the ordinary `/auth/refresh/` bootstrap. Nothing is stubbed and no store is
 * poked at from the outside -- the app authenticates itself, exactly as it
 * does for a returning admin whose tab has been closed since yesterday.
 */
export async function useSession(page, baseURL, { refresh }) {
  const origin = (baseURL ?? 'http://127.0.0.1:5173').replace(/\/+$/, '')
  await page.context().addCookies([
    {
      name: REFRESH_COOKIE,
      value: refresh,
      url: `${origin}${REFRESH_COOKIE_PATH}`,
    },
  ])
}

/**
 * A label matcher that tolerates the required marker.
 *
 * `Input`/`Select`/`Textarea` append `<span aria-hidden>*</span>` inside the
 * `<label>` for a required field, so the label's TEXT is "Price (৳)*" even
 * though its accessible name is "Price (৳)". `getByLabel` matches the text, so
 * an exact string misses every required field -- and a loose substring is
 * worse, because "Price (৳)" is a substring of "Compare-at price (৳)" and
 * would match two controls. Anchoring with an optional asterisk is the only
 * form that is both tolerant and unambiguous.
 */
export function labelled(text) {
  const escaped = text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`^${escaped}\\s*\\*?$`)
}

/** Sign in through the real form. Used where signing in is the thing under test. */
export async function signInWithForm(page, { email, password }) {
  await page.goto('/login')
  await page.getByLabel(labelled('Email')).fill(email)
  await page.getByLabel(labelled('Password')).fill(password)

  const login = page.waitForResponse((response) =>
    response.url().includes('/api/v1/auth/login/'),
  )
  await page.getByRole('button', { name: 'Sign in' }).click()
  const response = await login

  // Read the refusal rather than letting it become a timeout on whatever
  // assertion comes next. A 429 from the auth throttle and a wrong password
  // fail identically from the outside, and they need very different fixes.
  expect(
    response.status(),
    `Sign-in as ${email} was refused: ${await response.text()}`,
  ).toBe(200)
  await expect(page).not.toHaveURL(/\/login$/)
}

/**
 * Collect everything the browser complained about.
 *
 * Two kinds of message reach `console.error` and they are not the same thing:
 *
 * * the application throwing or logging -- always a defect, always collected;
 * * Chromium narrating an HTTP status it did not like ("Failed to load
 *   resource: ... 401"). That is the network, not the page, and several of
 *   these specs provoke a refusal on purpose.
 *
 * So a failed-resource line is judged on its URL and status rather than
 * dropped wholesale. One is allowed by default and only one: the `401` from
 * `/auth/refresh/` that App.jsx's bootstrap earns on every anonymous page
 * load, which is the app correctly discovering it has no session. Anything
 * else has to be named by the test that expects it.
 */
const RESOURCE_FAILURE = /Failed to load resource.*status of (\d{3})/i

const ALWAYS_ALLOWED = [{ url: /\/api\/v1\/auth\/refresh\/$/, status: 401 }]

export function watchConsole(page, { allow = [] } = {}) {
  const permitted = [...ALWAYS_ALLOWED, ...allow]
  const problems = []

  page.on('console', (message) => {
    if (message.type() !== 'error') return
    const text = message.text()

    const failure = RESOURCE_FAILURE.exec(text)
    if (failure) {
      const status = Number(failure[1])
      const url = message.location()?.url ?? ''
      if (permitted.some((rule) => rule.status === status && rule.url.test(url))) return
      problems.push(`${status} from ${url}`)
      return
    }

    problems.push(`console.error: ${text}`)
  })

  page.on('pageerror', (error) => {
    problems.push(`pageerror: ${error.message}`)
  })

  return problems
}

/*
 * How `src/lib/money.js` renders a decimal string, restated here on purpose.
 *
 * Importing the app's own formatter would make the assertion circular: the
 * screen and the expectation would agree however either one changed. Written
 * out, a change to how money is displayed shows up here as a failing
 * assertion, which is the correct amount of noise for the currency on an
 * admin's revenue tile. The input stays a decimal string end to end; the
 * Number below is a formatting argument, never an arithmetic step (PRD §6.1).
 */
const BDT = new Intl.NumberFormat('en-BD', {
  style: 'currency',
  currency: 'BDT',
  currencyDisplay: 'narrowSymbol',
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
})

export function displayMoney(value) {
  return BDT.format(Number(value)).replace('BDT', '৳')
}

/** The admin surfaces that are `IsAdminRole` — staff must be refused all of them. */
export const ADMIN_ONLY_ENDPOINTS = [
  { method: 'get', path: '/api/v1/admin/dashboard/' },
  { method: 'get', path: '/api/v1/admin/products/' },
  { method: 'get', path: '/api/v1/admin/variants/' },
  { method: 'get', path: '/api/v1/admin/categories/' },
  { method: 'get', path: '/api/v1/admin/brands/' },
  { method: 'get', path: '/api/v1/admin/inventory/' },
  { method: 'get', path: '/api/v1/admin/coupons/' },
  { method: 'get', path: '/api/v1/admin/reviews/' },
  { method: 'get', path: '/api/v1/admin/customers/' },
  { method: 'get', path: '/api/v1/admin/settings/' },
]

/**
 * The writes, kept separate from the reads above.
 *
 * A gate that only covered GET would be a gate that let staff edit the
 * catalogue and move stock, so the refusal is proved on the methods that
 * change something too. DRF checks permissions before it validates a body,
 * which is why an empty payload is enough to prove the point.
 */
export const ADMIN_ONLY_WRITES = [
  { method: 'post', path: '/api/v1/admin/products/', data: {} },
  { method: 'post', path: '/api/v1/admin/inventory/adjust/', data: {} },
  { method: 'post', path: '/api/v1/admin/coupons/', data: {} },
  { method: 'patch', path: '/api/v1/admin/settings/', data: {} },
]
