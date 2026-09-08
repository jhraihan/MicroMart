import { Link } from 'react-router-dom'

import { formatMoney } from '@/lib/money'

/*
 * The review list is rendered from the *quote's* lines, not from the local
 * cart. What a shopper approves at the review step is therefore the same
 * document the server priced, down to the unit price and the line total. The
 * local cart only decided which variants and how many.
 */
export default function ReviewLines({ lines = [], isBusy = false }) {
  if (!lines.length) {
    return (
      <p className="text-sm text-ink-muted">
        Confirming your items with the server…
      </p>
    )
  }

  return (
    <ul className={isBusy ? 'divide-y divide-line opacity-60' : 'divide-y divide-line'}>
      {lines.map((line) => (
        <li key={line.variant_id} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
          <div className="h-12 w-12 shrink-0 overflow-hidden rounded-card border border-line bg-white">
            {line.image ? (
              <img src={line.image} alt="" loading="lazy" className="h-full w-full object-contain" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-[10px] text-ink-muted">
                —
              </div>
            )}
          </div>

          <div className="min-w-0 flex-1">
            {line.product_slug ? (
              <Link
                to={`/p/${line.product_slug}?variant=${line.variant_id}`}
                className="text-sm font-medium text-ink hover:text-action hover:underline"
              >
                {line.product_name}
              </Link>
            ) : (
              <span className="text-sm font-medium text-ink">{line.product_name}</span>
            )}
            <p className="text-xs text-ink-muted">
              {line.variant_label && <span>{line.variant_label} · </span>}
              {line.quantity} × {formatMoney(line.unit_price)}
            </p>
            {!line.is_available && (
              <p role="alert" className="mt-1 text-xs font-medium text-danger">
                {line.available_stock > 0
                  ? `Only ${line.available_stock} left — go back to the cart to adjust.`
                  : 'Out of stock — go back to the cart to remove it.'}
              </p>
            )}
          </div>

          <p className="shrink-0 text-sm font-semibold text-ink tabular-nums">
            {formatMoney(line.line_total)}
          </p>
        </li>
      ))}
    </ul>
  )
}
