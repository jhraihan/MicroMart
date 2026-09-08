/*
 * Catalogue URL state (FR-SRC-5).
 *
 * Every bit of search / filter / sort / page state lives in the query string,
 * never in component state, so copying a URL into a new tab reproduces the
 * identical result set. The URL parameter names are deliberately the same as
 * the API's (docs/api-contract-catalogue.md) -- one vocabulary, no mapping
 * table to drift.
 */

/** Canonical order, so the same filters always produce the same URL. */
export const PARAM_ORDER = [
  'q',
  'category',
  'brand',
  'min_price',
  'max_price',
  'in_stock',
  'min_rating',
  'has_discount',
  'sort',
  'page',
  'page_size',
]

/** Params the API accepts. Anything else is passed through the URL untouched. */
const API_PARAMS = new Set(PARAM_ORDER)

/** Repeatable (multi-select) params. Everything else is single-valued. */
const MULTI_PARAMS = new Set(['category', 'brand'])

/*
 * Presentation state that lives in the URL but is never sent to the API.
 * `view` decides grid vs list; it changes how the same result set is drawn,
 * not what is in it, so it is deliberately absent from PARAM_ORDER's
 * API_PARAMS set -- canonicalise() preserves it as an unknown key.
 */
export const VIEW_GRID = 'grid'
export const VIEW_LIST = 'list'

/** Scalar params forwarded verbatim once `q`, `category` and `brand` are done. */
const SCALAR_PARAMS = [
  'min_price',
  'max_price',
  'in_stock',
  'min_rating',
  'has_discount',
  'sort',
  'page',
  'page_size',
]

export const SORT_OPTIONS = [
  { value: 'relevance', label: 'Relevance', searchOnly: true },
  { value: 'newest', label: 'Newest arrivals' },
  { value: 'price_asc', label: 'Price: low to high' },
  { value: 'price_desc', label: 'Price: high to low' },
  { value: 'rating', label: 'Customer rating' },
  { value: 'best_selling', label: 'Best selling' },
]

export const RATING_OPTIONS = [4, 3, 2, 1]

export const DEFAULT_PAGE_SIZE = 24

/** The server's default sort: `relevance` when searching, `newest` otherwise. */
export function defaultSortFor(q) {
  return q ? 'relevance' : 'newest'
}

/**
 * Rebuild a URLSearchParams in canonical order, dropping empty values.
 * Unknown keys (utm_*, and anything a future feature adds) are preserved at
 * the end rather than silently discarded.
 */
export function canonicalise(params) {
  const out = new URLSearchParams()
  for (const key of PARAM_ORDER) {
    for (const value of params.getAll(key)) {
      if (value !== '') out.append(key, value)
    }
  }
  for (const [key, value] of params.entries()) {
    if (!API_PARAMS.has(key) && value !== '') out.append(key, value)
  }
  return out
}

/**
 * Apply a patch to the current query string and return the next one.
 *
 * `null` / `''` / `false` removes a key, `true` writes `"true"`, and an array
 * writes one entry per value (the repeatable filters). Page is reset to 1 on
 * every change that is not itself a page change -- otherwise narrowing a
 * filter from page 7 lands the shopper on an empty page.
 */
export function applyPatch(current, patch) {
  const next = new URLSearchParams(current)

  for (const [key, value] of Object.entries(patch)) {
    next.delete(key)
    if (value === null || value === undefined || value === '' || value === false) {
      continue
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== null && item !== undefined && item !== '') next.append(key, String(item))
      }
    } else if (value === true) {
      next.set(key, 'true')
    } else {
      next.set(key, String(value))
    }
  }

  if (!Object.prototype.hasOwnProperty.call(patch, 'page')) next.delete('page')
  return canonicalise(next)
}

/** Read the query string into a plain, comparable object. */
export function parseState(params) {
  const q = params.get('q') ?? ''
  return {
    q,
    category: params.getAll('category').filter(Boolean),
    brand: params.getAll('brand').filter(Boolean),
    min_price: params.get('min_price') ?? '',
    max_price: params.get('max_price') ?? '',
    in_stock: params.get('in_stock') === 'true',
    min_rating: params.get('min_rating') ?? '',
    has_discount: params.get('has_discount') === 'true',
    sort: params.get('sort') ?? '',
    page: Math.max(1, Number.parseInt(params.get('page') ?? '1', 10) || 1),
    page_size: Number.parseInt(params.get('page_size') ?? '', 10) || DEFAULT_PAGE_SIZE,
  }
}

/**
 * Build the query string sent to GET /api/v1/products/.
 *
 * `lockedCategory` is the category page's own slug. It scopes the request
 * only while no category facet is checked; once the shopper ticks a child
 * category the checked slugs replace it, because the API ORs multiple
 * `category` values together and adding the parent back would widen the
 * result set instead of narrowing it.
 */
export function buildApiQuery(params, lockedCategory) {
  const state = parseState(params)
  const out = new URLSearchParams()

  if (state.q) out.set('q', state.q)

  const categories = state.category.length
    ? state.category
    : lockedCategory
      ? [lockedCategory]
      : []
  for (const slug of categories) out.append('category', slug)
  for (const slug of state.brand) out.append('brand', slug)

  for (const key of SCALAR_PARAMS) {
    const value = params.get(key)
    if (value) out.set(key, value)
  }

  return out.toString()
}

/** How many filters (not sort, not page, not the keyword) are active. */
export function countActiveFilters(state) {
  return (
    state.category.length +
    state.brand.length +
    (state.min_price ? 1 : 0) +
    (state.max_price ? 1 : 0) +
    (state.in_stock ? 1 : 0) +
    (state.min_rating ? 1 : 0) +
    (state.has_discount ? 1 : 0)
  )
}

export { MULTI_PARAMS }
