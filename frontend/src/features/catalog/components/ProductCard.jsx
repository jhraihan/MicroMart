import { Link } from 'react-router-dom'

import CompareButton from '@/features/compare/components/CompareButton'
import WishlistButton from '@/features/wishlist/components/WishlistButton'

import PriceTag from './PriceTag'
import StarRating from './StarRating'

/*
 * The primary listing unit (design-system.md §6.3), on the tokens in
 * index.css. Two-up at 360px, so the whole grid is usable one-handed.
 */

// The spec keys worth showing on a card, in preference order. A laptop's
// processor tells a shopper more than its warranty; the first two that a
// product actually has are the ones shown.
const CARD_SPEC_KEYS = [
  'Processor',
  'Chipset',
  'Capacity',
  'Memory Size',
  'RAM',
  'Storage',
  'Resolution',
  'Screen Size',
  'Wattage',
  'Speed',
  'Socket',
  'Type',
]

/**
 * Pull a short spec line out of whatever the row carries.
 *
 * The list endpoint does not include specs, so on a listing page this returns
 * the product's highlights instead when they are present, and nothing at all
 * otherwise. Rendering nothing is correct -- inventing a line from the name
 * would just repeat the title.
 */
function shortSpecLine(product) {
  if (product.highlights?.length) return product.highlights[0]
  if (!product.specs?.length) return null

  const byKey = new Map(product.specs.map((s) => [s.key, s.value]))
  const picked = CARD_SPEC_KEYS.filter((key) => byKey.has(key))
    .slice(0, 2)
    .map((key) => `${key}: ${byKey.get(key)}`)
  return picked.length ? picked.join(' · ') : null
}

function Badges({ hasDiscount, discountPercent, outOfStock }) {
  return (
    /* pointer-events-none: these sit above the stretched link's overlay, and
       they are labels, not controls -- a tap here must still open the card. */
    <div className="pointer-events-none absolute left-0 top-3 z-10 flex flex-col items-start gap-1">
      {hasDiscount && (
        <span className="rounded-r-pill bg-price px-2.5 py-1 text-[11px] font-medium text-white">
          Save {discountPercent}%
        </span>
      )}
      {outOfStock && (
        <span className="rounded-r-pill bg-ink px-2.5 py-1 text-[11px] font-medium text-white">
          Out of stock
        </span>
      )}
    </div>
  )
}

export default function ProductCard({ product, layout = 'grid' }) {
  const image = product.primary_image
  const to = `/p/${product.slug}`
  const outOfStock = !product.in_stock
  const hasDiscount = Boolean(product.compare_at_price) && product.discount_percent > 0
  const multiVariant = (product.variant_count ?? 1) > 1
  const specLine = shortSpecLine(product)

  if (layout === 'list') {
    return (
      <article className="group relative flex gap-3 overflow-hidden rounded-card bg-white p-3 shadow-el-1 transition-shadow hover:shadow-el-2 sm:gap-4 sm:p-4">
        <Badges
          hasDiscount={hasDiscount}
          discountPercent={product.discount_percent}
          outOfStock={outOfStock}
        />

        <div className="flex h-24 w-24 shrink-0 items-center justify-center rounded-card border border-line bg-white p-2 sm:h-36 sm:w-36">
          {image?.url ? (
            <img
              src={image.url}
              alt=""
              width={144}
              height={144}
              loading="lazy"
              decoding="async"
              className="h-full w-full object-contain"
            />
          ) : (
            <span className="text-xs text-ink-muted">No image</span>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <h3 className="text-sm font-medium leading-5 text-ink sm:text-base">
            <Link
              to={to}
              className="after:absolute after:inset-0 after:content-[''] hover:text-action hover:underline"
            >
              {product.name}
            </Link>
          </h3>

          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
            {product.brand?.name && <span>{product.brand.name}</span>}
            <StarRating value={product.rating_avg} count={product.rating_count} />
          </div>

          {specLine && (
            <p className="line-clamp-2 text-xs leading-relaxed text-ink-muted">{specLine}</p>
          )}

          <div className="mt-auto flex flex-wrap items-end justify-between gap-2 pt-1">
            <PriceTag
              price={product.price_min}
              priceMax={product.price_max}
              compareAtPrice={product.compare_at_price}
              discountPercent={product.discount_percent}
            />

            {/* z-20 lifts the real controls above the stretched link. */}
            <div className="relative z-20 flex items-center gap-1.5">
              <CompareButton product={product} />
              <WishlistButton product={product} />
              {outOfStock ? (
                <span className="flex min-h-[44px] items-center justify-center rounded-card border-2 border-line bg-page px-4 text-sm font-medium text-ink-muted">
                  Out of stock
                </span>
              ) : (
                <Link
                  to={to}
                  className="flex min-h-[44px] items-center justify-center rounded-card border-2 border-action px-4 text-sm font-medium text-action transition-colors hover:bg-action hover:text-white"
                >
                  {multiVariant ? 'Choose options' : 'View details'}
                </Link>
              )}
            </div>
          </div>
        </div>
      </article>
    )
  }

  return (
    <article className="group relative flex h-full flex-col overflow-hidden rounded-card bg-white shadow-el-1 transition-shadow hover:shadow-el-2">
      <Badges
        hasDiscount={hasDiscount}
        discountPercent={product.discount_percent}
        outOfStock={outOfStock}
      />

      {/* FR-WSH-1 and comparison. z-20 puts these above both the badges (z-10)
          and the stretched link's ::after overlay, and unlike the badges they
          keep their pointer events -- a tap here must act, not navigate. */}
      <div className="absolute right-1.5 top-1.5 z-20 flex flex-col gap-1.5">
        <WishlistButton product={product} />
        <CompareButton product={product} />
      </div>

      {/* The stretched link below already covers this area, so the image is not
          a second link -- one tab stop. alt is deliberately empty: the link
          right underneath announces the product name, and a duplicate would be
          read out twice. */}
      <div className="flex aspect-square items-center justify-center border-b-2 border-tint bg-white p-4">
        {image?.url ? (
          <img
            src={image.url}
            alt=""
            width={228}
            height={228}
            loading="lazy"
            decoding="async"
            className="h-full w-full object-contain transition-opacity group-hover:opacity-90"
          />
        ) : (
          <span className="text-xs text-ink-muted">No image</span>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 p-3">
        <h3 className="text-sm font-normal leading-5 text-ink">
          {/* The whole card is clickable via this stretched link, but the link
              text stays the product name so a screen reader announces it. */}
          <Link
            to={to}
            className="after:absolute after:inset-0 after:content-[''] hover:text-action hover:underline"
          >
            {product.name}
          </Link>
        </h3>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
          {product.brand?.name && <span>{product.brand.name}</span>}
          <StarRating value={product.rating_avg} count={product.rating_count} />
        </div>

        {specLine && (
          <p className="line-clamp-2 text-xs leading-relaxed text-ink-muted">{specLine}</p>
        )}

        <div className="mt-auto flex flex-col gap-2">
          <PriceTag
            price={product.price_min}
            priceMax={product.price_max}
            compareAtPrice={product.compare_at_price}
            discountPercent={product.discount_percent}
          />

          {outOfStock ? (
            /* A span, not a disabled button: a disabled button neither fires
               nor bubbles a click, so painting one over the stretched link
               would make the largest region of a sold-out card inert and
               leave the wrapped title as the only way into the product. The
               state is still shown -- never hidden -- and the badge top-left
               announces it too. */
            <span className="flex min-h-[44px] items-center justify-center rounded-card border-2 border-line bg-page text-sm font-medium text-ink-muted">
              Out of stock
            </span>
          ) : (
            <span className="flex min-h-[44px] items-center justify-center rounded-card border-2 border-action text-sm font-medium text-action transition-colors group-hover:bg-action group-hover:text-white">
              {multiVariant ? 'Choose options' : 'View details'}
            </span>
          )}
        </div>
      </div>
    </article>
  )
}

/** Matches the card's shape so the grid does not jump when data lands. */
export function ProductCardSkeleton({ layout = 'grid' }) {
  if (layout === 'list') {
    return (
      <div className="flex gap-4 rounded-card bg-white p-4 shadow-el-1">
        <div className="h-36 w-36 shrink-0 animate-pulse rounded-card bg-page" />
        <div className="flex flex-1 flex-col gap-2">
          <div className="h-4 animate-pulse rounded bg-page" />
          <div className="h-3.5 w-1/3 animate-pulse rounded bg-page" />
          <div className="h-3 w-2/3 animate-pulse rounded bg-page" />
          <div className="mt-auto h-6 w-1/4 animate-pulse rounded bg-page" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-card bg-white shadow-el-1">
      <div className="aspect-square animate-pulse bg-page" />
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="h-3.5 animate-pulse rounded bg-page" />
        <div className="h-3.5 w-2/3 animate-pulse rounded bg-page" />
        <div className="mt-auto h-5 w-1/2 animate-pulse rounded bg-page" />
        <div className="h-11 animate-pulse rounded-card bg-page" />
      </div>
    </div>
  )
}

export { shortSpecLine }
