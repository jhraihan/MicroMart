import clsx from 'clsx'
import { forwardRef, useId } from 'react'

/** Multi-line sibling of Input, with the same label/error/aria contract. */
const Textarea = forwardRef(function Textarea(
  {
    label,
    error,
    hint,
    id,
    rows = 3,
    required = false,
    className,
    containerClassName,
    ...props
  },
  ref,
) {
  const generatedId = useId()
  const fieldId = id || generatedId
  const errorId = `${fieldId}-error`
  const hintId = `${fieldId}-hint`

  const describedBy =
    [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ') ||
    undefined

  return (
    <div className={clsx('flex flex-col gap-1.5', containerClassName)}>
      {label && (
        <label htmlFor={fieldId} className="text-sm font-medium text-ink">
          {label}
          {required && (
            <span className="ml-0.5 text-danger" aria-hidden="true">
              *
            </span>
          )}
        </label>
      )}
      <textarea
        ref={ref}
        id={fieldId}
        rows={rows}
        required={required}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={describedBy}
        className={clsx(
          'w-full rounded-card border bg-white px-3 py-2 text-sm text-ink',
          'placeholder:text-ink-muted',
          'disabled:cursor-not-allowed disabled:bg-page',
          error ? 'border-danger' : 'border-line focus:border-action',
          className,
        )}
        {...props}
      />
      {hint && !error && (
        <p id={hintId} className="text-xs text-ink-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  )
})

export default Textarea
