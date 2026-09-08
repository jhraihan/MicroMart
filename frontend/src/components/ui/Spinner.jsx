import clsx from 'clsx'

const SIZES = { sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-10 w-10' }

export default function Spinner({ size = 'md', label = 'Loading', className }) {
  return (
    <span role="status" aria-live="polite" className={clsx('inline-flex items-center gap-2', className)}>
      <span
        aria-hidden="true"
        className={clsx(
          'animate-spin rounded-full border-2 border-action border-t-transparent',
          SIZES[size],
        )}
      />
      <span className="sr-only">{label}</span>
    </span>
  )
}

export function PageSpinner({ label = 'Loading' }) {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <Spinner size="lg" label={label} />
    </div>
  )
}
