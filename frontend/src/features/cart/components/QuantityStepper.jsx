import clsx from 'clsx'

/*
 * A stepper rather than a bare number input: on a phone, "+" is one thumb tap
 * where a spinner arrow is a 12px target. Both buttons are 44px (PRD §9.2).
 *
 * `max` is the stock the server last reported. Capping here is a courtesy so
 * a shopper is not marched to a doomed checkout -- it is not a reservation,
 * and placement re-checks stock under a row lock regardless (FR-INV-4).
 */
export default function QuantityStepper({
  value,
  max = null,
  min = 1,
  onChange,
  disabled = false,
  label = 'Quantity',
  className,
}) {
  const atMax = max != null && value >= max
  const atMin = value <= min

  const button =
    'flex h-11 w-11 shrink-0 items-center justify-center text-lg leading-none text-ink ' +
    'hover:bg-tint hover:text-action disabled:cursor-not-allowed disabled:text-ink-subtle'

  function commit(next) {
    if (Number.isNaN(next)) return
    const clamped = Math.max(min, max != null ? Math.min(next, max) : next)
    if (clamped !== value) onChange(clamped)
  }

  return (
    <div
      className={clsx(
        'inline-flex items-center rounded-card border border-line bg-white',
        disabled && 'opacity-60',
        className,
      )}
    >
      <button
        type="button"
        className={clsx(button, 'rounded-l-card')}
        onClick={() => commit(value - 1)}
        disabled={disabled || atMin}
        aria-label={`Decrease ${label.toLowerCase()}`}
      >
        &minus;
      </button>

      <input
        type="number"
        inputMode="numeric"
        className="h-11 w-12 border-x border-line text-center text-sm tabular-nums text-ink [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        value={value}
        min={min}
        max={max ?? undefined}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => commit(Number.parseInt(event.target.value, 10))}
      />

      <button
        type="button"
        className={clsx(button, 'rounded-r-card')}
        onClick={() => commit(value + 1)}
        disabled={disabled || atMax}
        aria-label={`Increase ${label.toLowerCase()}`}
      >
        +
      </button>
    </div>
  )
}
