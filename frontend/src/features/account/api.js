import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'

/*
 * Account endpoints: the profile, the address book and the password.
 *
 * The address queries share their cache key with the checkout's own address
 * hook (`['addresses']`), deliberately -- adding an address here must make it
 * appear in the checkout picker without a reload, and two separate keys would
 * mean two separate truths.
 */

export const accountKeys = {
  me: () => ['account', 'me'],
  addresses: () => ['addresses'],
}

/** GET /auth/me/ */
export function useMe(options = {}) {
  return useQuery({
    queryKey: accountKeys.me(),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/auth/me/', { signal })
      return data
    },
    ...options,
  })
}

/**
 * PATCH /auth/me/ -- name and phone only.
 *
 * Email and role are read-only server-side. Changing an email is an identity
 * change that needs re-verification, and the account API deliberately does
 * not offer it as a field edit.
 */
export function useUpdateProfile() {
  const queryClient = useQueryClient()
  const setUser = useAuthStore((s) => s.setUser)

  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.patch('/auth/me/', payload)
      return data
    },
    onSuccess: (user) => {
      queryClient.setQueryData(accountKeys.me(), user)
      // The header greets the shopper by name, so the store has to hear about
      // this too or the chrome disagrees with the page.
      setUser(user)
    },
  })
}

/** POST /auth/change-password/ */
export function useChangePassword() {
  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.post('/auth/change-password/', payload)
      return data
    },
  })
}

/** GET /addresses/ */
export function useAddresses(options = {}) {
  return useQuery({
    queryKey: accountKeys.addresses(),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/addresses/', { signal })
      return data?.results ?? data ?? []
    },
    ...options,
  })
}

function invalidateAddresses(queryClient) {
  // Always a refetch rather than a local splice: setting one address as the
  // default clears the flag on another, so a mutation can change rows the
  // response never mentions.
  return queryClient.invalidateQueries({ queryKey: accountKeys.addresses() })
}

export function useCreateAddress() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.post('/addresses/', payload)
      return data
    },
    onSuccess: () => invalidateAddresses(queryClient),
  })
}

export function useUpdateAddress() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }) => {
      const { data } = await api.patch(`/addresses/${id}/`, payload)
      return data
    },
    onSuccess: () => invalidateAddresses(queryClient),
  })
}

export function useDeleteAddress() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id) => {
      await api.delete(`/addresses/${id}/`)
      return id
    },
    onSuccess: () => invalidateAddresses(queryClient),
  })
}

/** POST /auth/password-reset/ -- starts the reset flow. */
export function useRequestPasswordReset() {
  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.post('/auth/password-reset/', payload)
      return data
    },
  })
}

/** POST /auth/password-reset/confirm/ -- completes it with the emailed token. */
export function useConfirmPasswordReset() {
  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.post('/auth/password-reset/confirm/', payload)
      return data
    },
  })
}
