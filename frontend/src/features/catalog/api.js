import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

/*
 * TanStack Query hooks for the catalogue endpoints in
 * docs/api-contract-catalogue.md. Nothing here transforms money -- decimal
 * strings go straight to formatMoney(), and the server stays authoritative
 * on every number.
 */

export const catalogKeys = {
  all: ['catalog'],
  categories: () => ['catalog', 'categories'],
  brands: () => ['catalog', 'brands'],
  // The query string is the identity of a result set, which is exactly what
  // FR-SRC-5 makes the URL mean too.
  products: (query) => ['catalog', 'products', query],
  product: (slug) => ['catalog', 'product', slug],
  related: (slug) => ['catalog', 'product', slug, 'related'],
}

async function get(url, signal) {
  const { data } = await api.get(url, { signal })
  return data
}

/** GET /categories/ -- the full tree, one level of nesting. */
export function useCategories() {
  return useQuery({
    queryKey: catalogKeys.categories(),
    queryFn: ({ signal }) => get('/categories/', signal),
    staleTime: 10 * 60_000, // navigation chrome; it barely changes
  })
}

/** GET /brands/ */
export function useBrands() {
  return useQuery({
    queryKey: catalogKeys.brands(),
    queryFn: ({ signal }) => get('/brands/', signal),
    staleTime: 10 * 60_000,
  })
}

/**
 * GET /products/?<query>
 *
 * `keepPreviousData` keeps the current grid on screen while the next page or
 * a newly ticked facet loads, so the page does not collapse to a spinner and
 * bounce the scroll position on every filter change.
 */
export function useProducts(query, options = {}) {
  return useQuery({
    queryKey: catalogKeys.products(query),
    queryFn: ({ signal }) => get(`/products/${query ? `?${query}` : ''}`, signal),
    placeholderData: keepPreviousData,
    ...options,
  })
}

/** GET /products/{slug}/ -- inactive products 404 (FR-CAT-7). */
export function useProduct(slug) {
  return useQuery({
    queryKey: catalogKeys.product(slug),
    queryFn: ({ signal }) => get(`/products/${encodeURIComponent(slug)}/`, signal),
    enabled: Boolean(slug),
  })
}

/** GET /products/{slug}/related/ -- bare array, in-stock only (FR-CAT-6). */
export function useRelatedProducts(slug, options = {}) {
  return useQuery({
    queryKey: catalogKeys.related(slug),
    queryFn: ({ signal }) => get(`/products/${encodeURIComponent(slug)}/related/`, signal),
    enabled: Boolean(slug),
    ...options,
  })
}

/** Depth-first lookup over the one-level category tree. */
export function findCategory(tree, slug) {
  if (!tree || !slug) return null
  for (const node of tree) {
    if (node.slug === slug) return { category: node, parent: null }
    for (const child of node.children ?? []) {
      if (child.slug === slug) return { category: child, parent: node }
    }
  }
  return null
}

/**
 * GET /search/suggest/?q= -- the header type-ahead (FR-SRC-6).
 *
 * Short `staleTime` rather than none: a shopper who backspaces a character
 * and retypes it should not re-hit the API, but a suggestion list must not
 * outlive a price change by long.
 */
export function useSearchSuggestions(keyword, options = {}) {
  const trimmed = (keyword ?? '').trim()
  return useQuery({
    queryKey: ['catalog', 'suggest', trimmed],
    queryFn: ({ signal }) =>
      get(`/search/suggest/?q=${encodeURIComponent(trimmed)}`, signal),
    // Two characters is the server's own floor; asking below it just burns a
    // round trip to get an empty list back.
    enabled: trimmed.length >= 2,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    ...options,
  })
}

/** GET /products/compare/?slugs=a,b,c -- products plus the spec matrix. */
export function useCompare(slugs, options = {}) {
  const key = (slugs ?? []).join(',')
  return useQuery({
    queryKey: ['catalog', 'compare', key],
    queryFn: ({ signal }) =>
      get(`/products/compare/?slugs=${encodeURIComponent(key)}`, signal),
    enabled: Boolean(key),
    ...options,
  })
}

/** GET /products/{slug}/bought-together/ -- real co-purchase data, may be empty. */
export function useBoughtTogether(slug, options = {}) {
  return useQuery({
    queryKey: ['catalog', 'product', slug, 'bought-together'],
    queryFn: ({ signal }) =>
      get(`/products/${encodeURIComponent(slug)}/bought-together/`, signal),
    enabled: Boolean(slug),
    ...options,
  })
}
