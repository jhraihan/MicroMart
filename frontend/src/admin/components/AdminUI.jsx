import clsx from 'clsx'

import { Button, Spinner } from '@/components/ui'
import { parseApiError } from '@/lib/api'

import { AdminForbidden } from './AdminOnly'

/** Page title, one line of context, and the page's primary actions. */
export function AdminPageHeader({ title, description, actions, children }) {
  return (
    <div className="mb-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">{title}</h1>
          {description && (
            <p className="mt-1 max-w-prose text-sm text-ink-muted">{description}</p>
          )}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

const CALLOUT_TONES = {
  info: 'border-action/30 bg-tint text-ink',
  warning: 'border-warning/40 bg-warning/10 text-ink',
  danger: 'border-danger/40 bg-danger/10 text-ink',
}

/**
 * A standing explanation of a rule the screen enforces.
 *
 * Used where a screen would otherwise be quietly surprising: stock that is
 * not editable on the product form, settings that do not reach a placed
 * order, reviews that only count once approved.
 */
export function Callout({ tone = 'info', title, children, className }) {
  return (
    <div
      className={clsx(
        'rounded-card border px-4 py-3 text-sm',
        CALLOUT_TONES[tone] ?? CALLOUT_TONES.info,
        className,
      )}
    >
      {title && <p className="font-semibold">{title}</p>}
      <div className={clsx(title && 'mt-1', 'text-ink-muted')}>{children}</div>
    </div>
  )
}

/**
 * The form-level half of the error envelope.
 *
 * Everything the server names a field for lands on that field
 * (admin/serverErrors.js); this renders only what genuinely belongs to the
 * request as a whole.
 */
export function FormAlert({ message }) {
  if (!message) return null
  return (
    <p role="alert" className="rounded-card bg-danger/10 px-3 py-2 text-sm font-medium text-danger">
      {message}
    </p>
  )
}

/** A short-lived confirmation, announced rather than merely shown. */
export function SuccessNote({ message }) {
  if (!message) return null
  return (
    <p
      role="status"
      className="rounded-card bg-success/10 px-3 py-2 text-sm font-medium text-success"
    >
      {message}
    </p>
  )
}

/**
 * A failed query, rendered rather than thrown.
 *
 * A 403 here means a staff account reached an admin-only endpoint -- the
 * server's refusal, which is the real control -- so it gets the same
 * explanation the route guard gives rather than a stack of red text.
 */
export function AdminError({ error, onRetry, title = 'Could not load this screen' }) {
  if (!error) return null
  if (error?.response?.status === 403) return <AdminForbidden />

  const { message, code } = parseApiError(error)
  return (
    <div className="rounded-card border border-danger/40 bg-white p-5">
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <p className="mt-2 text-sm text-ink-muted">{message}</p>
      <p className="mt-1 text-xs text-ink-muted">Error code: {code}</p>
      {onRetry && (
        <Button className="mt-4" variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}

/** Inline "working" indicator for a table that is refetching. */
export function LoadingRowNote({ show, label = 'Loading' }) {
  if (!show) return null
  return (
    <div className="flex items-center gap-2 py-2 text-sm text-ink-muted">
      <Spinner size="sm" label={label} />
      <span>{label}…</span>
    </div>
  )
}

/**
 * Page-number pagination over the PRD §7.1 envelope.
 *
 * Announced as a navigation landmark with the current page in words, because
 * "2" as the only signal is not one for a screen reader.
 */
export function AdminPager({ page, count, pageSize, onChange }) {
  const pages = Math.max(1, Math.ceil((count || 0) / pageSize))
  if (pages <= 1) return null

  return (
    <nav aria-label="Pagination" className="mt-4 flex items-center justify-between gap-3">
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
      >
        Previous
      </Button>
      <p aria-live="polite" className="text-sm text-ink-muted">
        Page {page} of {pages} · {count} total
      </p>
      <Button
        variant="outline"
        size="sm"
        disabled={page >= pages}
        onClick={() => onChange(page + 1)}
      >
        Next
      </Button>
    </nav>
  )
}
