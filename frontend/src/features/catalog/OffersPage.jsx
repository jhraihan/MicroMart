import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import { itemListJsonLd, useJsonLd, useSeo } from '@/lib/seo'

import { useProducts } from './api'
import ErrorState from './components/ErrorState'
import ProductGrid from './components/ProductGrid'

/*
 * Everything currently discounted.
 *
 * This is `/products/?has_discount=true` with a headline on it, not a
 * separate concept: "on offer" means the cheapest sellable variant carries a
 * compare-at above its own price, which is exactly the test the card's
 * discount badge uses. Defining it anywhere else would let a product appear
 * here without a badge, or vice versa.
 *
 * Sorted cheapest-first by default, which is what someone browsing offers is
 * usually after; the full listing page is one link away for anything more.
 */
const QUERY = 'has_discount=true&in_stock=true&sort=price_asc&page_size=48'

export default function OffersPage() {
  useSeo({
    title: 'Today’s offers',
    description:
      'Every discounted product at MicroMart, in one place. Genuine stock, official warranty, cash on delivery across Bangladesh.',
    canonical: '/offers',
  })

  const { data, isPending, isError, error, refetch } = useProducts(QUERY)
  const products = data?.results ?? []

  const listLd = useMemo(
    () => itemListJsonLd(products, { name: 'Discounted products' }),
    [products],
  )
  useJsonLd(listLd)

  return (
    <div className="px-4 py-5">
      <section className="rounded-card bg-chrome px-5 py-8 text-white sm:px-8">
        <p className="text-xs font-semibold uppercase tracking-widest text-brand">
          Live discounts
        </p>
        <h1 className="mt-2 text-2xl font-bold leading-8 sm:text-3xl">
          Today’s offers
        </h1>
        <p className="mt-2 max-w-xl text-sm text-ink-inverse">
          Every product currently marked down. Prices update as stock moves, so
          what you see here is what the checkout will charge.
        </p>
      </section>

      <div className="mt-5 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-ink">
          {isPending ? 'Loading offers…' : `${data?.count ?? 0} products on offer`}
        </h2>
        <Link
          to={`/search?${QUERY}`}
          className="flex min-h-[44px] items-center text-sm font-semibold text-action hover:underline"
        >
          Open in the full listing, with filters
          <span aria-hidden="true" className="ml-1">&rarr;</span>
        </Link>
      </div>

      <div className="mt-3">
        {isError ? (
          <ErrorState error={error} onRetry={refetch} title="Could not load offers" />
        ) : !isPending && products.length === 0 ? (
          <div className="rounded-card bg-white p-8 text-center shadow-el-1">
            <h3 className="text-base font-semibold text-ink">
              Nothing is discounted right now
            </h3>
            <p className="mt-2 text-sm text-ink-muted">
              Offers change regularly &mdash; check back, or browse the full
              catalogue in the meantime.
            </p>
            <Link
              to="/search"
              className="mt-5 inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-semibold text-white hover:bg-action-hover"
            >
              Browse everything
            </Link>
          </div>
        ) : (
          <ProductGrid
            products={products}
            loading={isPending}
            skeletonCount={12}
            variant="wide"
          />
        )}
      </div>
    </div>
  )
}
