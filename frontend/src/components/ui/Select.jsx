import clsx from 'clsx'
import { forwardRef, useId } from 'react'

/*
 * A labelled <select> with the same error wiring as Input: the message is
 * bound through aria-describedby so a screen reader announces it rather than
 * leaving the control merely red (PRD §9.3).
 *
 * Division and district are selects at checkout (FR-CHK-2) and both are on
 * the critical path of a phone order, so the control keeps the 44px target.
 */
const Select = forwardRef(function Select(
  {
    label,
    error,
    hint,
    id,
    required = false,
    placeholder,
    options = [],
    className,
    containerClassName,
    children,
    ...props
  },
  ref,
) {
  const generatedId = useId()
  const selectId = id || generatedId
  const errorId = `${selectId}-error`
  const hintId = `${selectId}-hint`

  const describedBy =
    [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ') ||
    undefined

  return (
    <div className={clsx('flex flex-col gap-1.5', containerClassName)}>
      {label && (
        <label htmlFor={selectId} className="text-sm font-medium text-ink">
          {label}
          {required && (
            <span className="ml-0.5 text-danger" aria-hidden="true">
              *
            </span>
          )}
        </label>
      )}
      <select
        ref={ref}
        id={selectId}
        required={required}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={describedBy}
        className={clsx(
          'min-h-[44px] w-full rounded-card border bg-white px-3 text-sm text-ink',
          'disabled:cursor-not-allowed disabled:bg-page',
          error ? 'border-danger' : 'border-line focus:border-action',
          className,
        )}
        {...props}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((option) =>
          typeof option === 'string' ? (
            <option key={option} value={option}>
              {option}
            </option>
          ) : (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ),
        )}
        {children}
      </select>
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

export default Select
