import { expect, test } from '@playwright/test'

import { apiLogin, clearServerCart, fetchServerCart } from './helpers/api'
import { SHOPPER, seedFixture } from './helpers/fixture'
import { addVariantToCart, signIn } from './helpers/storefront'

/*
 * FR-CRT-2: a basket built while signed out survives signing in.
 *
 * This is the flow with the most moving parts and the least visible failure.
 * A guest cart lives in localStorage; a signed-in cart lives in the database;
 * LoginPage bridges them with one POST /cart/merge/ and then drops the local
 * copy. If that POST is skipped, fails quietly, or lands after the cart query
 * has already cached an empty answer, the shopper simply finds their basket
 * gone -- with no error anywhere to explain it.
 *
 * So this spec asserts on three things and not just the last one: the guest
 * cart before, the *response* of the merge call itself, and the server's cart
 * after -- read back over the API, not merely repainted.
 */

const STANDARD_QTY = 2
const LIMITED_QTY = 1

let fixture

test.beforeAll(() => {
  fixture = seedFixture()
})

test('a guest cart survives signing in', async ({ page, request }) => {
  // The account's cart persists between runs and merge *adds* to it, so an
  // un-emptied cart would make every quantity below drift by one run's worth.
  await clearServerCart(request, SHOPPER)

  // --- Build a cart as a guest ------------------------------------------
  await addVariantToCart(page, {
    productSlug: fixture.productSlug,
    variantId: fixture.buyable.id,
    quantity: STANDARD_QTY,
  })
  await addVariantToCart(page, {
    productSlug: fixture.productSlug,
    variantId: fixture.capped.id,
    quantity: LIMITED_QTY,
  })

  await page.goto('/cart')
  const totalUnits = STANDARD_QTY + LIMITED_QTY
  await expect(
    page.getByRole('heading', { name: `Your cart (${totalUnits} items)` }),
  ).toBeVisible()

  const cartItems = page.getByRole('region', { name: 'Cart items' })
  await expect(cartItems.getByText(`SKU ${fixture.buyable.sku}`)).toBeVisible()
  await expect(cartItems.getByText(`SKU ${fixture.capped.sku}`)).toBeVisible()

  // It really is the guest cart -- held in localStorage, with no server cart
  // behind it (GET /cart/ is 401 for an anonymous caller by design).
  const stored = await page.evaluate(() => window.localStorage.getItem('guest-cart'))
  expect(JSON.parse(stored).state.items).toHaveLength(2)

  // --- Sign in ----------------------------------------------------------
  // Armed before signing in: LoginPage fires the merge inside its onSuccess,
  // so by the time the header shows "Sign out" the POST is already in flight.
  const mergeCall = page.waitForResponse(
    (response) => response.url().includes('/api/v1/cart/merge/'),
    { timeout: 30_000 },
  )

  await signIn(page, SHOPPER)

  const merge = await mergeCall
  expect(merge.ok(), `POST /cart/merge/ answered ${merge.status()}`).toBeTruthy()

  // --- The lines survived, on the server --------------------------------
  const token = await apiLogin(request, SHOPPER)
  const serverCart = await fetchServerCart(request, token)

  const byVariant = new Map(serverCart.items.map((item) => [item.variant_id, item]))
  expect(byVariant.get(fixture.buyable.id)?.quantity).toBe(STANDARD_QTY)
  expect(byVariant.get(fixture.capped.id)?.quantity).toBe(LIMITED_QTY)
  expect(serverCart.item_count).toBe(totalUnits)

  /*
   * And the shopper sees them. Reloaded rather than repainted, so the session
   * is rebuilt from the HttpOnly refresh cookie the way it would be on a real
   * return visit -- the access token lives in memory only and does not survive
   * a navigation.
   */
  await page.goto('/cart')
  await expect(
    page.getByRole('heading', { name: `Your cart (${totalUnits} items)` }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()

  const mergedItems = page.getByRole('region', { name: 'Cart items' })
  await expect(mergedItems.getByText(`SKU ${fixture.buyable.sku}`)).toBeVisible()
  await expect(mergedItems.getByText(`SKU ${fixture.capped.sku}`)).toBeVisible()

  // The local copy is dropped once the server holds it, so the two cannot
  // drift and the next sign-in cannot re-merge a stale basket.
  const afterMerge = await page.evaluate(() => window.localStorage.getItem('guest-cart'))
  expect(JSON.parse(afterMerge ?? '{"state":{"items":[]}}').state.items).toHaveLength(0)
})
