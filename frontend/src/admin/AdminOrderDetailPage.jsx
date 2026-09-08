import { Link, useParams } from 'react-router-dom'

import { Badge, OrderStatusBadge, PageSpinner } from '@/components/ui'
import OrderTotals from '@/features/cart/components/OrderTotals'
import ErrorState from '@/features/catalog/components/ErrorState'
import AddressSummary from '@/features/orders/components/AddressSummary'
import OrderLines from '@/features/orders/components/OrderLines'
import {
  formatOrderDate,
  paymentMethodLabel,
  paymentStatusLabel,
  paymentStatusTone,
  totalsFromOrder,
} from '@/features/orders/orderDisplay'
import { parseApiError } from '@/lib/api'
import { formatMoney } from '@/lib/money'

import AdminTimeline from './components/AdminTimeline'
import FulfilmentActions from './components/FulfilmentActions'
import { useAdminOrder } from './ordersApi'

// One order, everything about it, and the two writes that move it (US-A3).

function Card({ title, children, className }) {
  return (
    <section className={className}>
      <div className="rounded-card border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-sm font-semibold text-ink">
          {title}
        </h2>
        <div className="px-4 py-4">{children}</div>
      </div>
    </section>
  )
}

function Field({ label, children }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="text-sm text-ink">{children}</dd>
    </div>
  )
}

export default function AdminOrderDetailPage() {
  const { reference } = useParams()
  const { data: order, isPending, isError, error, refetch } = useAdminOrder(reference)

  if (isPending) return <PageSpinner label="Loading the order" />

  if (isError) {
    const apiError = parseApiError(error)

    if (apiError.status === 404) {
      return (
        <div className="mx-auto max-w-md rounded-card border border-line bg-white px-4 py-12 text-center">
          <h1 className="text-xl font-semibold text-ink">Order not found</h1>
          <p className="mt-2 text-sm text-ink-muted">
            No order is stored under{' '}
            <span className="font-medium tabular-nums text-ink">{reference}</span>.
          </p>
          <Link
            to="/admin/orders"
            className="mt-5 inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-medium text-white hover:bg-action-hover"
          >
            Back to orders
          </Link>
        </div>
      )
    }

    return <ErrorState error={error} title="Could not load this order" onRetry={refetch} />
  }

  const customer = order.customer ?? {}
  const paymentStatus = paymentStatusLabel(order.payment_status)

  return (
    <div className="flex flex-col gap-4">
      <nav aria-label="Breadcrumb">
        <Link
          to="/admin/orders"
          className="inline-flex min-h-[44px] items-center text-sm text-action hover:underline"
        >
          <span aria-hidden="true">&larr;</span>&nbsp;All orders
        </Link>
      </nav>

      {/* --- Header and the actions, together ------------------------------ */}
      <div className="flex flex-col gap-4 rounded-card border border-line bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tabular-nums text-ink">
                {order.reference}
              </h1>
              <OrderStatusBadge status={order.status} />
              {customer.is_guest && <Badge tone="neutral">Guest checkout</Badge>}
            </div>
            <p className="mt-1 text-xs text-ink-muted">
              Placed{' '}
              <time dateTime={order.placed_at}>
                {formatOrderDate(order.placed_at, { withTime: true })}
              </time>{' '}
              &middot; {paymentMethodLabel(order.payment_method)}
            </p>
          </div>

          <p className="text-right">
            <span className="block text-xs text-ink-muted">Order total</span>
            <span className="text-xl font-bold tabular-nums text-price">
              {formatMoney(order.grand_total)}
            </span>
          </p>
        </div>

        <div className="border-t border-line pt-3">
          <FulfilmentActions order={order} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-4 lg:col-span-2">
          <Card title={`Items (${order.item_count})`}>
            <OrderLines items={order.items} />
            <div className="mt-4 border-t border-line pt-3">
              <OrderTotals
                quote={totalsFromOrder(order)}
                footnote="Snapshotted at purchase. Later catalogue or VAT edits never change these figures."
              />
            </div>
          </Card>

          {order.note && (
            <Card title="Customer note">
              <p className="whitespace-pre-line text-sm text-ink">{order.note}</p>
            </Card>
          )}

          <Card title="Status history">
            <AdminTimeline entries={order.timeline} />
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          <Card title="Customer">
            <dl className="divide-y divide-line">
              <Field label="Name">{customer.name || '—'}</Field>
              <Field label="Email">
                {customer.email ? (
                  <a className="text-action hover:underline" href={`mailto:${customer.email}`}>
                    {customer.email}
                  </a>
                ) : (
                  '—'
                )}
              </Field>
              <Field label="Phone">
                {customer.phone ? (
                  <a className="text-action hover:underline" href={`tel:${customer.phone}`}>
                    {customer.phone}
                  </a>
                ) : (
                  '—'
                )}
              </Field>
              <Field label="Account">
                {customer.is_guest ? 'Guest — no account' : 'Registered customer'}
              </Field>
            </dl>
          </Card>

          <Card title="Deliver to">
            <AddressSummary address={order.shipping_address} />
            {order.shipping_zone && (
              <p className="mt-2 text-xs text-ink-muted">Zone: {order.shipping_zone}</p>
            )}
          </Card>

          <Card title="Payment">
            <dl className="divide-y divide-line">
              <Field label="Method">{paymentMethodLabel(order.payment_method)}</Field>
              <Field label="Status">
                {paymentStatus ? (
                  <Badge tone={paymentStatusTone(order.payment_status)} size="sm">
                    {paymentStatus}
                  </Badge>
                ) : (
                  <span className="text-ink-muted">
                    {order.payment_method === 'cod'
                      ? 'Collected by the courier'
                      : 'Not recorded yet'}
                  </span>
                )}
              </Field>
              {order.coupon_code && <Field label="Coupon">{order.coupon_code}</Field>}
            </dl>
          </Card>

          <Card title="Shipment">
            {order.shipment ? (
              <dl className="divide-y divide-line">
                <Field label="Courier">{order.shipment.courier_name}</Field>
                <Field label="Tracking">
                  <span className="tabular-nums">{order.shipment.tracking_number}</span>
                </Field>
                <Field label="Dispatched">
                  {order.shipment.shipped_at
                    ? formatOrderDate(order.shipment.shipped_at, { withTime: true })
                    : 'Not yet'}
                </Field>
                <Field label="Delivered">
                  {order.shipment.delivered_at
                    ? formatOrderDate(order.shipment.delivered_at, { withTime: true })
                    : 'Not yet'}
                </Field>
              </dl>
            ) : (
              <p className="text-sm text-ink-muted">
                No courier yet. Adding one is what makes “Mark shipped” legal.
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
