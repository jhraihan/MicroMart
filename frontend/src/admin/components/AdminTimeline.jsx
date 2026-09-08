import { OrderStatusBadge } from '@/components/ui'
import { formatOrderDate, statusLabel } from '@/features/orders/orderDisplay'

/*
 * The append-only OrderStatusLog, oldest first (US-A3: "every status change
 * is logged with actor and timestamp").
 */

function actorLabel(entry) {
  if (entry.actor_name || entry.actor_email) {
    return entry.actor_name ? `${entry.actor_name} (${entry.actor_email})` : entry.actor_email
  }
  // No actor row: either the customer's own action or the system's.
  if (entry.actor_role === 'customer') return 'the customer'
  if (entry.actor_role === 'system') return 'the system'
  return 'an account since removed'
}

export default function AdminTimeline({ entries = [] }) {
  if (!entries.length) {
    return <p className="text-sm text-ink-muted">No status changes recorded yet.</p>
  }

  return (
    <ol className="flex flex-col">
      {entries.map((entry, index) => (
        <li
          key={`${entry.created_at}-${entry.to_status}-${index}`}
          className="flex gap-3 pb-4 last:pb-0"
        >
          {/* Decorative rail: the meaning is all in the badge and the text. */}
          <div className="flex flex-col items-center" aria-hidden="true">
            <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-pill bg-action" />
            {index < entries.length - 1 && <span className="w-px flex-1 bg-line" />}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <OrderStatusBadge status={entry.to_status} size="sm" />
              <time dateTime={entry.created_at} className="text-xs text-ink-muted">
                {formatOrderDate(entry.created_at, { withTime: true })}
              </time>
            </div>

            <p className="mt-1 text-xs text-ink-muted">
              {entry.from_status
                ? `${statusLabel(entry.from_status)} → ${statusLabel(entry.to_status)}`
                : 'Order placed'}{' '}
              by {actorLabel(entry)}
            </p>

            {entry.note && <p className="mt-1 text-sm text-ink">{entry.note}</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}
