/*
 * Money arrives from the API as decimal strings and is never parsed into a
 * float for arithmetic. These helpers format for display only -- every total
 * shown to a shopper is computed server-side (PRD §5.4).
 */
const BDT = new Intl.NumberFormat('en-BD', {
  style: 'currency',
  currency: 'BDT',
  currencyDisplay: 'narrowSymbol',
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
})

export function formatMoney(value) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  return BDT.format(n).replace('BDT', '৳')
}

export function formatMoneyPlain(value) {
  const n = Number(value)
  return Number.isNaN(n) ? String(value) : n.toLocaleString('en-BD')
}
