import clsx from 'clsx'

import { formatMoney } from '@/lib/money'

/*
 * FR-CAT-8: when compare_at_price exceeds price, the original is struck
 * through and the discount percentage is shown beside it.
 *
 * No arithmetic happens here. `discount_percent` is computed server-side and
 * rendered as given -- the client never recomputes a price or a saving.
 *
 * Current price uses `text-price` (5.36:1 on white), so the figure a shopper
 * reads always clears WCAG AA.
 */
const SIZES = {
  sm: { now: 'text-sm font-semibold', was: 'text-[11px]' },
  md: { now: 'text-base font-semibold', was: 'text-xs' },
  lg: { now: 'text-2xl font-bold', was: 'text-sm' },
}

export default function PriceTag({
  price,
  priceMax = null,
  compareAtPrice = null,
  discountPercent = 0,
  size = 'md',
  className,
}) {
  const scale = SIZES[size] ?? SIZES.md
  const isRange = priceMax != null && String(priceMax) !== String(price)
  const hasDiscount = Boolean(compareAtPrice) && discountPercent > 0

  return (
    <div className={clsx('flex flex-wrap items-baseline gap-x-2 gap-y-1', className)}>
      <span className={clsx('text-price', scale.now)}>
        {formatMoney(price)}
        {isRange && (
          <>
            <span aria-hidden="true"> &ndash; </span>
            <span className="sr-only"> to </span>
            {formatMoney(priceMax)}
          </>
        )}
      </span>

      {hasDiscount && (
        <>
          <s className={clsx('text-ink-muted', scale.was)}>
            <span className="sr-only">Was </span>
            {formatMoney(compareAtPrice)}
          </s>
          <span
            className={clsx(
              'rounded-pill bg-price px-2 py-0.5 font-medium text-white',
              scale.was,
            )}
          >
            <span aria-hidden="true">-{discountPercent}%</span>
            <span className="sr-only">Save {discountPercent} percent</span>
          </span>
        </>
      )}
    </div>
  )
}
