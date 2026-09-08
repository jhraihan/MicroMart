import { describe, expect, it } from 'vitest'

import { formatMoney, formatMoneyPlain } from './money'

describe('formatMoney', () => {
  it('shows a dash when there is no value', () => {
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
    expect(formatMoney('')).toBe('—')
  })

  it('uses the taka symbol, not the BDT currency code', () => {
    const result = formatMoney('1500')
    expect(result).toContain('৳')
    expect(result).not.toContain('BDT')
  })

  it('formats a whole number without decimals', () => {
    expect(formatMoney(1500)).toBe('৳1,500')
  })

  it('keeps the paisa when a price has them', () => {
    expect(formatMoney('1500.50')).toBe('৳1,500.5')
  })

  it('accepts the decimal strings the API sends', () => {
    expect(formatMoney('92000.00')).toBe('৳92,000')
  })

  it('groups thousands so long prices stay readable', () => {
    expect(formatMoney(138000)).toBe('৳138,000')
  })

  it('formats zero rather than treating it as missing', () => {
    expect(formatMoney(0)).toBe('৳0')
  })

  it('returns the input unchanged when it is not a number', () => {
    expect(formatMoney('not a price')).toBe('not a price')
  })
})

describe('formatMoneyPlain', () => {
  it('formats a number without the currency symbol', () => {
    expect(formatMoneyPlain(1500)).not.toContain('৳')
  })

  it('returns the input unchanged when it is not a number', () => {
    expect(formatMoneyPlain('abc')).toBe('abc')
  })
})
