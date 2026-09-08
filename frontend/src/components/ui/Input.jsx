import clsx from 'clsx'
import { forwardRef, useId } from 'react'

/*
 * A labelled input with the error wired to the field through aria-describedby,
 * so a screen reader announces the message rather than leaving the field
 * merely red (PRD §9.3).
 */
const Input = forwardRef(function Input(
  {
    label,
    error,
    hint,
    id,
    type = 'text',
    required = false,
    className,
    containerClassName,
    ...props
  },
  ref,
) {
  const generatedId = useId()
  const inputId = id || generatedId
  const errorId = `${inputId}-error`
  const hintId = `${inputId}-hint`

  const describedBy =
    [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ') ||
    undefined

  return (
    <div className={clsx('flex flex-col gap-1.5', containerClassName)}>
      {label && (
        <label htmlFor={inputId} className="text-sm font-medium text-ink">
          {label}
          {required && (
            <span className="ml-0.5 text-danger" aria-hidden="true">
              *
            </span>
          )}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
        type={type}
        required={required}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={describedBy}
        className={clsx(
          'min-h-[44px] w-full rounded-card border bg-white px-3 text-sm text-ink',
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

export default Input
