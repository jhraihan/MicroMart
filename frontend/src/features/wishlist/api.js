import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'

// Wishlist data access, against apps/reviews/urls.py:

export const wishlistKeys = {
  all: ['wishlist'],
  list: (page) => ['wishlist', 'list', page],
  ids: () => ['wishlist', 'ids'],
}

/** GET /wishlist/ -- one page, for the wishlist screen. */
export function useWishlist(page = 1) {
  const user = useAuthStore((s) => s.user)

  return useQuery({
    queryKey: wishlistKeys.list(page),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/wishlist/', { params: { page }, signal })
      return data
    },
    enabled: Boolean(user),
    // Price and stock are re-read every time the page is opened (FR-WSH-2),
    // so a cached wishlist is never good enough.
    staleTime: 0,
    placeholderData: keepPreviousData,
  })
}

// Every saved product id, for the heart on a card or a product page.
const MAX_PAGES = 20
const PAGE_SIZE = 100

export function useWishlistIds() {
  const user = useAuthStore((s) => s.user)

  return useQuery({
    queryKey: wishlistKeys.ids(),
    queryFn: async ({ signal }) => {
      const ids = []
      for (let page = 1; page <= MAX_PAGES; page += 1) {
        // Page numbers are built here rather than following `next`: that URL
        // is absolute and would bypass the dev proxy, taking the session
        // cookie with it.
        const { data } = await api.get('/wishlist/', {
          params: { page, page_size: PAGE_SIZE },
          signal,
        })
        for (const item of data.results ?? []) {
          if (item.product?.id != null) ids.push(item.product.id)
        }
        if (!data.next) break
      }
      return ids
    },
    enabled: Boolean(user),
    staleTime: 60_000,
  })
}

/** Is this product on the caller's wishlist? False for a signed-out visitor. */
export function useIsWishlisted(productId) {
  const { data } = useWishlistIds()
  return Array.isArray(data) && data.includes(productId)
}

/*
 * Add and remove.
 *
 * Called once per control, so `isPending` is that control's own state -- one
 * card's heart never spins because another card's did.
 *
 * The id list is updated optimistically so the heart answers the tap
 * immediately, then reconciled from the server on settle. The server is
 * idempotent on a repeat add (200 rather than an error), so the worst case of
 * a double tap is a redundant request, never a duplicate row.
 */
export function useWishlistMutations() {
  const queryClient = useQueryClient()

  const patchIds = async (productId, saved) => {
    await queryClient.cancelQueries({ queryKey: wishlistKeys.ids() })
    const previous = queryClient.getQueryData(wishlistKeys.ids())
    queryClient.setQueryData(wishlistKeys.ids(), (ids) => {
      const current = Array.isArray(ids) ? ids : []
      if (saved) return current.includes(productId) ? current : [...current, productId]
      return current.filter((id) => id !== productId)
    })
    return { previous }
  }

  const rollback = (_error, _variables, context) => {
    if (context) queryClient.setQueryData(wishlistKeys.ids(), context.previous)
  }

  const settle = () => queryClient.invalidateQueries({ queryKey: wishlistKeys.all })

  const add = useMutation({
    mutationFn: async (productId) => {
      const { data } = await api.post('/wishlist/', { product_id: productId })
      return data
    },
    onMutate: (productId) => patchIds(productId, true),
    onError: rollback,
    onSettled: settle,
  })

  const remove = useMutation({
    mutationFn: async (productId) => {
      await api.delete(`/wishlist/${productId}/`)
      return productId
    },
    onMutate: (productId) => patchIds(productId, false),
    onError: rollback,
    onSettled: settle,
  })

  return { add, remove }
}
