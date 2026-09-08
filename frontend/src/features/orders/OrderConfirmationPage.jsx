import { Link, useLocation, useParams } from 'react-router-dom'

import { Badge, OrderStatusBadge, PageSpinner } from '@/components/ui'
import OrderTotals from '@/features/cart/components/OrderTotals'
import ErrorState from '@/features/catalog/components/ErrorState'
import { formatMoney } from '@/lib/money'
import { useAuthStore } from '@/stores/authStore'

import { useOrder } from './api'
import AddressSummary from './components/AddressSummary'
import OrderLines from './components/OrderLines'
import PaymentRetry from './components/PaymentRetry'
import {
  formatOrderDate,
  needsPayment,
  paymentMethodLabel,
  paymentStatusLabel,
  paymentStatusTone,
  totalsFromOrder,
} from './orderDisplay'

// The screen after placement (PRD §5.4, FR-CHK-8).

function NextSteps({ order }) {
  const isCod = order.payment_method === 'cod'
  const unpaid = needsPayment(order)

  const steps = isCod
    ? [
        'We call the number above to confirm the order.',
        'We pack it and hand it to the courier.',
        `Pay the courier ${formatMoney(order.grand_total)} in cash when it arrives.`,
      ]
    : unpaid
      ? [
          'Finish the payment — the order stays pending until it is confirmed.',
          'Once your bank or wallet confirms, we pack the order.',
          'The courier calls the delivery number before arriving.',
        ]
      : [
          'Your payment is confirmed and the order is queued for packing.',
          'We pack it and hand it to the courier.',
          'The courier calls the delivery number before arriving.',
        ]

  return (
    <ol className="flex flex-col gap-2">
      {steps.map((step, index) => (
        <li key={step} className="flex gap-3 text-sm text-ink">
          <span
            aria-hidden="true"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-pill bg-tint text-xs font-bold text-action"
          >
            {index + 1}
          </span>
          {step}
        </li>
      ))}
    </ol>
  )
}

export default function OrderConfirmationPage() {
  const { reference } = useParams()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const isAuthed = Boolean(user)
  const guestEmail = location.state?.email ?? null

  const { data: order, isLoading, isError, error, refetch } = useOrder(reference, {
    email: guestEmail,
    enabled: isAuthed,
  })

  if (!order) {
    if (isLoading) return <PageSpinner label="Loading your order" />

    if (isError && isAuthed) {
      return (
        <div className="px-4 py-6">
          <ErrorState error={error} onRetry={refetch} title="Could not load this order" />
        </div>
      )
    }

    // A guest who reloaded, or arrived by a shared link: the order may well be
    // fine, we simply cannot read it back without an account.
    return (
      <div className="px-4 py-16">
        <div className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-card border border-line bg-white px-4 py-12 text-center">
          <h1 className="text-xl font-semibold text-ink">Order details not on this device</h1>
          <p className="text-sm text-ink-muted">
            We cannot show{' '}
            <span className="font-medium text-ink tabular-nums">{reference}</span> here
            because this browser is not signed in. Your confirmation email has the full
            order — keep that reference safe.
          </p>
          <Link
            to="/login"
            state={{ from: `/orders/${reference}` }}
            className="inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-medium text-white hover:bg-action-hover"
          >
            Sign in to see it
          </Link>
          <Link
            to="/"
            className="inline-flex min-h-[44px] items-center rounded-card px-4 text-sm font-medium text-action hover:underline"
          >
            Continue shopping
          </Link>
        </div>
      </div>
    )
  }

  const paymentStatus = paymentStatusLabel(order.payment_status)
  const isCod = order.payment_method === 'cod'

  return (
    <div className="px-4 py-5">
      <div className="mb-4 rounded-card border border-line bg-white p-4 text-center sm:p-6">
        <p className="text-sm font-medium text-success" role="status">
          Order placed
        </p>
        <h1 className="mt-1 text-xl font-semibold text-ink sm:text-2xl">
          Thank you{user?.full_name ? `, ${user.full_name.split(' ')[0]}` : ''} — we have
          your order
        </h1>

        <p className="mt-3 text-xs text-ink-muted">Your order reference</p>
        <p className="text-2xl font-bold tracking-tight text-ink tabular-nums select-all">
          {order.reference}
        </p>

        <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
          <OrderStatusBadge status={order.status} />
          {paymentStatus && (
            <Badge tone={paymentStatusTone(order.payment_status)} size="sm">
              {paymentStatus}
            </Badge>
          )}
          <span className="text-xs text-ink-muted">
            <time dateTime={order.placed_at}>
              {formatOrderDate(order.placed_at, { withTime: true })}
            </time>
          </span>
        </div>

        <p className="mt-3 text-sm text-ink-muted">
          A confirmation is on its way to{' '}
          <span className="font-medium text-ink">{order.email}</span>. Keep the reference
          above — it is how we find this order.
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        <div className="flex flex-col gap-4">
          {needsPayment(order) && (
            <section
              aria-labelledby="confirmation-payment"
              className="rounded-card border border-line bg-white p-4"
            >
              <h2 id="confirmation-payment" className="sr-only">
                Payment
              </h2>
              <PaymentRetry order={order} />
            </section>
          )}

          {isCod && (
            <section
              aria-labelledby="confirmation-cod"
              className="rounded-card border border-line bg-white p-4"
            >
              <h2 id="confirmation-cod" className="text-base font-semibold text-ink">
                Have this ready for the courier
              </h2>
              <p className="mt-2 text-2xl font-bold text-price tabular-nums">
                {formatMoney(order.grand_total)}
              </p>
              <p className="mt-1 text-sm text-ink-muted">
                Cash on delivery. The courier collects the full amount when the order
                arrives — there is nothing to pay now.
              </p>
            </section>
          )}

          <section
            aria-labelledby="confirmation-next"
            className="rounded-card border border-line bg-white p-4"
          >
            <h2 id="confirmation-next" className="mb-3 text-base font-semibold text-ink">
              What happens next
            </h2>
            <NextSteps order={order} />
          </section>

          <section
            aria-labelledby="confirmation-items"
            className="rounded-card border border-line bg-white p-4"
          >
            <h2 id="confirmation-items" className="mb-3 text-base font-semibold text-ink">
              What you ordered
            </h2>
            <OrderLines items={order.items} />
          </section>

          <section
            aria-labelledby="confirmation-delivery"
            className="rounded-card border border-line bg-white p-4"
          >
            <h2
              id="confirmation-delivery"
              className="mb-3 text-base font-semibold text-ink"
            >
              Delivering to
            </h2>
            <AddressSummary address={order.shipping_address} />
            {order.shipping_zone && (
              <p className="mt-2 text-xs text-ink-muted">Zone: {order.shipping_zone}</p>
            )}
          </section>
        </div>

        <aside className="flex flex-col gap-4 lg:sticky lg:top-20">
          <section
            aria-labelledby="confirmation-summary"
            className="rounded-card border border-line bg-white p-4"
          >
            <h2
              id="confirmation-summary"
              className="mb-2 text-base font-semibold text-ink"
            >
              Order summary
            </h2>

            <OrderTotals
              quote={totalsFromOrder(order)}
              footnote="These totals were calculated by the server and stored with the order."
            />

            <dl className="mt-3 flex flex-wrap items-baseline justify-between gap-2 border-t border-line pt-3 text-sm">
              <dt className="text-ink-muted">Payment method</dt>
              <dd className="font-medium text-ink">
                {paymentMethodLabel(order.payment_method)}
              </dd>
            </dl>

            {isAuthed ? (
              <Link
                to={`/orders/${order.reference}`}
                className="mt-4 flex min-h-[44px] w-full items-center justify-center rounded-card border-2 border-action px-4 text-sm font-medium text-action hover:bg-action hover:text-white"
              >
                View order details
              </Link>
            ) : (
              <p className="mt-4 rounded-card bg-page px-3 py-2 text-xs text-ink-muted">
                You ordered as a guest.{' '}
                <Link
                  to="/register"
                  className="font-medium text-action hover:underline"
                  state={{ email: order.email }}
                >
                  Create an account
                </Link>{' '}
                with {order.email} to keep your orders in one place.
              </p>
            )}

            <Link
              to="/"
              className="mt-2 flex min-h-[44px] w-full items-center justify-center rounded-card px-4 text-sm font-medium text-action hover:underline"
            >
              Continue shopping
            </Link>
          </section>
        </aside>
      </div>
    </div>
  )
}
