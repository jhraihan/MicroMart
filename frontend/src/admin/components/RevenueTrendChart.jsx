import clsx from 'clsx'
import { useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatMoney } from '@/lib/money'

import { compactMoneyTick, formatCount } from '../adminDisplay'

/*
 * Revenue and orders over the last N days (US-A1).
 *
 * **One measure at a time, on one axis.** Revenue (thousands of taka) and
 * order count (single digits) share no scale, and plotting them together on
 * two y-axes would let the reader see a correlation that is an artefact of
 * where the two scales were pinned. The toggle costs one click and cannot lie.
 *
 * The series is drawn from the server's own array, zero-filled days included
 * (metrics.revenue_trend). A sparse series would draw a straight line from
 * Tuesday to Friday and read as steady trade across a three-day outage.
 */

/*
 * Recharts writes these into SVG presentation attributes, which do not
 * resolve CSS custom properties -- so the design tokens from
 * src/index.css @theme are repeated here as literals rather than referenced.
 * Keep them in step with that file if the palette changes.
 */
const SERIES = '#4f46e5'
const GRID = '#e2e8f0'
const AXIS_TEXT = '#475569'
const SURFACE = '#ffffff'

const METRICS = {
  revenue: {
    key: 'revenue_value',
    label: 'Revenue',
    tick: compactMoneyTick,
  },
  orders: {
    key: 'orders',
    label: 'Orders',
    tick: (value) => formatCount(value),
  },
}

// A bare `YYYY-MM-DD` is a calendar day, so it is formatted as one -- read in
// UTC to keep the label the same day the server bucketed it into.
const DAY_LABEL = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  timeZone: 'UTC',
})

function formatDay(value) {
  const date = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(date.getTime()) ? value : DAY_LABEL.format(date)
}

function TrendTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const point = payload[0].payload

  return (
    <div className="rounded-card border border-line bg-white px-3 py-2 shadow-el-2">
      <p className="text-xs font-semibold text-ink">{formatDay(point.date)}</p>
      {/* Both figures in the tooltip even though one is plotted: the reader
          asking "why did revenue spike" wants the order count beside it. */}
      <p className="mt-1 text-sm tabular-nums text-ink">{formatMoney(point.revenue)}</p>
      <p className="text-xs tabular-nums text-ink-muted">
        {formatCount(point.orders)} {point.orders === 1 ? 'order' : 'orders'}
      </p>
    </div>
  )
}

export default function RevenueTrendChart({ trend = [], days = 30, revenueStatuses = [] }) {
  const [metric, setMetric] = useState('revenue')
  const config = METRICS[metric]

  /*
   * `revenue` stays the server's decimal string and is what every figure a
   * person reads is formatted from. `revenue_value` is a plotting coordinate
   * and nothing else -- no total, average or difference is ever derived from
   * it (PRD §5.4).
   */
  const data = trend.map((point) => ({
    ...point,
    revenue_value: Number(point.revenue),
  }))

  const hasTrade = data.some((point) => point.orders > 0)

  return (
    <figure className="rounded-card border border-line bg-white p-4">
      <figcaption className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-ink">
            {config.label} — last {days} days
          </h2>
          <p className="mt-0.5 text-xs text-ink-muted">
            Counts orders that are{' '}
            {revenueStatuses.length ? revenueStatuses.join(', ') : 'confirmed or later'}.
            Days in Asia/Dhaka.
          </p>
        </div>

        <div
          role="group"
          aria-label="Choose the measure to plot"
          className="flex overflow-hidden rounded-card border border-line"
        >
          {Object.entries(METRICS).map(([value, entry]) => (
            <button
              key={value}
              type="button"
              aria-pressed={metric === value}
              onClick={() => setMetric(value)}
              className={clsx(
                'min-h-[44px] px-4 text-sm font-medium',
                metric === value
                  ? 'bg-action text-white'
                  : 'bg-white text-ink hover:bg-tint hover:text-action',
              )}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </figcaption>

      {hasTrade ? (
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={data}
              margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
              /* Keyboard users get the tooltip with the arrow keys. */
              accessibilityLayer
            >
              <defs>
                <linearGradient id="admin-trend-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={SERIES} stopOpacity={0.18} />
                  <stop offset="100%" stopColor={SERIES} stopOpacity={0} />
                </linearGradient>
              </defs>

              {/* Hairline, solid, horizontal only -- the grid is a reading aid,
                  not a mark. */}
              <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />

              <XAxis
                dataKey="date"
                tickFormatter={formatDay}
                tickLine={false}
                axisLine={{ stroke: GRID }}
                tick={{ fill: AXIS_TEXT, fontSize: 11 }}
                minTickGap={24}
                interval="preserveStartEnd"
              />
              <YAxis
                dataKey={config.key}
                tickFormatter={config.tick}
                tickLine={false}
                axisLine={false}
                tick={{ fill: AXIS_TEXT, fontSize: 11 }}
                width={64}
                allowDecimals={false}
              />

              <Tooltip
                content={<TrendTooltip />}
                cursor={{ stroke: AXIS_TEXT, strokeWidth: 1 }}
              />

              <Area
                /*
                 * Straight segments between days, not a spline. A daily bucket
                 * is a discrete total; a smooth curve through it paints ৳40k on
                 * a Wednesday that took nothing, which is a number the store
                 * never made.
                 */
                type="linear"
                dataKey={config.key}
                name={config.label}
                stroke={SERIES}
                strokeWidth={2}
                fill="url(#admin-trend-fill)"
                dot={false}
                // 2px surface ring so the hovered point reads clearly over the
                // fill beneath it.
                activeDot={{ r: 4, fill: SERIES, stroke: SURFACE, strokeWidth: 2 }}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="flex h-[260px] items-center justify-center text-sm text-ink-muted">
          No orders in this window yet.
        </p>
      )}

      {/* The same series as a table, for a reader who cannot use the plot. */}
      <details className="mt-3">
        <summary className="inline-flex min-h-[44px] cursor-pointer items-center text-xs font-medium text-action">
          Show the numbers
        </summary>
        <div className="mt-2 max-h-64 overflow-auto rounded-card border border-line">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">
              Revenue and order count for each of the last {days} days
            </caption>
            <thead className="bg-page text-ink-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Day
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  Revenue
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  Orders
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.map((point) => (
                <tr key={point.date}>
                  <th scope="row" className="px-3 py-1.5 font-normal text-ink">
                    {formatDay(point.date)}
                  </th>
                  <td className="px-3 py-1.5 text-right tabular-nums text-ink">
                    {formatMoney(point.revenue)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-ink-muted">
                    {formatCount(point.orders)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}
