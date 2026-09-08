import { expect, test } from '@playwright/test'

import { apiLogin, clearServerCart, fetchOrderAsAdmin, variantStock } from './helpers/api'
import { SHOPPER, seedFixture } from './helpers/fixture'
import { addVariantToCart, formatMoney, placeOrder, signIn } from './helpers/storefront'

/*
 * The account path: sign in, buy against the saved address, then find the
 * order in the history where it belongs.
 *
 * The server cart is emptied first, and that is a correctness step rather than
 * tidiness. A signed-in cart persists in the database between runs, and
 * placement orders *the whole cart* -- so a line left over from an earlier run
 * would silently become an extra order item and every total below would be
 * wrong for a reason that has nothing to do with this test.
 */

let fixture

test.beforeAll(() => {
  fixture = seedFixture()
})

/** Street addresses carry commas; keep them out of the regex engine's way. */
function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

test('a signed-in shopper checks out against their saved address', async ({
  page,
  request,
}) => {
  const unitPrice = Number(fixture.buyable.price)
  const shipping = 60
  const expectedTotal = unitPrice + shipping

  const token = await clearServerCart(request, SHOPPER)
  const stockBefore = await variantStock(request, fixture.productSlug, fixture.buyable.id)

  const addresses = await (
    await request.get('/api/v1/addresses/', {
      headers: { Authorization: `Bearer ${token}` },
    })
  ).json()
  const preferred = addresses.find((address) => address.is_default) ?? addresses[0]
  expect(preferred, 'the seeded shopper has no address to preselect').toBeTruthy()

  // --- Sign in through the form, then fill a server cart ----------------
  await signIn(page, SHOPPER)
  await addVariantToCart(page, {
    productSlug: fixture.productSlug,
    variantId: fixture.buyable.id,
  })

  await page.goto('/checkout')
  await expect(page.getByRole('heading', { name: 'Checkout' })).toBeVisible()
  // The guest banner must be absent -- its presence would mean the session
  // was lost and this is silently testing the guest flow again.
  await expect(page.getByText('Checking out as a guest.')).toHaveCount(0)

  // --- FR-CHK-4: the saved default address is already chosen ------------
  const savedRadio = page.getByRole('radio', {
    name: new RegExp(escapeRegExp(preferred.street)),
  })
  await expect(savedRadio).toBeChecked()
  await expect(page.getByText(preferred.recipient_name).first()).toBeVisible()

  // Delivery was priced from that address's district without anything being
  // typed in.
  await expect(page.getByText('Inside Dhaka', { exact: true })).toBeVisible()
  await expect(page.getByText(formatMoney(expectedTotal)).first()).toBeVisible()

  const cod = page.getByRole('radio', { name: /Cash on Delivery/ })
  await cod.click()
  await expect(cod).toBeChecked()

  const reference = await placeOrder(page)

  // A signed-in shopper is offered the real order screen; a guest is not.
  await expect(page.getByRole('link', { name: 'View order details' })).toBeVisible()

  // --- It appears in the account's own history --------------------------
  await page.goto('/orders')
  await expect(page.getByRole('heading', { name: 'Your orders' })).toBeVisible()

  // `exact`, because each row carries two links to the same order: the
  // reference itself and a "View order <reference>" affordance below it.
  const row = page.getByRole('link', { name: reference, exact: true })
  await expect(row).toBeVisible()

  await row.click()
  await page.waitForURL(`**/orders/${reference}`)

  await expect(page.getByRole('heading', { name: `Order ${reference}` })).toBeVisible()
  await expect(page.getByText('Confirmed').first()).toBeVisible()

  const items = page.getByRole('region', { name: 'Items' })
  await expect(items.getByRole('link', { name: fixture.productName })).toBeVisible()
  await expect(items).toContainText(fixture.buyable.sku)
  await expect(items).toContainText(`1 × ${formatMoney(unitPrice)}`)

  await expect(page.getByRole('region', { name: 'Order summary' })).toContainText(
    formatMoney(expectedTotal),
  )

  // --- Server-side truth -------------------------------------------------
  const order = await fetchOrderAsAdmin(request, reference)
  expect(order.status).toBe('confirmed')
  expect(order.payment_method).toBe('cod')
  expect(Number(order.grand_total)).toBe(expectedTotal)
  expect(order.items).toHaveLength(1)
  expect(order.items[0].sku).toBe(fixture.buyable.sku)
  expect(order.items[0].quantity).toBe(1)
  // Placed by the account, not as a guest.
  expect(order.customer?.email ?? order.email).toBe(SHOPPER.email)
  // The address was snapshotted from the address book, not pointed at it.
  expect(order.shipping_address.street).toBe(preferred.street)

  const stockAfter = await variantStock(request, fixture.productSlug, fixture.buyable.id)
  expect(stockAfter).toBe(stockBefore - 1)

  /*
   * --- Pinning a defect, deliberately -----------------------------------
   *
   * This asserts what the system does TODAY, which is not what it should do.
   * The frozen contract says "On success the authenticated user's server cart
   * is emptied" (docs/api-contract-cart-checkout-orders.md, POST /orders/),
   * and it is not emptied: the shopper buys, and the thing they just bought is
   * still sitting in their cart with the header badge still counting it.
   *
   * The cause is a three-way disagreement, which is why this spec reports it
   * rather than fixing it:
   *   - placement.place_order only clears the cart the basket *came from*;
   *   - checkout.resolve_basket returns no source cart when the request names
   *     its own `items`, on purpose -- its docstring calls that "buying
   *     straight from a product page without disturbing their cart";
   *   - CheckoutPage always sends `items`, built from the cart it is
   *     displaying, so the cart-sourced branch is never taken from the
   *     storefront at all.
   *
   * Any of the three could give: the client could omit `items` when it is
   * checking out the whole cart, the service could clear the ordered lines
   * whoever named them, or the contract could drop the promise. That is an
   * owner's call. **When it is made, invert this expectation to
   * toHaveLength(0).**
   */
  const freshToken = await apiLogin(request, SHOPPER)
  const cart = await (
    await request.get('/api/v1/cart/', {
      headers: { Authorization: `Bearer ${freshToken}` },
    })
  ).json()
  expect(
    cart.items,
    'the server cart survives placement today -- see the comment above',
  ).toHaveLength(1)
})
