import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

/*
 * PC-builder endpoints.
 *
 * Validation is a POST rather than a GET because the selection is a list of
 * objects, not a query string -- but it writes nothing, so it is safe to call
 * on every change. `useBuildValidation` is deliberately a *query* keyed on
 * the selection for that reason: repeated identical selections are served
 * from cache instead of re-posting.
 */

export const builderKeys = {
  slots: () => ['builder', 'slots'],
  components: (slot, selection, filters) => ['builder', 'components', slot, selection, filters],
  validation: (items) => ['builder', 'validate', items],
  builds: () => ['builder', 'builds'],
  build: (token) => ['builder', 'build', token],
}

/** The builder's own vocabulary -- which slots exist and which are required. */
export function useBuilderSlots() {
  return useQuery({
    queryKey: builderKeys.slots(),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/pc-builder/slots/', { signal })
      return data.slots
    },
    staleTime: 60 * 60_000, // this is a code-level constant, not catalogue data
  })
}

/**
 * Parts that can fill one slot.
 *
 * `selection` is the compact `cpu:12,motherboard:34` form the API expects, so
 * the picker narrows itself as choices are made.
 */
export function useBuilderComponents(slot, { selection = '', q = '', brand = '', compatibleOnly = true } = {}) {
  const filters = { q, brand, compatibleOnly }
  return useQuery({
    queryKey: builderKeys.components(slot, selection, filters),
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ slot })
      if (selection) params.set('selected', selection)
      if (q) params.set('q', q)
      if (brand) params.set('brand', brand)
      if (!compatibleOnly) params.set('compatible_only', 'false')
      const { data } = await api.get(`/pc-builder/components/?${params}`, { signal })
      return data
    },
    enabled: Boolean(slot),
  })
}

/**
 * The compatibility verdict for a selection.
 *
 * Keyed on the items themselves, so an unchanged build is not revalidated and
 * a changed one always is.
 */
export function useBuildValidation(items) {
  return useQuery({
    queryKey: builderKeys.validation(items),
    queryFn: async ({ signal }) => {
      const { data } = await api.post('/pc-builder/validate/', { items }, { signal })
      return data
    },
    enabled: items.length > 0,
  })
}

export function useSavedBuilds(options = {}) {
  return useQuery({
    queryKey: builderKeys.builds(),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/builds/', { signal })
      return data.results ?? []
    },
    ...options,
  })
}

export function useSavedBuild(token, options = {}) {
  return useQuery({
    queryKey: builderKeys.build(token),
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/builds/${token}/`, { signal })
      return data
    },
    enabled: Boolean(token),
    ...options,
  })
}

export function useSaveBuild() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, items }) => {
      const { data } = await api.post('/builds/', { name, items })
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: builderKeys.builds() }),
  })
}

export function useDeleteBuild() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (token) => {
      await api.delete(`/builds/${token}/`)
      return token
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: builderKeys.builds() }),
  })
}
