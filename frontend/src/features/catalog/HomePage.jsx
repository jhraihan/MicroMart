import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import {
  organizationJsonLd,
  useJsonLd,
  useSeo,
  websiteJsonLd,
} from '@/lib/seo'

import { useBrands, useCategories, useProducts } from './api'
import ErrorState from './components/ErrorState'
import ProductGrid from './components/ProductGrid'

// Storefront home.

// Rows are ordered by what a returning shopper most wants to see first.
const ROWS = [
  {
    id: 'flash-offers',
    title: 'Today’s offers',
    blurb: 'Discounted right now, while stock lasts.',
    query: 'has_discount=true&in_stock=true&sort=price_asc&page_size=5',
    viewAll: '/offers',
    accent: true,
  },
  {
    id: 'featured',
    title: 'Featured products',
    blurb: 'Hand-picked by the people who sell them.',
    query: 'featured=true&in_stock=true&page_size=5',
  },
  {
    id: 'best-selling',
    title: 'Best selling',
    blurb: 'What people are actually buying this month.',
    query: 'sort=best_selling&in_stock=true&page_size=5',
  },
  {
    id: 'new-arrivals',
    title: 'New arrivals',
    blurb: 'The latest additions to the catalogue.',
    query: 'sort=newest&page_size=5',
  },
  {
    id: 'gaming',
    title: 'Gaming',
    blurb: 'Machines, screens and gear built for playing properly.',
    query: 'category=gaming&category=gaming-laptop&category=gaming-monitor&category=gaming-pc&in_stock=true&page_size=5',
  },
  {
    id: 'laptops',
    title: 'Laptops',
    blurb: 'From study machines to workstations.',
    query: 'category=laptop&in_stock=true&sort=price_asc&page_size=5',
    viewAll: '/c/laptop',
  },
  {
    id: 'components',
    title: 'Components',
    blurb: 'Everything that goes inside the case.',
    query: 'category=component&in_stock=true&page_size=5',
    viewAll: '/c/component',
  },
  {
    id: 'accessories',
    title: 'Accessories',
    blurb: 'Keyboards, mice, audio and the rest of the desk.',
    query: 'category=accessories&in_stock=true&page_size=5',
    viewAll: '/c/accessories',
  },
  {
    id: 'top-rated',
    title: 'Top rated',
    blurb: 'Rated four stars and up by verified buyers.',
    query: 'sort=rating&min_rating=4&page_size=5',
  },
]

function ProductRow({ id, title, blurb, query, viewAll, accent }) {
  const { data, isPending, isError, error, refetch } = useProducts(query)
  const products = data?.results ?? []

  // A quiet row with nothing in it is noise, not content.
  if (!isPending && !isError && products.length === 0) return null

  return (
    <section aria-labelledby={`${id}-heading`} className="mt-8">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2
            id={`${id}-heading`}
            className="flex items-center gap-2 text-lg font-semibold text-ink"
          >
            {accent && (
              <span
                aria-hidden="true"
                className="inline-flex h-6 w-6 items-center justify-center rounded-pill bg-price text-white"
              >
                <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none"
                     stroke="currentColor" strokeWidth="2.5">
                  <path d="M13 3L5 14h6l-1 7 8-11h-6z" strokeLinejoin="round" />
                </svg>
              </span>
            )}
            {title}
          </h2>
          <p className="text-sm text-ink-muted">{blurb}</p>
        </div>
        <Link
          to={viewAll ?? `/search?${query}`}
          className="flex min-h-[44px] items-center text-sm font-semibold text-action hover:underline"
        >
          View all
          <span aria-hidden="true" className="ml-1">&rarr;</span>
          <span className="sr-only"> {title.toLowerCase()}</span>
        </Link>
      </div>

      {isError ? (
        <ErrorState
          error={error}
          onRetry={refetch}
          title={`Could not load ${title.toLowerCase()}`}
        />
      ) : (
        <ProductGrid
          products={products}
          loading={isPending}
          skeletonCount={5}
          variant="wide"
        />
      )}
    </section>
  )
}

function CategoryTiles() {
  const { data: categories, isPending, isError } = useCategories()

  if (isError) return null

  return (
    <section aria-labelledby="categories-heading" className="mt-8">
      <h2 id="categories-heading" className="mb-3 text-lg font-semibold text-ink">
        Shop by category
      </h2>
      <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-9">
        {isPending
          ? Array.from({ length: 9 }, (_, i) => (
              <li key={i} className="h-28 animate-pulse rounded-card bg-white shadow-el-1" />
            ))
          : (categories ?? []).map((category) => (
              <li key={category.id}>
                <Link
                  to={`/c/${category.slug}`}
                  className="flex h-28 flex-col items-center justify-center gap-1 rounded-card bg-white px-1.5 text-center shadow-el-1 transition-shadow hover:shadow-el-2"
                >
                  {category.image ? (
                    <img
                      src={category.image}
                      alt=""
                      width={48}
                      height={48}
                      loading="lazy"
                      className="h-12 w-12 object-contain"
                    />
                  ) : (
                    <span
                      aria-hidden="true"
                      className="flex h-10 w-10 items-center justify-center rounded-pill bg-tint text-base font-semibold text-action"
                    >
                      {category.name.slice(0, 1)}
                    </span>
                  )}
                  <span className="text-[12px] font-semibold leading-tight text-ink">
                    {category.name}
                  </span>
                  <span className="text-[11px] text-ink-muted">
                    {category.product_count}
                  </span>
                </Link>
              </li>
            ))}
      </ul>
    </section>
  )
}

function BrandStrip() {
  const { data: brands, isPending } = useBrands()
  if (isPending || !brands?.length) return null

  return (
    <section aria-labelledby="brands-heading" className="mt-8">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 id="brands-heading" className="text-lg font-semibold text-ink">
          Brands we carry
        </h2>
        <Link
          to="/brands"
          className="flex min-h-[44px] items-center text-sm font-semibold text-action hover:underline"
        >
          All brands <span aria-hidden="true" className="ml-1">&rarr;</span>
        </Link>
      </div>
      <ul className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-8">
        {brands.slice(0, 16).map((brand) => (
          <li key={brand.id}>
            <Link
              to={`/search?brand=${brand.slug}`}
              className="flex h-16 items-center justify-center rounded-card border border-line bg-white px-2 transition-colors hover:border-action"
            >
              {brand.logo ? (
                <img
                  src={brand.logo}
                  alt={brand.name}
                  loading="lazy"
                  className="max-h-10 w-full object-contain"
                />
              ) : (
                <span className="text-sm font-semibold text-ink">{brand.name}</span>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

/* Two promotional panels. Both link somewhere real -- a banner that goes
   nowhere is the classic dead pixel on an e-commerce homepage. */
function PromoBanners() {
  return (
    <section aria-label="Promotions" className="mt-8 grid gap-3 lg:grid-cols-2">
      <Link
        to="/pc-builder"
        className="group flex flex-col justify-between overflow-hidden rounded-card bg-chrome p-6 text-white transition-shadow hover:shadow-el-4"
      >
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-brand">
            Build it yourself
          </p>
          <h2 className="mt-2 text-xl font-bold leading-7">
            PC Builder with compatibility checks
          </h2>
          <p className="mt-2 max-w-md text-sm text-ink-inverse">
            Pick a processor and we narrow the motherboards to the ones that fit.
            Socket, memory type, case size and power draw are all checked as you go.
          </p>
        </div>
        <span className="mt-4 inline-flex min-h-[44px] w-fit items-center rounded-card bg-action px-5 text-sm font-semibold text-white group-hover:bg-action-hover">
          Start building
        </span>
      </Link>

      <Link
        to="/offers"
        className="group flex flex-col justify-between overflow-hidden rounded-card border border-line bg-white p-6 transition-shadow hover:shadow-el-4"
      >
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-price">
            On offer now
          </p>
          <h2 className="mt-2 text-xl font-bold leading-7 text-ink">
            Discounts across the catalogue
          </h2>
          <p className="mt-2 max-w-md text-sm text-ink-muted">
            Everything currently marked down, in one place. Cash on delivery is
            available nationwide, and every product carries its official warranty.
          </p>
        </div>
        <span className="mt-4 inline-flex min-h-[44px] w-fit items-center rounded-card border-2 border-action px-5 text-sm font-semibold text-action group-hover:bg-action group-hover:text-white">
          See all offers
        </span>
      </Link>
    </section>
  )
}

export default function HomePage() {
  useSeo({
    title: 'Computers & Electronics in Bangladesh',
    description:
      'Shop laptops, desktops, PC components, monitors, phones and accessories in Bangladesh. Genuine products, official warranty, cash on delivery nationwide.',
    canonical: '/',
  })

  // Memoised so the JSON-LD script is attached once rather than on every
  // render -- these builders return a fresh object each call.
  const orgLd = useMemo(() => organizationJsonLd(), [])
  const siteLd = useMemo(() => websiteJsonLd(), [])
  useJsonLd(orgLd)
  useJsonLd(siteLd)

  return (
    <div className="px-4 py-5">
      <h1 className="sr-only">
        MicroMart &mdash; computers and electronics in Bangladesh
      </h1>

      <section className="overflow-hidden rounded-card bg-chrome px-5 py-8 text-white sm:px-8 sm:py-12">
        <p className="text-xs font-semibold uppercase tracking-widest text-brand">
          Genuine products, official warranty
        </p>
        <h2 className="mt-2 max-w-xl text-2xl font-bold leading-8 sm:text-3xl sm:leading-10">
          Laptops, phones and components &mdash; delivered across Bangladesh
        </h2>
        <p className="mt-3 max-w-xl text-sm text-ink-inverse">
          Cash on delivery or pay online with bKash, Nagad, Rocket or a card.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            to="/search"
            className="inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-semibold text-white hover:bg-action-hover"
          >
            Browse the catalogue
          </Link>
          <Link
            to="/pc-builder"
            className="inline-flex min-h-[44px] items-center rounded-card border-2 border-white/30 px-6 text-sm font-semibold text-white hover:border-white"
          >
            Build a PC
          </Link>
        </div>
      </section>

      <CategoryTiles />

      {ROWS.slice(0, 4).map((row) => (
        <ProductRow key={row.id} {...row} />
      ))}

      <PromoBanners />

      {ROWS.slice(4).map((row) => (
        <ProductRow key={row.id} {...row} />
      ))}

      <BrandStrip />
    </div>
  )
}
