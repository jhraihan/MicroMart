/*
 * Display helpers shared by the three order screens.
 *
 * Nothing here calculates money. An order's figures were computed server-side
 * and snapshotted at placement (FR-ORD-2, FR-CHK-6); these helpers relabel and
 * reshape that snapshot, never recompute it. `totalsFromOrder` is the sharpest
 * case: it exists precisely so the stored totals go through the same breakdown
 * component the quote does, instead of a second one that could drift.
 */

// The shop is in Bangladesh and the API sends UTC ISO strings, so timestamps
// are pinned to the shop's own clock rather than the reader's device.
const DHAKA = 'Asia/Dhaka'

const DAY = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: DHAKA,
})

const DAY_AND_TIME = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
  timeZone: DHAKA,
})

export function formatOrderDate(value, { withTime = false } = {}) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return (withTime ? DAY_AND_TIME : DAY).format(date)
}

/** Title-cased status, for the places a Badge is not the right element. */
export function statusLabel(status) {
  return status ? status[0].toUpperCase() + status.slice(1) : '—'
}

const PAYMENT_METHOD_LABELS = {
  cod: 'Cash on Delivery',
  online: 'Card / bKash / Nagad / Rocket',
}

export function paymentMethodLabel(code) {
  return PAYMENT_METHOD_LABELS[code] ?? 'Payment'
}

/*
 * `payment_status` is null until apps/payments writes a Payment row, and a COD
 * order never gets one -- the courier collects. Null therefore means "nothing
 * to report here", not "unpaid", so it is rendered as nothing at all.
 */
const PAYMENT_STATUS_LABELS = {
  initiated: 'Payment started',
  pending: 'Awaiting payment',
  paid: 'Paid',
  failed: 'Payment failed',
  cancelled: 'Payment cancelled',
  refunded: 'Refunded',
}

const PAYMENT_STATUS_TONES = {
  initiated: 'warning',
  pending: 'warning',
  paid: 'success',
  failed: 'danger',
  cancelled: 'danger',
  refunded: 'neutral',
}

export function paymentStatusLabel(status) {
  if (!status) return null
  return PAYMENT_STATUS_LABELS[status] ?? statusLabel(status)
}

export function paymentStatusTone(status) {
  return PAYMENT_STATUS_TONES[status] ?? 'neutral'
}

/**
 * Whether to offer the payment retry (FR-PAY-7).
 *
 * Read off the order, never off the redirect the browser came back through:
 * that redirect is display-only and proves nothing (FR-PAY-3). Order state
 * moves on the validated IPN alone.
 */
export function needsPayment(order) {
  if (!order || order.payment_method !== 'online') return false
  if (order.status === 'cancelled' || order.status === 'refunded') return false
  return order.payment_status !== 'paid'
}

const STATUS_EXPLAINERS = {
  confirmed: 'Confirmed and queued for packing — the items are set aside for you.',
  packed: 'Packed and waiting for the courier to collect it.',
  shipped: 'On its way. The courier calls the delivery number before arriving.',
  delivered: 'Delivered. Thank you for shopping with MicroMart.',
  cancelled: 'This order was cancelled. Nothing will be delivered and nothing is owed.',
  refunded: 'This order was refunded.',
}

/** One plain sentence about where the order stands right now. */
export function statusExplainer(order) {
  if (!order) return ''
  if (order.status === 'pending') {
    return order.payment_method === 'cod'
      ? 'We have your order and will call to confirm it before packing.'
      : 'Waiting for your payment to be confirmed. The order stays pending until it is.'
  }
  return STATUS_EXPLAINERS[order.status] ?? ''
}

const ACTOR_PHRASES = {
  customer: 'by you',
  admin: 'by MicroMart',
  system: 'automatically',
}

export function actorPhrase(role) {
  return ACTOR_PHRASES[role] ?? 'by MicroMart'
}

/**
 * A stored order in the shape `<OrderTotals>` reads.
 *
 * Every value is copied across untouched — no arithmetic, no coercion, no
 * parseFloat. Money stays the decimal string the API sent and only
 * `formatMoney` ever looks at it.
 */
export function totalsFromOrder(order) {
  if (!order) return null
  return {
    subtotal: order.subtotal,
    discount_total: order.discount_total,
    shipping_total: order.shipping_total,
    tax_total: order.tax_total,
    tax_rate_applied: order.tax_rate_applied,
    grand_total: order.grand_total,
    // VAT is added on top in v1; an order carries no tax-inclusive flag.
    prices_include_tax: false,
    coupon: order.coupon_code ? { code: order.coupon_code } : null,
    zone: order.shipping_zone ? { name: order.shipping_zone } : null,
  }
}
