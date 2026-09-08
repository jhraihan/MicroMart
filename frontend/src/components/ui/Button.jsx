import clsx from 'clsx'
import { forwardRef } from 'react'

/*
 * Button fill is `action` (indigo), which passes WCAG AA on white. The
 * contrast numbers for every text colour live in src/index.css.
 *
 * Every size keeps a >=44px touch target so the storefront is usable
 * one-handed at 360px (PRD §9.2).
 */
const VARIANTS = {
  primary:
    'bg-action text-white border-2 border-action hover:bg-action-hover hover:border-action-hover',
  outline:
    'bg-transparent text-action border-2 border-action hover:bg-action hover:text-white',
  subtle:
    'bg-tint text-action border-2 border-transparent hover:bg-action hover:text-white',
  danger:
    'bg-danger text-white border-2 border-danger hover:opacity-90',
  ghost:
    'bg-transparent text-ink border-2 border-transparent hover:bg-tint hover:text-action',
}

// `sm` is smaller in type and padding only -- the touch target stays 44px,
// because a shorter button is still a button a thumb has to hit.
const SIZES = {
  sm: 'text-[13px] px-3 min-h-[44px]',
  md: 'text-sm px-4 min-h-[44px]',
  lg: 'text-base px-6 min-h-[52px]',
}

const Button = forwardRef(function Button(
  {
    variant = 'primary',
    size = 'md',
    type = 'button',
    fullWidth = false,
    loading = false,
    disabled = false,
    className,
    children,
    ...props
  },
  ref,
) {
  const isDisabled = disabled || loading
  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-card font-medium',
        'transition-colors duration-150',
        'disabled:cursor-not-allowed disabled:opacity-55',
        VARIANTS[variant],
        SIZES[size],
        fullWidth && 'w-full',
        className,
      )}
      {...props}
    >
      {loading && (
        <span
          aria-hidden="true"
          className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  )
})

export default Button
