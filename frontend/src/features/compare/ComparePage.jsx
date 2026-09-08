import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useCompare } from '@/features/catalog/api'
import PriceTag from '@/features/catalog/components/PriceTag'
import StarRating from '@/features/catalog/components/StarRating'
import StockBadge from '@/features/catalog/components/StockBadge'
import { useSeo } from '@/lib/seo'
import { MAX_COMPARE, useCompareStore } from '@/stores/compareStore'

// Side-by-side comparison of up to four products.
export default function ComparePage() {
  const slugs = useCompareStore((s) => s.slugs)
  const remove = useCompareStore((s) => s.remove)
  const clear = useCompareStore((s) => s.clear)
  const [differencesOnly, setDifferencesOnly] = useState(false)

  useSeo({
    title: 'Compare products',
    description: 'Compare specifications, prices and ratings side by side.',
    canonical: '/compare',
    // A personal scratchpad keyed to one browser has nothing to index.
    noIndex: true,
  })

  const { data, isPending, isError } = useCompare(slugs)
  const products = data?.products ?? []

  if (slugs.length === 0) {
    return (
      <div className="px-4 py-10">
        <EmptyTray />
      </div>
    )
  }

  if (isPending) {
    return (
      <div className="px-4 py-6">
        <h1 className="text-xl font-semibold text-ink">Compare products</h1>
        <div className="mt-4 h-96 animate-pulse rounded-card bg-white shadow-el-1" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="px-4 py-10 text-center">
        <h1 className="text-xl font-semibold text-ink">Could not load the comparison</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Something went wrong fetching these products. Try again in a moment.
        </p>
      </div>
    )
  }

  // A slug in the tray that the API did not return no longer exists or is no
  // longer listable. Saying so beats a silently shorter table.
  const missing = slugs.filter((slug) => !products.some((p) => p.slug === slug))

  const groups = (data?.spec_matrix ?? [])
    .map((group) => ({
      ...group,
      rows: differencesOnly ? group.rows.filter((row) => row.differs) : group.rows,
    }))
    .filter((group) => group.rows.length > 0)

  return (
    <div className="px-4 py-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Compare products</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {products.length} of {MAX_COMPARE} slots used. Add products from any
            listing with the compare button.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={differencesOnly}
              onChange={(event) => setDifferencesOnly(event.target.checked)}
              className="h-4 w-4 accent-action"
            />
            Show differences only
          </label>
          <button
            type="button"
            onClick={clear}
            className="flex min-h-[44px] items-center rounded-card border border-line px-3 text-sm text-ink hover:border-danger hover:text-danger"
          >
            Clear all
          </button>
        </div>
      </div>

      {missing.length > 0 && (
        <p role="status" className="mb-3 rounded-card bg-warning/10 p-3 text-sm text-warning">
          {missing.length} product{missing.length > 1 ? 's are' : ' is'} no longer
          available and could not be compared.
        </p>
      )}

      <div className="overflow-x-auto rounded-card bg-white shadow-el-1">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <caption className="sr-only">
            Specification comparison across {products.length} products
          </caption>

          <thead>
            <tr>
              {/* Sticky so the row label stays readable while the value
                  columns scroll sideways. */}
              <th
                scope="col"
                className="sticky left-0 z-10 w-40 bg-white p-3 text-left align-top text-xs font-semibold uppercase tracking-wide text-ink-muted"
              >
                Product
              </th>
              {products.map((product) => (
                <th
                  key={product.id}
                  scope="col"
                  className="min-w-[200px] border-l border-line p-3 text-left align-top font-normal"
                >
                  <div className="flex flex-col gap-2">
                    <Link
                      to={`/p/${product.slug}`}
                      className="flex h-28 items-center justify-center rounded-card border border-line bg-white p-2"
                    >
                      {product.primary_image?.url ? (
                        <img
                          src={product.primary_image.url}
                          alt=""
                          loading="lazy"
                          className="h-full w-full object-contain"
                        />
                      ) : (
                        <span className="text-xs text-ink-muted">No image</span>
                      )}
                    </Link>
                    <Link
                      to={`/p/${product.slug}`}
                      className="text-sm font-medium leading-5 text-ink hover:text-action hover:underline"
                    >
                      {product.name}
                    </Link>
                    <button
                      type="button"
                      onClick={() => remove(product.slug)}
                      className="self-start text-xs font-medium text-danger hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            <FixedRow label="Price" products={products}>
              {(product) => (
                <PriceTag
                  price={product.price_min}
                  priceMax={product.price_max}
                  compareAtPrice={product.compare_at_price}
                  discountPercent={product.discount_percent}
                />
              )}
            </FixedRow>

            <FixedRow label="Brand" products={products}>
              {(product) => product.brand?.name ?? '—'}
            </FixedRow>

            <FixedRow label="Rating" products={products}>
              {(product) => (
                <StarRating value={product.rating_avg} count={product.rating_count} />
              )}
            </FixedRow>

            <FixedRow label="Availability" products={products}>
              {(product) => (
                <StockBadge inStock={product.in_stock} stock={product.total_stock} />
              )}
            </FixedRow>

            <FixedRow label="Warranty" products={products}>
              {(product) =>
                product.warranty_months > 0
                  ? `${product.warranty_months} months`
                  : 'Not covered'
              }
            </FixedRow>

            <FixedRow label="Model" products={products}>
              {(product) => product.model_number || '—'}
            </FixedRow>

            {groups.map((group) => (
              <SpecGroupRows
                key={group.group}
                group={group}
                columns={products.length}
              />
            ))}
          </tbody>
        </table>
      </div>

      {differencesOnly && groups.length === 0 && (
        <p className="mt-4 rounded-card bg-white p-4 text-sm text-ink-muted shadow-el-1">
          These products list identical specifications. Turn off &ldquo;differences
          only&rdquo; to see the full table.
        </p>
      )}
    </div>
  )
}

function FixedRow({ label, products, children }) {
  return (
    <tr className="border-t border-line">
      <th
        scope="row"
        className="sticky left-0 z-10 bg-white p-3 text-left align-top font-medium text-ink-muted"
      >
        {label}
      </th>
      {products.map((product) => (
        <td key={product.id} className="border-l border-line p-3 align-top text-ink">
          {children(product)}
        </td>
      ))}
    </tr>
  )
}

function SpecGroupRows({ group, columns }) {
  return (
    <>
      <tr className="border-t border-line bg-page">
        <th
          scope="colgroup"
          colSpan={columns + 1}
          className="p-2 text-left text-xs font-semibold uppercase tracking-wide text-action"
        >
          {group.group}
        </th>
      </tr>
      {group.rows.map((row) => (
        <tr key={row.key} className="border-t border-line">
          <th
            scope="row"
            className="sticky left-0 z-10 bg-white p-3 text-left align-top font-medium text-ink-muted"
          >
            {row.key}
          </th>
          {row.values.map((value, index) => (
            <td
              key={index}
              className={
                'border-l border-line p-3 align-top ' +
                // A differing row is what the shopper is here for, so it is
                // weighted; identical rows stay quiet rather than hidden.
                (row.differs ? 'font-medium text-ink' : 'text-ink-muted')
              }
            >
              {value ?? '—'}
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

function EmptyTray() {
  return (
    <div className="mx-auto max-w-md text-center">
      <span
        aria-hidden="true"
        className="mx-auto flex h-14 w-14 items-center justify-center rounded-pill bg-tint text-action"
      >
        <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none"
             stroke="currentColor" strokeWidth="1.7">
          <path d="M9 4v16M15 4v16M4 8h5M15 8h5M4 16h5M15 16h5" strokeLinecap="round" />
        </svg>
      </span>
      <h1 className="mt-4 text-xl font-semibold text-ink">Nothing to compare yet</h1>
      <p className="mt-2 text-sm text-ink-muted">
        Add up to {MAX_COMPARE} products using the compare button on any product
        card, then come back here to see their specifications side by side.
      </p>
      <Link
        to="/search"
        className="mt-5 inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-semibold text-white hover:bg-action-hover"
      >
        Browse the catalogue
      </Link>
    </div>
  )
}
