import { expect, test } from '@playwright/test'

import { apiLogin, clearServerCart, fetchServerCart } from './helpers/api'
import { SHOPPER, seedFixture } from './helpers/fixture'
import { addVariantToCart, formatMoney, signIn } from './helpers/storefront'

/*
 * The signed-in cart, rendered in full.
 *
 * This is the surface that was broken end to end until 2026-08-22 by a
 * serializer that nested every field under a `variant` object while the page
 * read them flat (docs/HANDOFF.md §4). Every line rendered with no name, no
 * image and no link, and because `variant_id` went missing too, the quote
 * request built from those lines came back 400 and took the totals down with
 * it. The whole backend suite stayed green throughout, because no test ever
 * compared what the API emits against what the page reads.
 *
 * That is what the last test here does, and why it checks for the *presence*
 * of each key rather than its value: the bug was missing keys, and a missing
 * key and a null one are indistinguishable once `undefined` has been rendered.
 * The first test is the other half -- the page itself, which can only paint a
 * name, an image, a link and a stock-capped stepper if the flat shape arrived.
 */

/** Exactly the keys `fromServerItem` in features/cart/useCart.js reads. */
const KEYS_THE_PAGE_READS = [
  'id',
  'variant_id',
  'product_name',
  'product_slug',
  'variant_label',
  'sku',
  'image',
  'unit_price',
  'quantity',
  'stock',
]

let fixture

test.beforeAll(() => {
  fixture = seedFixture()
})

test.beforeEach(async ({ request }) => {
  await clearServerCart(request, SHOPPER)
})

test('a signed-in cart line renders everything needed to act on it', async ({ page }) => {
  await signIn(page, SHOPPER)

  // The low-stock variant, so "capped at available stock" is an assertion
  // with a real number behind it rather than a theoretical ceiling.
  await addVariantToCart(page, {
    productSlug: fixture.productSlug,
    variantId: fixture.capped.id,
  })

  await page.goto('/cart')
  await expect(page.getByRole('heading', { name: 'Your cart (1 item)' })).toBeVisible()

  const line = page
    .getByRole('region', { name: 'Cart items' })
    .getByRole('listitem')
    .filter({ hasText: `SKU ${fixture.capped.sku}` })
  await expect(line).toHaveCount(1)

  // --- Name, and a link that actually goes somewhere --------------------
  const link = line.getByRole('link', { name: fixture.productName })
  await expect(link).toBeVisible()
  await expect(link).toHaveAttribute(
    'href',
    `/p/${fixture.productSlug}?variant=${fixture.capped.id}`,
  )

  // --- The variant, spelled out -----------------------------------------
  await expect(line.getByText(fixture.capped.label)).toBeVisible()
  await expect(line.getByText(`SKU ${fixture.capped.sku}`)).toBeVisible()

  // --- Money: the unit price, and a line total only the server can supply
  await expect(line.getByText(formatMoney(fixture.capped.price), { exact: true })).toHaveCount(
    2, // once as "each", once as the line total -- one unit, so they match
  )
  // A dash here is the tell that the quote never answered.
  await expect(line.getByText('—')).toHaveCount(0)

  /*
   * --- The image ---------------------------------------------------------
   * Located by element rather than by role on purpose: its alt is empty,
   * because the product link beside it already announces the product and a
   * duplicate would be read out twice. That is correct, and it means the
   * image is deliberately absent from the accessibility tree.
   *
   * Asserted as *loaded*, not merely present -- a broken src still renders an
   * <img> element, and the point is that the URL the API emitted resolves.
   */
  const image = line.locator('img')
  await expect(image).toHaveAttribute('src', /^\/media\/products\/.+\.png$/)
  await expect(line.getByText('No image')).toHaveCount(0)
  await expect
    .poll(() => image.evaluate((el) => el.complete && el.naturalWidth > 0))
    .toBe(true)

  // --- The stepper, capped at what is actually in stock -----------------
  const quantity = line.getByRole('spinbutton', { name: /Quantity for/ })
  await expect(quantity).toHaveValue('1')
  await expect(quantity).toHaveAttribute('max', String(fixture.capped.stock))

  const increase = line.getByRole('button', { name: /Increase quantity for/ })
  const decrease = line.getByRole('button', { name: /Decrease quantity for/ })
  await expect(decrease).toBeDisabled() // already at the minimum

  for (let next = 2; next <= fixture.capped.stock; next += 1) {
    await increase.click()
    await expect(quantity).toHaveValue(String(next))
  }

  // At the ceiling the control stops, rather than marching the shopper to a
  // checkout that would be refused.
  await expect(increase).toBeDisabled()
  await expect(decrease).toBeEnabled()

  // The line total followed the quantity, and it followed it server-side.
  await expect(
    line.getByText(formatMoney(Number(fixture.capped.price) * fixture.capped.stock), {
      exact: true,
    }),
  ).toBeVisible()
})

test('the cart API emits every field the cart page reads', async ({ page, request }) => {
  await signIn(page, SHOPPER)
  await addVariantToCart(page, {
    productSlug: fixture.productSlug,
    variantId: fixture.buyable.id,
  })

  const token = await apiLogin(request, SHOPPER)
  const cart = await fetchServerCart(request, token)

  expect(cart.items).toHaveLength(1)
  const [item] = cart.items

  for (const key of KEYS_THE_PAGE_READS) {
    expect(
      Object.hasOwn(item, key),
      `GET /cart/ item is missing "${key}", which useCart.fromServerItem reads`,
    ).toBe(true)
  }

  // Flat, not nested -- the shape the contract freezes and the page expects.
  expect(Object.hasOwn(item, 'variant')).toBe(false)

  expect(item.variant_id).toBe(fixture.buyable.id)
  expect(item.sku).toBe(fixture.buyable.sku)
  expect(item.product_slug).toBe(fixture.productSlug)
  expect(Number(item.unit_price)).toBe(Number(fixture.buyable.price))
  expect(typeof item.stock).toBe('number')
})
