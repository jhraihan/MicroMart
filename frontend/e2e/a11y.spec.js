import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'

import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/*
 * Accessibility guard (PRD §9.2, §9.3, §10).
 *
 * Every significant storefront and admin surface is scanned with axe at 360px
 * *and* at desktop width, then checked by hand for the four things axe cannot
 * see: horizontal overflow at 360px, a keyboard path through the buying and
 * fulfilment flows, focus trapping and restoration in dialogs, and form errors
 * that are bound to their field rather than only coloured red.
 *
 * **The rule set is never relaxed.** If this file grows a `disableRules`, an
 * axe `exclude`, or a rule tag removal, the fix went in the wrong place —
 * every violation this suite found was fixed in the component it came from.
 *
 * Two things about how it is wired are deliberate:
 *
 * 1. **Nothing here posts to /auth/login/.** DRF throttles the `auth` scope at
 *    10/min keyed on the caller's IP, so a suite that signs in per test spends
 *    its whole budget on plumbing and then goes red on a 429 that says nothing
 *    about accessibility. Sessions are established the way a returning visitor
 *    establishes one: a refresh cookie minted with the same `issue_tokens` the
 *    login view calls, which the app trades in through its real (unthrottled)
 *    /auth/refresh/ path on load. Browser contexts are then shared per
 *    (viewport, account), so there are four sessions in the whole run.
 * 2. **Fixtures are resolved from the running API, not hard-coded.** The
 *    product, category, order and wishlist row this file navigates to are
 *    whatever the database actually holds, so a reseed cannot rot the suite.
 *    They are created on first run if missing, so it is idempotent.
 *
 * Prerequisites are the two processes the app needs anyway (playwright.config
 * starts both if they are not already up), plus `manage.py seed_demo`, whose
 * two accounts this file signs in as.
 */

const BASE = (process.env.A11Y_BASE_URL || 'http://127.0.0.1:5173').replace(/\/+$/, '')
const API = `${BASE}/api/v1`

const SHOPPER = { email: 'shopper@example.com', password: 'Str0ngPass!2026' }
const ADMIN = { email: 'admin@example.com', password: 'ChangeMe!2026' }

/*
 * WCAG 2.1 AA is the bar in PRD §9.3. `best-practice` is included on purpose:
 * heading order, unique landmarks and list semantics are not AA failures on
 * paper, but they are exactly the defects that make a page unusable with a
 * screen reader, and they are cheap to keep clean.
 */
const RULE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']

const MOBILE = { width: 360, height: 780 }
const DESKTOP = { width: 1280, height: 900 }

// ---------------------------------------------------------------------------
// Sessions, minted rather than logged in — see note 1 in the header
// ---------------------------------------------------------------------------

/*
 * Refresh tokens minted server-side, one pool per account.
 *
 * `ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION` are both on, so a
 * refresh token is single-use: the app spends one on every load and the server
 * blacklists it. Rather than relying on each page handing the next one a
 * freshly rotated cookie -- which makes one slow or aborted load poison every
 * scan after it -- each navigation is given its own token from a pool minted
 * up front. A scan should fail because the page is inaccessible, never because
 * the session ahead of it rotated at the wrong moment.
 */
const REFRESH_COOKIE = 'refresh_token'
const REFRESH_COOKIE_PATH = '/api/v1/auth/'
// Comfortably more than the run needs: ~46 admin and ~16 shopper page
// loads across the four passes over SURFACES, plus the standalone tests.
const POOL_SIZE = 80

const MINT = `
import json
from django.contrib.auth import get_user_model
from apps.accounts.cookies import issue_tokens

User = get_user_model()
out = {}
for email in ${JSON.stringify([SHOPPER.email, ADMIN.email])}:
    user = User.objects.get(email=email)
    refresh_tokens = []
    access = None
    for _ in range(${POOL_SIZE}):
        refresh, access = issue_tokens(user)
        refresh_tokens.append(refresh)
    out[email] = {"refresh": refresh_tokens, "access": access}
print("A11Y_TOKENS " + json.dumps(out))
`

function mintTokens() {
  const backend = path.resolve(import.meta.dirname, '..', '..', 'backend')
  const python = [
    path.join(backend, '.venv', 'bin', 'python'),
    path.join(backend, '.venv', 'Scripts', 'python.exe'),
  ].find(existsSync)
  if (!python) {
    throw new Error(`No virtualenv interpreter under ${backend}/.venv (docs/HANDOFF.md §2).`)
  }

  const stdout = execFileSync(python, ['manage.py', 'shell', '-c', MINT], {
    cwd: backend,
    encoding: 'utf8',
    timeout: 120_000,
    maxBuffer: 16 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  // Django's shell prints a banner, so the payload is marked rather than
  // assumed to be the only thing on stdout.
  const line = stdout.split('\n').find((row) => row.startsWith('A11Y_TOKENS '))
  if (!line) throw new Error(`Token mint printed no A11Y_TOKENS line. Got:\n${stdout}`)
  return JSON.parse(line.slice('A11Y_TOKENS '.length))
}

// ---------------------------------------------------------------------------
// Fixtures. Top-level await so the surface list exists at collection time and
// every scan gets a name of its own in the report.
// ---------------------------------------------------------------------------

async function json(path, init) {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} → ${res.status} ${await res.text()}`)
  }
  return res.json()
}

async function resolveFixtures(accessToken) {
  const products = await json('/products/?in_stock=true&page_size=12')
  const listed = products.results ?? []
  if (!listed.length) throw new Error('The catalogue is empty. Run: manage.py seed_demo')

  // A product with more than one variant exercises the variant selector and
  // the "Choose options" card state as well as the plain detail layout.
  const chosen = listed.find((p) => p.variant_count > 1) ?? listed[0]
  const detail = await json(`/products/${chosen.slug}/`)
  const variant = (detail.variants ?? []).find((v) => v.in_stock) ?? detail.variants[0]

  /*
   * A product with photographs, so the gallery renders and the alt-text rules
   * below are checked against something rather than against an empty page.
   * Searched across the whole catalogue rather than the twelve rows above,
   * because whether the first page happens to carry a photo is an accident of
   * sort order.
   */
  const everything = await json('/products/?page_size=100')
  const illustrated = (everything.results ?? []).find((p) => p.primary_image) ?? null

  const categories = await json('/categories/')
  const category = categories.find((c) => c.product_count > 0) ?? categories[0]

  const headers = {
    Authorization: `Bearer ${accessToken}`,
    'Content-Type': 'application/json',
  }

  // --- An order to read back on the confirmation, history and detail screens ---
  let orders = await json('/orders/', { headers })
  if (!orders.results?.length) {
    const addresses = await json('/addresses/', { headers })
    if (!addresses.length) {
      throw new Error('The seeded shopper has no address. Run: manage.py seed_demo')
    }
    await json('/orders/', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        idempotency_key: `a11y-fixture-${Date.now()}`,
        payment_method: 'cod',
        address_id: (addresses.find((a) => a.is_default) ?? addresses[0]).id,
        email: SHOPPER.email,
        phone: addresses[0].phone,
        items: [{ variant_id: variant.id, quantity: 1 }],
        note: 'Fixture order for the accessibility suite.',
      }),
    })
    orders = await json('/orders/', { headers })
  }

  // --- Something saved, so the wishlist renders rows and not its empty state ---
  const wishlist = await json('/wishlist/', { headers })
  if (!wishlist.results?.length) {
    await json('/wishlist/', {
      method: 'POST',
      headers,
      body: JSON.stringify({ product_id: chosen.id }),
    })
  }

  return {
    productSlug: chosen.slug,
    productName: detail.name,
    variantId: variant.id,
    variantLabel: variant.option_label || 'Default',
    sku: variant.sku,
    unitPrice: variant.price,
    categorySlug: category.slug,
    orderReference: orders.results[0].reference,
    illustratedSlug: illustrated?.slug ?? null,
  }
}

let setupError = null
let tokens = {}
let fixtures = {
  productSlug: 'unknown',
  productName: 'unknown',
  variantId: 0,
  variantLabel: '',
  sku: '',
  unitPrice: '0.00',
  categorySlug: 'unknown',
  orderReference: 'unknown',
  illustratedSlug: null,
}
try {
  tokens = mintTokens()
  fixtures = await resolveFixtures(tokens[SHOPPER.email].access)
} catch (error) {
  setupError = error
}

test('the dev servers and seed data this suite needs are up', () => {
  expect(
    setupError &&
      `${setupError.message}\n\nStart Django on :8000 and Vite on :5173, then run manage.py seed_demo.`,
    'accessibility fixtures could not be resolved',
  ).toBeNull()
})

// ---------------------------------------------------------------------------
// Contexts, shared per (viewport, account) — four sessions for the whole run
// ---------------------------------------------------------------------------

const contexts = new Map()

async function contextFor(browser, viewport, account) {
  const key = `${viewport.width}|${account?.email ?? 'guest'}`
  if (contexts.has(key)) return contexts.get(key)

  const isPhone = viewport.width <= 480
  const context = await browser.newContext({
    viewport,
    isMobile: isPhone,
    hasTouch: isPhone,
    deviceScaleFactor: isPhone ? 3 : 1,
  })
  contexts.set(key, context)
  return context
}

/** Hand the next page load a session of its own. */
async function armSession(context, account) {
  if (!account) return
  const pool = tokens[account.email]?.refresh
  expect(
    pool?.length,
    `the ${account.email} token pool ran dry — raise POOL_SIZE in this file`,
  ).toBeGreaterThan(0)
  await context.addCookies([
    {
      name: REFRESH_COOKIE,
      value: pool.pop(),
      domain: new URL(BASE).hostname,
      path: REFRESH_COOKIE_PATH,
      httpOnly: true,
      secure: false,
      sameSite: 'Lax',
    },
  ])
}

test.afterAll(async () => {
  for (const context of contexts.values()) await context.close()
  contexts.clear()
})

// ---------------------------------------------------------------------------
// Assertions
// ---------------------------------------------------------------------------

/** A stable, readable list of what axe found, so a failure names the element. */
function summarise(violations) {
  return violations.flatMap((violation) =>
    violation.nodes.map(
      (node) =>
        `${violation.id} [${violation.impact}] ${node.target.join(' ')} — ${violation.help}` +
        (node.failureSummary
          ? `\n      ${node.failureSummary.replace(/\n/g, '\n      ')}`
          : ''),
    ),
  )
}

async function expectNoAxeViolations(page, label) {
  const results = await new AxeBuilder({ page }).withTags(RULE_TAGS).analyze()
  expect(summarise(results.violations), `axe violations on ${label}`).toEqual([])
}

/**
 * PRD §9.2: fully usable one-handed at 360px. A page that scrolls sideways is
 * not. Wide content (tables, spec sheets, the category strip) has to scroll
 * inside its own container, so the failure message names the offender.
 */
async function expectNoHorizontalScroll(page, label) {
  const report = await page.evaluate(() => {
    const doc = document.documentElement
    const limit = doc.clientWidth

    // An element inside an `overflow-x: auto` box is clipped by that box, so
    // it cannot widen the document however far right it reaches. Reporting it
    // would bury the one element that actually did.
    const inScroller = (el) => {
      for (let node = el.parentElement; node && node !== doc; node = node.parentElement) {
        const overflow = getComputedStyle(node).overflowX
        if (overflow === 'auto' || overflow === 'scroll' || overflow === 'hidden') return true
      }
      return false
    }

    const offenders = []
    for (const el of document.querySelectorAll('body *')) {
      const box = el.getBoundingClientRect()
      if (box.width === 0 && box.height === 0) continue
      if (box.right <= limit + 1) continue
      if (inScroller(el)) continue
      const classes =
        typeof el.className === 'string' && el.className.trim()
          ? `.${el.className.trim().split(/\s+/).slice(0, 4).join('.')}`
          : ''
      offenders.push(
        `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${classes}` +
          ` → left ${Math.round(box.left)}, right ${Math.round(box.right)}`,
      )
      if (offenders.length >= 6) break
    }
    return { scrollWidth: doc.scrollWidth, clientWidth: limit, offenders }
  })

  expect(
    report.scrollWidth,
    `${label} scrolls horizontally at 360px` +
      ` (scrollWidth ${report.scrollWidth} > clientWidth ${report.clientWidth}).` +
      `\nOverflowing elements:\n  ${report.offenders.join('\n  ')}`,
  ).toBeLessThanOrEqual(report.clientWidth)
}

// ---------------------------------------------------------------------------
// The surfaces. `ready` keeps a scan off a loading skeleton, which would
// otherwise make contrast results depend on how fast the API answered.
// ---------------------------------------------------------------------------

/** Seed the persisted guest cart so /cart and /checkout have something to show. */
async function seedGuestCart(page) {
  await page.addInitScript(
    (payload) => window.localStorage.setItem('guest-cart', payload),
    JSON.stringify({
      state: {
        items: [
          {
            variantId: fixtures.variantId,
            productSlug: fixtures.productSlug,
            productName: fixtures.productName,
            variantLabel: fixtures.variantLabel,
            sku: fixtures.sku,
            unitPrice: fixtures.unitPrice,
            image: null,
            quantity: 2,
            maxStock: 5,
          },
        ],
      },
      version: 1,
    }),
  )
}

const SURFACES = [
  { name: 'home', path: '/', ready: 'h2:has-text("Shop by category")' },
  {
    name: 'category listing',
    path: `/c/${fixtures.categorySlug}`,
    ready: 'nav[aria-label="Breadcrumb"]',
  },
  { name: 'search results', path: '/search?q=pro', ready: 'nav[aria-label="Breadcrumb"]' },
  {
    name: 'product detail',
    path: `/p/${fixtures.productSlug}`,
    ready: 'button:has-text("Add to cart"), button:has-text("Out of stock")',
  },
  {
    name: 'cart',
    path: '/cart',
    before: seedGuestCart,
    ready: 'section[aria-label="Cart items"]',
  },
  {
    name: 'checkout',
    path: '/checkout',
    before: seedGuestCart,
    ready: 'h2:has-text("Review & pay")',
  },
  {
    name: 'checkout with a delivery zone resolved',
    path: '/checkout',
    before: seedGuestCart,
    ready: 'h2:has-text("Review & pay")',
    // Division and district populate the delivery panel and the payment
    // picker, which are otherwise placeholder prose and never get scanned.
    after: async (page) => {
      await page.getByLabel(/^Division/).selectOption('Dhaka')
      await page.getByLabel(/^District/).selectOption('Dhaka')
      await expect(page.getByRole('radio').first()).toBeVisible()
    },
  },
  { name: 'login', path: '/login', ready: 'form' },
  { name: 'register', path: '/register', ready: 'form' },
  {
    name: 'order confirmation',
    path: `/order/${fixtures.orderReference}`,
    auth: SHOPPER,
    ready: `text=${fixtures.orderReference}`,
  },
  {
    name: 'order history',
    path: '/orders',
    auth: SHOPPER,
    ready: 'h1:has-text("Your orders")',
  },
  {
    name: 'order detail',
    path: `/orders/${fixtures.orderReference}`,
    auth: SHOPPER,
    ready: 'h2:has-text("Items")',
  },
  { name: 'wishlist', path: '/wishlist', auth: SHOPPER, ready: 'h1' },
  { name: 'admin overview', path: '/admin', auth: ADMIN, ready: 'h1:has-text("Overview")' },
  { name: 'admin orders', path: '/admin/orders', auth: ADMIN, ready: 'table' },
  {
    name: 'admin order detail',
    path: `/admin/orders/${fixtures.orderReference}`,
    auth: ADMIN,
    ready: 'h1',
  },
  { name: 'admin product form', path: '/admin/products/new', auth: ADMIN, ready: 'form' },
  { name: 'admin products', path: '/admin/products', auth: ADMIN, ready: 'table' },
  { name: 'admin inventory', path: '/admin/inventory', auth: ADMIN, ready: 'table' },
  { name: 'admin coupons', path: '/admin/coupons', auth: ADMIN, ready: 'h1' },
  { name: 'admin reviews', path: '/admin/reviews', auth: ADMIN, ready: 'h1' },
  { name: 'admin settings', path: '/admin/settings', auth: ADMIN, ready: 'form' },

  /*
   * Dialogs get their own entries rather than being folded into the page they
   * open from: a Modal is a separate accessibility surface (its own label, its
   * own focus scope) and it is invisible to a scan of the page behind it.
   */
  {
    name: 'the mobile filter drawer, open',
    path: `/c/${fixtures.categorySlug}`,
    ready: 'nav[aria-label="Breadcrumb"]',
    // The Filters button is `lg:hidden`: this drawer only exists on a phone,
    // where the facet sidebar is not on screen.
    phoneOnly: true,
    after: async (page) => {
      await page.getByRole('button', { name: /^Filters/ }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
    },
  },
  {
    name: 'the admin cancel-order dialog, open',
    path: `/admin/orders/${fixtures.orderReference}`,
    auth: ADMIN,
    ready: 'h1',
    after: async (page) => {
      await page.getByRole('button', { name: /cancel order/i }).first().click()
      await expect(page.getByRole('dialog')).toBeVisible()
    },
  },
  {
    name: 'the admin courier dialog, open',
    path: `/admin/orders/${fixtures.orderReference}`,
    auth: ADMIN,
    ready: 'h1',
    after: async (page) => {
      /*
       * `Edit courier & tracking` only ever opens the form — every other
       * fulfilment button either transitions the order outright or does so as
       * soon as the form is saved, and an accessibility suite must not move a
       * real order down the pipeline to look at a dialog. When the fixture
       * order has no shipment yet the button is absent and this surface is
       * simply the page behind it, which is still worth scanning.
       */
      const opener = page.getByRole('button', { name: /edit courier/i })
      if (!(await opener.count())) return
      await opener.first().click()
      await expect(page.getByRole('dialog')).toBeVisible()
    },
  },
]

/** Open one surface in the right shared context and hand the page to `check`. */
async function onSurface(browser, viewport, surface, check) {
  const context = await contextFor(browser, viewport, surface.auth)
  await armSession(context, surface.auth)
  const page = await context.newPage()
  try {
    if (surface.before) await surface.before(page)
    await page.goto(`${BASE}${surface.path}`, { waitUntil: 'domcontentloaded' })
    await expect(page.locator(surface.ready).first()).toBeVisible({ timeout: 20_000 })
    if (surface.after) await surface.after(page)
    await check(page)
  } finally {
    await page.close()
  }
}

// ---------------------------------------------------------------------------
// 1. axe — every surface, both widths
// ---------------------------------------------------------------------------

for (const [label, viewport] of [
  ['360px', MOBILE],
  ['desktop', DESKTOP],
]) {
  test.describe(`axe at ${label}`, () => {
    test.skip(() => setupError !== null, 'fixtures unavailable')

    for (const surface of SURFACES) {
      if (surface.phoneOnly && viewport !== MOBILE) continue
      test(surface.name, async ({ browser }) => {
        await onSurface(browser, viewport, surface, (page) =>
          expectNoAxeViolations(page, `${surface.name} @ ${label}`),
        )
      })
    }
  })
}

// ---------------------------------------------------------------------------
// 2. No horizontal scroll at 360px (PRD §9.2) — axe cannot see this
// ---------------------------------------------------------------------------

test.describe('360px layout', () => {
  test.skip(() => setupError !== null, 'fixtures unavailable')

  for (const surface of SURFACES) {
    test(`${surface.name} does not scroll sideways`, async ({ browser }) => {
      await onSurface(browser, MOBILE, surface, (page) =>
        expectNoHorizontalScroll(page, surface.name),
      )
    })
  }

  test('a wide admin table scrolls inside its own container, not the page body', async ({
    browser,
  }) => {
    const surface = SURFACES.find((s) => s.name === 'admin orders')
    await onSurface(browser, MOBILE, surface, async (page) => {
      // The table being wider than the phone is fine — as long as the element
      // that scrolls is its own wrapper and not <body>.
      const scrolls = await page.evaluate(() => {
        const table = document.querySelector('table')
        let node = table?.parentElement
        while (node && node !== document.body) {
          const style = getComputedStyle(node)
          if (
            (style.overflowX === 'auto' || style.overflowX === 'scroll') &&
            node.scrollWidth > node.clientWidth
          ) {
            return true
          }
          node = node.parentElement
        }
        return false
      })
      expect(
        scrolls,
        'the admin orders table is not inside an overflow-x container',
      ).toBeTruthy()
      await expectNoHorizontalScroll(page, 'admin orders')
    })
  })
})

// ---------------------------------------------------------------------------
// 3. Touch targets are at least 44px (PRD §9.2, docs/HANDOFF.md §5)
//
// Not an axe rule at AA -- `target-size` is WCAG 2.2 -- but it is a bar this
// codebase is held to explicitly, and a 28px chevron beside a link is how a
// thumb ends up navigating away instead of expanding a menu.
//
// The rule enforced here is the one the components already state: **44px tall
// for everything**, and **44px wide as well when the control has no visible
// text**, because an icon-only button has nothing else to grow its hit area.
// Requiring 44px of width from a text link would mean padding the word "Home"
// out to a third of a phone screen, which helps nobody.
// ---------------------------------------------------------------------------

const MIN_TARGET = 44

async function expectTargetsAreThumbSized(page, label) {
  const undersized = await page.evaluate((min) => {
    const SELECTOR = [
      'a[href]',
      'button',
      'input:not([type="hidden"])',
      'select',
      'textarea',
      'summary',
      '[role="button"]',
      '[role="link"]',
      '[tabindex]:not([tabindex="-1"])',
    ].join(',')

    const describe = (el) => {
      const classes =
        typeof el.className === 'string' && el.className.trim()
          ? `.${el.className.trim().split(/\s+/).slice(0, 3).join('.')}`
          : ''
      const name = (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 40)
      return `${el.tagName.toLowerCase()}${classes} "${name}"`
    }

    const found = []
    for (const el of document.querySelectorAll(SELECTOR)) {
      // WCAG exempts inactive controls, and an aria-hidden node is not a
      // target at all.
      if (el.disabled || el.closest('[aria-hidden="true"]')) continue

      const style = getComputedStyle(el)
      if (style.visibility === 'hidden' || style.display === 'none') continue

      /*
       * A checkbox or radio is 16px by design; the label wrapping it is the
       * thing a thumb actually hits, so that is what gets measured.
       */
      const wrapper = el.closest('label')
      const measured = wrapper && wrapper.contains(el) ? wrapper : el
      const box = measured.getBoundingClientRect()
      if (box.width === 0 || box.height === 0) continue

      /*
       * WCAG 2.2 SC 2.5.8's "inline" exception: a link inside a run of text is
       * sized by the sentence it lives in, and padding it to 44px would break
       * the paragraph. Only links that flow inline are let through.
       */
      if (el.tagName === 'A' && style.display === 'inline') continue

      // Icon-only, i.e. nothing visible but a glyph: an "x", a chevron, an
      // arrow. `sr-only` text does not count -- it has no hit area.
      const visibleText = [...measured.childNodes]
        .map((node) =>
          node.nodeType === Node.TEXT_NODE
            ? node.textContent
            : node.nodeType === Node.ELEMENT_NODE && !node.classList?.contains('sr-only')
              ? node.textContent
              : '',
        )
        .join('')
        .trim()
      const needsWidth = visibleText.length <= 2

      if (box.height + 0.5 < min || (needsWidth && box.width + 0.5 < min)) {
        found.push(`${describe(el)} → ${Math.round(box.width)}×${Math.round(box.height)}`)
      }
      if (found.length >= 8) break
    }
    return found
  }, MIN_TARGET)

  expect(undersized, `${label} has interactive targets under ${MIN_TARGET}px`).toEqual([])
}

test.describe('touch targets at 360px', () => {
  test.skip(() => setupError !== null, 'fixtures unavailable')

  for (const surface of SURFACES) {
    test(`${surface.name} keeps every target thumb-sized`, async ({ browser }) => {
      await onSurface(browser, MOBILE, surface, (page) =>
        expectTargetsAreThumbSized(page, surface.name),
      )
    })
  }
})

// ---------------------------------------------------------------------------
// 4. Keyboard operability (PRD §9.3) — axe cannot see focus order or traps
// ---------------------------------------------------------------------------

/** Walk `steps` tab stops, asserting focus stays visible and keeps moving. */
async function tabThrough(page, steps, label) {
  const seen = []
  let repeats = 0

  for (let i = 0; i < steps; i += 1) {
    await page.keyboard.press('Tab')
    const state = await page.evaluate(() => {
      const el = document.activeElement
      if (!el || el === document.body) return null
      const box = el.getBoundingClientRect()
      return {
        tag: el.tagName.toLowerCase(),
        id: el.id,
        name:
          el.getAttribute('aria-label') ||
          el.getAttribute('name') ||
          el.textContent?.trim().slice(0, 40) ||
          '',
        visible: box.width > 0 && box.height > 0,
      }
    })
    if (!state) continue

    expect(state.visible, `${label}: focus landed on a zero-size ${state.tag}`).toBeTruthy()

    const key = `${state.tag}#${state.id}:${state.name}`
    repeats = seen.length && seen[seen.length - 1] === key ? repeats + 1 : 0
    expect(repeats, `${label}: focus stopped moving at ${key} — keyboard trap`).toBeLessThan(3)
    seen.push(key)
  }

  expect(seen.length, `${label}: nothing was reachable by keyboard`).toBeGreaterThan(3)
  return seen
}

/** Tab `rounds` times and assert focus never leaves the open dialog. */
async function expectFocusTrapped(page, rounds, label) {
  for (let i = 0; i < rounds; i += 1) {
    await page.keyboard.press('Tab')
    const inside = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]')
      return Boolean(dialog && dialog.contains(document.activeElement))
    })
    expect(inside, `focus escaped ${label}`).toBeTruthy()
  }
}

test.describe('keyboard', () => {
  test.skip(() => setupError !== null, 'fixtures unavailable')

  test('checkout is fully operable from the keyboard', async ({ browser }) => {
    // The zone-resolved variant on purpose: District is `disabled` until a
    // Division is chosen -- correct behaviour, and it keeps the control out of
    // the tab order -- and the payment radios only exist once the quote has
    // priced a zone. Walking the plain page would skip both.
    const surface = SURFACES.find((s) => s.name === 'checkout with a delivery zone resolved')
    await onSurface(browser, DESKTOP, surface, async (page) => {
      // `after` left focus on the District select; start the walk from the top.
      await page.evaluate(() => document.activeElement?.blur())
      const stops = await tabThrough(page, 60, 'checkout')
      const joined = stops.join('\n').toLowerCase()
      for (const field of ['email', 'phone', 'division', 'district', 'street']) {
        expect(joined, `checkout: never tabbed to the ${field} field`).toContain(field)
      }

      // Nothing may be reachable by pointer but not by keyboard.
      const unreachable = await page.evaluate(() =>
        [...document.querySelectorAll('a[href], button, input, select, textarea')]
          .filter(
            (el) => !el.disabled && el.tabIndex < 0 && el.getBoundingClientRect().width > 0,
          )
          .map((el) => el.tagName.toLowerCase() + (el.id ? `#${el.id}` : '')),
      )
      expect(unreachable, 'checkout has controls removed from the tab order').toEqual([])
    })
  })

  test('the admin fulfilment actions are reachable, and the dialog traps and restores focus', async ({
    browser,
  }) => {
    const surface = SURFACES.find((s) => s.name === 'admin order detail')
    await onSurface(browser, DESKTOP, surface, async (page) => {
      await tabThrough(page, 40, 'admin order detail')

      // A destructive transition opens a dialog. It must trap focus while
      // open and hand focus back to the button that opened it on close.
      const opener = page.getByRole('button', { name: /cancel order/i }).first()
      expect(
        await opener.count(),
        'the fixture order offers no destructive transition to test the dialog with',
      ).toBeGreaterThan(0)

      await opener.focus()
      await page.keyboard.press('Enter')
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      await expectFocusTrapped(page, 12, 'the confirmation dialog')

      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden()
      const restored = await page.evaluate(
        () => document.activeElement?.textContent?.trim() ?? '',
      )
      expect(
        restored,
        'focus was not restored to the control that opened the dialog',
      ).toMatch(/cancel order/i)
    })
  })

  test('the mobile filter drawer traps focus and restores it on close', async ({ browser }) => {
    const surface = SURFACES.find((s) => s.name === 'category listing')
    await onSurface(browser, MOBILE, surface, async (page) => {
      const trigger = page.getByRole('button', { name: /^Filters/ })
      await expect(trigger).toBeVisible()
      await trigger.focus()
      await page.keyboard.press('Enter')

      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await expectFocusTrapped(page, 15, 'the filter drawer')

      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden()
      const restored = await page.evaluate(
        () => document.activeElement?.textContent?.trim() ?? '',
      )
      expect(restored, 'focus was not restored to the Filters button').toMatch(/Filters/)
    })
  })

  test('the skip link is the first tab stop and becomes visible when focused', async ({
    browser,
  }) => {
    await onSurface(browser, DESKTOP, SURFACES[0], async (page) => {
      await page.keyboard.press('Tab')
      const first = await page.evaluate(() => ({
        text: document.activeElement?.textContent?.trim() ?? '',
        href: document.activeElement?.getAttribute('href') ?? '',
        onScreen: (document.activeElement?.getBoundingClientRect().left ?? -9999) > -100,
      }))
      expect(first.text).toMatch(/skip to main content/i)
      expect(first.href).toBe('#main')
      expect(first.onScreen, 'the skip link stays off-screen when focused').toBeTruthy()
    })
  })
})

// ---------------------------------------------------------------------------
// 5. Form errors are announced and bound to their field (PRD §9.3)
// ---------------------------------------------------------------------------

test.describe('form errors', () => {
  test.skip(() => setupError !== null, 'fixtures unavailable')

  test('a rejected sign-in binds each message to its field and announces it', async ({
    browser,
  }) => {
    const surface = SURFACES.find((s) => s.name === 'login')
    await onSurface(browser, MOBILE, surface, async (page) => {
      await page.getByRole('button', { name: 'Sign in', exact: true }).click()

      const fields = await page.evaluate(() =>
        [...document.querySelectorAll('input[aria-invalid="true"]')].map((input) => {
          const described = (input.getAttribute('aria-describedby') ?? '')
            .split(/\s+/)
            .filter(Boolean)
            .map((id) => document.getElementById(id))
            .filter(Boolean)
          return {
            name: input.getAttribute('name'),
            hasLabel: Boolean(input.labels?.length || input.getAttribute('aria-label')),
            messages: described.map((el) => ({
              text: el.textContent.trim(),
              role: el.getAttribute('role'),
            })),
          }
        }),
      )

      expect(
        fields.length,
        'submitting an empty sign-in form raised no field errors',
      ).toBeGreaterThan(0)
      for (const field of fields) {
        expect(field.hasLabel, `${field.name} has no label`).toBeTruthy()
        expect(
          field.messages.length,
          `${field.name}'s error is not linked by aria-describedby`,
        ).toBeGreaterThan(0)
        expect(
          field.messages.some((m) => m.role === 'alert' && m.text.length > 0),
          `${field.name}'s error is shown but never announced (no role="alert")`,
        ).toBeTruthy()
      }
    })
  })

  test('every checkout control has a name, and no error floats free of its field', async ({
    browser,
  }) => {
    // Again the zone-resolved variant: "Place order" is disabled until the
    // server returns `can_place_order`, so on the plain page the click never
    // reaches the validator and no error is ever raised to check.
    const surface = SURFACES.find((s) => s.name === 'checkout with a delivery zone resolved')
    await onSurface(browser, MOBILE, surface, async (page) => {
      const unlabelled = await page.evaluate(() =>
        [...document.querySelectorAll('input, select, textarea')]
          .filter((el) => el.type !== 'hidden')
          .filter(
            (el) =>
              !el.labels?.length &&
              !el.getAttribute('aria-label') &&
              !el.getAttribute('aria-labelledby') &&
              !el.closest('label'),
          )
          .map((el) => `${el.tagName.toLowerCase()}[name=${el.getAttribute('name')}]`),
      )
      expect(unlabelled, 'checkout has form controls with no accessible name').toEqual([])

      // Run the validation pass with contact and street still blank, so
      // several fields fail at once and every message has to find its field.
      const submit = page.getByRole('button', { name: /Place order|Pay now/ })
      await expect(submit).toBeEnabled()
      await submit.click()
      await expect(page.locator('p[role="alert"]').first()).toBeVisible()

      const dangling = await page.evaluate(() =>
        [...document.querySelectorAll('p[role="alert"][id]')]
          .filter((el) => !document.querySelector(`[aria-describedby~="${el.id}"]`))
          .map((el) => `${el.id}: ${el.textContent.trim()}`),
      )
      expect(dangling, 'a checkout field error is not bound to any field').toEqual([])
    })
  })

  test('the admin product form binds its own errors to their fields', async ({ browser }) => {
    /*
     * A second, differently built form: this one is react-hook-form + zod with
     * the admin's own server-error mapping on top, not the storefront's. An
     * empty submit is refused client-side, so nothing is written.
     */
    const surface = SURFACES.find((s) => s.name === 'admin product form')
    await onSurface(browser, DESKTOP, surface, async (page) => {
      await page.getByRole('button', { name: /create product/i }).first().click()
      await expect(page.locator('[aria-invalid="true"]').first()).toBeVisible()

      const fields = await page.evaluate(() =>
        [...document.querySelectorAll('[aria-invalid="true"]')].map((el) => {
          const described = (el.getAttribute('aria-describedby') ?? '')
            .split(/\s+/)
            .filter(Boolean)
            .map((id) => document.getElementById(id))
            .filter(Boolean)
          return {
            name: el.getAttribute('name') || el.id,
            hasLabel: Boolean(el.labels?.length || el.getAttribute('aria-label')),
            announced: described.some(
              (node) => node.getAttribute('role') === 'alert' && node.textContent.trim(),
            ),
          }
        }),
      )

      expect(fields.length, 'an empty admin product form raised no field errors').toBeGreaterThan(0)
      for (const field of fields) {
        expect(field.hasLabel, `${field.name} has no label`).toBeTruthy()
        expect(field.announced, `${field.name}'s error is not announced`).toBeTruthy()
      }
    })
  })
})

// ---------------------------------------------------------------------------
// 6. Images (PRD §9.3) — described, or explicitly decorative
// ---------------------------------------------------------------------------

test.describe('images', () => {
  test.skip(() => setupError !== null, 'fixtures unavailable')

  test('no image anywhere is missing its alt attribute', async ({ browser }) => {
    for (const name of ['home', 'category listing', 'product detail', 'cart', 'admin products']) {
      const surface = SURFACES.find((s) => s.name === name)
      await onSurface(browser, DESKTOP, surface, async (page) => {
        const missing = await page.evaluate(() =>
          [...document.querySelectorAll('img')]
            .filter((img) => img.getAttribute('alt') === null)
            .map((img) => img.getAttribute('src')),
        )
        expect(missing, `images with no alt attribute at all on ${name}`).toEqual([])
      })
    }
  })

  test('the product gallery describes its main image and hides the decorative ones', async ({
    browser,
  }) => {
    expect(
      fixtures.illustratedSlug,
      'no catalogue product has an image, so alt text cannot be checked — ' +
        'import or seed a product with a photo before trusting this test',
    ).not.toBeNull()

    const surface = {
      name: 'product detail (illustrated)',
      path: `/p/${fixtures.illustratedSlug}`,
      ready: 'button:has-text("Add to cart"), button:has-text("Out of stock")',
    }
    await onSurface(browser, DESKTOP, surface, async (page) => {
      const gallery = await page.evaluate(() => {
        const main = document.querySelector('.aspect-square img')
        const thumbs = [...document.querySelectorAll('button img')]
        return {
          mainAlt: main?.getAttribute('alt') ?? null,
          thumbs: thumbs.map((img) => ({
            alt: img.getAttribute('alt'),
            buttonName: img.closest('button')?.getAttribute('aria-label') ?? '',
          })),
        }
      })

      // The image a shopper is buying from carries the description.
      expect(gallery.mainAlt, 'the gallery main image has no alt text').toBeTruthy()

      // A thumbnail is a picker, not content: the alt is empty and the button
      // it sits in carries the name, so the position is announced once.
      for (const thumb of gallery.thumbs) {
        expect(thumb.alt, 'a gallery thumbnail is not marked decorative').toBe('')
        expect(thumb.buttonName, 'a gallery thumbnail button has no accessible name').not.toBe('')
      }
    })
  })
})
