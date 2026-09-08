import { Link } from 'react-router-dom'

import { formatMoney } from '@/lib/money'

/*
 * The purchased lines, read from the order's own snapshot.
 *
 * Product name, variant label, SKU and unit price were copied onto the order
 * at purchase time (FR-ORD-2), so a later catalogue edit cannot rewrite what
 * somebody bought. Nothing here consults the live catalogue: `product_slug` is
 * a link back and nothing more, and it is null once the product is gone — the
 * line still reads correctly, it just stops linking.
 *
 * Laid out as blocks rather than table rows so it survives 360px without
 * sideways scrolling (PRD §9.2), the same shape CartLine uses.
 */
export default function OrderLines({ items = [] }) {
  if (!items.length) {
    return <p className="text-sm text-ink-muted">This order has no items.</p>
  }

  return (
    <ul className="divide-y divide-line">
      {items.map((item) => (
        <li
          key={item.id}
          className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 py-3 first:pt-0 last:pb-0"
        >
          <div className="min-w-0 flex-1">
            {item.product_slug ? (
              <Link
                to={`/p/${item.product_slug}`}
                className="text-sm font-medium text-ink hover:text-action hover:underline"
              >
                {item.product_name}
              </Link>
            ) : (
              <span className="text-sm font-medium text-ink">{item.product_name}</span>
            )}

            <p className="mt-0.5 text-xs text-ink-muted">
              {item.variant_label && <span>{item.variant_label} · </span>}
              {item.sku && <span>SKU {item.sku} · </span>}
              <span className="tabular-nums">
                {item.quantity} × {formatMoney(item.unit_price)}
              </span>
            </p>
          </div>

          <p className="shrink-0 text-sm font-semibold text-ink tabular-nums">
            {formatMoney(item.line_total)}
          </p>
        </li>
      ))}
    </ul>
  )
}
