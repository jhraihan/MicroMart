import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

/*
 * Seeds (and re-stocks) the catalogue rows the buying-path specs use, by
 * running e2e/fixtures/seed_e2e_fixture.py through `manage.py shell`.
 *
 * Memoised per worker process: the specs each call it from `beforeAll` so any
 * one of them can be run on its own, but a whole-suite run pays Django's
 * startup cost once.
 */

const here = import.meta.dirname
const frontendDir = path.resolve(here, '..', '..')
const backendDir = path.resolve(frontendDir, '..', 'backend')
const scriptPath = path.join(here, '..', 'fixtures', 'seed_e2e_fixture.py')

const MARKER = 'E2E_FIXTURE_JSON '

function venvPython() {
  const candidates = [
    path.join(backendDir, '.venv', 'bin', 'python'),
    path.join(backendDir, '.venv', 'Scripts', 'python.exe'),
  ]
  const found = candidates.find(existsSync)
  if (!found) {
    throw new Error(
      `No virtualenv interpreter under ${backendDir}/.venv. ` +
        'Create it and install requirements/dev.txt (docs/HANDOFF.md §2).',
    )
  }
  return found
}

let cached = null

/**
 * @returns {{
 *   productSlug: string, productName: string, categorySlug: string,
 *   buyable: { id: number, sku: string, label: string, price: string, stock: number },
 *   capped:  { id: number, sku: string, label: string, price: string, stock: number },
 * }}
 */
export function seedFixture() {
  if (cached) return cached

  const source = readFileSync(scriptPath, 'utf8')
  let stdout
  try {
    stdout = execFileSync(venvPython(), ['manage.py', 'shell', '-c', source], {
      cwd: backendDir,
      encoding: 'utf8',
      timeout: 120_000,
      // Django's shell prints an import banner to stdout, so the payload is
      // marked rather than assumed to be the only thing there.
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  } catch (error) {
    throw new Error(
      `Seeding the E2E catalogue fixture failed.\n${error.stderr || error.message}`,
    )
  }

  const line = stdout.split('\n').find((row) => row.startsWith(MARKER))
  if (!line) {
    throw new Error(`Fixture script printed no ${MARKER.trim()} line. Got:\n${stdout}`)
  }

  cached = JSON.parse(line.slice(MARKER.length))
  return cached
}

/** The two seeded logins, per docs/HANDOFF.md §2. */
export const SHOPPER = {
  email: 'shopper@example.com',
  password: 'Str0ngPass!2026',
}

export const ADMIN = {
  email: 'admin@example.com',
  password: 'ChangeMe!2026',
}
