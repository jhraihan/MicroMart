import clsx from 'clsx'
import { useId } from 'react'

import { RATING_LABELS, RATING_MAX, RATING_MIN } from '../schemas'

const VALUES = Array.from(
  { length: RATING_MAX - RATING_MIN + 1 },
  (_, index) => RATING_MIN + index,
)

const PATH =
  'M10 1.6l2.47 5.01 5.53.8-4 3.9.94 5.5L10 14.22 5.06 16.8 6 11.3l-4-3.9 5.53-.8L10 1.6z'

/*
 * A chosen star is SOLID, an unchosen one is an OUTLINE. That is a shape
 * difference, not a colour one, so the control still reads correctly in
 * greyscale or with a colour-vision difference.
 */
function Star({ filled, className }) {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      className={className}
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={filled ? 0 : 1.4}
      strokeLinejoin="round"
    >
      <path d={PATH} />
    </svg>
  )
}

// The rating control (FR-REV-1).
export default function RatingInput({
  registration,
  value,
  error,
  legend = 'Your rating',
  disabled = false,
}) {
  const groupId = useId()
  const errorId = `${groupId}-error`
  const selected = Number(value) || 0

  return (
    <fieldset disabled={disabled} className="flex flex-col gap-1.5">
      <legend className="text-sm font-medium text-ink">
        {legend}
        <span className="ml-0.5 text-danger" aria-hidden="true">
          *
        </span>
      </legend>

      <div className="flex flex-wrap items-center gap-x-1 gap-y-2">
        {VALUES.map((star) => {
          const inputId = `${groupId}-${star}`
          const active = selected >= star
          return (
            <span key={star} className="inline-flex">
              <input
                type="radio"
                id={inputId}
                value={star}
                className="peer sr-only"
                aria-describedby={error ? errorId : undefined}
                {...registration}
              />
              <label
                htmlFor={inputId}
                className={clsx(
                  // 44px square: the whole star is the target, not just its
                  // points (PRD §9.2).
                  'flex h-11 w-11 cursor-pointer items-center justify-center rounded-card',
                  'transition-colors',
                  // Same focus-ring idiom as VariantSelector: the input is
                  // sr-only, so the ring has to be projected onto its label.
                  'peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-action',
                  'peer-disabled:cursor-not-allowed peer-disabled:opacity-55',
                  active ? 'text-warning' : 'text-ink-muted hover:text-warning',
                )}
              >
                <Star filled={active} className="h-7 w-7" />
                <span className="sr-only">
                  {star} {star === 1 ? 'star' : 'stars'} &mdash; {RATING_LABELS[star]}
                </span>
              </label>
            </span>
          )
        })}

        {/* The text equivalent. Stars alone would leave the score to colour
            and shape; this says it in words for everyone. */}
        <span aria-hidden="true" className="ml-1 text-sm font-medium text-ink">
          {selected ? `${selected}/5 — ${RATING_LABELS[selected]}` : 'Not rated yet'}
        </span>
      </div>

      {error && (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </fieldset>
  )
}
