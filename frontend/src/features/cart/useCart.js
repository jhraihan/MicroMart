import { useMemo } from 'react'

import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useAuthStore } from '@/stores/authStore'
import { useCartStore } from '@/stores/cartStore'

import { useAddCartItem, useServerCart, useServerCartMutations } from './api'

// One cart for the UI, two storages underneath (FR-CRT-1).

function fromServerItem(item) {
  return {
    key: `s${item.id}`,
    itemId: item.id,
    variantId: item.variant_id,
    productName: item.product_name,
    productSlug: item.product_slug,
    variantLabel: item.variant_label,
    sku: item.sku,
    image: item.image,
    unitPrice: item.unit_price,
    quantity: item.quantity,
    maxStock: item.stock,
  }
}

function fromGuestItem(item) {
  return {
    key: `g${item.variantId}`,
    itemId: null,
    variantId: item.variantId,
    productName: item.productName,
    productSlug: item.productSlug,
    variantLabel: item.variantLabel,
    sku: item.sku,
    image: item.image,
    unitPrice: item.unitPrice,
    quantity: item.quantity,
    maxStock: item.maxStock,
  }
}

export function useCart() {
  const user = useAuthStore((s) => s.user)
  const authStatus = useAuthStore((s) => s.status)
  const isAuthed = Boolean(user)

  const guestItems = useCartStore((s) => s.items)
  const guestAdd = useCartStore((s) => s.add)
  const guestSetQuantity = useCartStore((s) => s.setQuantity)
  const guestRemove = useCartStore((s) => s.remove)
  const guestClear = useCartStore((s) => s.clear)

  // Both hooks run on every render regardless of mode; the query is gated by
  // `enabled` rather than by a conditional call.
  const serverCart = useServerCart(isAuthed)
  const serverAdd = useAddCartItem()
  const { setQuantity: serverSetQuantity, remove: serverRemove } =
    useServerCartMutations()

  const lines = useMemo(
    () =>
      isAuthed
        ? (serverCart.data?.items ?? []).map(fromServerItem)
        : guestItems.map(fromGuestItem),
    [isAuthed, serverCart.data, guestItems],
  )

  /*
   * The quote's request body, settled before it becomes a query key. The
   * serialised form is what gets debounced: an array literal is a new
   * reference on every render, and debouncing one would restart its own timer
   * forever and never settle.
   */
  const itemsKey = useMemo(
    () =>
      JSON.stringify(
        lines.map((line) => ({ variant_id: line.variantId, quantity: line.quantity })),
      ),
    [lines],
  )
  const settledItemsKey = useDebouncedValue(itemsKey, 300)
  const quoteItems = useMemo(() => JSON.parse(settledItemsKey), [settledItemsKey])

  /*
   * The only arithmetic in this file, and it is deliberately quarantined: a
   * placeholder shown while the first quote is in flight, rendered muted and
   * labelled "Estimated" by OrderTotals, and discarded the moment the server
   * answers. For a signed-in shopper it is not even client-side -- the server
   * cart carries its own subtotal.
   */
  const placeholderSubtotal = useMemo(() => {
    if (isAuthed) return serverCart.data?.subtotal ?? null
    if (!lines.length) return null
    return lines
      .reduce((sum, line) => sum + Number(line.unitPrice) * line.quantity, 0)
      .toFixed(2)
  }, [isAuthed, serverCart.data, lines])

  return {
    mode: isAuthed ? 'server' : 'guest',
    lines,
    quoteItems,
    placeholderSubtotal,
    // True while the settled key is still catching up, so the summary can say
    // "updating" instead of showing a figure for a cart that just changed.
    isSettling: itemsKey !== settledItemsKey,
    itemCount: lines.reduce((n, line) => n + line.quantity, 0),
    isEmpty: lines.length === 0,
    notices: serverCart.data?.notices ?? [],

    /*
     * The guest cart is synchronous, so only the server path can be loading --
     * but "is this a guest at all" is not known synchronously. The access token
     * lives in memory only, so on a cold load App.jsx has to call bootstrap()
     * and wait for /auth/refresh/ before anyone knows whether there is a server
     * cart to fetch. Until that settles, a signed-in shopper reads as a guest
     * with an empty localStorage cart.
     */
    isPending: isAuthed
      ? serverCart.isPending
      : authStatus === 'idle' || authStatus === 'loading',
    isError: isAuthed ? serverCart.isError : false,
    error: serverCart.error,
    refetch: serverCart.refetch,
    isMutating:
      serverSetQuantity.isPending || serverRemove.isPending || serverAdd.isPending,
    isAdding: serverAdd.isPending,

    // Add a variant to whichever cart is live.
    add(item, quantity = 1) {
      if (!isAuthed) {
        guestAdd(item, quantity)
        return Promise.resolve(null)
      }
      return serverAdd.mutateAsync({ variantId: item.variantId, quantity })
    },

    setQuantity(line, quantity) {
      const next = Math.max(1, quantity)
      if (isAuthed) serverSetQuantity.mutate({ itemId: line.itemId, quantity: next })
      else guestSetQuantity(line.variantId, next)
    },

    remove(line) {
      if (isAuthed) serverRemove.mutate({ itemId: line.itemId })
      else guestRemove(line.variantId)
    },

    /** Called after a successful placement -- the server empties its own. */
    clear() {
      if (!isAuthed) guestClear()
    },
  }
}
