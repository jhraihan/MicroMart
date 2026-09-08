/*
 * The order reference the browser left with, remembered across the round
 * trip to SSLCommerz.
 */

const KEY = 'micromart:pending-payment-reference'

/*
 * Mirrors the pattern the server applies to a reference before it will echo
 * one back (apps/payments/services/payments.py). A reference arrives here from
 * a URL anyone can type, and it goes straight back out into a request path, so
 * anything that does not look like one of ours is dropped rather than used.
 */
const REFERENCE_PATTERN = /^[A-Za-z0-9-]{1,24}$/

export function isPaymentReference(value) {
  return REFERENCE_PATTERN.test(String(value ?? '').trim())
}

/** Called just before the browser is handed to the gateway. */
export function rememberPendingPayment(reference) {
  if (!isPaymentReference(reference)) return
  try {
    window.sessionStorage.setItem(KEY, String(reference).trim())
  } catch {
    // Storage denied. The return screen falls back to the URL, and failing
    // that says so honestly rather than guessing.
  }
}

export function readPendingPayment() {
  try {
    const stored = window.sessionStorage.getItem(KEY)
    return isPaymentReference(stored) ? stored.trim() : ''
  } catch {
    return ''
  }
}

export function forgetPendingPayment() {
  try {
    window.sessionStorage.removeItem(KEY)
  } catch {
    // Nothing to do: the value expires with the tab regardless.
  }
}
