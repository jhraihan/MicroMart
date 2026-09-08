import { beforeEach, describe, expect, it } from 'vitest'

import {
  forgetPendingPayment,
  isPaymentReference,
  readPendingPayment,
  rememberPendingPayment,
} from './paymentReturn'

beforeEach(() => {
  sessionStorage.clear()
})

describe('isPaymentReference', () => {
  it('accepts a real order reference', () => {
    expect(isPaymentReference('ORD-2026-000148')).toBe(true)
  })

  it('rejects empty and missing values', () => {
    expect(isPaymentReference('')).toBe(false)
    expect(isPaymentReference(null)).toBe(false)
    expect(isPaymentReference(undefined)).toBe(false)
  })

  it('rejects anything with characters a reference never contains', () => {
    expect(isPaymentReference('ORD/2026')).toBe(false)
    expect(isPaymentReference('<script>')).toBe(false)
    expect(isPaymentReference('ORD 2026')).toBe(false)
  })

  it('rejects a reference that is too long', () => {
    expect(isPaymentReference('A'.repeat(25))).toBe(false)
  })
})

describe('remembering a payment across the trip to the gateway', () => {
  it('stores a reference and reads it back', () => {
    rememberPendingPayment('ORD-2026-000148')
    expect(readPendingPayment()).toBe('ORD-2026-000148')
  })

  it('returns an empty string when nothing was stored', () => {
    expect(readPendingPayment()).toBe('')
  })

  it('refuses to store a reference that fails the pattern', () => {
    rememberPendingPayment('<script>alert(1)</script>')
    expect(readPendingPayment()).toBe('')
  })

  it('forgets the reference once it is done with', () => {
    rememberPendingPayment('ORD-2026-000148')
    forgetPendingPayment()
    expect(readPendingPayment()).toBe('')
  })
})
