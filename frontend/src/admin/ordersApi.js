import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api } from '@/lib/api'

/*
 * The dashboard and the order pipeline: the endpoints registered in
 * apps/dashboard/urls.py (PRD §7.3).
 */

export const pipelineKeys = {
  dashboard: (days) => ['admin', 'dashboard', days],
  orderLists: ['admin', 'orders', 'list'],
  orderList: (params) => ['admin', 'orders', 'list', params],
  orderDetail: (reference) => ['admin', 'orders', 'detail', reference],
}

/** Drop empty values so an untouched filter never reaches the query string. */
function compact(params) {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== undefined && value !== null && value !== '',
    ),
  )
}

/**
 * GET /admin/dashboard/ -- revenue windows, trend series, alert counts (US-A1).
 *
 * Admin only. A staff caller gets 403 from the server; passing
 * `enabled: false` for a staff session just avoids asking.
 */
export function useAdminDashboard({ days = 30, enabled = true } = {}) {
  return useQuery({
    queryKey: pipelineKeys.dashboard(days),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/admin/dashboard/', { params: { days }, signal })
      return data
    },
    enabled,
    // Shorter than the app default: this is the screen an owner leaves open
    // while orders arrive.
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
}

/**
 * GET /admin/orders/ -- the pipeline (US-A3, US-T1).
 *
 * `status` goes over the wire as one comma-separated value. The server accepts
 * that, a repeated `?status=`, or a single value
 * (apps/orders/services/history._parse_statuses), and the comma form is the one
 * that round-trips through this app's own URL unchanged -- so what the admin
 * sees in the address bar is what was asked for.
 */
export function useAdminOrders(filters = {}) {
  const params = compact({
    page: filters.page && filters.page > 1 ? filters.page : undefined,
    status: filters.status?.length ? filters.status.join(',') : undefined,
    payment_method: filters.payment_method,
    placed_from: filters.placed_from,
    placed_to: filters.placed_to,
    q: filters.q,
  })

  return useQuery({
    queryKey: pipelineKeys.orderList(params),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/admin/orders/', { params, signal })
      return data
    },
    // Paging and re-filtering hold the current rows on screen instead of
    // collapsing the table to a spinner under the reader's cursor.
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  })
}

/** GET /admin/orders/{reference}/ -- full detail plus `allowed_transitions`. */
export function useAdminOrder(reference) {
  return useQuery({
    queryKey: pipelineKeys.orderDetail(reference),
    queryFn: async ({ signal }) => {
      const { data } = await api.get(
        `/admin/orders/${encodeURIComponent(reference)}/`,
        { signal },
      )
      return data
    },
    enabled: Boolean(reference),
    // The fulfilment screen is the one place a stale status would be acted on.
    staleTime: 0,
  })
}

/** Replace the cached order and drop every list and metric that just went stale. */
function useOrderWriteHandlers(reference) {
  const queryClient = useQueryClient()

  return {
    onSuccess: (order) => {
      queryClient.setQueryData(pipelineKeys.orderDetail(reference), order)
      queryClient.invalidateQueries({ queryKey: pipelineKeys.orderLists })
      queryClient.invalidateQueries({ queryKey: ['admin', 'dashboard'] })
      // A status move can decrement or restore stock, so the inventory screens
      // and the customer's own order history are stale too.
      queryClient.invalidateQueries({ queryKey: ['admin', 'inventory'] })
      queryClient.invalidateQueries({ queryKey: ['orders'] })
    },
  }
}

/**
 * POST /admin/orders/{reference}/status/ -- advance the order.
 *
 * The server's transition table is the gate. An illegal move comes back 422
 * ILLEGAL_STATUS_TRANSITION, a move this actor may not make comes back 403
 * TRANSITION_NOT_PERMITTED, and `packed -> shipped` without a courier comes
 * back 422 SHIPMENT_REQUIRED. All three are shown to the admin verbatim -- this
 * hook never guesses which one it will be.
 */
export function useAdvanceOrderStatus(reference) {
  const handlers = useOrderWriteHandlers(reference)

  return useMutation({
    mutationFn: async ({ status, note = '' }) => {
      const { data } = await api.post(
        `/admin/orders/${encodeURIComponent(reference)}/status/`,
        note ? { status, note } : { status },
      )
      return data
    },
    // A status change moves stock and writes an audit row. Whether to try again
    // after a failure is the admin's call, not an automatic one.
    retry: false,
    ...handlers,
  })
}

/**
 * POST /admin/orders/{reference}/shipment/ -- courier and tracking number
 * (FR-ORD-7).
 *
 * Separate from the status write because the server keeps them separate:
 * `packed -> shipped` is marked `requires_shipment`, so this call is what makes
 * that transition legal rather than a field smuggled into it.
 */
export function useRecordShipment(reference) {
  const handlers = useOrderWriteHandlers(reference)

  return useMutation({
    mutationFn: async ({ courier_name, tracking_number }) => {
      const { data } = await api.post(
        `/admin/orders/${encodeURIComponent(reference)}/shipment/`,
        { courier_name, tracking_number },
      )
      return data
    },
    retry: false,
    ...handlers,
  })
}
