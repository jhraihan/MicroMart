import { existsSync } from 'node:fs'
import path from 'node:path'

import { defineConfig, devices } from '@playwright/test'

/*
 * End-to-end harness for the shopper critical path.
 *
 * Two things about this suite are unusual and deliberate.
 *
 * 1. **It runs against the DEV database, not a test database.** Placing an
 *    order really creates an order and really decrements stock. Everything
 *    the specs buy is therefore seeded by e2e/fixtures/seed_e2e_fixture.py,
 *    which tops its own variant back up on every run -- so the suite never
 *    spends the demo catalogue and stays re-runnable forever. Nothing asserts
 *    a global count ("3 orders exist"), because a previous run changed it.
 *
 * 2. **The viewport is 360px wide, not a desktop.** PRD §9.2 requires the
 *    store to be fully usable one-handed at 360px, so that is the honest
 *    default for these tests. It has teeth: at 360px the facet sidebar is
 *    `hidden lg:block`, so the browse spec has to reach filters through the
 *    mobile "Filters" dialog, which is what a real phone shopper does.
 */

const frontendDir = import.meta.dirname
const backendDir = path.resolve(frontendDir, '..', 'backend')

const BASE_URL = 'http://127.0.0.1:5173'
const API_URL = 'http://127.0.0.1:8000'

/*
 * The venv interpreter, macOS layout first and Windows second -- this project
 * has lived on both (docs/HANDOFF.md §2) and the harness should not be the
 * thing that breaks when it moves again.
 */
const venvPython =
  [
    path.join(backendDir, '.venv', 'bin', 'python'),
    path.join(backendDir, '.venv', 'Scripts', 'python.exe'),
  ].find(existsSync) ?? 'python3'

/*
 * Vite is launched from node_modules/.bin directly rather than through
 * `npm run dev`. npm spawns vite as a grandchild, and when Playwright tears
 * the web server down it is npm that dies -- leaving vite holding :5173, so
 * the *next* cold run fails with EADDRINUSE. Exec'ing the binary keeps the
 * process Playwright started and the process listening on the port the same
 * one. (Observed, not theorised: it orphaned a server during this suite's
 * own bring-up.)
 */
const viteBin =
  [
    path.join(frontendDir, 'node_modules', '.bin', 'vite'),
    path.join(frontendDir, 'node_modules', '.bin', 'vite.cmd'),
  ].find(existsSync) ?? 'vite'

export default defineConfig({
  testDir: './e2e',
  /*
   * One worker, no parallelism. There is a single MySQL schema behind this and
   * the specs move real stock; two workers buying the same variant would make
   * the "stock fell by exactly the quantity ordered" assertion a race rather
   * than a check. Serial is also what docs/HANDOFF.md §1 asks of anything
   * touching this database.
   */
  fullyParallel: false,
  workers: 1,
  /*
   * No retries, on purpose. A retry would hide exactly the flakiness this
   * suite is supposed to report honestly.
   */
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],

  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: 'mobile-chromium',
      use: {
        // Pixel 5 for the mobile user agent, touch and DPR, with the width
        // pinned to the 360px the PRD actually names.
        ...devices['Pixel 5'],
        viewport: { width: 360, height: 780 },
      },
    },
  ],

  /*
   * Both servers, so `npx playwright test` works from cold. Each is reused if
   * something is already listening, so the usual "two terminals already
   * running" workflow costs nothing.
   *
   * Vite is started with `--host 127.0.0.1` deliberately: its default host is
   * `localhost`, which Node resolves to ::1 first, so a plain `npm run dev`
   * binds IPv6 only and http://127.0.0.1:5173 is dead. Binding the loopback
   * IPv4 address explicitly is what makes the baseURL above true, and it
   * coexists happily with an IPv6-bound dev server on the same port.
   */
  webServer: [
    {
      // --noreload on purpose. The autoreloader forks a second process, which
      // is the same orphan hazard as the npm wrapper above; and a test run
      // wants the code as it was when the run started, not as it is halfway
      // through. Day-to-day `manage.py runserver` should keep the reloader
      // (docs/HANDOFF.md §2) -- this is a test-run-only trade.
      command: `"${venvPython}" manage.py runserver --noreload 127.0.0.1:8000`,
      cwd: backendDir,
      // A readiness probe that actually touches the database. A server that
      // answers on the port but cannot reach MySQL is not ready, and finding
      // that out here beats finding it out as a mystery failure in spec three.
      url: `${API_URL}/api/v1/products/?page_size=1`,
      reuseExistingServer: true,
      timeout: 120_000,
      stdout: 'ignore',
      stderr: 'pipe',
      env: {
        // Django holds a connection open for CONN_MAX_AGE seconds (60 by
        // default) per worker thread. On a box where several things share one
        // MySQL that is how you reach `(1040, 'Too many connections')`, and
        // this suite opens a lot of short connections. Nothing here benefits
        // from connection reuse, so give them straight back.
        DB_CONN_MAX_AGE: '0',
      },
    },
    {
      command: `"${viteBin}" --host 127.0.0.1 --strictPort --port 5173`,
      cwd: frontendDir,
      url: BASE_URL,
      reuseExistingServer: true,
      timeout: 120_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
  ],
})
