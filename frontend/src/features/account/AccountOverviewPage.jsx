import { Link } from 'react-router-dom'

import { useOrders } from '@/features/orders/api'
import { formatMoney } from '@/lib/money'
import { useSeo } from '@/lib/seo'
import { useAuthStore } from '@/stores/authStore'

import { useAddresses } from './api'

/*
 * Account landing screen.
 *
 * Deliberately a summary with routes out of it rather than a dashboard of
 * metrics: what a customer wants here is "where is my order" and "is my
 * address still right", not a chart. The most recent orders are shown inline
 * because that is the question that brought most people to this page.
 */
export default function AccountOverviewPage() {
  useSeo({
    title: 'My account',
    canonical: '/account',
    // Nothing behind a login belongs in a search index.
    noIndex: true,
  })

  const user = useAuthStore((s) => s.user)
  const { data: orderData, isPending: ordersPending, isError: ordersFailed } = useOrders()
  const {
    data: addresses = [],
    isPending: addressesPending,
    isError: addressesFailed,
  } = useAddresses()

  const orders = orderData?.results ?? []
  const recent = orders.slice(0, 3)
  const defaultAddress = addresses.find((address) => address.is_default) ?? addresses[0]

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-card bg-white p-4 shadow-el-1">
        <h2 className="text-base font-semibold text-ink">
          Welcome back{user?.full_name ? `, ${user.full_name.split(' ')[0]}` : ''}
        </h2>
        <p className="mt-1 text-sm text-ink-muted">
          Track an order, update where it goes, or pick up a saved product.
        </p>

        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <Tile
            to="/orders"
            label="Orders"
            value={ordersPending ? '…' : ordersFailed ? '—' : orders.length}
          />
          <Tile
            to="/account/addresses"
            label="Saved addresses"
            value={addressesPending ? '…' : addressesFailed ? '—' : addresses.length}
          />
          <Tile to="/wishlist" label="Wishlist" value="View" />
        </div>
      </section>

      <section className="rounded-card bg-white p-4 shadow-el-1">
        <div className="mb-3 flex items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold text-ink">Recent orders</h2>
          <Link to="/orders" className="text-sm font-semibold text-action hover:underline">
            View all
          </Link>
        </div>

        {ordersPending ? (
          <div className="h-20 animate-pulse rounded-card bg-page" />
        ) : ordersFailed ? (
          <div className="rounded-card bg-page p-5 text-center" role="alert">
            <p className="text-sm text-ink">Could not load your orders.</p>
            <p className="mt-1 text-sm text-ink-muted">
              Check your connection and refresh the page.
            </p>
          </div>
        ) : recent.length === 0 ? (
          <div className="rounded-card bg-page p-5 text-center">
            <p className="text-sm text-ink">You have not placed an order yet.</p>
            <Link
              to="/search"
              className="mt-3 inline-flex min-h-[44px] items-center rounded-card bg-action px-5 text-sm font-semibold text-white hover:bg-action-hover"
            >
              Start shopping
            </Link>
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {recent.map((order) => (
              <li key={order.reference} className="flex items-center gap-3 py-3">
                <span className="min-w-0 flex-1">
                  <Link
                    to={`/orders/${order.reference}`}
                    className="block truncate text-sm font-medium text-action hover:underline"
                  >
                    {order.reference}
                  </Link>
                  <span className="block text-xs text-ink-muted">
                    {new Date(order.placed_at).toLocaleDateString('en-GB', {
                      day: 'numeric',
                      month: 'short',
                      year: 'numeric',
                    })}
                    {' · '}
                    {order.status}
                  </span>
                </span>
                <span className="shrink-0 text-sm font-semibold text-ink">
                  {formatMoney(order.total)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-card bg-white p-4 shadow-el-1">
        <div className="mb-3 flex items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold text-ink">Default delivery address</h2>
          <Link
            to="/account/addresses"
            className="text-sm font-semibold text-action hover:underline"
          >
            Manage
          </Link>
        </div>

        {addressesPending ? (
          <div className="h-16 animate-pulse rounded-card bg-page" />
        ) : defaultAddress ? (
          <address className="text-sm not-italic leading-6 text-ink">
            <span className="block font-medium">{defaultAddress.recipient_name}</span>
            <span className="block text-ink-muted">
              {[
                defaultAddress.street,
                defaultAddress.area,
                defaultAddress.upazila,
                defaultAddress.district,
                defaultAddress.division,
                defaultAddress.postcode,
              ]
                .filter(Boolean)
                .join(', ')}
            </span>
            <span className="block text-ink-muted">{defaultAddress.phone}</span>
          </address>
        ) : (
          <div className="rounded-card bg-page p-5 text-center">
            <p className="text-sm text-ink">No address saved yet.</p>
            <Link
              to="/account/addresses"
              className="mt-3 inline-flex min-h-[44px] items-center rounded-card border-2 border-action px-5 text-sm font-semibold text-action hover:bg-action hover:text-white"
            >
              Add an address
            </Link>
          </div>
        )}
      </section>
    </div>
  )
}

function Tile({ to, label, value }) {
  return (
    <Link
      to={to}
      className="flex flex-col justify-between rounded-card border border-line p-3 transition-colors hover:border-action"
    >
      <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">
        {label}
      </span>
      <span className="mt-1 text-xl font-semibold text-ink">{value}</span>
    </Link>
  )
}
