import { Link, useSearchParams } from 'react-router-dom'

import {
  Badge,
  EmptyRow,
  OrderStatusBadge,
  Spinner,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from '@/components/ui'
import ErrorState from '@/features/catalog/components/ErrorState'
import Pagination from '@/features/catalog/components/Pagination'
import { formatOrderDate } from '@/features/orders/orderDisplay'
import { formatMoney } from '@/lib/money'

import { formatCount, paymentMethodShort } from './adminDisplay'
import OrderFilters from './components/OrderFilters'
import { buildOrderSearch, hasActiveFilters, parseOrderFilters } from './orderFilters'
import { useAdminOrders } from './ordersApi'

/*
 * The order pipeline (US-A3, FR-ADM-4).
 *
 * Filter and page state lives in the query string, never in component state:
 * that is what lets a dashboard tile be a link to a filtered list, what makes
 * the back button walk back through filters, and what lets one admin send
 * another "the packed COD orders from Tuesday" as a URL.
 *
 * Sorting is the server's -- newest first, always. There is no sort control
 * because the pipeline is a work queue, and a work queue that can be reordered
 * is a work queue somebody loses their place in.
 */

const PAGE_SIZE = 24
const COLUMNS = 7

function CustomerCell({ customer }) {
  if (!customer) return <span className="text-ink-muted">—</span>
  return (
    <div className="min-w-0">
      <p className="truncate font-medium text-ink">{customer.name || '—'}</p>
      <p className="truncate text-xs text-ink-muted">
        {customer.phone || customer.email}
        {customer.is_guest && (
          <>
            {' '}
            <Badge tone="neutral" size="sm">
              Guest
            </Badge>
          </>
        )}
      </p>
    </div>
  )
}

export default function AdminOrdersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = parseOrderFilters(searchParams)

  const { data, isPending, isError, error, refetch, isFetching, isPlaceholderData } =
    useAdminOrders(filters)

  /*
   * Any filter change returns to page one. Staying on page 7 of a result set
   * that just shrank to two pages shows an empty table and reads as "no
   * matches" for a filter that in fact matched plenty.
   */
  function applyFilters(patch) {
    setSearchParams(buildOrderSearch({ ...filters, ...patch, page: 1 }).replace(/^\?/, ''), {
      replace: true,
    })
  }

  const orders = data?.results ?? []
  const count = data?.count ?? 0

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Orders</h1>
          <p className="mt-1 text-xs text-ink-muted" role="status">
            {isPending
              ? 'Loading orders…'
              : `${formatCount(count)} ${count === 1 ? 'order' : 'orders'}${
                  hasActiveFilters(filters) ? ' match these filters' : ''
                }`}
          </p>
        </div>
        {isFetching && !isPending && <Spinner size="sm" label="Refreshing orders" />}
      </header>

      <OrderFilters
        filters={filters}
        onChange={applyFilters}
        busy={isFetching && isPlaceholderData}
      />

      {isError ? (
        <ErrorState error={error} title="Could not load orders" onRetry={refetch} />
      ) : (
        <>
          <Table caption="Orders, newest first">
            <THead>
              <TR>
                <TH>Reference</TH>
                <TH>Placed</TH>
                <TH>Customer</TH>
                <TH align="right">Items</TH>
                <TH align="right">Total</TH>
                <TH>Payment</TH>
                <TH>Status</TH>
              </TR>
            </THead>
            <TBody>
              {isPending && (
                <EmptyRow colSpan={COLUMNS}>
                  <Spinner label="Loading orders" />
                </EmptyRow>
              )}

              {!isPending && !orders.length && (
                <EmptyRow colSpan={COLUMNS}>
                  {hasActiveFilters(filters)
                    ? 'No orders match these filters.'
                    : 'No orders yet.'}
                </EmptyRow>
              )}

              {orders.map((order) => (
                <TR key={order.reference}>
                  <TD>
                    {/* The reference is the row's link: an admin recognises an
                        order by it, and it is what a customer reads out. */}
                    <Link
                      to={`/admin/orders/${encodeURIComponent(order.reference)}`}
                      className="inline-flex min-h-[44px] items-center whitespace-nowrap font-semibold tabular-nums text-action hover:underline"
                    >
                      {order.reference}
                    </Link>
                  </TD>
                  <TD className="whitespace-nowrap text-ink-muted">
                    <time dateTime={order.placed_at}>
                      {formatOrderDate(order.placed_at, { withTime: true })}
                    </time>
                  </TD>
                  <TD>
                    <CustomerCell customer={order.customer} />
                  </TD>
                  <TD align="right" className="tabular-nums text-ink-muted">
                    {formatCount(order.item_count)}
                  </TD>
                  <TD align="right" className="font-semibold tabular-nums text-ink">
                    {formatMoney(order.grand_total)}
                  </TD>
                  <TD className="whitespace-nowrap text-ink-muted">
                    {paymentMethodShort(order.payment_method)}
                  </TD>
                  <TD>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <OrderStatusBadge status={order.status} size="sm" />
                      {order.has_shipment && (
                        <span className="text-[11px] text-ink-muted">tracked</span>
                      )}
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>

          <Pagination
            page={filters.page}
            count={count}
            pageSize={PAGE_SIZE}
            hrefForPage={(page) => buildOrderSearch({ ...filters, page })}
          />
        </>
      )}
    </div>
  )
}
