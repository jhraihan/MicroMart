import { beforeEach, describe, expect, it } from 'vitest'

import { useCartStore } from './cartStore'

function product(overrides = {}) {
  return {
    variantId: 1,
    productSlug: 'rtx-4060',
    productName: 'RTX 4060 Graphics Card',
    variantLabel: '8GB',
    sku: 'GPU-4060-8',
    unitPrice: '42000.00',
    image: null,
    maxStock: 10,
    ...overrides,
  }
}

beforeEach(() => {
  useCartStore.getState().clear()
})

describe('guest cart', () => {
  it('starts empty', () => {
    expect(useCartStore.getState().items).toEqual([])
    expect(useCartStore.getState().itemCount()).toBe(0)
  })

  it('adds an item', () => {
    useCartStore.getState().add(product())

    expect(useCartStore.getState().items).toHaveLength(1)
    expect(useCartStore.getState().itemCount()).toBe(1)
  })

  it('adds the quantity to the existing line instead of duplicating it', () => {
    useCartStore.getState().add(product(), 2)
    useCartStore.getState().add(product(), 3)

    expect(useCartStore.getState().items).toHaveLength(1)
    expect(useCartStore.getState().itemCount()).toBe(5)
  })

  it('keeps different variants on separate lines', () => {
    useCartStore.getState().add(product({ variantId: 1 }))
    useCartStore.getState().add(product({ variantId: 2 }))

    expect(useCartStore.getState().items).toHaveLength(2)
  })

  it('counts every unit, not every line', () => {
    useCartStore.getState().add(product({ variantId: 1 }), 2)
    useCartStore.getState().add(product({ variantId: 2 }), 3)

    expect(useCartStore.getState().itemCount()).toBe(5)
  })

  it('adds up the subtotal to two decimal places', () => {
    useCartStore.getState().add(product({ unitPrice: '42000.00' }), 2)

    expect(useCartStore.getState().subtotal()).toBe('84000.00')
  })

  it('changes a quantity', () => {
    useCartStore.getState().add(product())
    useCartStore.getState().setQuantity(1, 4)

    expect(useCartStore.getState().itemCount()).toBe(4)
  })

  it('removes the line when the quantity drops below one', () => {
    useCartStore.getState().add(product())
    useCartStore.getState().setQuantity(1, 0)

    expect(useCartStore.getState().items).toEqual([])
  })

  it('removes an item', () => {
    useCartStore.getState().add(product({ variantId: 1 }))
    useCartStore.getState().add(product({ variantId: 2 }))
    useCartStore.getState().remove(1)

    expect(useCartStore.getState().items).toHaveLength(1)
    expect(useCartStore.getState().items[0].variantId).toBe(2)
  })

  it('empties the cart', () => {
    useCartStore.getState().add(product())
    useCartStore.getState().clear()

    expect(useCartStore.getState().items).toEqual([])
  })
})

describe('syncing with the server', () => {
  it('takes the server price and reports what changed', () => {
    useCartStore.getState().add(product({ unitPrice: '42000.00' }))

    const changed = useCartStore
      .getState()
      .syncFromServer([{ variant_id: 1, unit_price: '39000.00' }])

    expect(useCartStore.getState().items[0].unitPrice).toBe('39000.00')
    expect(changed).toHaveLength(1)
    expect(changed[0]).toMatchObject({ was: '42000.00', now: '39000.00' })
  })

  it('reports nothing when the price is unchanged', () => {
    useCartStore.getState().add(product({ unitPrice: '42000.00' }))

    const changed = useCartStore
      .getState()
      .syncFromServer([{ variant_id: 1, unit_price: '42000.00' }])

    expect(changed).toEqual([])
  })

  it('leaves items the server did not mention alone', () => {
    useCartStore.getState().add(product({ variantId: 1 }))
    useCartStore.getState().add(product({ variantId: 2 }))

    useCartStore.getState().syncFromServer([{ variant_id: 1, unit_price: '42000.00' }])

    expect(useCartStore.getState().items).toHaveLength(2)
  })

  it('copes with an empty or missing server response', () => {
    useCartStore.getState().add(product())

    expect(useCartStore.getState().syncFromServer([])).toEqual([])
    expect(useCartStore.getState().syncFromServer(undefined)).toEqual([])
  })
})
