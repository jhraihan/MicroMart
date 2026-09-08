import { Button } from '@/components/ui'
import { parseApiError } from '@/lib/api'

/**
 * One error surface for every catalogue query. The message comes from the
 * API's error envelope via parseApiError -- never assembled here.
 */
export default function ErrorState({ error, onRetry, title = 'Could not load this' }) {
  const { message, code } = parseApiError(error)

  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-card border border-line bg-white px-4 py-10 text-center"
    >
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <p className="max-w-md text-sm text-ink-muted">{message}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry}>
          Try again
        </Button>
      )}
      <p className="text-[11px] text-ink-muted">Reference: {code}</p>
    </div>
  )
}
