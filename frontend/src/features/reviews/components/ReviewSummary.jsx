import clsx from 'clsx'

import ReviewStars from './ReviewStars'

/*
 * The aggregate that sits above the review list, and the star filter
 * (FR-REV-7).
 */
export default function ReviewSummary({ summary, activeRating, onFilterRating }) {
  const count = summary?.rating_count ?? 0
  const average = summary?.rating_avg ?? '0.00'
  const breakdown = summary?.breakdown ?? []

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-8">
      <div className="flex items-center gap-3 sm:flex-col sm:items-start">
        <p className="text-3xl font-bold leading-none text-ink">
          {count > 0 ? average : '—'}
          <span className="text-base font-normal text-ink-muted"> / 5</span>
        </p>
        <div className="flex flex-col gap-1">
          <ReviewStars rating={count > 0 ? average : 0} size="md" />
          <p className="text-xs text-ink-muted">
            {count === 0
              ? 'No reviews yet'
              : `Based on ${count} ${count === 1 ? 'review' : 'reviews'}`}
          </p>
        </div>
      </div>

      {count > 0 && (
        <div className="min-w-0 flex-1">
          <ul className="flex flex-col gap-1">
            {breakdown.map((row) => {
              const isActive = activeRating === row.rating
              // Width is a computed percentage, so it is an inline style:
              // Tailwind extracts class names statically and an interpolated
              // `w-[${n}%]` would simply not exist.
              const percent = count > 0 ? Math.round((row.count / count) * 100) : 0
              return (
                <li key={row.rating}>
                  <button
                    type="button"
                    aria-pressed={isActive}
                    onClick={() => onFilterRating(isActive ? null : row.rating)}
                    className={clsx(
                      'flex min-h-[44px] w-full items-center gap-3 rounded-card px-2 text-left',
                      isActive ? 'bg-tint' : 'hover:bg-page',
                    )}
                  >
                    <span className="w-16 shrink-0 text-xs font-medium text-ink">
                      {row.rating} {row.rating === 1 ? 'star' : 'stars'}
                    </span>
                    <span
                      aria-hidden="true"
                      className="h-2 min-w-0 flex-1 overflow-hidden rounded-pill bg-page"
                    >
                      <span
                        className="block h-full rounded-pill bg-warning"
                        style={{ width: `${percent}%` }}
                      />
                    </span>
                    <span className="w-16 shrink-0 text-right text-xs text-ink-muted">
                      {row.count} ({percent}%)
                    </span>
                    <span className="sr-only">
                      {isActive
                        ? `Showing only ${row.rating}-star reviews. Activate to show all reviews.`
                        : `Show only ${row.rating}-star reviews.`}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>

          {activeRating != null && (
            <button
              type="button"
              onClick={() => onFilterRating(null)}
              className="mt-1 inline-flex min-h-[44px] items-center px-2 text-sm font-medium text-action hover:underline"
            >
              Clear the {activeRating}-star filter
            </button>
          )}
        </div>
      )}
    </div>
  )
}
