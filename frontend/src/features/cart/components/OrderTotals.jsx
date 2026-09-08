import clsx from 'clsx'

import { Spinner } from '@/components/ui'
import { formatMoney } from '@/lib/money'

/*
 * Every figure on this panel comes from POST /checkout/quote/. Nothing here
 * adds, multiplies or discounts anything (FR-CRT-4, FR-CHK-6).
 */

function Row({ label, value, hint, strong = false, tone }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <span
        className={clsx(
          strong ? 'text-sm font-semibold text-ink' : 'text-sm text-ink-muted',
        )}
      >
        {label}
        {hint && <span className="ml-1 text-xs text-ink-muted">{hint}</span>}
      </span>
      <span
        className={clsx(
          'text-right tabular-nums',
          strong ? 'text-lg font-bold text-price' : 'text-sm font-medium text-ink',
          tone === 'save' && 'text-success',
          tone === 'muted' && 'text-sm font-normal text-ink-muted',
        )}
      >
        {value}
      </span>
    </div>
  )
}

export default function OrderTotals({
  quote,
  isFetching = false,
  isSettling = false,
  isError = false,
  placeholderSubtotal = null,
  shippingHint = 'Calculated at checkout',
  footnote = 'Totals confirmed by the server.',
  className,
}) {
  const busy = isFetching || isSettling

  // --- No server figures yet: an estimate, clearly flagged as one. ---
  if (!quote) {
    return (
      <div className={clsx('flex flex-col', className)} aria-busy={busy || undefined}>
        <Row
          label="Estimated subtotal"
          value={
            <span className="text-ink-muted">
              {placeholderSubtotal == null ? '—' : formatMoney(placeholderSubtotal)}
            </span>
          }
        />
        <Row label="Delivery" value={<span className="text-ink-muted">{shippingHint}</span>} tone="muted" />
        <div
          role="status"
          className="mt-2 flex items-center gap-2 rounded-card bg-page px-3 py-2 text-xs text-ink-muted"
        >
          {isError ? (
            <span className="text-danger">
              Could not confirm prices with the server. Totals below are not final.
            </span>
          ) : (
            <>
              <Spinner size="sm" label="Confirming prices" />
              <span>Confirming prices and stock with the server…</span>
            </>
          )}
        </div>
      </div>
    )
  }

  const hasDiscount = quote.discount_total != null && Number(quote.discount_total) > 0
  const showTax =
    quote.tax_total != null &&
    (Number(quote.tax_total) > 0 || Number(quote.tax_rate_applied) > 0)

  const shippingValue =
    quote.shipping_total == null ? (
      <span className="text-sm font-normal text-ink-muted">{shippingHint}</span>
    ) : Number(quote.shipping_total) === 0 ? (
      <span className="text-success">Free</span>
    ) : (
      formatMoney(quote.shipping_total)
    )

  return (
    <div
      className={clsx('flex flex-col', busy && 'opacity-60', className)}
      aria-busy={busy || undefined}
    >
      <Row label="Subtotal" value={formatMoney(quote.subtotal)} />

      {hasDiscount && (
        <Row
          label="Discount"
          hint={quote.coupon?.code ? `(${quote.coupon.code})` : undefined}
          value={<>&minus;{formatMoney(quote.discount_total)}</>}
          tone="save"
        />
      )}

      <Row label="Delivery" hint={quote.zone?.name ? `(${quote.zone.name})` : undefined} value={shippingValue} />

      {showTax && (
        <Row
          label={
            quote.prices_include_tax
              ? `VAT ${quote.tax_rate_applied}% (included)`
              : `VAT ${quote.tax_rate_applied}%`
          }
          value={formatMoney(quote.tax_total)}
        />
      )}

      <div className="mt-1.5 border-t border-line pt-1.5">
        <Row
          label="Total"
          strong
          value={
            quote.grand_total == null ? (
              <span className="text-sm font-normal text-ink-muted">{shippingHint}</span>
            ) : (
              formatMoney(quote.grand_total)
            )
          }
        />
      </div>

      <p className="mt-1 text-[11px] text-ink-muted" role="status">
        {busy ? 'Updating totals…' : footnote}
      </p>
    </div>
  )
}
