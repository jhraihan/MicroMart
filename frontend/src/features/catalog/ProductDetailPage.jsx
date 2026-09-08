import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { Badge, Button, PageSpinner } from '@/components/ui'
import { useCart } from '@/features/cart/useCart'
import CompareButton from '@/features/compare/components/CompareButton'
import ProductReviews from '@/features/reviews/ProductReviews'
import WishlistButton from '@/features/wishlist/components/WishlistButton'
import { parseApiError } from '@/lib/api'
import { breadcrumbJsonLd, productJsonLd, useJsonLd, useSeo } from '@/lib/seo'

import { useProduct, useRelatedProducts } from './api'
import BoughtTogether from './components/BoughtTogether'
import Breadcrumbs from './components/Breadcrumbs'
import DeliveryInfo from './components/DeliveryInfo'
import ErrorState from './components/ErrorState'
import PriceTag from './components/PriceTag'
import ProductGallery from './components/ProductGallery'
import ProductGrid from './components/ProductGrid'
import SpecTable from './components/SpecTable'
import StarRating from './components/StarRating'
import StockBadge from './components/StockBadge'
import VariantSelector from './components/VariantSelector'

/*
 * Product detail (FR-CAT-4..8).
 *
 * The selected variant is held in the query string (?variant=<id>) rather
 * than component state, so a chosen configuration is linkable -- and because
 * the detail response already carries every variant, switching between them
 * repaints price, stock, SKU and gallery with no refetch and no reload.
 *
 * Nothing here reserves stock. `stock` only caps the quantity input; the real
 * decrement happens on order confirmation, server-side (PRD §6.5).
 */

function pickVariant(variants, requestedId) {
  if (!variants?.length) return null
  const requested = variants.find((variant) => variant.id === requestedId)
  if (requested) return requested
  return variants.find((variant) => variant.in_stock) ?? variants[0]
}

export default function ProductDetailPage() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const { data: product, isPending, isError, error, refetch } = useProduct(slug)
  const { data: related = [], isPending: relatedPending } = useRelatedProducts(slug, {
    enabled: Boolean(product?.slug),
  })

  /*
   * The cart facade, not the guest store. Reaching straight for
   * useCartStore.add here wrote a signed-in shopper's item into localStorage
   * while every cart surface read the server cart -- so the add vanished. One
   * `add` that knows which cart is live is the fix; see features/cart/useCart.
   */
  const { add: addToCart, isAdding } = useCart()
  const [quantity, setQuantity] = useState(1)
  const [confirmation, setConfirmation] = useState('')
  const [addError, setAddError] = useState('')
  const [lastVariantId, setLastVariantId] = useState(null)

  const variants = useMemo(() => product?.variants ?? [], [product])
  const requestedVariantId = Number.parseInt(searchParams.get('variant') ?? '', 10)
  const variant = useMemo(
    () => pickVariant(variants, requestedVariantId),
    [variants, requestedVariantId],
  )

  /*
   * Gallery for the current variant: its own images first, then the shared
   * product-level ones. Falls back to everything so a product whose images
   * are all variant-tagged is never blank.
   */
  const galleryImages = useMemo(() => {
    const all = product?.images ?? []
    if (!all.length && !variant?.images?.length) return []

    const variantImages = variant
      ? variant.images?.length
        ? variant.images
        : all.filter((image) => image.variant_id === variant.id)
      : []
    const shared = all.filter((image) => image.variant_id == null)

    const seen = new Set()
    const ordered = [...variantImages, ...shared].filter((image) => {
      if (seen.has(image.id)) return false
      seen.add(image.id)
      return true
    })
    return ordered.length ? ordered : all
  }, [product, variant])

  /*
   * Head tags and structured data. Both builders return a fresh object each
   * call, so they are memoised -- otherwise the JSON-LD script would be torn
   * down and reinserted on every render.
   */
  useSeo({
    title: product?.name,
    description:
      product?.description?.slice(0, 300) ||
      (product ? `Buy the ${product.name} in Bangladesh with official warranty.` : undefined),
    canonical: product ? `/p/${product.slug}` : undefined,
    image: product?.primary_image?.url,
    type: 'product',
  })
  const productLd = useMemo(() => productJsonLd(product), [product])
  const crumbLd = useMemo(
    () =>
      product
        ? breadcrumbJsonLd([
            { name: 'Home', path: '/' },
            ...(product.category
              ? [{ name: product.category.name, path: `/c/${product.category.slug}` }]
              : []),
            { name: product.name, path: `/p/${product.slug}` },
          ])
        : null,
    [product],
  )
  useJsonLd(productLd)
  useJsonLd(crumbLd)

  // A new variant means a fresh quantity -- the previous one may not even be
  // in stock. Adjusted during render rather than in an effect, so the reset
  // lands in the same commit as the variant change instead of one paint later.
  if (variant && lastVariantId !== variant.id) {
    setLastVariantId(variant.id)
    setQuantity(1)
    setConfirmation('')
    setAddError('')
  }

  useEffect(() => {
    if (!confirmation) return undefined
    const timer = setTimeout(() => setConfirmation(''), 4000)
    return () => clearTimeout(timer)
  }, [confirmation])

  if (isPending) return <PageSpinner label="Loading product" />

  if (isError) {
    const { status } = parseApiError(error)
    if (status === 404) {
      return (
        <div className="flex min-h-[50vh] flex-col items-center justify-center px-4 py-10 text-center">
          <h1 className="text-xl font-semibold text-ink">This product is not available</h1>
          <p className="mt-2 max-w-md text-sm text-ink-muted">
            It may have been removed from the catalogue, or the link may be wrong.
          </p>
          <Link
            to="/search"
            className="mt-6 inline-flex min-h-[44px] items-center rounded-card bg-action px-5 text-sm font-medium text-white hover:bg-action-hover"
          >
            Browse the catalogue
          </Link>
        </div>
      )
    }
    return (
      <div className="px-4 py-10">
        <ErrorState error={error} onRetry={refetch} title="Could not load this product" />
      </div>
    )
  }

  const outOfStock = !product.in_stock
  const canAddToCart = Boolean(variant?.in_stock)
  const maxQuantity = Math.max(1, Math.min(variant?.stock ?? 1, 10))

  function selectVariant(next) {
    const params = new URLSearchParams(searchParams)
    params.set('variant', String(next.id))
    // replace:true keeps the back button pointing at the previous *page*,
    // not at every variant the shopper tried.
    setSearchParams(params, { replace: true })
  }

  async function handleAddToCart() {
    if (!canAddToCart || isAdding) return
    setAddError('')
    try {
      // For a signed-in shopper this is a POST that the server can refuse --
      // stock is re-read there and never reserved by a cart (PRD 6.5) -- so
      // the confirmation waits for it rather than being printed on faith.
      await addToCart(
        {
          variantId: variant.id,
          productSlug: product.slug,
          productName: product.name,
          variantLabel: variant.option_label || 'Default',
          sku: variant.sku,
          unitPrice: variant.price,
          image: galleryImages[0]?.url ?? product.primary_image?.url ?? null,
          maxStock: variant.stock,
        },
        quantity,
      )
    } catch (err) {
      setAddError(
        parseApiError(err).message || 'We could not add this to your cart. Try again.',
      )
      return
    }
    setConfirmation(
      `${quantity} × ${product.name}${
        variant.option_label ? ` (${variant.option_label})` : ''
      } added to your cart.`,
    )
  }

  /*
   * Buy now is add-to-cart plus a redirect, not a separate express path.
   * Routing it through the same cart keeps one place where stock is checked
   * and one place where totals are computed -- a parallel "instant checkout"
   * is how the two drift apart and a shopper gets a different price on each.
   */
  async function handleBuyNow() {
    setAddError('')
    if (!variant?.in_stock) return
    try {
      await addToCart(
        {
          variantId: variant.id,
          productSlug: product.slug,
          productName: product.name,
          variantLabel: variant.option_label || 'Default',
          sku: variant.sku,
          unitPrice: variant.price,
          image: galleryImages[0]?.url ?? product.primary_image?.url ?? null,
          maxStock: variant.stock,
        },
        quantity,
      )
    } catch (err) {
      setAddError(
        parseApiError(err).message || 'We could not add this to your cart. Try again.',
      )
      return
    }
    navigate('/checkout')
  }

  return (
    <div className="px-4 py-5">
      <Breadcrumbs
        items={[
          { label: 'Home', to: '/' },
          ...(product.category
            ? [{ label: product.category.name, to: `/c/${product.category.slug}` }]
            : []),
          { label: product.name },
        ]}
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        {/* Keyed on the variant so switching options resets to its first image. */}
        <ProductGallery
          key={variant?.id ?? 'default'}
          images={galleryImages}
          productName={product.name}
        />

        <div className="flex flex-col gap-4">
          <div>
            <h1 className="text-xl font-semibold leading-7 text-ink sm:text-2xl">
              {product.name}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-muted">
              {product.brand && (
                <Link
                  to={`/search?brand=${encodeURIComponent(product.brand.slug)}`}
                  className="font-medium text-action hover:underline"
                >
                  {product.brand.name}
                </Link>
              )}
              {/* The aggregate the reviews section recomputes, and the way
                  into it. rating_avg/rating_count are written server-side by
                  recompute_product_rating from approved reviews only, so this
                  figure and the one above the review list are one number. */}
              <a
                href="#reviews"
                className="inline-flex min-h-[44px] items-center gap-1.5 rounded-card hover:underline"
              >
                <StarRating value={product.rating_avg} count={product.rating_count} size="md" />
                <span className="text-xs font-medium text-action">Read reviews</span>
              </a>
              {product.model_number && <span>Model: {product.model_number}</span>}
              {variant && <span>SKU: {variant.sku}</span>}
            </div>
          </div>

          <div className="rounded-card bg-white p-4 shadow-el-1">
            <PriceTag
              price={variant?.price ?? product.price_min}
              compareAtPrice={variant?.compare_at_price ?? null}
              discountPercent={variant?.discount_percent ?? 0}
              size="lg"
            />

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <StockBadge
                inStock={Boolean(variant?.in_stock)}
                isLowStock={Boolean(variant?.is_low_stock)}
                stock={variant?.stock ?? 0}
              />
              {product.warranty_months > 0 && (
                <Badge tone="action">{product.warranty_months} month warranty</Badge>
              )}
              {outOfStock && <Badge tone="neutral">All options sold out</Badge>}
            </div>

            {variants.length > 1 && (
              <div className="mt-4">
                <VariantSelector
                  variants={variants}
                  selectedId={variant?.id ?? null}
                  onSelect={selectVariant}
                />
              </div>
            )}

            <div className="mt-4 flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <label htmlFor="quantity" className="text-sm font-medium text-ink">
                  Quantity
                </label>
                <div className="flex items-stretch">
                  <button
                    type="button"
                    onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                    disabled={!canAddToCart || quantity <= 1}
                    aria-label="Decrease quantity"
                    className="flex h-11 w-11 items-center justify-center rounded-l-card border border-line bg-white text-lg text-ink disabled:cursor-not-allowed disabled:text-ink-subtle"
                  >
                    &minus;
                  </button>
                  <input
                    id="quantity"
                    type="number"
                    inputMode="numeric"
                    min="1"
                    max={maxQuantity}
                    value={quantity}
                    disabled={!canAddToCart}
                    onChange={(event) => {
                      const next = Number.parseInt(event.target.value, 10)
                      if (Number.isNaN(next)) return
                      setQuantity(Math.min(Math.max(1, next), maxQuantity))
                    }}
                    className="h-11 w-14 border-y border-line bg-white text-center text-base text-ink disabled:bg-page"
                  />
                  <button
                    type="button"
                    onClick={() => setQuantity((q) => Math.min(maxQuantity, q + 1))}
                    disabled={!canAddToCart || quantity >= maxQuantity}
                    aria-label="Increase quantity"
                    className="flex h-11 w-11 items-center justify-center rounded-r-card border border-line bg-white text-lg text-ink disabled:cursor-not-allowed disabled:text-ink-subtle"
                  >
                    +
                  </button>
                </div>
              </div>

              <Button
                size="lg"
                className="flex-1"
                disabled={!canAddToCart || isAdding}
                onClick={handleAddToCart}
              >
                {canAddToCart ? (isAdding ? 'Adding…' : 'Add to cart') : 'Out of stock'}
              </Button>
            </div>

            {canAddToCart && (
              <button
                type="button"
                onClick={handleBuyNow}
                disabled={isAdding}
                className="mt-2 flex min-h-[44px] w-full items-center justify-center rounded-card border-2 border-action text-sm font-semibold text-action transition-colors hover:bg-action hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                Buy now
              </button>
            )}

            <p role="status" aria-live="polite" className="mt-2 min-h-[20px] text-sm text-success">
              {confirmation}
            </p>

            {addError && (
              <p role="alert" className="text-sm text-danger">
                {addError}
              </p>
            )}

            {!canAddToCart && (
              <p className="text-sm text-ink-muted">
                {variants.length > 1
                  ? 'This option is sold out. Try another option above.'
                  : 'This product is sold out. Check back soon.'}
              </p>
            )}

            {/* FR-WSH-1. Saving is per product, not per variant -- the
                wishlist stores a product and the row offers its cheapest
                active variant when moving to the cart. Deliberately still
                offered when the product is sold out: saving something to
                wait for it is most of the point. */}
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <WishlistButton product={product} variant="inline" />
              <CompareButton product={product} variant="inline" />
            </div>

            {/* A part the builder understands links straight into it, so a
                shopper reading about a motherboard can check what it fits
                without navigating back out to the tool. */}
            {product.component && (
              <Link
                to={`/pc-builder?slot=${product.component.slot}&variant=${variant?.id ?? ''}`}
                className="mt-2 flex min-h-[44px] items-center justify-center gap-2 rounded-card bg-page px-3 text-sm font-medium text-action hover:underline"
              >
                Add to a PC build as {product.component.label.toLowerCase()}
              </Link>
            )}
          </div>

          {product.highlights?.length > 0 && (
            <section
              aria-labelledby="highlights-heading"
              className="rounded-card bg-white p-4 shadow-el-1"
            >
              <h2 id="highlights-heading" className="mb-2 text-base font-semibold text-ink">
                At a glance
              </h2>
              <ul className="flex flex-col gap-1.5 text-sm text-ink">
                {product.highlights.map((point) => (
                  <li key={point} className="flex gap-2">
                    <span aria-hidden="true" className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-pill bg-action" />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <SpecTable product={product} />

          <DeliveryInfo product={product} />
        </div>
      </div>

      {product.description && (
        <section aria-labelledby="description-heading" className="mt-6 rounded-card bg-white p-4 shadow-el-1">
          <h2 id="description-heading" className="mb-2 text-base font-semibold text-ink">
            Description
          </h2>
          <p className="max-w-prose whitespace-pre-line text-sm leading-6 text-ink">
            {product.description}
          </p>
        </section>
      )}

      <BoughtTogether product={product} />

      <ProductReviews product={product} />

      {(relatedPending || related.length > 0) && (
        <section aria-labelledby="related-heading" className="mt-8">
          <h2 id="related-heading" className="mb-3 text-lg font-semibold text-ink">
            Related products
          </h2>
          <ProductGrid
            products={related}
            loading={relatedPending}
            skeletonCount={4}
            variant="wide"
          />
        </section>
      )}
    </div>
  )
}
