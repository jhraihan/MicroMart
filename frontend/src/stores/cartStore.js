import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/*
 * The guest cart (PRD §5.3). Persisting to localStorage through Zustand's
 * persist middleware is exactly the guest-cart requirement; on login the
 * contents are POSTed to /cart/merge/ and the server cart takes over.
 *
 * Prices stored here are for display only. Adding to a cart never reserves
 * stock, and every total is recomputed server-side at checkout.
 */
export const useCartStore = create(
  persist(
    (set, get) => ({
      items: [], // { variantId, productSlug, productName, variantLabel, sku, unitPrice, image, quantity, maxStock }

      itemCount: () => get().items.reduce((sum, i) => sum + i.quantity, 0),

      /** Display-only subtotal. The server's figure is the one that counts. */
      subtotal: () =>
        get()
          .items.reduce((sum, i) => sum + Number(i.unitPrice) * i.quantity, 0)
          .toFixed(2),

      add(item, quantity = 1) {
        const items = [...get().items]
        const existing = items.findIndex((i) => i.variantId === item.variantId)
        if (existing >= 0) {
          items[existing] = {
            ...items[existing],
            quantity: items[existing].quantity + quantity,
          }
        } else {
          items.push({ ...item, quantity })
        }
        set({ items })
      },

      setQuantity(variantId, quantity) {
        if (quantity < 1) return get().remove(variantId)
        set({
          items: get().items.map((i) =>
            i.variantId === variantId ? { ...i, quantity } : i,
          ),
        })
      },

      remove(variantId) {
        set({ items: get().items.filter((i) => i.variantId !== variantId) })
      },

      clear() {
        set({ items: [] })
      },

      /*
       * Fold the server's view of these variants back into the stored
       * snapshot (FR-CRT-5). The guest cart holds a price and a stock cap
       * copied at add-to-cart time; the checkout quote is the authority on
       * both, so once it arrives the snapshot is realigned rather than left
       * to drift. Returns the variant ids whose price moved, which is what
       * the cart page surfaces as "price updated".
       */
      syncFromServer(serverLines) {
        const byVariant = new Map(
          (serverLines ?? []).map((line) => [line.variant_id, line]),
        )
        const changed = []

        const items = get().items.map((item) => {
          const line = byVariant.get(item.variantId)
          if (!line) return item
          if (Number(line.unit_price) !== Number(item.unitPrice)) {
            changed.push({
              variantId: item.variantId,
              productName: item.productName,
              variantLabel: item.variantLabel,
              was: item.unitPrice,
              now: line.unit_price,
            })
          }
          return {
            ...item,
            unitPrice: line.unit_price,
            maxStock: line.available_stock ?? item.maxStock,
            productName: line.product_name ?? item.productName,
            variantLabel: line.variant_label ?? item.variantLabel,
          }
        })

        if (changed.length || items.some((item, i) => item !== get().items[i])) {
          set({ items })
        }
        return changed
      },

      /** Payload for POST /cart/merge/ on login. */
      mergePayload() {
        return get().items.map((i) => ({
          variant_id: i.variantId,
          quantity: i.quantity,
        }))
      },
    }),
    {
      name: 'guest-cart',
      version: 1,
      partialize: (state) => ({ items: state.items }),
    },
  ),
)
