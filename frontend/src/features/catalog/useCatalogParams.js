import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  applyPatch,
  buildApiQuery,
  countActiveFilters,
  defaultSortFor,
  parseState,
} from './searchParams'

/**
 * The single source of truth for a listing page's state (FR-SRC-5).
 *
 * Nothing here is held in React state: the URL *is* the state. Every mutator
 * writes back through `setSearchParams`, so the back button, a bookmark and a
 * copy-pasted link all behave identically.
 *
 * @param {object}  options
 * @param {?string} options.lockedCategory slug of the category page we are on
 */
export function useCatalogParams({ lockedCategory = null } = {}) {
  const [searchParams, setSearchParams] = useSearchParams()

  const state = useMemo(() => parseState(searchParams), [searchParams])
  const apiQuery = useMemo(
    () => buildApiQuery(searchParams, lockedCategory),
    [searchParams, lockedCategory],
  )

  const setParams = useCallback(
    (patch) => {
      setSearchParams((prev) => applyPatch(prev, patch))
    },
    [setSearchParams],
  )

  /** Add or remove one value of a repeatable filter (brand, category). */
  const toggleValue = useCallback(
    (key, value) => {
      setSearchParams((prev) => {
        const current = prev.getAll(key)
        const next = current.includes(value)
          ? current.filter((v) => v !== value)
          : [...current, value]
        return applyPatch(prev, { [key]: next })
      })
    },
    [setSearchParams],
  )

  /** Drop every filter but keep the keyword and the sort the shopper chose. */
  const clearFilters = useCallback(() => {
    setSearchParams((prev) =>
      applyPatch(prev, {
        category: null,
        brand: null,
        min_price: null,
        max_price: null,
        in_stock: null,
        min_rating: null,
        has_discount: null,
      }),
    )
  }, [setSearchParams])

  /** `to={{ search: hrefForPage(3) }}` -- real links, so middle-click works. */
  const hrefForPage = useCallback(
    (page) => `?${applyPatch(searchParams, { page }).toString()}`,
    [searchParams],
  )

  return {
    searchParams,
    state,
    apiQuery,
    // Presentation only -- see VIEW_* in searchParams.js. Defaults to grid.
    view: searchParams.get('view') === 'list' ? 'list' : 'grid',
    effectiveSort: state.sort || defaultSortFor(state.q),
    activeFilterCount: countActiveFilters(state),
    setParams,
    toggleValue,
    clearFilters,
    hrefForPage,
  }
}
