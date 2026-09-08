import { Badge } from '@/components/ui'

import ReviewStars from './ReviewStars'

/*
 * The public review list (FR-REV-1, FR-REV-6).
 *
 * Only approved reviews ever reach here -- the endpoint filters on status, so
 * this component has no notion of moderation and cannot accidentally paint a
 * pending one as published.
 *
 * The author is printed by display name. The API deliberately never sends an
 * email address on this surface (apps/reviews/serializers.py::display_name
 * masks the mailbox when a customer has no name), because a public review
 * list carrying addresses is a harvestable one.
 */

const DATE_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

function formatReviewDate(value) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : DATE_FORMAT.format(date)
}

export function ReviewCard({ review }) {
  const written = formatReviewDate(review.created_at)
  const edited =
    review.updated_at && review.updated_at !== review.created_at
      ? formatReviewDate(review.updated_at)
      : null

  return (
    <article className="flex flex-col gap-2 border-b border-line py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <ReviewStars rating={review.rating} />
        {review.is_verified_purchase && (
          // FR-REV-6. Derived server-side from the delivered order that
          // proved eligibility -- never a flag a request can set.
          <Badge tone="success" size="sm">
            Verified Purchase
          </Badge>
        )}
      </div>

      {review.title && (
        <h3 className="text-sm font-semibold leading-5 text-ink">{review.title}</h3>
      )}

      {review.body && (
        <p className="max-w-prose whitespace-pre-line text-sm leading-6 text-ink">
          {review.body}
        </p>
      )}

      <p className="text-xs text-ink-muted">
        <span className="font-medium text-ink">{review.author_name}</span>
        {written && (
          <>
            {' · '}
            <time dateTime={review.created_at}>{written}</time>
          </>
        )}
        {edited && <> · edited {edited}</>}
      </p>
    </article>
  )
}

export default function ReviewList({ reviews = [], emptyMessage = 'No reviews yet.' }) {
  if (!reviews.length) {
    return (
      <p className="rounded-card border border-line bg-white px-4 py-8 text-center text-sm text-ink-muted">
        {emptyMessage}
      </p>
    )
  }

  return (
    <div className="rounded-card bg-white px-4 shadow-el-1">
      {reviews.map((review) => (
        <ReviewCard key={review.id} review={review} />
      ))}
    </div>
  )
}
