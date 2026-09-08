import { useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'

import { Button, Spinner } from '@/components/ui'
import ErrorState from '@/features/catalog/components/ErrorState'
import Pagination from '@/features/catalog/components/Pagination'
import { useAuthStore } from '@/stores/authStore'

import { useDeleteReview, useMyReview, useProductReviews } from './api'
import ReviewForm from './components/ReviewForm'
import ReviewList, { ReviewCard } from './components/ReviewList'
import ReviewSummary from './components/ReviewSummary'

// The reviews section of the product page (PRD §5.8).

// config/pagination.py — PAGE_SIZE 24, not overridden by this client.
const PAGE_SIZE = 24

const SORT_OPTIONS = [
  { value: 'recent', label: 'Most recent' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'rating_high', label: 'Highest rated' },
  { value: 'rating_low', label: 'Lowest rated' },
]

const STATUS_NOTE = {
  pending: 'Your review is awaiting moderation. It will appear here once our team has checked it.',
  approved: 'Your review has been published.',
  rejected: 'Your review was not published. You can edit it and submit it again.',
}

export default function ProductReviews({ product }) {
  const slug = product.slug
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const user = useAuthStore((s) => s.user)

  const [isEditing, setIsEditing] = useState(false)
  const [announcement, setAnnouncement] = useState('')

  const requestedPage = Number.parseInt(searchParams.get('rpage') ?? '1', 10)
  const page = Number.isFinite(requestedPage) && requestedPage > 1 ? requestedPage : 1
  const requestedStars = Number.parseInt(searchParams.get('stars') ?? '', 10)
  const rating = requestedStars >= 1 && requestedStars <= 5 ? requestedStars : null
  const sortParam = searchParams.get('rsort') ?? 'recent'
  const sort = SORT_OPTIONS.some((option) => option.value === sortParam) ? sortParam : 'recent'

  const { data, isPending, isFetching, isError, error, refetch } = useProductReviews(slug, {
    page,
    rating,
    sort,
  })
  const { data: myReview } = useMyReview(slug)
  const removeReview = useDeleteReview(slug)

  /* Rewrite only the review parameters; ?variant and anything else survive. */
  function applyParams(overrides) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(overrides)) {
      if (value === null || value === undefined || value === '') next.delete(key)
      else next.set(key, String(value))
    }
    setSearchParams(next, { replace: true })
  }

  function hrefForPage(nextPage) {
    const next = new URLSearchParams(searchParams)
    if (nextPage > 1) next.set('rpage', String(nextPage))
    else next.delete('rpage')
    const query = next.toString()
    return query ? `?${query}` : ''
  }

  const reviews = data?.results ?? []
  const summary = data?.summary
  const total = data?.count ?? 0
  const canReview = data?.can_review === true

  function handleSaved(saved) {
    setIsEditing(false)
    setAnnouncement(
      saved?.status === 'pending'
        ? 'Thank you. Your review has been submitted and is awaiting moderation.'
        : 'Your review has been saved.',
    )
  }

  function handleWithdraw() {
    removeReview.mutate(myReview.id, {
      onSuccess: () => {
        setIsEditing(false)
        setAnnouncement('Your review has been removed.')
      },
    })
  }

  return (
    <section id="reviews" aria-labelledby="reviews-heading" className="mt-8 scroll-mt-20">
      <h2 id="reviews-heading" className="mb-3 text-lg font-semibold text-ink">
        Ratings and reviews
      </h2>

      <div className="rounded-card bg-white p-4 shadow-el-1">
        {isPending ? (
          <Spinner label="Loading reviews" />
        ) : (
          <ReviewSummary
            summary={summary}
            activeRating={rating}
            onFilterRating={(next) => applyParams({ stars: next, rpage: null })}
          />
        )}
      </div>

      {/* --- write / edit ------------------------------------------------ */}
      <div className="mt-4">
        <p role="status" aria-live="polite" className="min-h-[20px] text-sm text-success">
          {announcement}
        </p>

        {isEditing && myReview ? (
          <ReviewForm
            slug={slug}
            review={myReview}
            onDone={handleSaved}
            onCancel={() => setIsEditing(false)}
          />
        ) : myReview ? (
          <div className="rounded-card border border-line bg-white p-4">
            <p className="text-sm font-medium text-ink">Your review</p>
            <p className="mt-1 text-sm text-ink-muted">
              {STATUS_NOTE[myReview.status] ?? STATUS_NOTE.pending}
            </p>
            <ReviewCard review={myReview} />
            <div className="flex flex-wrap gap-2">
              {myReview.is_editable && (
                <Button variant="outline" size="sm" onClick={() => setIsEditing(true)}>
                  Edit your review
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                loading={removeReview.isPending}
                onClick={handleWithdraw}
              >
                Remove it
              </Button>
            </div>
            {!myReview.is_editable && (
              <p className="mt-2 text-xs text-ink-muted">
                A review can be edited for 30 days after it is written.
              </p>
            )}
          </div>
        ) : !user ? (
          <div className="rounded-card border border-line bg-white p-4">
            <p className="text-sm text-ink">
              Bought this product? Sign in to write a review.
            </p>
            <Link
              to="/login"
              state={{ from: `${location.pathname}${location.search}` }}
              className="mt-2 inline-flex min-h-[44px] items-center rounded-card border-2 border-action px-4 text-sm font-medium text-action hover:bg-action hover:text-white"
            >
              Sign in to review
            </Link>
          </div>
        ) : canReview ? (
          <ReviewForm slug={slug} onDone={handleSaved} />
        ) : !isPending ? (
          /* Why, without saying which: `can_review` is false both for "you
             have not had one delivered" and for "you already reviewed it",
             and the server does not distinguish them on this endpoint. FR-REV-2
             is stated plainly so the shopper knows the rule rather than
             thinking the button is broken. */
          <p className="rounded-card border border-line bg-white p-4 text-sm text-ink-muted">
            Reviews come from customers who bought the product here. Once an order
            containing it has been delivered, you can leave one — and each customer
            may review a product once.
          </p>
        ) : null}
      </div>

      {/* --- list -------------------------------------------------------- */}
      {isError ? (
        <div className="mt-4">
          <ErrorState error={error} onRetry={refetch} title="Could not load the reviews" />
        </div>
      ) : (
        <>
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-ink-muted" aria-live="polite">
              {total === 0
                ? 'No published reviews yet'
                : `Showing ${total} ${total === 1 ? 'review' : 'reviews'}${
                    rating ? ` rated ${rating} ${rating === 1 ? 'star' : 'stars'}` : ''
                  }`}
              {isFetching && !isPending && <span className="ml-2">updating…</span>}
            </p>

            {total > 1 && (
              <div className="flex items-center gap-2">
                <label htmlFor="review-sort" className="whitespace-nowrap text-sm text-ink-muted">
                  Sort by
                </label>
                <select
                  id="review-sort"
                  value={sort}
                  onChange={(event) =>
                    applyParams({ rsort: event.target.value, rpage: null })
                  }
                  className="min-h-[44px] rounded-card border border-line bg-white px-2 text-sm text-ink focus:border-action"
                >
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="mt-3" aria-busy={isFetching || undefined}>
            {isPending ? (
              <div className="rounded-card bg-white px-4 py-10 text-center">
                <Spinner label="Loading reviews" />
              </div>
            ) : (
              <ReviewList
                reviews={reviews}
                emptyMessage={
                  rating
                    ? `No ${rating}-star reviews yet. Clear the filter to see the rest.`
                    : 'No reviews yet. Be the first to review this product once your order is delivered.'
                }
              />
            )}
          </div>

          <Pagination
            page={page}
            count={total}
            pageSize={PAGE_SIZE}
            hrefForPage={hrefForPage}
          />
        </>
      )}
    </section>
  )
}
