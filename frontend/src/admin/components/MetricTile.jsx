import clsx from 'clsx'
import { Link } from 'react-router-dom'

/*
 * A dashboard figure that is also the way in to the rows behind it (US-A1).
 *
 * Every tile is a real <Link>, not a card with an onClick: an owner who wants
 * "today's orders" in a second tab should be able to middle-click, and a
 * keyboard user should reach it by tabbing. The whole tile is the target, so
 * it is far past 44px in both directions.
 */

const ACCENTS = {
  neutral: 'border-line',
  action: 'border-l-4 border-l-action border-y-line border-r-line',
  warning: 'border-l-4 border-l-warning border-y-line border-r-line',
  danger: 'border-l-4 border-l-danger border-y-line border-r-line',
}

export default function MetricTile({
  to,
  label,
  value,
  sub,
  hint,
  accent = 'neutral',
  className,
}) {
  return (
    <Link
      to={to}
      className={clsx(
        'group flex min-h-[104px] flex-col justify-between gap-2 rounded-card border bg-white p-4',
        'hover:border-action hover:shadow-el-2',
        ACCENTS[accent] ?? ACCENTS.neutral,
        className,
      )}
    >
      <span className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
        {label}
      </span>

      <span className="text-2xl font-bold tabular-nums text-ink">{value}</span>

      <span className="flex items-baseline justify-between gap-2 text-xs text-ink-muted">
        <span>{sub}</span>
        <span className="font-medium text-action group-hover:underline">
          View
          <span aria-hidden="true"> &rarr;</span>
        </span>
      </span>

      {hint && <span className="sr-only">{hint}</span>}
    </Link>
  )
}

/**
 * The compact variant used for the awaiting-action breakdown: a count, a word,
 * and the same link-to-the-rows behaviour.
 */
export function CountTile({ to, label, value, accent = 'neutral' }) {
  return (
    <Link
      to={to}
      className={clsx(
        'flex min-h-[72px] flex-1 flex-col justify-center gap-0.5 rounded-card border bg-white px-4 py-3',
        'hover:border-action hover:shadow-el-2',
        ACCENTS[accent] ?? ACCENTS.neutral,
      )}
    >
      <span className="text-xl font-bold tabular-nums text-ink">{value}</span>
      <span className="text-xs text-ink-muted">{label}</span>
    </Link>
  )
}
