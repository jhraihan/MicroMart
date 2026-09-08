import { beforeEach, describe, expect, it } from 'vitest'

import { MAX_COMPARE, useCompareStore } from './compareStore'

beforeEach(() => {
  useCompareStore.getState().clear()
})

describe('compare tray', () => {
  it('starts empty', () => {
    expect(useCompareStore.getState().slugs).toEqual([])
  })

  it('adds a product', () => {
    const result = useCompareStore.getState().add('rtx-4060')
    expect(result.ok).toBe(true)
    expect(useCompareStore.getState().slugs).toEqual(['rtx-4060'])
  })

  it('will not add the same product twice', () => {
    useCompareStore.getState().add('rtx-4060')
    const result = useCompareStore.getState().add('rtx-4060')

    expect(result).toEqual({ ok: false, reason: 'duplicate' })
    expect(useCompareStore.getState().slugs).toHaveLength(1)
  })

  it('stops at the maximum and says why', () => {
    for (let i = 0; i < MAX_COMPARE; i += 1) {
      useCompareStore.getState().add(`product-${i}`)
    }
    const result = useCompareStore.getState().add('one-too-many')

    expect(result).toEqual({ ok: false, reason: 'full' })
    expect(useCompareStore.getState().slugs).toHaveLength(MAX_COMPARE)
  })

  it('reports when the tray is full', () => {
    expect(useCompareStore.getState().isFull()).toBe(false)
    for (let i = 0; i < MAX_COMPARE; i += 1) {
      useCompareStore.getState().add(`product-${i}`)
    }
    expect(useCompareStore.getState().isFull()).toBe(true)
  })

  it('removes a product', () => {
    useCompareStore.getState().add('rtx-4060')
    useCompareStore.getState().add('rtx-4070')
    useCompareStore.getState().remove('rtx-4060')

    expect(useCompareStore.getState().slugs).toEqual(['rtx-4070'])
  })

  it('knows what it holds', () => {
    useCompareStore.getState().add('rtx-4060')

    expect(useCompareStore.getState().has('rtx-4060')).toBe(true)
    expect(useCompareStore.getState().has('rtx-4070')).toBe(false)
  })

  it('toggle adds when absent and removes when present', () => {
    const added = useCompareStore.getState().toggle('rtx-4060')
    expect(added.ok).toBe(true)
    expect(useCompareStore.getState().has('rtx-4060')).toBe(true)

    const removed = useCompareStore.getState().toggle('rtx-4060')
    expect(removed).toEqual({ ok: true, removed: true })
    expect(useCompareStore.getState().has('rtx-4060')).toBe(false)
  })

  it('clears everything', () => {
    useCompareStore.getState().add('rtx-4060')
    useCompareStore.getState().add('rtx-4070')
    useCompareStore.getState().clear()

    expect(useCompareStore.getState().slugs).toEqual([])
  })
})
