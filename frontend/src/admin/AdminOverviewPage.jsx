import clsx from 'clsx'
import { Link, useSearchParams } from 'react-router-dom'

import { Spinner } from '@/components/ui'
import ErrorState from '@/features/catalog/components/ErrorState'
import { parseApiError } from '@/lib/api'
import { formatMoney } from '@/lib/money'
import { useAuthStore } from '@/stores/authStore'

import {
  AWAITING_ACTION_STATUSES,
  formatCount,
  shopDaysAgo,
  shopToday,
  titleCase,
} from './adminDisplay'
import MetricTile, { CountTile } from './components/MetricTile'
import RevenueTrendChart from './components/RevenueTrendChart'
import { ordersHref } from './orderFilters'
import { useAdminDashboard } from './ordersApi'

// The store at a glance (US-A1, FR-ADM-1).

const TREND_RANGES = [7, 30, 90]

function parseDays(raw) {
  const days = Number.parseInt(raw ?? '', 10)
  return TREND_RANGES.includes(days) ? days : 30
}

const AS_OF = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
  timeZone: 'Asia/Dhaka',
})

/** A window tile's link: the same statuses and the same local days it counted. */
function windowHref(revenueStatuses, fromDaysAgo) {
  return ordersHref({
    status: revenueStatuses,
    placed_from: fromDaysAgo === 0 ? shopToday() : shopDaysAgo(fromDaysAgo),
    placed_to: shopToday(),
  })
}

function RevenueTile({ label, window: metrics, href }) {
  return (
    <MetricTile
      to={href}
      label={label}
      value={formatMoney(metrics?.revenue)}
      sub={
        <>
          {formatCount(metrics?.orders)} {metrics?.orders === 1 ? 'order' : 'orders'}
          {metrics?.orders > 0 && (
            <> &middot; avg {formatMoney(metrics.average_order_value)}</>
          )}
        </>
      }
      accent="action"
    />
  )
}

export default function AdminOverviewPage() {
  const role = useAuthStore((s) => s.user?.role)
  const isAdmin = role === 'admin'

  const [searchParams, setSearchParams] = useSearchParams()
  const days = parseDays(searchParams.get('days'))

  const { data, isPending, isError, error, refetch, isFetching } = useAdminDashboard({
    days,
    enabled: isAdmin,
  })

  function setDays(next) {
    const params = new URLSearchParams(searchParams)
    if (next === 30) params.delete('days')
    else params.set('days', String(next))
    setSearchParams(params, { replace: true })
  }

  // --- Staff: the dashboard is not theirs to read (US-A8) -------------------
  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-xl rounded-card border border-line bg-white px-4 py-10 text-center">
        <h1 className="text-xl font-semibold text-ink">Orders are your desk</h1>
        <p className="mx-auto mt-2 max-w-prose text-sm text-ink-muted">
          Revenue reporting is limited to the store owner. Your account can open
          every order and move it through the pipeline.
        </p>
        <Link
          to="/admin/orders"
          className="mt-5 inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-medium text-white hover:bg-action-hover"
        >
          Go to orders
        </Link>
      </div>
    )
  }

  if (isPending) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner size="lg" label="Loading the dashboard" />
      </div>
    )
  }

  if (isError) {
    const apiError = parseApiError(error)
    if (apiError.status === 403) {
      return (
        <ErrorState
          error={error}
          title="This account cannot read the dashboard"
          onRetry={null}
        />
      )
    }
    return <ErrorState error={error} title="Could not load the dashboard" onRetry={refetch} />
  }

  const revenueStatuses = data.revenue_statuses ?? []
  const awaiting = data.orders_awaiting_action ?? {}

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Overview</h1>
          <p className="mt-1 text-xs text-ink-muted">
            As of {AS_OF.format(new Date(data.generated_at))} (Asia/Dhaka)
            {isFetching && <> &middot; refreshing…</>}
          </p>
        </div>

        <div
          role="group"
          aria-label="Trend range"
          className="flex overflow-hidden rounded-card border border-line bg-white"
        >
          {TREND_RANGES.map((range) => (
            <button
              key={range}
              type="button"
              aria-pressed={days === range}
              onClick={() => setDays(range)}
              className={clsx(
                'min-h-[44px] px-4 text-sm font-medium',
                days === range
                  ? 'bg-action text-white'
                  : 'text-ink hover:bg-tint hover:text-action',
              )}
            >
              {range}d
            </button>
          ))}
        </div>
      </header>

      {/* --- Revenue windows (US-A1) ---------------------------------------- */}
      <section aria-labelledby="revenue-heading">
        <h2 id="revenue-heading" className="sr-only">
          Revenue and order count
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <RevenueTile
            label="Today"
            window={data.today}
            href={windowHref(revenueStatuses, 0)}
          />
          <RevenueTile
            label="Last 7 days"
            window={data.last_7_days}
            href={windowHref(revenueStatuses, 6)}
          />
          <RevenueTile
            label="Last 30 days"
            window={data.last_30_days}
            href={windowHref(revenueStatuses, 29)}
          />
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          Revenue counts orders that are{' '}
          {revenueStatuses.length ? revenueStatuses.join(', ') : 'confirmed or later'} —
          pending, cancelled and refunded orders are excluded.
        </p>
      </section>

      {/* --- What needs doing ---------------------------------------------- */}
      <section aria-labelledby="awaiting-heading" className="flex flex-col gap-3">
        <h2 id="awaiting-heading" className="text-base font-semibold text-ink">
          Needs action
        </h2>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <MetricTile
            to={ordersHref({ status: AWAITING_ACTION_STATUSES })}
            label="Orders awaiting action"
            value={formatCount(awaiting.total)}
            sub="Pending, confirmed or packed"
            accent={awaiting.total > 0 ? 'warning' : 'neutral'}
          />
          <MetricTile
            to="/admin/inventory?low_stock=true"
            label="Low stock"
            value={formatCount(data.low_stock_count)}
            sub="Variants at or below their threshold"
            accent={data.low_stock_count > 0 ? 'danger' : 'neutral'}
          />
        </div>

        <div className="flex flex-wrap gap-3">
          {AWAITING_ACTION_STATUSES.map((status) => (
            <CountTile
              key={status}
              to={ordersHref({ status: [status] })}
              label={titleCase(status)}
              value={formatCount(awaiting[status])}
            />
          ))}
        </div>
      </section>

      {/* --- Trend --------------------------------------------------------- */}
      <section aria-labelledby="trend-heading">
        <h2 id="trend-heading" className="sr-only">
          Sales trend
        </h2>
        <RevenueTrendChart
          trend={data.trend ?? []}
          days={data.trend_days ?? days}
          revenueStatuses={revenueStatuses}
        />
      </section>
    </div>
  )
}
