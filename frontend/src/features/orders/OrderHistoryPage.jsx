import { Link, useSearchParams } from 'react-router-dom'

import { OrderStatusBadge, PageSpinner } from '@/components/ui'
import ErrorState from '@/features/catalog/components/ErrorState'
import Pagination from '@/features/catalog/components/Pagination'
import { parseApiError } from '@/lib/api'
import { formatMoney } from '@/lib/money'

import { useOrders } from './api'
import SignInPrompt from './components/SignInPrompt'
import { formatOrderDate, paymentMethodLabel } from './orderDisplay'

// Order history (PRD §5.5, FR-ORD-1).

// config/pagination.py — PAGE_SIZE 24, and this client does not override it.
const PAGE_SIZE = 24

function preview(items = []) {
  return items.slice(0, 3)
}

export default function OrderHistoryPage() {
  const [searchParams] = useSearchParams()
  const requested = Number.parseInt(searchParams.get('page') ?? '1', 10)
  const page = Number.isFinite(requested) && requested > 1 ? requested : 1

  const { data, isPending, isFetching, isError, error, refetch } = useOrders(page)

  const orders = data?.results ?? []
  const count = data?.count ?? 0
  const apiError = isError ? parseApiError(error) : null
  const hrefForPage = (next) => (next <= 1 ? '' : `?page=${next}`)

  if (isPending) return <PageSpinner label="Loading your orders" />

  // 401 here is the ordinary signed-out case, not a failure worth an alert.
  if (apiError?.status === 401 || apiError?.status === 403) {
    return (
      <div className="px-4 py-16">
        <SignInPrompt message="Sign in to see the orders placed with this account. A guest order is traced by the reference in its confirmation email." />
      </div>
    )
  }

  // DRF 404s a page past the end. Offer the way back rather than a dead end.
  if (apiError?.status === 404 && page > 1) {
    return (
      <div className="px-4 py-6">
        <div className="rounded-card border border-line bg-white px-4 py-10 text-center">
          <h1 className="text-base font-semibold text-ink">That page is empty</h1>
          <p className="mt-2 text-sm text-ink-muted">
            You do not have that many orders.
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
        <ErrorState
          error={error}
          onRetry={refetch}
          title="Could not load your orders"
        />
      </div>
    )
  }

  if (!orders.length) {
    return (
      <div className="px-4 py-16">
        <div className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-card border border-line bg-white px-4 py-12 text-center">
          <h1 className="text-xl font-semibold text-ink">No orders yet</h1>
          <p className="text-sm text-ink-muted">
            Once you place an order it appears here, with its status and
            everything it contained.
          </p>
          <Link
            to="/"
            className="inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-medium text-white hover:bg-action-hover"
          >
            Browse the catalogue
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="px-4 py-5">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h1 className="text-xl font-semibold text-ink">Your orders</h1>
        <p role="status" aria-live="polite" className="text-sm text-ink-muted">
          {count} {count === 1 ? 'order' : 'orders'}
          {isFetching && ' · updating'}
        </p>
      </div>

      <ul className="flex flex-col gap-3">
        {orders.map((order) => (
          <li
            key={order.reference}
            className="rounded-card border border-line bg-white p-4"
          >
            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-ink">
                  {/* The row's primary target, so it carries the 44px
                      itself rather than relying on the text's line box. */}
                  <Link
                    to={`/orders/${order.reference}`}
                    className="inline-flex min-h-[44px] items-center tabular-nums hover:text-action hover:underline"
                  >
                    {order.reference}
                  </Link>
                </h2>
                <p className="mt-1 text-xs text-ink-muted">
                  <time dateTime={order.placed_at}>
                    {formatOrderDate(order.placed_at, { withTime: true })}
                  </time>
                  {' · '}
                  {order.item_count} {order.item_count === 1 ? 'item' : 'items'}
                  {' · '}
                  {paymentMethodLabel(order.payment_method)}
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <OrderStatusBadge status={order.status} />
                <p className="text-base font-bold text-price tabular-nums">
                  {formatMoney(order.grand_total)}
                </p>
              </div>
            </div>

            {order.items?.length > 0 && (
              <ul className="mt-3 flex flex-col gap-1 border-t border-line pt-3">
                {preview(order.items).map((item) => (
                  <li
                    key={item.id}
                    className="flex justify-between gap-3 text-xs text-ink-muted"
                  >
                    <span className="min-w-0 truncate">
                      <span className="tabular-nums">{item.quantity}</span> ×{' '}
                      {item.product_name}
                      {item.variant_label ? ` (${item.variant_label})` : ''}
                    </span>
                    <span className="shrink-0 tabular-nums">
                      {formatMoney(item.line_total)}
                    </span>
                  </li>
                ))}
                {order.items.length > 3 && (
                  <li className="text-xs text-ink-muted">
                    + {order.items.length - 3} more{' '}
                    {order.items.length - 3 === 1 ? 'item' : 'items'}
                  </li>
                )}
              </ul>
            )}

            <div className="mt-2 flex flex-wrap items-center gap-x-4">
              <Link
                to={`/orders/${order.reference}`}
                className="inline-flex min-h-[44px] items-center text-sm font-medium text-action hover:underline"
              >
                View order
                <span className="sr-only"> {order.reference}</span>
              </Link>
              {order.can_cancel && (
                <span className="text-xs text-ink-muted">
                  Still cancellable
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>

      <Pagination
        page={page}
        count={count}
        pageSize={PAGE_SIZE}
        hrefForPage={hrefForPage}
      />
    </div>
  )
}
