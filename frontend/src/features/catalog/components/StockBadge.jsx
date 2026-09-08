import { Badge } from '@/components/ui'

/**
 * Stock is informational, never a reservation -- stock moves only on order
 * confirmation (PRD §6.5). The wording carries the meaning; colour alone
 * never does.
 */
export default function StockBadge({ inStock, isLowStock = false, stock = null, size = 'md' }) {
  if (!inStock) {
    return (
      <Badge tone="danger" size={size}>
        Out of stock
      </Badge>
    )
  }
  if (isLowStock && stock != null) {
    return (
      <Badge tone="warning" size={size}>
        Only {stock} left
      </Badge>
    )
  }
  return (
    <Badge tone="success" size={size}>
      In stock
    </Badge>
  )
}
