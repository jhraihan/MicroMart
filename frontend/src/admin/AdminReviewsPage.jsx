import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge, Button, Spinner } from '@/components/ui'
import StarRating from '@/features/catalog/components/StarRating'
import { parseApiError } from '@/lib/api'

import { useAdminReviews, useModerateReview } from './api'
import {
  AdminError,
  AdminPageHeader,
  AdminPager,
  Callout,
  FormAlert,
  LoadingRowNote,
} from './components/AdminUI'

const PAGE_SIZE = 24

const TABS = [
  { value: 'pending', label: 'Awaiting moderation' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'all', label: 'Everything' },
]

const STATUS_TONE = { pending: 'warning', approved: 'success', rejected: 'danger' }

function formatWhen(value) {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

/**
 * The moderation queue (US-A6, FR-REV-4).
 *
 * Defaults to `pending` because that is what the endpoint defaults to and
 * what the screen is for: an admin opening it wants what is waiting, not the
 * archive.
 *
 * Approve and reject both POST to the same moderation endpoint, which calls
 * the one service function that recomputes the product's rating. Nothing is
 * adjusted client-side -- only approved reviews count toward `rating_avg`,
 * and only the server knows which those are.
 */
export default function AdminReviewsPage() {
  const [status, setStatus] = useState('pending')
  const [page, setPage] = useState(1)

  const reviews = useAdminReviews({ status, page, page_size: PAGE_SIZE })
  const moderate = useModerateReview()

  const rows = reviews.data?.results ?? []

  function decide(review, decision) {
    moderate.mutate({ id: review.id, decision })
  }

  return (
    <div>
      <AdminPageHeader
        title="Reviews"
        description="Approve or reject customer reviews. A review is only published — and only counted in a product's rating — once it is approved."
      />

      <Callout tone="info" className="mb-4">
        <strong className="text-ink">Only approved reviews count.</strong> A
        pending or rejected review is invisible on the storefront and
        contributes nothing to the product&rsquo;s star average or review
        count. Approving or rejecting recalculates that average immediately.
        Editing a review returns it here for moderation again.
      </Callout>

      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Filter by moderation status">
        {TABS.map((tab) => (
          <Button
            key={tab.value}
            size="sm"
            variant={status === tab.value ? 'primary' : 'outline'}
            aria-pressed={status === tab.value}
            onClick={() => {
              setStatus(tab.value)
              setPage(1)
            }}
          >
            {tab.label}
          </Button>
        ))}
      </div>

      {moderate.isError && <FormAlert message={parseApiError(moderate.error).message} />}

      {reviews.isError ? (
        <AdminError error={reviews.error} onRetry={() => reviews.refetch()} />
      ) : reviews.isPending ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" label="Loading reviews" />
        </div>
      ) : (
        <>
          <LoadingRowNote show={reviews.isFetching} label="Updating queue" />

          {rows.length === 0 ? (
            <p className="rounded-card border border-line bg-white px-4 py-12 text-center text-sm text-ink-muted">
              {status === 'pending'
                ? 'Nothing is waiting for moderation.'
                : 'No reviews with this status.'}
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {rows.map((review) => {
                const busy = moderate.isPending && moderate.variables?.id === review.id
                return (
                  <li
                    key={review.id}
                    className="rounded-card border border-line bg-white p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          {/* The storefront's own star treatment --
                              `warning` amber, never brand orange,
                              which fails AA on white. */}
                          <StarRating
                            value={review.rating}
                            showCount={false}
                            label={`Rated ${review.rating} out of 5`}
                          />
                          <Badge tone={STATUS_TONE[review.status] ?? 'neutral'} size="sm">
                            {review.status}
                          </Badge>
                          {review.is_verified_purchase && (
                            <Badge tone="action" size="sm">
                              Verified purchase
                            </Badge>
                          )}
                        </div>
                        <p className="mt-2 text-sm font-semibold text-ink">
                          {review.title || <span className="text-ink-muted">No title</span>}
                        </p>
                        <p className="mt-1 max-w-prose whitespace-pre-line text-sm text-ink">
                          {review.body || <span className="text-ink-muted">No comment left.</span>}
                        </p>
                      </div>

                      <div className="flex shrink-0 gap-2">
                        <Button
                          size="sm"
                          loading={busy && moderate.variables?.decision === 'approve'}
                          disabled={busy || review.status === 'approved'}
                          onClick={() => decide(review, 'approve')}
                        >
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="danger"
                          loading={busy && moderate.variables?.decision === 'reject'}
                          disabled={busy || review.status === 'rejected'}
                          onClick={() => decide(review, 'reject')}
                        >
                          Reject
                        </Button>
                      </div>
                    </div>

                    <dl className="mt-3 grid gap-x-6 gap-y-1 border-t border-line pt-3 text-xs text-ink-muted sm:grid-cols-2 lg:grid-cols-4">
                      <div>
                        <dt className="inline font-medium text-ink">Product: </dt>
                        <dd className="inline">
                          <Link
                            to={`/admin/products/${review.product.id}`}
                            className="inline-flex min-h-[44px] items-center text-action hover:underline"
                          >
                            {review.product.name}
                          </Link>
                        </dd>
                      </div>
                      <div>
                        <dt className="inline font-medium text-ink">Customer: </dt>
                        <dd className="inline">
                          {review.author_name} ({review.author_email})
                        </dd>
                      </div>
                      <div>
                        <dt className="inline font-medium text-ink">Submitted: </dt>
                        <dd className="inline">{formatWhen(review.created_at)}</dd>
                      </div>
                      <div>
                        <dt className="inline font-medium text-ink">Proving order: </dt>
                        <dd className="inline">{review.order_reference ?? '—'}</dd>
                      </div>
                      {review.moderated_at && (
                        <div className="sm:col-span-2 lg:col-span-4">
                          <dt className="inline font-medium text-ink">Last moderated: </dt>
                          <dd className="inline">
                            {formatWhen(review.moderated_at)}
                            {review.moderated_by_email ? ` by ${review.moderated_by_email}` : ''}
                          </dd>
                        </div>
                      )}
                    </dl>
                  </li>
                )
              })}
            </ul>
          )}

          <AdminPager
            page={page}
            count={reviews.data?.count ?? 0}
            pageSize={PAGE_SIZE}
            onChange={setPage}
          />
        </>
      )}
    </div>
  )
}
