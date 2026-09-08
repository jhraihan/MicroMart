/*
 * FR-WSH-4: a wishlist click while signed out prompts login, and the add
 * completes once authentication succeeds.
 */
const KEY = 'wishlist-intent'

export function rememberWishlistIntent(productId) {
  try {
    sessionStorage.setItem(KEY, String(productId))
  } catch {
    // No storage: the shopper signs in and taps the heart again.
  }
}

/** Read and clear in one step, so a replay can never run twice. */
export function takeWishlistIntent() {
  try {
    const raw = sessionStorage.getItem(KEY)
    sessionStorage.removeItem(KEY)
    const productId = Number.parseInt(raw ?? '', 10)
    return Number.isFinite(productId) ? productId : null
  } catch {
    return null
  }
}
