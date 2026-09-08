import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

/*
 * Cart and checkout-quote data access, against
 * docs/api-contract-cart-checkout-orders.md.
 *
 * The rule this module exists to enforce: no money is ever calculated here.
 * The quote endpoint is the only source of a subtotal, a discount, a shipping
 * charge, a VAT figure or a grand total (FR-CRT-4, FR-CHK-6). Anything the
 * client holds -- the guest cart's stored unit price -- is a display snapshot
 * with no authority, and is superseded the moment a quote lands.
 */

export const cartKeys = {
  all: ['cart'],
  cart: () => ['cart', 'server'],
  quote: (input) => ['cart', 'quote', input],
}

/** GET /cart/ -- the server cart, authenticated users only (FR-CRT-1). */
export function useServerCart(enabled) {
  return useQuery({
    queryKey: cartKeys.cart(),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/cart/', { signal })
      return data
    },
    enabled,
    // Stock and price are re-read every time the cart is opened (FR-CRT-5),
    // so a cached cart is never good enough.
    staleTime: 0,
  })
}

/*
 * Every cart mutation answers with the whole cart, so the response is written
 * straight into the cache. Nothing is patched locally -- a client that edits
 * its own copy of a total is exactly what FR-CRT-4 forbids.
 */
/**
 * POST /cart/items/ -- add a variant to the signed-in shopper's server cart.
 *
 * Adding never reserves stock (PRD §6.5); the endpoint answers with the whole
 * cart, which is written straight into the cache like every other cart
 * mutation. Used by "move to cart" on the wishlist, where the shopper is
 * authenticated by definition.
 */
export function useAddCartItem() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ variantId, quantity = 1 }) => {
      const { data } = await api.post('/cart/items/', {
        variant_id: variantId,
        quantity,
      })
      return data
    },
    onSuccess: (data) => queryClient.setQueryData(cartKeys.cart(), data),
  })
}

export function useServerCartMutations() {
  const queryClient = useQueryClient()
  const write = (data) => queryClient.setQueryData(cartKeys.cart(), data)

  const setQuantity = useMutation({
    mutationFn: async ({ itemId, quantity }) => {
      const { data } = await api.patch(`/cart/items/${itemId}/`, { quantity })
      return data
    },
    onSuccess: write,
  })

  const remove = useMutation({
    mutationFn: async ({ itemId }) => {
      const { data } = await api.delete(`/cart/items/${itemId}/`)
      return data
    },
    onSuccess: write,
  })

  return { setQuantity, remove }
}

/**
 * POST /checkout/quote/ -- the server's arithmetic, read as a query.
 *
 * It is a POST because the cart travels in the body, but it is a read: it
 * changes nothing, and re-running it is free. Modelling it as a query is what
 * gives the "recompute on every district, coupon or quantity change"
 * requirement its implementation -- those values *are* the query key, so a
 * change to any of them refetches by construction rather than by remembering
 * to call something.
 */
export function useCheckoutQuote(input, options = {}) {
  const { items, district, couponCode, paymentMethod } = input

  return useQuery({
    queryKey: cartKeys.quote({ items, district, couponCode, paymentMethod }),
    queryFn: async ({ signal }) => {
      const body = { items }
      if (district) body.district = district
      if (couponCode) body.coupon_code = couponCode
      if (paymentMethod) body.payment_method = paymentMethod
      const { data } = await api.post('/checkout/quote/', body, { signal })
      return data
    },
    enabled: Boolean(items?.length) && options.enabled !== false,
    // Hold the previous figures on screen while the next ones load, so the
    // summary does not collapse to a spinner on every "+" tap. The caller
    // dims them and marks aria-busy while isFetching is true, so a stale
    // number is never presented as a settled one.
    placeholderData: keepPreviousData,
    staleTime: 0,
    ...options,
  })
}

/** Index a quote's lines by variant id, for line-level rendering. */
export function quoteLinesByVariant(quote) {
  const map = new Map()
  for (const line of quote?.lines ?? []) map.set(line.variant_id, line)
  return map
}
