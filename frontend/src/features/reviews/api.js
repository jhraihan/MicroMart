import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { catalogKeys } from '@/features/catalog/api'

// Reviews data access, against the endpoints in apps/reviews/urls.py:

export const reviewKeys = {
  all: ['reviews'],
  /** Prefix over every page/filter of one product's list. */
  product: (slug) => ['reviews', 'product', slug],
  list: (slug, params) => ['reviews', 'product', slug, params],
  /** The caller's own copy of their review -- see useMyReview below. */
  mine: (slug) => ['reviews', 'mine', slug],
}

/** GET /products/{slug}/reviews/ */
export function useProductReviews(slug, { page = 1, rating = null, sort = 'recent' } = {}) {
  return useQuery({
    queryKey: reviewKeys.list(slug, { page, rating, sort }),
    queryFn: async ({ signal }) => {
      const params = {}
      if (page > 1) params.page = page
      if (rating) params.rating = rating
      if (sort && sort !== 'recent') params.sort = sort
      const { data } = await api.get(
        `/products/${encodeURIComponent(slug)}/reviews/`,
        { params, signal },
      )
      return data
    },
    enabled: Boolean(slug),
    // Hold the current reviews on screen while the next page or a newly
    // ticked star filter loads, exactly as the product grid does.
    placeholderData: keepPreviousData,
  })
}

/**
 * The caller's own review of this product, for this session.
 *
 * A deliberately never-fetched cache slot: there is no `GET my review`
 * endpoint, and the public list carries approved reviews only -- so a
 * just-submitted (pending) review appears in no response at all. The POST and
 * PATCH responses are the only copy that exists, and they are written here so
 * the "awaiting moderation" panel survives navigating away and back within
 * the SPA session. A reload clears it, which is honest: the client has no way
 * to re-read a pending review, and inventing a persisted copy would keep
 * claiming "awaiting moderation" long after a moderator approved it.
 */
export function useMyReview(slug) {
  return useQuery({
    queryKey: reviewKeys.mine(slug),
    queryFn: () => null,
    enabled: false,
    staleTime: Infinity,
    gcTime: Infinity,
  })
}

/** POST /products/{slug}/reviews/ -- the new review is always `pending`. */
export function useSubmitReview(slug) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ rating, title, body }) => {
      const { data } = await api.post(`/products/${encodeURIComponent(slug)}/reviews/`, {
        rating,
        title,
        body,
      })
      return data
    },
    onSuccess: (review) => {
      queryClient.setQueryData(reviewKeys.mine(slug), review)
      // The list will not contain it -- it is pending -- but `can_review`
      // has just flipped to false, so the form must stop being offered.
      queryClient.invalidateQueries({ queryKey: reviewKeys.product(slug) })
    },
    retry: false,
  })
}

/**
 * PATCH /reviews/{id}/ -- the author's own edit, inside the 30-day window.
 *
 * An edit returns the review to `pending` and recomputes the product
 * aggregate server-side, so the product detail cache is invalidated too: the
 * stars in the page header are the figure this write just changed.
 */
export function useUpdateReview(slug) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, ...values }) => {
      const { data } = await api.patch(`/reviews/${id}/`, values)
      return data
    },
    onSuccess: (review) => {
      queryClient.setQueryData(reviewKeys.mine(slug), review)
      queryClient.invalidateQueries({ queryKey: reviewKeys.product(slug) })
      queryClient.invalidateQueries({ queryKey: catalogKeys.product(slug) })
    },
    retry: false,
  })
}

/** DELETE /reviews/{id}/ -- the author withdraws it (the FR-REV-5 removal path). */
export function useDeleteReview(slug) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id) => {
      await api.delete(`/reviews/${id}/`)
      return id
    },
    onSuccess: () => {
      queryClient.setQueryData(reviewKeys.mine(slug), null)
      queryClient.invalidateQueries({ queryKey: reviewKeys.product(slug) })
      queryClient.invalidateQueries({ queryKey: catalogKeys.product(slug) })
    },
    retry: false,
  })
}
