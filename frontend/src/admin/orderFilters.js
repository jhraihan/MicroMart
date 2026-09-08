import { ORDER_STATUSES } from './adminDisplay'

/*
 * Pipeline filter state lives in the URL, not in component state.
 *
 * That is what lets a dashboard tile *be* a link to the list behind it
 * (US-A1), and what makes the back button walk back through filters instead
 * of out of the screen. The parameter names are the API's own, so the address
 * bar and the request agree and there is no mapping table to drift.
 */

/** Canonical order, so the same filters always produce the same URL. */
const PARAM_ORDER = ['q', 'status', 'payment_method', 'placed_from', 'placed_to', 'page']

const VALID_PAYMENT_METHODS = new Set(['cod', 'online'])
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

/**
 * Read filters off the query string.
 *
 * Unknown statuses and malformed dates are dropped here rather than forwarded.
 * The server answers a bad filter with 422 INVALID_FILTER and that is the
 * right answer for a hand-typed URL, but this app should not be the thing
 * generating one.
 */
export function parseOrderFilters(searchParams) {
  const status = (searchParams.get('status') || '')
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter((value) => ORDER_STATUSES.includes(value))

  const paymentMethod = (searchParams.get('payment_method') || '').trim().toLowerCase()
  const from = (searchParams.get('placed_from') || '').trim()
  const to = (searchParams.get('placed_to') || '').trim()
  const page = Number.parseInt(searchParams.get('page') || '1', 10)

  return {
    q: searchParams.get('q') || '',
    // De-duplicated and put back into pipeline order, so ?status=packed,pending
    // and ?status=pending,packed are one cache key rather than two.
    status: ORDER_STATUSES.filter((value) => status.includes(value)),
    payment_method: VALID_PAYMENT_METHODS.has(paymentMethod) ? paymentMethod : '',
    placed_from: ISO_DAY.test(from) ? from : '',
    placed_to: ISO_DAY.test(to) ? to : '',
    page: Number.isFinite(page) && page > 0 ? page : 1,
  }
}

/** The query string for a set of filters, defaults omitted. */
export function buildOrderSearch(filters = {}) {
  const params = new URLSearchParams()

  for (const key of PARAM_ORDER) {
    const value = filters[key]
    if (value === undefined || value === null || value === '') continue
    if (key === 'status') {
      if (Array.isArray(value) && value.length) params.set('status', value.join(','))
      continue
    }
    if (key === 'page') {
      if (Number(value) > 1) params.set('page', String(value))
      continue
    }
    params.set(key, String(value))
  }

  const search = params.toString()
  return search ? `?${search}` : ''
}

/** A link to the pipeline, filtered. This is what a dashboard tile points at. */
export function ordersHref(filters = {}) {
  return `/admin/orders${buildOrderSearch(filters)}`
}

export function hasActiveFilters(filters) {
  return Boolean(
    filters.q ||
      filters.status.length ||
      filters.payment_method ||
      filters.placed_from ||
      filters.placed_to,
  )
}
