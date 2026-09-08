import { useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'

import { Badge, Button, Modal, OrderStatusBadge, PageSpinner, Textarea } from '@/components/ui'
import OrderTotals from '@/features/cart/components/OrderTotals'
import Breadcrumbs from '@/features/catalog/components/Breadcrumbs'
import ErrorState from '@/features/catalog/components/ErrorState'
import { parseApiError } from '@/lib/api'

import { useCancelOrder, useOrder } from './api'
import AddressSummary from './components/AddressSummary'
import OrderLines from './components/OrderLines'
import PaymentRetry from './components/PaymentRetry'
import SignInPrompt from './components/SignInPrompt'
import StatusTimeline from './components/StatusTimeline'
import {
  formatOrderDate,
  needsPayment,
  paymentMethodLabel,
  paymentStatusLabel,
  paymentStatusTone,
  statusExplainer,
  totalsFromOrder,
} from './orderDisplay'

// One order, by reference (PRD §5.5, FR-ORD-5).
export default function OrderDetailPage() {
  const { reference } = useParams()
  const location = useLocation()
  // A just-placed guest order carries its email in navigation state; an
  // authenticated read needs nothing extra, since the API scopes by user.
  const guestEmail = location.state?.email ?? null

  const { data: order, isPending, isError, error, refetch } = useOrder(reference, {
    email: guestEmail,
  })

  const cancel = useCancelOrder(reference)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [cancelError, setCancelError] = useState('')
  const [justCancelled, setJustCancelled] = useState(false)

  function closeConfirm() {
    if (cancel.isPending) return
    setConfirmOpen(false)
    setCancelError('')
  }

  function submitCancel() {
    setCancelError('')
    cancel.mutate(reason.trim(), {
      // The mutation answers with the whole order and writes it into the
      // cache (features/orders/api.js), so the new status, the released
      // cancel action and the fresh timeline entry all repaint from one
      // server response. Nothing is patched locally.
      onSuccess: () => {
        setConfirmOpen(false)
        setReason('')
        setJustCancelled(true)
      },
      onError: (err) => setCancelError(parseApiError(err).message),
    })
  }

  if (!order) {
    if (isPending) return <PageSpinner label="Loading your order" />

    const apiError = isError ? parseApiError(error) : null

    if (apiError?.status === 401 || apiError?.status === 403) {
      return (
        <div className="px-4 py-16">
          <SignInPrompt
            title="Sign in to see this order"
            message="Order details are only shown to the account that placed the order."
          />
        </div>
      )
    }

    // 404 is also the answer for somebody else's order, deliberately: a 403
    // would confirm the reference exists (PRD §10.2). So this copy never
    // claims the order does or does not exist.
    if (apiError?.status === 404) {
      return (
        <div className="px-4 py-16">
          <div className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-card border border-line bg-white px-4 py-12 text-center">
            <h1 className="text-xl font-semibold text-ink">Order not available</h1>
            <p className="text-sm text-ink-muted">
              We could not open{' '}
              <span className="font-medium text-ink tabular-nums">{reference}</span> for
              this account. Check the reference in your confirmation email, or sign in
              with the account that placed it.
            </p>
            <Link
              to="/orders"
              className="inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-medium text-white hover:bg-action-hover"
            >
              Your orders
            </Link>
          </div>
        </div>
      )
    }

    return (
      <div className="px-4 py-6">
        <ErrorState error={error} onRetry={refetch} title="Could not load this order" />
      </div>
    )
  }

  const paymentStatus = paymentStatusLabel(order.payment_status)

  return (
    <div className="px-4 py-5">
      <Breadcrumbs
        items={[
          { label: 'Home', to: '/' },
          { label: 'Your orders', to: '/orders' },
          { label: order.reference },
        ]}
      />

      <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div>
          <h1 className="text-xl font-semibold text-ink tabular-nums">
            Order {order.reference}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            Placed{' '}
            <time dateTime={order.placed_at}>
              {formatOrderDate(order.placed_at, { withTime: true })}
            </time>
            {' · '}
            {order.item_count} {order.item_count === 1 ? 'item' : 'items'}
          </p>
        </div>
        <OrderStatusBadge status={order.status} />
      </div>

      {justCancelled && (
        <p
          role="status"
          className="mb-4 rounded-card bg-success/10 px-3 py-2 text-sm font-medium text-success"
        >
          This order has been cancelled. Anything already set aside for it has been
          returned to stock.
        </p>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        <div className="flex flex-col gap-4">
          <section
            aria-labelledby="order-items"
            className="rounded-card border border-line bg-white p-4"
          >
            <h2 id="order-items" className="mb-3 text-base font-semibold text-ink">
              Items
            </h2>
            <OrderLines items={order.items} />
            <p className="mt-3 text-[11px] text-ink-muted">
              Names, options, SKUs and prices are recorded as they were on the day you
              ordered.
            </p>
          </section>

          <section
            aria-labelledby="order-delivery"
            className="rounded-card border border-line bg-white p-4"
          >
            <h2 id="order-delivery" className="mb-3 text-base font-semibold text-ink">
              Delivery
            </h2>

            <AddressSummary address={order.shipping_address} />

            <dl className="mt-3 grid gap-x-4 gap-y-2 border-t border-line pt-3 text-sm sm:grid-cols-2">
              {order.shipping_zone && (
                <div>
                  <dt className="text-xs text-ink-muted">Delivery zone</dt>
                  <dd className="text-ink">{order.shipping_zone}</dd>
                </div>
              )}
              <div>
                <dt className="text-xs text-ink-muted">Contact email</dt>
                <dd className="break-words text-ink">{order.email}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-muted">Contact phone</dt>
                <dd className="text-ink tabular-nums">{order.phone}</dd>
              </div>
            </dl>

            {order.note && (
              <div className="mt-3 border-t border-line pt-3">
                <p className="text-xs text-ink-muted">Your note</p>
                <p className="text-sm text-ink">{order.note}</p>
              </div>
            )}

            {order.shipment && (
              <div className="mt-3 rounded-card bg-page px-3 py-2 text-sm">
                <p className="text-ink">
                  <span className="font-medium">Courier:</span>{' '}
                  {order.shipment.courier_name || 'Assigned'}
                </p>
                {order.shipment.tracking_number && (
                  <p className="text-ink">
                    <span className="font-medium">Tracking number:</span>{' '}
                    <span className="tabular-nums">{order.shipment.tracking_number}</span>
                  </p>
                )}
                {order.shipment.shipped_at && (
                  <p className="text-xs text-ink-muted">
                    Shipped {formatOrderDate(order.shipment.shipped_at, { withTime: true })}
                  </p>
                )}
                {order.shipment.delivered_at && (
                  <p className="text-xs text-ink-muted">
                    Delivered{' '}
                    {formatOrderDate(order.shipment.delivered_at, { withTime: true })}
                  </p>
                )}
              </div>
            )}
          </section>

          <section
            aria-labelledby="order-timeline"
            className="rounded-card border border-line bg-white p-4"
          >
            <h2 id="order-timeline" className="mb-3 text-base font-semibold text-ink">
              Status history
            </h2>
            <StatusTimeline entries={order.timeline} />
          </section>
        </div>

        <aside className="flex flex-col gap-4 lg:sticky lg:top-20">
          <section
            aria-labelledby="order-summary"
            className="rounded-card border border-line bg-white p-4"
          >
            <h2 id="order-summary" className="mb-2 text-base font-semibold text-ink">
              Order summary
            </h2>

            <OrderTotals
              quote={totalsFromOrder(order)}
              footnote="These totals were calculated by the server when the order was placed."
            />

            <dl className="mt-3 flex flex-col gap-2 border-t border-line pt-3 text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <dt className="text-ink-muted">Payment method</dt>
                <dd className="font-medium text-ink">
                  {paymentMethodLabel(order.payment_method)}
                </dd>
              </div>
              {paymentStatus && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <dt className="text-ink-muted">Payment status</dt>
                  <dd>
                    <Badge tone={paymentStatusTone(order.payment_status)} size="sm">
                      {paymentStatus}
                    </Badge>
                  </dd>
                </div>
              )}
            </dl>

            {statusExplainer(order) && (
              <p className="mt-3 rounded-card bg-page px-3 py-2 text-xs text-ink-muted">
                {statusExplainer(order)}
              </p>
            )}

            {needsPayment(order) && (
              <div className="mt-3">
                <PaymentRetry order={order} />
              </div>
            )}

            {order.can_cancel && (
              <>
                <Button
                  variant="outline"
                  fullWidth
                  className="mt-4"
                  onClick={() => setConfirmOpen(true)}
                  aria-haspopup="dialog"
                >
                  Cancel this order
                </Button>
                <p className="mt-2 text-[11px] text-ink-muted">
                  An order can only be cancelled before it ships.
                </p>
              </>
            )}

            <Link
              to="/orders"
              className="mt-2 flex min-h-[44px] w-full items-center justify-center rounded-card px-4 text-sm font-medium text-action hover:underline"
            >
              Back to your orders
            </Link>
          </section>
        </aside>
      </div>

      <Modal
        open={confirmOpen}
        onClose={closeConfirm}
        title="Cancel this order?"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={closeConfirm} disabled={cancel.isPending}>
              Keep order
            </Button>
            <Button variant="danger" loading={cancel.isPending} onClick={submitCancel}>
              Cancel order
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">
          Order <span className="font-medium tabular-nums">{order.reference}</span> will be
          cancelled and nothing will be delivered. This cannot be undone — you would need
          to place a new order.
        </p>

        <div className="mt-4">
          <Textarea
            label="Reason (optional)"
            rows={3}
            maxLength={255}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Ordered the wrong variant, found it cheaper, no longer needed…"
            hint="Sent to the store with the cancellation."
          />
        </div>

        {cancelError && (
          <p
            role="alert"
            className="mt-3 rounded-card bg-danger/10 px-3 py-2 text-sm font-medium text-danger"
          >
            {cancelError}
          </p>
        )}
      </Modal>
    </div>
  )
}
