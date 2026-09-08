import { expect, test } from '@playwright/test'

import { fetchOrderAsAdmin, variantStock } from './helpers/api'
import { seedFixture } from './helpers/fixture'
import {
  DHAKA_ADDRESS,
  addVariantToCart,
  fillNewAddress,
  formatMoney,
  placeOrder,
} from './helpers/storefront'

/*
 * FR-CHK-5: a guest buys, end to end, without ever holding an account.
 *
 * The last third of this spec is the part that matters. A green "Order placed"
 * screen proves the page painted; it does not prove an order exists, that its
 * total is right, or that stock moved -- and stock movement is the one thing
 * in this flow that cannot be undone. So the run finishes by reading the order
 * back out of the API and comparing the stock before and after.
 */

const QUANTITY = 2

let fixture

test.beforeAll(() => {
  fixture = seedFixture()
})

test('a guest can buy without signing in, and the server agrees', async ({ page, request }) => {
  const unitPrice = Number(fixture.buyable.price)
  const expectedSubtotal = unitPrice * QUANTITY
  const shipping = 60 // "Inside Dhaka" flat rate, seeded by seed_demo
  const expectedTotal = expectedSubtotal + shipping

  // Read live, not from the fixture: the fixture guarantees a floor, and this
  // is a shared database.
  const stockBefore = await variantStock(request, fixture.productSlug, fixture.buyable.id)

  // --- Add to cart from the product page --------------------------------
  await addVariantToCart(page, {
    productSlug: fixture.productSlug,
    variantId: fixture.buyable.id,
    quantity: QUANTITY,
  })

  // --- The cart shows the right line and the right money ----------------
  await page.goto('/cart')
  await expect(page.getByRole('heading', { name: `Your cart (${QUANTITY} items)` })).toBeVisible()

  const cartItems = page.getByRole('region', { name: 'Cart items' })
  await expect(cartItems.getByRole('link', { name: fixture.productName })).toBeVisible()
  await expect(cartItems.getByText(`SKU ${fixture.buyable.sku}`)).toBeVisible()
  await expect(cartItems.getByText(formatMoney(unitPrice), { exact: true })).toBeVisible()
  // The line total is only ever printed from the server's quote, so its
  // presence is also evidence the quote round trip succeeded.
  await expect(cartItems.getByText(formatMoney(expectedSubtotal), { exact: true })).toBeVisible()

  await expect(page.getByText('Subtotal')).toBeVisible()
  await expect(page.getByText(formatMoney(expectedSubtotal)).first()).toBeVisible()
  // No district yet, so the server has not priced delivery -- and says so
  // rather than guessing.
  await expect(page.getByText('Calculated at checkout').first()).toBeVisible()

  await page.getByRole('link', { name: 'Proceed to checkout' }).click()
  await page.waitForURL('**/checkout')

  // --- Checkout, as a guest ---------------------------------------------
  await expect(page.getByRole('heading', { name: 'Checkout' })).toBeVisible()
  // The proof that no sign-in was required. If this banner is missing the
  // shopper is authenticated and the spec is testing the wrong flow.
  await expect(page.getByText('Checking out as a guest.')).toBeVisible()

  await fillNewAddress(page)

  // Delivery resolves from the district, server-side. `exact` because the
  // totals panel also names the zone, as "(Inside Dhaka)".
  await expect(page.getByText('Inside Dhaka', { exact: true })).toBeVisible()

  const cod = page.getByRole('radio', { name: /Cash on Delivery/ })
  await cod.click()
  await expect(cod).toBeChecked()

  // Every figure below came from POST /checkout/quote/.
  await expect(page.getByText(formatMoney(shipping)).first()).toBeVisible()
  await expect(page.getByText(formatMoney(expectedTotal)).first()).toBeVisible()

  const reference = await placeOrder(page)

  // --- The confirmation screen ------------------------------------------
  await expect(page.getByText(reference).first()).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Have this ready for the courier' }),
  ).toContainText(formatMoney(expectedTotal))
  await expect(page.getByRole('region', { name: 'Order summary' })).toContainText(
    formatMoney(expectedTotal),
  )
  // Named twice on this screen -- once in "a confirmation is on its way to",
  // once in the guest's "create an account with" prompt.
  await expect(page.getByText(DHAKA_ADDRESS.email).first()).toBeVisible()

  /*
   * --- Server-side truth -------------------------------------------------
   * Read back through the admin endpoint, which is the only surface that can
   * see a guest's order at all.
   */
  const order = await fetchOrderAsAdmin(request, reference)

  expect(order.reference).toBe(reference)
  expect(order.email).toBe(DHAKA_ADDRESS.email)
  expect(order.payment_method).toBe('cod')
  // COD confirms on placement -- which is exactly why stock is allowed to move.
  expect(order.status).toBe('confirmed')
  expect(Number(order.subtotal)).toBe(expectedSubtotal)
  expect(Number(order.shipping_total)).toBe(shipping)
  expect(Number(order.grand_total)).toBe(expectedTotal)

  expect(order.items).toHaveLength(1)
  const [line] = order.items
  expect(line.quantity).toBe(QUANTITY)
  expect(line.sku).toBe(fixture.buyable.sku)
  expect(line.product_name).toBe(fixture.productName)
  expect(Number(line.unit_price)).toBe(unitPrice)
  expect(Number(line.line_total)).toBe(expectedSubtotal)

  // The address was snapshotted onto the order, not referenced (FR-ORD-2).
  expect(order.shipping_address.district).toBe(DHAKA_ADDRESS.district)
  expect(order.shipping_address.recipient_name).toBe(DHAKA_ADDRESS.recipientName)

  // And the stock really moved, by exactly what was bought.
  const stockAfter = await variantStock(request, fixture.productSlug, fixture.buyable.id)
  expect(stockAfter).toBe(stockBefore - QUANTITY)
})
