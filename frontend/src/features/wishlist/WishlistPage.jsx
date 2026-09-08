import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { PageSpinner } from '@/components/ui'
import { useAddCartItem } from '@/features/cart/api'
import ErrorState from '@/features/catalog/components/ErrorState'
import Pagination from '@/features/catalog/components/Pagination'
import { parseApiError } from '@/lib/api'

import { useWishlist, useWishlistMutations } from './api'
import WishlistRow from './components/WishlistRow'

// The wishlist screen (PRD §5.9, FR-WSH-2, FR-WSH-3).

// config/pagination.py — PAGE_SIZE 24, not overridden by this client.
const PAGE_SIZE = 24

export default function WishlistPage() {
  const [searchParams] = useSearchParams()
  const requested = Number.parseInt(searchParams.get('page') ?? '1', 10)
  const page = Number.isFinite(requested) && requested > 1 ? requested : 1

  const { data, isPending, isFetching, isError, error, refetch } = useWishlist(page)
  const { remove } = useWishlistMutations()
  const addToCart = useAddCartItem()

  const [pendingId, setPendingId] = useState(null)
  const [announcement, setAnnouncement] = useState('')
  const [failure, setFailure] = useState('')

  const items = data?.results ?? []
  const count = data?.count ?? 0
  const apiError = isError ? parseApiError(error) : null
  const hrefForPage = (next) => (next <= 1 ? '' : `?page=${next}`)

  function handleMoveToCart(item) {
    setPendingId(item.id)
    setFailure('')
    addToCart.mutate(
      { variantId: item.default_variant_id, quantity: 1 },
      {
        onSuccess: () => {
          remove.mutate(item.product.id, {
            onSettled: () => setPendingId(null),
          })
          setAnnouncement(`${item.product.name} moved to your cart.`)
        },
        onError: (mutationError) => {
          setPendingId(null)
          setFailure(parseApiError(mutationError).message)
        },
      },
    )
  }

  function handleRemove(item) {
    setPendingId(item.id)
    setFailure('')
    remove.mutate(item.product.id, {
      onSuccess: () => setAnnouncement(`${item.product.name} removed from your wishlist.`),
      onError: (mutationError) => setFailure(parseApiError(mutationError).message),
      onSettled: () => setPendingId(null),
    })
  }

  if (isPending) return <PageSpinner label="Loading your wishlist" />

  // DRF 404s a page past the end. Offer the way back rather than a dead end.
  if (apiError?.status === 404 && page > 1) {
    return (
      <div className="px-4 py-6">
        <div className="rounded-card border border-line bg-white px-4 py-10 text-center">
          <h1 className="text-base font-semibold text-ink">That page is empty</h1>
          <p className="mt-2 text-sm text-ink-muted">
            You do not have that many saved products.
          </p>
          <Link
            to={{ search: hrefForPage(1) }}
            className="mt-4 inline-flex min-h-[44px] items-center rounded-card border-2 border-action px-4 text-sm font-medium text-action hover:bg-action hover:text-white"
          >
            Back to the first page
          </Link>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="px-4 py-6">
        <ErrorState error={error} onRetry={refetch} title="Could not load your wishlist" />
      </div>
    )
  }

  return (
    <div className="px-4 py-5">
      <h1 className="text-xl font-semibold text-ink">Your wishlist</h1>
      <p className="mt-1 text-sm text-ink-muted">
        {count === 0
          ? 'Nothing saved yet.'
          : `${count} saved ${count === 1 ? 'product' : 'products'}. Prices and stock are checked each time you open this page.`}
      </p>

      <p role="status" aria-live="polite" className="mt-2 min-h-[20px] text-sm text-success">
        {announcement}
      </p>
      {failure && (
        <p role="alert" className="rounded-card bg-danger/10 px-3 py-2 text-sm text-danger">
          {failure}
        </p>
      )}

      {count === 0 ? (
        <div className="mt-4 rounded-card border border-line bg-white px-4 py-12 text-center">
          <p className="text-sm text-ink">
            Save products you are thinking about, and they will wait for you here.
          </p>
          <Link
            to="/search"
            className="mt-4 inline-flex min-h-[44px] items-center rounded-card bg-action px-5 text-sm font-medium text-white hover:bg-action-hover"
          >
            Browse the catalogue
          </Link>
        </div>
      ) : (
        <>
          <ul
            aria-busy={isFetching || undefined}
            className="mt-4 rounded-card bg-white shadow-el-1"
          >
            {items.map((item) => (
              <WishlistRow
                key={item.id}
                item={item}
                busy={pendingId === item.id}
                onMoveToCart={handleMoveToCart}
                onRemove={handleRemove}
              />
            ))}
          </ul>

          <Pagination
            page={page}
            count={count}
            pageSize={PAGE_SIZE}
            hrefForPage={hrefForPage}
          />
        </>
      )}
    </div>
  )
}
