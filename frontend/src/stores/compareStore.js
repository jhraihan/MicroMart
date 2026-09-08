import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/*
 * The comparison tray.
 *
 * Held client-side and persisted to localStorage, deliberately: a comparison
 * list is a scratchpad, not an account asset. Putting it on the server would
 * mean a guest could not use it without signing up, which is exactly backwards
 * -- comparing is what someone does *before* they commit to anything.
 *
 * Only slugs are stored. The full product rows come from
 * GET /products/compare/?slugs=..., so a tray built last week shows this
 * week's prices and stock rather than a stale snapshot.
 */

// Matches catalogue.MAX_COMPARE_PRODUCTS server-side. Beyond four the table
// stops being readable and the endpoint truncates anyway.
export const MAX_COMPARE = 4

export const useCompareStore = create(
  persist(
    (set, get) => ({
      slugs: [],

      has: (slug) => get().slugs.includes(slug),
      isFull: () => get().slugs.length >= MAX_COMPARE,

      /**
       * Add a product to the tray.
       *
       * Returns a small result object rather than throwing or silently
       * failing, so the caller can tell the shopper *why* nothing happened --
       * "the tray is full" and "it was already there" need different messages.
       */
      add(slug) {
        const { slugs } = get()
        if (slugs.includes(slug)) return { ok: false, reason: 'duplicate' }
        if (slugs.length >= MAX_COMPARE) return { ok: false, reason: 'full' }
        set({ slugs: [...slugs, slug] })
        return { ok: true }
      },

      remove(slug) {
        set({ slugs: get().slugs.filter((s) => s !== slug) })
      },

      /** Add if absent, remove if present. What a card's compare button does. */
      toggle(slug) {
        if (get().has(slug)) {
          get().remove(slug)
          return { ok: true, removed: true }
        }
        return get().add(slug)
      },

      clear() {
        set({ slugs: [] })
      },
    }),
    {
      name: 'micromart-compare',
      version: 1,
      // Only the slugs are persisted; the derived helpers are recreated on
      // load, and persisting functions would break the rehydration.
      partialize: (state) => ({ slugs: state.slugs }),
    },
  ),
)
