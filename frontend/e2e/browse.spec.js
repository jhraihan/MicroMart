import { expect, test } from '@playwright/test'

import { seedFixture } from './helpers/fixture'
import { formatMoney, visibleProductNames } from './helpers/storefront'

/*
 * Browse, search, facet, sort, detail -- the way in.
 *
 * These assertions are anchored on the seeded fixture product rather than on
 * whatever the demo catalogue happens to hold, and that is a robustness
 * decision, not a shortcut. This suite runs against the shared dev database,
 * where products appear and disappear while it runs; an assertion like "the
 * category page shows 4 products" is a race against anybody else's seed
 * script. "The fixture product appears under its own category and not under
 * another one" is the same claim about filtering, and it stays true no matter
 * what else is in the catalogue.
 */

let fixture

test.beforeAll(() => {
  fixture = seedFixture()
})

test('the home page renders its catalogue rows and category tiles', async ({ page }) => {
  await page.goto('/')

  await expect(
    page.getByRole('heading', {
      name: /Laptops, phones and components/i,
    }),
  ).toBeVisible()

  await expect(page.getByRole('heading', { name: 'Shop by category' })).toBeVisible()

  // At least one category tile, and it goes somewhere.
  const firstTile = page.getByRole('link', { name: /items$/ }).first()
  await expect(firstTile).toBeVisible()

  // A merchandising row with real products in it. "Best selling" is the only
  // row guaranteed content: "Top rated" filters on min_rating=4 and the demo
  // catalogue has no approved reviews, so that row hides itself by design.
  await expect(page.getByRole('heading', { name: 'Best selling' })).toBeVisible()
  const names = await visibleProductNames(page)
  expect(names.length).toBeGreaterThan(0)

  await expect(page.getByRole('link', { name: 'Browse the catalogue' })).toBeVisible()
})

test('a category page shows only that category', async ({ page }) => {
  const categories = await (await page.request.get('/api/v1/categories/')).json()
  // The tree is two levels deep at most, so flattening it is the whole search.
  const flat = categories.flatMap((root) => [root, ...(root.children ?? [])])

  const own = flat.find((category) => category.slug === fixture.categorySlug)
  const other = flat.find((category) => category.slug !== fixture.categorySlug)
  expect(own, 'the fixture is in a category the API does not list').toBeTruthy()
  expect(other, 'need a second category to prove filtering').toBeTruthy()

  await page.goto(`/c/${own.slug}`)
  await expect(page.getByRole('heading', { level: 1, name: own.name })).toBeVisible()
  await expect(page.getByRole('status').first()).toContainText(/\d+ products?/)
  expect(await visibleProductNames(page)).toContain(fixture.productName)

  // The same page for somewhere else must not carry it. That is the filter.
  await page.goto(`/c/${other.slug}`)
  await expect(page.getByRole('heading', { level: 1, name: other.name })).toBeVisible()
  expect(await visibleProductNames(page)).not.toContain(fixture.productName)
})

test('searching from the header returns matching products', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('Search products').fill('Harness')
  await page.getByRole('button', { name: 'Search' }).click()

  await page.waitForURL(/\/search\?q=Harness/)
  await expect(page.getByRole('heading', { name: 'Results for "Harness"' })).toBeVisible()

  const names = await visibleProductNames(page)
  expect(names).toContain(fixture.productName)

  // A keyword that nothing sells should say so rather than showing everything.
  await page.goto('/search?q=zzzznotathing')
  await expect(page.getByRole('status').first()).toContainText('0 products')
})

/*
 * The fixture's own category, which is the scope both of the tests below run
 * in.
 *
 * Not the whole catalogue, and that is a hard-won detail: this suite shares a
 * dev database with other work, which has already pushed the unscoped listing
 * past a single page. "The fixture is somewhere on screen" then becomes a race
 * against whatever else happens to have been seeded, rather than a statement
 * about faceting or sorting. A category the fixture lives in stays small and
 * stays about the behaviour under test.
 */
function scopedListing(slug) {
  return `/c/${slug}?page_size=100`
}

test('a brand facet narrows the results', async ({ page }) => {
  await page.goto(scopedListing(fixture.categorySlug))

  // Present before filtering. The fixture carries no brand, which is what
  // makes it a clean witness: any brand filter must drop it.
  expect(await visibleProductNames(page)).toContain(fixture.productName)

  // At 360px the sidebar is `hidden lg:block`, so filters live behind this
  // button and the mobile dialog -- exactly the path a phone shopper takes.
  await page.getByRole('button', { name: /^Filters/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Filters' })
  await expect(dialog).toBeVisible()

  // Which brands the server is offering *in this scope*, so the spec ticks a
  // real one rather than a name baked in here.
  const listing = await (
    await page.request.get(
      `/api/v1/products/?category=${fixture.categorySlug}&page_size=100`,
    )
  ).json()
  const brand = listing.facets.brands[0]
  expect(brand, 'this category offers no brand facet to filter on').toBeTruthy()

  const brandBox = dialog.getByRole('checkbox', { name: new RegExp(`^${brand.name}`) })
  /*
   * click() then assert, rather than check(). These are *controlled* inputs
   * whose checked state is derived from the URL, so the native toggle is
   * reverted by React on the same tick and only comes back after the
   * navigation re-renders the panel. check() verifies immediately after
   * clicking and would report "clicking the checkbox did not change its
   * state" for a checkbox that works perfectly -- toBeChecked() retries,
   * which is what a URL-driven control needs.
   */
  await brandBox.click()
  await expect(brandBox).toBeChecked()

  await dialog.getByRole('button', { name: /^Show \d+ results?$/ }).click()
  await expect(dialog).toBeHidden()

  await expect(page).toHaveURL(new RegExp(`brand=${brand.slug}`))
  // The active-filter chip names the brand back to the shopper. Matched as a
  // regex because the chip's accessible name also carries its "Remove this
  // filter" sr-only text, and getByRole matches the whole name.
  await expect(
    page.getByRole('button', { name: new RegExp(`Brand: ${brand.name}`) }),
  ).toBeVisible()

  /*
   * Narrowed to exactly what the facet promised. A facet count is computed
   * with its own dimension excluded, so ticking one brand must land on that
   * brand's own number -- and the brandless fixture must be gone.
   */
  await expect(page.getByRole('status').first()).toContainText(
    `${brand.count} ${brand.count === 1 ? 'product' : 'products'}`,
  )

  const filtered = await visibleProductNames(page)
  expect(filtered).toHaveLength(brand.count)
  expect(filtered).not.toContain(fixture.productName)
})

/*
 * Choose a sort and wait for the grid to actually be showing *that* answer.
 *
 * The naive version of this -- select, assert the URL, read the cards -- reads
 * the previous sort's DOM, because the URL changes the instant the select
 * fires and the refetch lands some time later. So the expectation is taken
 * from the very response the page is about to render, and the poll waits for
 * the grid to agree with it. That also makes the assertion immune to anything
 * else mutating this shared dev catalogue mid-run.
 */
async function sortAndReadGrid(page, sort) {
  const [response] = await Promise.all([
    page.waitForResponse(
      (res) =>
        res.url().includes('/api/v1/products/') &&
        res.url().includes(`sort=${sort}`) &&
        res.ok(),
    ),
    page.getByLabel('Sort by').selectOption(sort),
  ])

  const expected = (await response.json()).results.map((product) => product.name)
  await expect
    .poll(() => visibleProductNames(page), { timeout: 20_000 })
    .toEqual(expected)
  return expected
}

test('sorting by price reorders the grid', async ({ page }) => {
  await page.goto(scopedListing(fixture.categorySlug))
  await expect(page.getByLabel('Sort by')).toBeVisible()

  const ascending = await sortAndReadGrid(page, 'price_asc')
  await expect(page).toHaveURL(/sort=price_asc/)

  const descending = await sortAndReadGrid(page, 'price_desc')
  await expect(page).toHaveURL(/sort=price_desc/)

  expect(ascending.length).toBeGreaterThan(1)
  expect(descending.length).toBeGreaterThan(1)

  /*
   * Asserted as a *movement* rather than as a fixed position. The fixture is
   * cheap, so it must sit nearer the front cheapest-first than it does
   * dearest-first -- true whatever else the catalogue is holding at the time,
   * which a hard-coded "first card is X" would not be.
   */
  const ascIndex = ascending.indexOf(fixture.productName)
  const descIndex = descending.indexOf(fixture.productName)
  expect(ascIndex, 'fixture missing from the ascending grid').toBeGreaterThanOrEqual(0)
  expect(descIndex, 'fixture missing from the descending grid').toBeGreaterThanOrEqual(0)
  expect(ascIndex).toBeLessThan(descIndex)
  expect(ascending[0]).not.toEqual(descending[0])
})

test('a product detail page opens with its price and stock', async ({ page }) => {
  await page.goto(`/c/${fixture.categorySlug}`)

  await page.getByRole('link', { name: fixture.productName }).first().click()
  await page.waitForURL(new RegExp(`/p/${fixture.productSlug}`))

  await expect(page.getByRole('heading', { level: 1, name: fixture.productName })).toBeVisible()

  // Price and availability, both read off the selected variant.
  await expect(page.getByText(formatMoney(fixture.buyable.price)).first()).toBeVisible()
  await expect(page.getByText('In stock').first()).toBeVisible()
  await expect(page.getByText(`SKU: ${fixture.buyable.sku}`)).toBeVisible()

  /*
   * Two variants, so the selector is offered -- and choosing the other one
   * must repaint price, SKU and stock with no reload, because price and stock
   * live on the variant and never on the product.
   *
   * The radio itself is `sr-only`, so the click goes to its visible label, the
   * way a thumb would land on it.
   */
  await page.getByText(fixture.capped.label, { exact: true }).click()
  await expect(page.getByText(`SKU: ${fixture.capped.sku}`)).toBeVisible()
  await expect(page.getByText(`Only ${fixture.capped.stock} left`)).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`variant=${fixture.capped.id}`))

  await expect(page.getByRole('button', { name: 'Add to cart', exact: true })).toBeEnabled()
})
