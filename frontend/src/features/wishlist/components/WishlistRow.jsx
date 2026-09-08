import { Link } from 'react-router-dom'

import { Badge, Button } from '@/components/ui'
import PriceTag from '@/features/catalog/components/PriceTag'
import StarRating from '@/features/catalog/components/StarRating'

// One saved product (FR-WSH-2, FR-WSH-3).

const ISSUE_LABEL = {
  out_of_stock: 'Out of stock',
  insufficient_stock: 'Not enough stock',
  unavailable: 'No longer sold',
}

const ISSUE_NOTE = {
  out_of_stock: 'Sold out for now — it stays on your list until you remove it.',
  insufficient_stock: 'Not enough stock to add right now.',
  unavailable: 'This product is no longer sold, so it cannot be added to a cart.',
}

const DATE_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

function formatAdded(value) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : DATE_FORMAT.format(date)
}

export default function WishlistRow({ item, onMoveToCart, onRemove, busy = false }) {
  const product = item.product ?? {}
  const image = product.primary_image
  const buyable = item.in_stock && item.default_variant_id != null
  const issue = item.issue
  const added = formatAdded(item.added_at)

  return (
    <li className="flex flex-col gap-3 border-b border-line p-3 last:border-b-0 sm:flex-row sm:gap-4 sm:p-4">
      <Link
        to={`/p/${product.slug}`}
        tabIndex={-1}
        aria-hidden="true"
        className="h-20 w-20 shrink-0 self-start overflow-hidden rounded-card border border-line bg-white"
      >
        {image?.url ? (
          <img
            src={image.url}
            alt=""
            loading="lazy"
            decoding="async"
            className="h-full w-full object-contain"
          />
        ) : (
          <span className="flex h-full w-full items-center justify-center text-[11px] text-ink-muted">
            No image
          </span>
        )}
      </Link>

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-col gap-1">
          <h2 className="text-sm font-medium leading-5 text-ink">
            <Link to={`/p/${product.slug}`} className="hover:text-action hover:underline">
              {product.name}
            </Link>
          </h2>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
            {product.brand?.name && <span>{product.brand.name}</span>}
            <StarRating value={product.rating_avg} count={product.rating_count} />
            {added && <span>Saved {added}</span>}
          </div>
        </div>

        <PriceTag
          price={product.price_min}
          priceMax={product.price_max}
          compareAtPrice={product.compare_at_price}
          discountPercent={product.discount_percent}
        />

        <div className="flex flex-wrap items-center gap-2">
          {/* FR-WSH-3: the state is said in words, never by colour alone. */}
          {item.in_stock ? (
            <Badge tone="success" size="sm">
              In stock
            </Badge>
          ) : (
            <Badge tone={issue === 'unavailable' ? 'neutral' : 'danger'} size="sm">
              {ISSUE_LABEL[issue] ?? 'Unavailable'}
            </Badge>
          )}
          {!item.in_stock && (
            <span className="text-xs text-ink-muted">
              {ISSUE_NOTE[issue] ?? 'Not available to buy right now.'}
            </span>
          )}
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap gap-2 sm:flex-col sm:justify-start">
        <Button
          size="sm"
          disabled={!buyable || busy}
          onClick={() => onMoveToCart(item)}
        >
          Move to cart
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => onRemove(item)}
        >
          Remove
          <span className="sr-only"> {product.name} from your wishlist</span>
        </Button>
      </div>
    </li>
  )
}
