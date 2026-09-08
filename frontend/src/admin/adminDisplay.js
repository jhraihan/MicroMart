/*
 * Labels, presets and day arithmetic shared by the admin screens.
 *
 * Nothing here computes money and nothing here decides what is legal. The
 * transition table lives on the server (PRD §15.1) and arrives on every order
 * as `allowed_transitions`; this file only supplies the wording and the tone
 * for a transition the server has already said it would accept.
 */

/*
 * The shop is in Bangladesh and the dashboard's windows are whole *local*
 * days (apps/dashboard/services/metrics.py computes them with
 * timezone.localtime). A date filter built from the reader's own device clock
 * would ask for a different day than the tile counted, so every date this
 * module produces is a Dhaka day.
 */
const SHOP_TZ = 'Asia/Dhaka'

const ISO_DAY = new Intl.DateTimeFormat('en-CA', {
  timeZone: SHOP_TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/** Today in the shop's timezone, as `YYYY-MM-DD` -- the API's date format. */
export function shopToday() {
  return ISO_DAY.format(new Date())
}

/**
 * `days` whole days before the shop's today, as `YYYY-MM-DD`.
 *
 * The shop day is re-anchored to UTC midnight before the subtraction so the
 * arithmetic is whole days on a fixed clock, never a DST-shifted 24 hours.
 */
export function shopDaysAgo(days) {
  const anchor = Date.parse(`${shopToday()}T00:00:00Z`)
  return new Date(anchor - days * 86_400_000).toISOString().slice(0, 10)
}

// --- Statuses ---------------------------------------------------------------

/** Every status the state machine knows, in pipeline order (PRD §15.1). */
export const ORDER_STATUSES = [
  'pending',
  'confirmed',
  'packed',
  'shipped',
  'delivered',
  'cancelled',
  'refunded',
]

/** What sits on the admin's desk -- the same three metrics.py counts. */
export const AWAITING_ACTION_STATUSES = ['pending', 'confirmed', 'packed']

export const PAYMENT_METHOD_OPTIONS = [
  { value: '', label: 'Any payment method' },
  { value: 'cod', label: 'Cash on Delivery' },
  { value: 'online', label: 'Online (SSLCommerz)' },
]

const PAYMENT_METHOD_SHORT = {
  cod: 'COD',
  online: 'Online',
}

export function paymentMethodShort(code) {
  return PAYMENT_METHOD_SHORT[code] ?? code ?? '—'
}

export function titleCase(value) {
  return value ? value[0].toUpperCase() + value.slice(1) : '—'
}

// --- Transitions ------------------------------------------------------------

/*
 * The verb for each destination status, plus how hard the button should push.
 *
 * `destructive` marks the two moves that cannot be walked back: cancelling
 * restores stock and releases the coupon, and a refund is a manual accounting
 * record. Both go through a confirmation step; the forward moves do not,
 * because the owner has to get an order out of the door in under a minute
 * (PRD §3.2) and a modal per step is most of that minute.
 */
const TRANSITION_ACTIONS = {
  confirmed: {
    label: 'Confirm order',
    hint: 'Reserves stock and emails the customer.',
    variant: 'primary',
  },
  packed: {
    label: 'Mark packed',
    hint: 'The parcel is made up and waiting for the courier.',
    variant: 'primary',
  },
  shipped: {
    label: 'Mark shipped',
    hint: 'Needs a courier and tracking number first.',
    variant: 'primary',
    requiresShipment: true,
  },
  delivered: {
    label: 'Mark delivered',
    hint: 'Closes the order and unlocks the customer’s review.',
    variant: 'primary',
  },
  cancelled: {
    label: 'Cancel order',
    hint: 'Restores stock and releases any coupon.',
    variant: 'danger',
    destructive: true,
  },
  refunded: {
    label: 'Record refund',
    hint: 'A manual record only — no gateway call in v1.',
    variant: 'danger',
    destructive: true,
  },
}

/**
 * Describe one of the server's `allowed_transitions`.
 *
 * An unrecognised status still yields a usable button rather than nothing:
 * the server said it would accept the move, so refusing to render it here
 * would hide a legal action behind a missing lookup entry.
 */
export function transitionAction(status) {
  return (
    TRANSITION_ACTIONS[status] ?? {
      label: `Mark ${status}`,
      hint: '',
      variant: 'primary',
    }
  )
}

/**
 * The transitions to offer, in the order the pipeline runs.
 *
 * A convenience only. `allowed_transitions` comes straight off the state
 * machine, and POSTing a status that is not in it is still refused with 422 --
 * this sort only decides which button is leftmost.
 */
export function orderedTransitions(allowed = []) {
  const rank = (status) => {
    const index = ORDER_STATUSES.indexOf(status)
    return index === -1 ? ORDER_STATUSES.length : index
  }
  return [...allowed].sort((a, b) => rank(a) - rank(b))
}

// --- Numbers ----------------------------------------------------------------

const COUNT = new Intl.NumberFormat('en-BD')

export function formatCount(value) {
  const number = Number(value ?? 0)
  return Number.isNaN(number) ? '0' : COUNT.format(number)
}

/**
 * A compact axis tick (`৳1.2k`).
 *
 * This is the one place a money value becomes a number, and it is an axis
 * label -- a position on a scale, not a total anybody is owed. Every figure a
 * person reads as an amount goes through `formatMoney` on the server's
 * decimal string instead.
 */
export function compactMoneyTick(value) {
  const number = Number(value ?? 0)
  if (!Number.isFinite(number)) return ''
  if (Math.abs(number) >= 1_000_000) return `৳${(number / 1_000_000).toFixed(1)}m`
  if (Math.abs(number) >= 1_000) return `৳${(number / 1_000).toFixed(1)}k`
  return `৳${COUNT.format(number)}`
}
