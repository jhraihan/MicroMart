import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

/*
 * Order placement, history and detail, against
 * docs/api-contract-cart-checkout-orders.md.
 */

export const orderKeys = {
  all: ['orders'],
  list: (params) => ['orders', 'list', params],
  detail: (reference) => ['orders', 'detail', reference],
}

/**
 * A key that survives a retry.
 *
 * FR-CHK-7: the same attempt must reuse its key so a retried or duplicated
 * request collapses into one order. The dangerous case is not the impatient
 * double-tap -- the button disables itself for that -- it is the request that
 * succeeded server-side and lost its response on a flaky mobile connection.
 * Retrying with the same key returns the order that already exists; minting a
 * fresh one would charge the customer twice.
 */
export function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // Non-secure contexts have no randomUUID. Uniqueness per attempt is all
  // that is required, and the server owns the uniqueness constraint anyway.
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

/** POST /orders/ -- placement. The body carries no totals (FR-CRT-4). */
export function usePlaceOrder() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.post('/orders/', payload)
      return data
    },
    onSuccess: (order) => {
      // Seed the detail cache so the confirmation page paints immediately,
      // including for a guest who has no way to refetch it.
      queryClient.setQueryData(orderKeys.detail(order.reference), order)
      queryClient.invalidateQueries({ queryKey: orderKeys.all })
    },
    // A placement is not safe to replay automatically: the key makes a retry
    // harmless, but the decision to retry belongs to the customer.
    retry: false,
  })
}

/**
 * GET /orders/{reference}/
 *
 * A guest passes the email the order was placed with; a mismatch is 404, the
 * same answer any other authorisation miss gets.
 */
export function useOrder(reference, { email = null, enabled = true } = {}) {
  return useQuery({
    queryKey: orderKeys.detail(reference),
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/orders/${encodeURIComponent(reference)}/`, {
        params: email ? { email } : undefined,
        signal,
      })
      return data
    },
    enabled: Boolean(reference) && enabled,
  })
}

/** GET /orders/ -- history, newest first (FR-ORD-1). */
export function useOrders(page = 1) {
  return useQuery({
    queryKey: orderKeys.list({ page }),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/orders/', { params: { page }, signal })
      return data
    },
    placeholderData: keepPreviousData,
  })
}

/** POST /orders/{reference}/cancel/ -- pre-shipment only (FR-ORD-4). */
export function useCancelOrder(reference) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (reason) => {
      const { data } = await api.post(
        `/orders/${encodeURIComponent(reference)}/cancel/`,
        { reason },
      )
      return data
    },
    onSuccess: (order) => {
      queryClient.setQueryData(orderKeys.detail(reference), order)
      queryClient.invalidateQueries({ queryKey: orderKeys.list({ page: 1 }) })
    },
  })
}

/**
 * POST /payments/initiate/ -- hand the browser to SSLCommerz.
 *
 * The redirect the customer comes back through proves nothing (FR-PAY-3).
 * Order state moves on the validated IPN alone, so every screen after this
 * reads `payment_status` off the order.
 */
export async function initiatePayment(orderReference) {
  const { data } = await api.post('/payments/initiate/', {
    order_reference: orderReference,
  })
  return data
}
