import { Link } from 'react-router-dom'

import { formatMoney } from '@/lib/money'

import { useBoughtTogether } from '../api'

// "Frequently bought together".
export default function BoughtTogether({ product }) {
  const { data: items = [], isPending } = useBoughtTogether(product.slug)

  if (isPending || items.length === 0) return null

  const total = [product, ...items].reduce(
    (sum, item) => sum + Number(item.price_min ?? 0),
    0,
  )

  return (
    <section
      aria-labelledby="bought-together-heading"
      className="mt-6 rounded-card bg-white p-4 shadow-el-1"
    >
      <h2 id="bought-together-heading" className="mb-1 text-base font-semibold text-ink">
        Frequently bought together
      </h2>
      <p className="mb-3 text-xs text-ink-muted">
        Based on what other customers ordered alongside this product.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Thumb product={product} isCurrent />
        {items.map((item) => (
          <span key={item.id} className="flex items-center gap-2">
            <span aria-hidden="true" className="text-lg text-ink-subtle">
              +
            </span>
            <Thumb product={item} />
          </span>
        ))}
      </div>

      <p className="mt-3 text-sm text-ink-muted">
        Combined price from{' '}
        <span className="font-semibold text-price">{formatMoney(total.toFixed(2))}</span>
        {' '}&mdash; add each item separately to choose its options.
      </p>
    </section>
  )
}

function Thumb({ product, isCurrent = false }) {
  const image = product.primary_image

  const inner = (
    <>
      <span className="flex h-20 w-20 items-center justify-center rounded-card border border-line bg-white p-1.5">
        {image?.url ? (
          <img
            src={image.url}
            alt=""
            width={80}
            height={80}
            loading="lazy"
            className="h-full w-full object-contain"
          />
        ) : (
          <span className="text-[10px] text-ink-muted">No image</span>
        )}
      </span>
      <span className="mt-1 block w-24 truncate text-center text-[11px] text-ink-muted">
        {isCurrent ? 'This item' : product.name}
      </span>
      <span className="block text-center text-[11px] font-semibold text-price">
        {formatMoney(product.price_min)}
      </span>
    </>
  )

  if (isCurrent) {
    return <span className="flex flex-col items-center">{inner}</span>
  }

  return (
    <Link
      to={`/p/${product.slug}`}
      className="flex flex-col items-center rounded-card hover:opacity-90"
    >
      {inner}
    </Link>
  )
}
