import { expect, test } from '@playwright/test'

import {
  SEEDED_ADMIN,
  bearer,
  displayMoney,
  fixture,
  labelled,
  signInWithForm,
  tokensFor,
  useSession,
  watchConsole,
} from './_support.js'

/*
 * Admin sign-in, and the overview screen (US-A1, FR-ADM-1).
 *
 * This is the one admin spec that drives the sign-in form, because signing in
 * is what it is testing. It starts at /admin so the round trip through the
 * guard is proved as well: an anonymous visitor is sent to /login and, having
 * signed in, is put back where they were going rather than dumped on the
 * storefront.
 *
 * Every figure is asserted as a DELTA, never as a value. "Today's revenue is
 * ৳4,560" is true for about a day and only on one machine; "placing one order
 * moved today's revenue by exactly that order's total" is true on anybody's
 * database, including one that has been run against a hundred times.
 */

test('an anonymous visitor to /admin signs in and lands back on /admin', async ({
  page,
}) => {
  const problems = watchConsole(page)

  await page.goto('/admin')
  await expect(page).toHaveURL(/\/login$/)

  await signInWithForm(page, SEEDED_ADMIN)

  await expect(page).toHaveURL(/\/admin$/)
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible()

  // --- the three revenue windows -----------------------------------------
  const revenue = page.getByRole('region', { name: 'Revenue and order count' })
  await expect(revenue).toBeVisible()

  for (const label of ['Today', 'Last 7 days', 'Last 30 days']) {
    const tile = revenue.getByRole('link').filter({ hasText: label }).first()
    // ৳ and a figure. formatMoney renders an em dash for a null, so a tile
    // showing one is a tile whose aggregate came back empty.
    await expect(tile).toContainText('৳')
    await expect(tile).toContainText(/\d/)
    // Every tile is a link to the rows it counted, which is the only way an
    // owner can check a figure it prints. A tile that were not one would be a
    // number with no provenance.
    await expect(tile).toHaveAttribute('href', /^\/admin\/orders\?/)
  }

  // --- what needs doing ---------------------------------------------------
  await expect(page.getByRole('heading', { name: 'Needs action', level: 2 })).toBeVisible()
  await expect(
    page.getByRole('link').filter({ hasText: 'Orders awaiting action' }),
  ).toContainText(/\d/)

  // The per-status breakdown, matched on the filtered list each one opens.
  for (const status of ['pending', 'confirmed', 'packed']) {
    await expect(page.locator(`a[href="/admin/orders?status=${status}"]`)).toHaveCount(1)
  }
  await expect(page.locator('a[href="/admin/inventory?low_stock=true"]')).toHaveCount(1)

  // --- the trend ----------------------------------------------------------
  await expect(page.getByRole('button', { name: 'Revenue', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  // The plot is a picture; this is the same series as a table, and it is what
  // a reader who cannot use the picture gets. It is present either way.
  await expect(page.getByText('Show the numbers')).toBeVisible()

  expect(problems, problems.join('\n')).toEqual([])
})

test('a confirmed order reaches the revenue tiles, the desk and the reorder list', async ({
  page,
  request,
  baseURL,
}) => {
  const admin = tokensFor(SEEDED_ADMIN.email)

  const dashboard = async () =>
    (
      await request.get('/api/v1/admin/dashboard/', { headers: bearer(admin.access) })
    ).json()

  const before = await dashboard()

  // A COD order confirms at placement, so it counts toward revenue the moment
  // it exists (metrics.REVENUE_STATUSES) and lands on the "confirmed" desk.
  const order = fixture('order', ['--payment', 'cod'])
  expect(order.status).toBe('confirmed')

  // A variant at 2 units against a threshold of 5 is one more low-stock line.
  const lowStockVariant = fixture('product', ['--stock', '2'])

  const after = await dashboard()

  /*
   * Directional, not exact, and deliberately so.
   *
   * The obvious assertion is "revenue moved by exactly this order's total",
   * and it is the one this test started out making. It is wrong: this suite
   * runs against the shared dev database (playwright.config.js), so anything
   * else placing an order between the two reads -- another agent's spec run,
   * a developer clicking through checkout in another tab -- makes the delta
   * larger and the test red for a reason that is not a defect. What is safe
   * to assert is the direction and the floor; the exact figure is checked
   * below, against a payload nothing could have changed underneath.
   */
  expect(Number(after.today.revenue)).toBeGreaterThanOrEqual(
    Number(before.today.revenue) + Number(order.grand_total),
  )
  expect(after.today.orders).toBeGreaterThanOrEqual(before.today.orders + 1)
  expect(after.orders_awaiting_action.confirmed).toBeGreaterThanOrEqual(
    before.orders_awaiting_action.confirmed + 1,
  )

  // Membership, not a delta: the low-stock population also shrinks whenever
  // the fixture command retires an older fixture product, so "the count went
  // up by one" is not a fact about this variant. "This variant is on the
  // reorder list" is.
  const reorderList = await (
    await request.get('/api/v1/admin/inventory/', {
      headers: bearer(admin.access),
      params: { low_stock: 'true', q: lowStockVariant.sku },
    })
  ).json()
  expect(reorderList.results.map((row) => row.sku)).toContain(lowStockVariant.sku)

  // --- the tile links to the rows it counted ------------------------------
  // The reason every tile is a link: an owner has to be able to check a
  // figure, and this is that check made by machine.
  const listed = await (
    await request.get('/api/v1/admin/orders/', {
      headers: bearer(admin.access),
      params: {
        status: after.revenue_statuses.join(','),
        placed_from: after.generated_at.slice(0, 10),
        placed_to: after.generated_at.slice(0, 10),
        page_size: 100,
      },
    })
  ).json()
  expect(listed.results.map((row) => row.reference)).toContain(order.reference)

  // --- the screen, against the payload the screen itself was given --------
  const problems = watchConsole(page)
  await useSession(page, baseURL, admin)

  const served = page.waitForResponse((response) =>
    response.url().includes('/api/v1/admin/dashboard/'),
  )
  await page.goto('/admin')
  const painted = await (await served).json()
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible()

  // Nothing can have moved between these two facts: this IS the response the
  // page rendered from, so the assertion is exact and cannot race.
  const todayTile = page
    .getByRole('region', { name: 'Revenue and order count' })
    .getByRole('link')
    .filter({ hasText: 'Today' })
    .first()
  await expect(todayTile).toContainText(displayMoney(painted.today.revenue))

  await expect(page.locator('a[href="/admin/inventory?low_stock=true"]')).toContainText(
    String(painted.low_stock_count),
  )
  await expect(page.locator('a[href="/admin/orders?status=confirmed"]')).toContainText(
    String(painted.orders_awaiting_action.confirmed),
  )

  // Trade happened today, so the plot itself is drawn rather than the
  // "no orders in this window" placeholder.
  await expect(page.getByText('No orders in this window yet.')).toHaveCount(0)
  await expect(page.locator('figure svg').first()).toBeVisible()

  // --- and the low-stock tile opens the list that explains it -------------
  await page.locator('a[href="/admin/inventory?low_stock=true"]').click()
  await expect(page).toHaveURL(/\/admin\/inventory\?low_stock=true$/)
  await page.getByLabel(labelled('Search')).fill(lowStockVariant.sku)
  await expect(page.getByRole('row').filter({ hasText: lowStockVariant.sku })).toContainText(
    'Low',
  )

  expect(problems, problems.join('\n')).toEqual([])
})
