import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/*
 * The in-progress PC build.
 *
 * Persisted to localStorage so a build survives a reload, a wrong turn into a
 * product page, or closing the tab -- a configurator that forgets an hour of
 * choosing is worse than not having one. It holds *variant ids only*; every
 * price, stock figure and compatibility verdict comes from the server on each
 * load, so a build opened next month is priced next month.
 *
 * A guest can build without an account. Saving needs one, because there would
 * otherwise be no way to list a saved build back.
 */
export const useBuilderStore = create(
  persist(
    (set, get) => ({
      // { [slot]: { variantId, quantity } }
      selection: {},
      name: 'My build',

      setName(name) {
        set({ name })
      },

      select(slot, variantId, quantity = 1) {
        set({
          selection: { ...get().selection, [slot]: { variantId, quantity } },
        })
      },

      setQuantity(slot, quantity) {
        const current = get().selection[slot]
        if (!current) return
        // 4 matches MAX_QUANTITY_PER_SLOT server-side; the API refuses more.
        const clamped = Math.min(Math.max(1, quantity), 4)
        set({
          selection: { ...get().selection, [slot]: { ...current, quantity: clamped } },
        })
      },

      clearSlot(slot) {
        const next = { ...get().selection }
        delete next[slot]
        set({ selection: next })
      },

      clear() {
        set({ selection: {}, name: 'My build' })
      },

      /** Replace the whole build -- used when opening a saved or shared one. */
      load(selection, name = 'My build') {
        set({ selection, name })
      },

      /** The wire shape both `/validate/` and `/builds/` accept. */
      items() {
        return Object.entries(get().selection).map(([slot, row]) => ({
          slot,
          variant_id: row.variantId,
          quantity: row.quantity,
        }))
      },

      /**
       * The compact `cpu:12,motherboard:34` form the component picker takes.
       *
       * Sorted, so an unchanged selection always produces the same string and
       * therefore the same query cache key -- object key order is not
       * guaranteed to be stable across the operations above.
       */
      selectionParam() {
        return Object.entries(get().selection)
          .map(([slot, row]) => `${slot}:${row.variantId}`)
          .sort()
          .join(',')
      },
    }),
    {
      name: 'micromart-build',
      version: 1,
      partialize: (state) => ({ selection: state.selection, name: state.name }),
    },
  ),
)
