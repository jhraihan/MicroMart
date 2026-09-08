import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

/** Reads that support checkout but are owned by other feature areas. */

export const checkoutKeys = {
  addresses: () => ['addresses'],
  zones: () => ['shipping', 'zones'],
}

/** GET /addresses/ -- the saved address book (FR-AUT-6, FR-CHK-4). */
export function useAddresses(enabled) {
  return useQuery({
    queryKey: checkoutKeys.addresses(),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/addresses/', { signal })
      // The address book is a small list; tolerate either envelope.
      return Array.isArray(data) ? data : (data?.results ?? [])
    },
    enabled,
    staleTime: 5 * 60_000,
  })
}

/**
 * GET /shipping/zones/ -- display only.
 *
 * It answers "what will delivery cost?" before an address exists. The charge
 * that is actually billed is the one in the quote, resolved from the district
 * server-side (FR-SHP-4).
 */
export function useShippingZones() {
  return useQuery({
    queryKey: checkoutKeys.zones(),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/shipping/zones/', { signal })
      return Array.isArray(data) ? data : (data?.results ?? [])
    },
    staleTime: 10 * 60_000,
  })
}
