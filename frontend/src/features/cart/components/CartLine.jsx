import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui'
import { formatMoney } from '@/lib/money'

import QuantityStepper from './QuantityStepper'

/*
 * One cart line, laid out as a card rather than a table row so it survives
 * 360px without sideways scrolling (PRD §9.2).
 *
 * Two prices appear here and they are not interchangeable:
 *   - the unit price, which the server sent (in the quote once it lands, in
 *     the stored snapshot before that), and
 *   - the line total, which is only ever printed from `quoteLine.line_total`.
 * The client never multiplies the first by the quantity to produce the
 * second. Until the quote arrives, the line total is a dash.
 */

function issueText(quoteLine) {
  if (!quoteLine || quoteLine.is_available) return null
  switch (quoteLine.issue) {
    case 'insufficient_stock':
      return quoteLine.available_stock > 0
        ? `Only ${quoteLine.available_stock} left — reduce the quantity to continue.`
        : 'Out of stock — remove this item to continue.'
    case 'out_of_stock':
      return 'Out of stock — remove this item to continue.'
    case 'unavailable':
      return 'No longer sold — remove this item to continue.'
    default:
      return 'Unavailable — remove this item to continue.'
  }
}

export default function CartLine({
  line,
  quoteLine,
  onQuantityChange,
  onRemove,
  disabled = false,
}) {
  const problem = issueText(quoteLine)
  const unitPrice = quoteLine?.unit_price ?? line.unitPrice
  const maxStock = quoteLine?.available_stock ?? line.maxStock ?? null
  const to = line.productSlug
    ? `/p/${line.productSlug}?variant=${line.variantId}`
    : null

  return (
    <li className="flex gap-3 border-b border-line px-3 py-4 last:border-b-0 sm:px-4">
      <div className="h-16 w-16 shrink-0 overflow-hidden rounded-card border border-line bg-white sm:h-20 sm:w-20">
        {line.image ? (
          <img
            src={line.image}
            alt=""
            loading="lazy"
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-[10px] text-ink-muted">
            No image
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <div className="min-w-0">
            {to ? (
              <Link
                to={to}
                className="text-sm font-medium text-ink hover:text-action hover:underline"
              >
                {line.productName}
              </Link>
            ) : (
              <span className="text-sm font-medium text-ink">{line.productName}</span>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {line.variantLabel && (
                <Badge tone="neutral" size="sm">
                  {line.variantLabel}
                </Badge>
              )}
              {line.sku && (
                <span className="text-[11px] text-ink-muted">SKU {line.sku}</span>
              )}
            </div>
          </div>

          <div className="text-right">
            <p className="text-sm font-medium text-ink tabular-nums">
              {formatMoney(unitPrice)}
            </p>
            <p className="text-[11px] text-ink-muted">each</p>
          </div>
        </div>

        {problem && (
          <p role="alert" className="text-xs font-medium text-danger">
            {problem}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <div className="flex items-center gap-1">
            <QuantityStepper
              value={line.quantity}
              max={maxStock}
              disabled={disabled}
              onChange={(next) => onQuantityChange(line, next)}
              label={`Quantity for ${line.productName}`}
            />
            <button
              type="button"
              onClick={() => onRemove(line)}
              disabled={disabled}
              className="flex min-h-[44px] items-center rounded-card px-3 text-sm font-medium text-ink-muted hover:text-danger hover:underline disabled:cursor-not-allowed"
            >
              Remove
              <span className="sr-only"> {line.productName} from cart</span>
            </button>
          </div>

          <p className="text-right text-sm font-semibold text-ink tabular-nums">
            {quoteLine ? (
              formatMoney(quoteLine.line_total)
            ) : (
              <span className="font-normal text-ink-muted">
                <span aria-hidden="true">—</span>
                <span className="sr-only">Line total is being confirmed</span>
              </span>
            )}
          </p>
        </div>
      </div>
    </li>
  )
}
