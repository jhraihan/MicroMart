import { expect } from '@playwright/test'

/*
 * Shared journeys, expressed the way a shopper performs them.
 *
 * Everything here addresses the page by role and visible text. Nothing reaches
 * for a CSS class or a test id, because a class is a styling decision that can
 * change without the experience changing -- and, more to the point, a class
 * selector cannot tell the difference between a page that renders and a page
 * that renders *the right thing*, which is the failure mode this suite exists
 * to catch (docs/HANDOFF.md §4, the serializer/contract mismatch).
 */

/** Order references look like ORD-2026-000148 (orders/services/placement.py). */
export const REFERENCE_PATTERN = /ORD-\d{4}-\d{6}/

/**
 * Sign in the way a shopper does -- through the form.
 *
 * Deliberately not by injecting a token: the access token lives in memory and
 * the refresh token in an HttpOnly cookie, so forging a session would skip the
 * exact mechanism most likely to break and would not exercise the cart merge
 * that LoginPage fires on success.
 */
export async function signIn(page, { email, password }) {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()

  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()

  // The header only grows a "Sign out" control once the store holds a user, so
  // this waits on the session itself rather than on a URL change.
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
}

/**
 * Add one variant to whichever cart is live, from its product page.
 *
 * The confirmation is awaited rather than assumed: for a signed-in shopper the
 * add is a POST the server can refuse, and ProductDetailPage holds the message
 * back until it lands.
 */
export async function addVariantToCart(page, { productSlug, variantId, quantity = 1 }) {
  await page.goto(`/p/${productSlug}?variant=${variantId}`)

  const addButton = page.getByRole('button', { name: 'Add to cart', exact: true })
  await expect(addButton).toBeEnabled()

  if (quantity > 1) {
    const increase = page.getByRole('button', { name: 'Increase quantity' })
    for (let i = 1; i < quantity; i += 1) await increase.click()
    // spinbutton, not getByLabel: the two stepper buttons are labelled
    // "Increase/Decrease quantity", so a label lookup for "Quantity" matches
    // all three controls.
    await expect(page.getByRole('spinbutton', { name: 'Quantity' })).toHaveValue(
      String(quantity),
    )
  }

  await addButton.click()
  await expect(page.getByText(/added to your cart/i)).toBeVisible()
}

/** A Dhaka delivery address -- Dhaka resolves to the "Inside Dhaka" zone. */
export const DHAKA_ADDRESS = {
  email: 'e2e-guest@example.com',
  phone: '01712345678',
  recipientName: 'E2E Guest Shopper',
  division: 'Dhaka',
  district: 'Dhaka',
  upazila: 'Dhanmondi',
  area: 'Road 27',
  street: 'House 12, Road 27, Dhanmondi',
  postcode: '1209',
}

/** Fill the guest contact + new-address half of checkout. */
export async function fillNewAddress(page, address = DHAKA_ADDRESS) {
  await page.getByLabel('Email').fill(address.email)
  await page.getByLabel('Mobile number').fill(address.phone)

  await page.getByLabel('Recipient name').fill(address.recipientName)
  await page.getByLabel('Delivery phone').fill(address.phone)

  await page.getByLabel('Division').selectOption(address.division)
  // The district list is derived from the division, so it only has real
  // options once the division above is set.
  await page.getByLabel('District').selectOption(address.district)

  await page.getByLabel('Upazila / Thana').fill(address.upazila)
  await page.getByLabel('Area').fill(address.area)
  await page.getByLabel('Street address').fill(address.street)
  await page.getByLabel('Postcode').fill(address.postcode)
}

/**
 * Place the order and return the reference the confirmation screen shows.
 *
 * Waits for the button to become enabled first: `can_place_order` is the
 * server's verdict, arriving with the quote, and clicking before it lands is
 * how this step would flake.
 */
export async function placeOrder(page) {
  const button = page.getByRole('button', { name: 'Place order' })
  await expect(button).toBeEnabled({ timeout: 30_000 })
  await button.click()

  await page.waitForURL(/\/order\/ORD-\d{4}-\d{6}$/, { timeout: 45_000 })
  await expect(page.getByText('Order placed')).toBeVisible()

  const reference = new URL(page.url()).pathname.split('/').pop()
  expect(reference).toMatch(REFERENCE_PATTERN)
  return reference
}

/**
 * How the storefront renders an amount, so a spec can assert on the figure a
 * shopper actually reads.
 *
 * Mirrors lib/money.js exactly -- narrow symbol, grouped, and *trailing zeroes
 * dropped* (minimumFractionDigits is 0), which is why "1260.00" reads as
 * "৳1,260" and not "৳1,260.00".
 */
export function formatMoney(value) {
  const amount = Number(value)
  return new Intl.NumberFormat('en-BD', {
    style: 'currency',
    currency: 'BDT',
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })
    .format(amount)
    .replace('BDT', '৳')
}

/**
 * The product names currently on the grid, in the order it shows them.
 *
 * Addressed through the card's own landmark and heading rather than its
 * classes, so a restyle cannot break it. An empty grid is a legitimate answer
 * (a filter that matched nothing), hence the swallowed wait.
 */
export async function visibleProductNames(page) {
  const headings = page.getByRole('article').getByRole('heading', { level: 3 })
  await headings
    .first()
    .waitFor({ state: 'visible', timeout: 15_000 })
    .catch(() => {})
  const names = await headings.allTextContents()
  return names.map((name) => name.trim())
}
