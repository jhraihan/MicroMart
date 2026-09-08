import { expect } from '@playwright/test'

import { ADMIN } from './fixture'

/*
 * The server-side truth channel.
 *
 * A green UI assertion proves the page painted something; it does not prove an
 * order was created correctly, or that stock moved. These helpers read the
 * same facts back out of the API so the checkout specs can assert on what the
 * database actually holds.
 *
 * They go through Playwright's `request` fixture, which is a separate context
 * from `page` -- it carries none of the browser's cookies, so verifying as an
 * admin can never accidentally borrow the shopper's session (or grant one).
 * Paths are relative to the Vite origin, which proxies /api to Django, so
 * these calls traverse exactly the path the app's own calls do.
 */

/*
 * One access token per account per worker.
 *
 * The auth endpoints share a throttle scope and the app itself spends that
 * budget on every full page load (App.jsx bootstraps with POST
 * /auth/refresh/). Logging in again for each verification call on top of that
 * is how this harness taught itself what a 429 looks like. Tokens last 15
 * minutes, comfortably longer than a run, so one login per account is enough.
 */
const tokens = new Map()

/** Sign in over the API and return the access token. */
export async function apiLogin(request, { email, password }) {
  const cached = tokens.get(email)
  if (cached) return cached

  const response = await request.post('/api/v1/auth/login/', {
    data: { email, password },
  })
  expect(
    response.ok(),
    `API login failed for ${email}: ${response.status()} ${await response.text()}`,
  ).toBeTruthy()
  const body = await response.json()
  expect(body.access, 'login response carried no access token').toBeTruthy()

  tokens.set(email, body.access)
  return body.access
}

function auth(token) {
  return { Authorization: `Bearer ${token}` }
}

/**
 * The live stock of one variant, read from the public catalogue.
 *
 * Read immediately before and immediately after a placement rather than taken
 * from the seed: the fixture guarantees a floor, not an exact number, and
 * anything else touching this dev database would make a remembered figure a
 * lie.
 */
export async function variantStock(request, productSlug, variantId) {
  const response = await request.get(`/api/v1/products/${productSlug}/`)
  expect(response.ok(), `could not read product ${productSlug}`).toBeTruthy()
  const product = await response.json()
  const variant = product.variants.find((item) => item.id === variantId)
  expect(variant, `variant ${variantId} is not on product ${productSlug}`).toBeTruthy()
  return variant.stock
}

/**
 * One order as the server holds it.
 *
 * Read through the admin endpoint on purpose: it is the only surface that can
 * see a *guest's* order, and a guest order is precisely the one the storefront
 * cannot read back (GET /orders/{reference}/ is IsAuthenticated -- see
 * docs/HANDOFF.md §4). Verifying through the customer's own session would only
 * work for half the specs.
 */
export async function fetchOrderAsAdmin(request, reference) {
  const token = await apiLogin(request, ADMIN)
  const response = await request.get(`/api/v1/admin/orders/${reference}/`, {
    headers: auth(token),
  })
  expect(
    response.ok(),
    `admin could not read order ${reference}: ${response.status()} ${await response.text()}`,
  ).toBeTruthy()
  return response.json()
}

/** The signed-in shopper's server cart, as JSON. */
export async function fetchServerCart(request, token) {
  const response = await request.get('/api/v1/cart/', { headers: auth(token) })
  expect(response.ok(), `could not read the server cart: ${response.status()}`).toBeTruthy()
  return response.json()
}

/**
 * Empty the account's server cart before a spec starts.
 *
 * Not housekeeping -- a correctness requirement. The cart persists between
 * runs, `POST /cart/merge/` *adds* to whatever is already there, and placement
 * orders the whole cart. A line left behind by a previous run would show up as
 * an extra order item and an inflated total, and every quantity assertion in
 * the merge spec would drift by one run's worth.
 */
export async function clearServerCart(request, credentials) {
  const token = await apiLogin(request, credentials)
  const cart = await fetchServerCart(request, token)
  for (const item of cart.items ?? []) {
    const response = await request.delete(`/api/v1/cart/items/${item.id}/`, {
      headers: auth(token),
    })
    expect(
      response.ok(),
      `could not remove cart item ${item.id}: ${response.status()}`,
    ).toBeTruthy()
  }
  return token
}
