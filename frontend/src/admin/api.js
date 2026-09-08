import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

// Data access for the admin route group, against the endpoints registered in

export const adminKeys = {
  all: ['admin'],
  products: (params) => ['admin', 'products', params],
  product: (id) => ['admin', 'product', String(id)],
  variants: (params) => ['admin', 'variants', params],
  categories: ['admin', 'categories'],
  brands: ['admin', 'brands'],
  inventory: (params) => ['admin', 'inventory', params],
  ledger: (variantId) => ['admin', 'ledger', String(variantId)],
  coupons: (params) => ['admin', 'coupons', params],
  reviews: (params) => ['admin', 'reviews', params],
  settings: ['admin', 'settings'],
}

/** Drop empty values so a blank filter never reaches the API as `?q=`. */
function clean(params) {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== '' && value !== null && value !== undefined,
    ),
  )
}

// ---------------------------------------------------------------------------
// Products (US-A2)
// ---------------------------------------------------------------------------
export function useAdminProducts(params, { enabled = true } = {}) {
  return useQuery({
    queryKey: adminKeys.products(params),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/admin/products/', { params: clean(params), signal })
      return data
    },
    enabled,
    // Hold the current page while the next one loads, exactly as the
    // storefront grid does -- a table that empties between pages reads as a
    // failed search.
    placeholderData: keepPreviousData,
  })
}

export function useAdminProduct(id) {
  return useQuery({
    queryKey: adminKeys.product(id),
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/admin/products/${id}/`, { signal })
      return data
    },
    enabled: Boolean(id),
  })
}

export function useCreateProduct() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.post('/admin/products/', payload)
      return data
    },
    onSuccess: (product) => {
      queryClient.setQueryData(adminKeys.product(product.id), product)
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
    },
  })
}

export function useUpdateProduct(id) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.patch(`/admin/products/${id}/`, payload)
      return data
    },
    onSuccess: (product) => {
      queryClient.setQueryData(adminKeys.product(id), product)
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
    },
  })
}

/**
 * DELETE deactivates -- it never destroys (contract §"DELETE deactivates").
 * Orders keep their OrderItem FK and the product can be brought back with a
 * PATCH, so the UI calls this "Deactivate", not "Delete".
 */
export function useSetProductActive() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, isActive }) => {
      const { data } = isActive
        ? await api.patch(`/admin/products/${id}/`, { is_active: true })
        : await api.delete(`/admin/products/${id}/`)
      return data
    },
    onSuccess: (product) => {
      queryClient.setQueryData(adminKeys.product(product.id), product)
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Product images
// ---------------------------------------------------------------------------
export function useUploadProductImage(productId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ file, alt_text = '', variant_id = null, is_primary = false }) => {
      const body = new FormData()
      body.append('image', file)
      if (alt_text) body.append('alt_text', alt_text)
      if (variant_id) body.append('variant_id', String(variant_id))
      if (is_primary) body.append('is_primary', 'true')
      // The axios instance defaults to application/json; multipart has to say
      // so explicitly or the boundary never reaches Django.
      const { data } = await api.post(`/admin/products/${productId}/images/`, body, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.product(productId) })
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
    },
  })
}

/**
 * PATCH the gallery order. `order` must list every image id; `primary_id` is
 * sent only when the primary is actually changing, because sorting and
 * designating are two different decisions (contract).
 */
export function useReorderProductImages(productId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ order, primary_id }) => {
      const body = primary_id ? { order, primary_id } : { order }
      const { data } = await api.patch(`/admin/products/${productId}/images/`, body)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.product(productId) })
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
    },
  })
}

export function useDeleteProductImage(productId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (imageId) => {
      const { data } = await api.delete(`/admin/products/${productId}/images/${imageId}/`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.product(productId) })
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Variants
// ---------------------------------------------------------------------------
export function useCreateVariant(productId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      // `stock` here is an OPENING quantity, which the service writes through
      // the ledger with reason `initial`. It is the one place stock may ride
      // on a variant body, and only at creation.
      const { data } = await api.post('/admin/variants/', { ...payload, product_id: productId })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.product(productId) })
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
      queryClient.invalidateQueries({ queryKey: ['admin', 'inventory'] })
    },
  })
}

export function useUpdateVariant(productId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }) => {
      // Note what is absent: `stock`. See the module header.
      const { data } = await api.patch(`/admin/variants/${id}/`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.product(productId) })
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
      queryClient.invalidateQueries({ queryKey: ['admin', 'inventory'] })
    },
  })
}

export function useSetVariantActive(productId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, isActive }) => {
      const { data } = isActive
        ? await api.patch(`/admin/variants/${id}/`, { is_active: true })
        : await api.delete(`/admin/variants/${id}/`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.product(productId) })
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
      queryClient.invalidateQueries({ queryKey: ['admin', 'inventory'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Taxonomy -- unpaginated, includes inactive
// ---------------------------------------------------------------------------
export function useAdminCategories() {
  return useQuery({
    queryKey: adminKeys.categories,
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/admin/categories/', { signal })
      return data
    },
    staleTime: 5 * 60_000,
  })
}

export function useAdminBrands() {
  return useQuery({
    queryKey: adminKeys.brands,
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/admin/brands/', { signal })
      return data
    },
    staleTime: 5 * 60_000,
  })
}

/*
 * Taxonomy writes.
 *
 * Every one invalidates both the admin list *and* the storefront's
 * `/categories/` tree: the nav, the mega-menu, the footer and the homepage
 * tiles all read that tree, so a category renamed here has to reach them
 * without a reload. Product lists go too, because deactivating a category
 * withdraws the products inside it.
 */
function invalidateTaxonomy(queryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: adminKeys.categories }),
    queryClient.invalidateQueries({ queryKey: adminKeys.brands }),
    queryClient.invalidateQueries({ queryKey: ['catalog'] }),
  ])
}

export function useSaveCategory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }) => {
      const { data } = id
        ? await api.patch(`/admin/categories/${id}/`, payload)
        : await api.post('/admin/categories/', payload)
      return data
    },
    onSuccess: () => invalidateTaxonomy(queryClient),
  })
}

export function useDeleteCategory() {
  const queryClient = useQueryClient()
  return useMutation({
    // DELETE deactivates rather than destroying -- a category with orders
    // behind its products must stay referenceable.
    mutationFn: async (id) => {
      await api.delete(`/admin/categories/${id}/`)
      return id
    },
    onSuccess: () => invalidateTaxonomy(queryClient),
  })
}

export function useSaveBrand() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }) => {
      const { data } = id
        ? await api.patch(`/admin/brands/${id}/`, payload)
        : await api.post('/admin/brands/', payload)
      return data
    },
    onSuccess: () => invalidateTaxonomy(queryClient),
  })
}

export function useDeleteBrand() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id) => {
      await api.delete(`/admin/brands/${id}/`)
      return id
    },
    onSuccess: () => invalidateTaxonomy(queryClient),
  })
}

// ---------------------------------------------------------------------------
// Inventory (US-A4)
// ---------------------------------------------------------------------------
export function useAdminInventory(params) {
  return useQuery({
    queryKey: adminKeys.inventory(params),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/admin/inventory/', { params: clean(params), signal })
      return data
    },
    placeholderData: keepPreviousData,
  })
}

/**
 * POST /admin/inventory/adjust/ -- the only way stock moves by hand.
 * `reason` is mandatory (FR-INV-8) and the server refuses the order-driven
 * reasons, so the form offers exactly the three it accepts.
 */
export function useAdjustStock() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.post('/admin/inventory/adjust/', payload)
      return data
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'inventory'] })
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
      queryClient.invalidateQueries({ queryKey: adminKeys.ledger(result.variant.id) })
    },
  })
}

export function useVariantLedger(variantId, { enabled = true } = {}) {
  return useQuery({
    queryKey: adminKeys.ledger(variantId),
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/admin/inventory/${variantId}/logs/`, { signal })
      return data
    },
    enabled: Boolean(variantId) && enabled,
    // The ledger is the audit trail behind a number that just changed --
    // never serve it from a stale cache.
    staleTime: 0,
  })
}

// ---------------------------------------------------------------------------
// Coupons (US-A5)
// ---------------------------------------------------------------------------
export function useAdminCoupons(params) {
  return useQuery({
    queryKey: adminKeys.coupons(params),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/admin/coupons/', { params: clean(params), signal })
      return data
    },
    placeholderData: keepPreviousData,
  })
}

export function useSaveCoupon() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }) => {
      const { data } = id
        ? await api.patch(`/admin/coupons/${id}/`, payload)
        : await api.post('/admin/coupons/', payload)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'coupons'] }),
  })
}

/**
 * DELETE retires the coupon (is_active=false) and answers 200 with it.
 * A real delete would cascade CouponRedemption away and SET_NULL the coupon
 * off placed orders -- i.e. rewrite the record of a promotion that ran.
 */
export function useRetireCoupon() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id) => {
      const { data } = await api.delete(`/admin/coupons/${id}/`)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'coupons'] }),
  })
}

// ---------------------------------------------------------------------------
// Review moderation (US-A6)
// ---------------------------------------------------------------------------
export function useAdminReviews(params) {
  return useQuery({
    queryKey: adminKeys.reviews(params),
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/admin/reviews/', { params: clean(params), signal })
      return data
    },
    placeholderData: keepPreviousData,
  })
}

/**
 * POST /admin/reviews/{id}/moderate/ -- approve or reject.
 *
 * The rating recompute happens server-side in the same service call, so the
 * product's rating_avg is invalidated here rather than adjusted locally: only
 * approved reviews count, and only the server knows which those are
 * (FR-REV-4).
 */
export function useModerateReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, decision }) => {
      const { data } = await api.post(`/admin/reviews/${id}/moderate/`, { decision })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'reviews'] })
      queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Store settings -- the singleton
// ---------------------------------------------------------------------------
export function useStoreSettings() {
  return useQuery({
    queryKey: adminKeys.settings,
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/admin/settings/', { signal })
      return data
    },
  })
}

export function useUpdateStoreSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const { data } = await api.patch('/admin/settings/', payload)
      return data
    },
    onSuccess: (settings) => queryClient.setQueryData(adminKeys.settings, settings),
  })
}

/**
 * GET /shipping/zones/ -- public, and the only place the free-shipping
 * threshold lives.
 *
 * It is a per-zone column (ShippingZone.free_shipping_threshold), not a store
 * setting: "free over ৳5,000" is a different promise inside Dhaka than it is
 * for a courier run to Sylhet. The settings screen reads it here so the
 * number is visible beside the tax rate and the COD cap, and says plainly
 * that editing it needs a zone endpoint that PRD §7.3 does not yet define.
 */
export function useShippingZones() {
  return useQuery({
    queryKey: ['admin', 'shipping-zones'],
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/shipping/zones/', { signal })
      return data
    },
    staleTime: 5 * 60_000,
  })
}
