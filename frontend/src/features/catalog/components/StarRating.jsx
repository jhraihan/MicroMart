import clsx from 'clsx'

const SIZES = { sm: 'h-3.5 w-3.5', md: 'h-4 w-4' }

function Star({ className }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className={className} fill="currentColor">
      <path d="M10 1.6l2.47 5.01 5.53.8-4 3.9.94 5.5L10 14.22 5.06 16.8 6 11.3l-4-3.9 5.53-.8L10 1.6z" />
    </svg>
  )
}

/**
 * Rating is announced once, as text; the stars themselves are decorative and
 * aria-hidden. A partial star is a width-clipped overlay, so a 4.3 does not
 * silently round to 4.
 *
 * An unrated product is the DEFAULT state of a fresh catalogue (rating_avg
 * "0.00", rating_count 0), so it gets "Not yet rated" rather than being
 * announced as a genuine zero-star rating. `label` overrides the whole string
 * for callers where the stars mean something else -- the rating facet, where
 * they are a threshold ("4 stars & up"), not a product's score.
 */
export default function StarRating({ value, count = 0, size = 'sm', showCount = true, label }) {
  const rating = Number(value) || 0
  const percent = Math.max(0, Math.min(100, (rating / 5) * 100))
  const starClass = SIZES[size] ?? SIZES.sm

  const announced =
    label ??
    (count > 0
      ? `Rated ${rating.toFixed(1)} out of 5, ${count} ${count === 1 ? 'review' : 'reviews'}`
      : 'Not yet rated')

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="relative inline-flex" aria-hidden="true">
        <span className="flex text-line">
          {[0, 1, 2, 3, 4].map((i) => (
            <Star key={i} className={starClass} />
          ))}
        </span>
        <span
          className="absolute inset-0 flex overflow-hidden text-warning"
          style={{ width: `${percent}%` }}
        >
          {[0, 1, 2, 3, 4].map((i) => (
            <Star key={i} className={clsx(starClass, 'shrink-0')} />
          ))}
        </span>
      </span>
      <span className="sr-only">{announced}</span>
      {/* The count is already inside `announced`; showing it twice to a screen
          reader would read "12 reviews (12)". */}
      {showCount && (
        <span aria-hidden="true" className="text-xs text-ink-muted">
          {count > 0 ? `(${count})` : 'No reviews yet'}
        </span>
      )}
    </span>
  )
}
