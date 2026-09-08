import { useEffect, useState } from 'react'

/**
 * Settle a fast-changing value before it is used as a query key.
 *
 * The checkout quote is recomputed on every district, coupon and quantity
 * change (PRD §5.4). Tapping "+" four times should be one recalculation, not
 * four, so the inputs pass through here before they reach TanStack Query.
 */
export function useDebouncedValue(value, delay = 300) {
  const [settled, setSettled] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])

  return settled
}

export default useDebouncedValue
