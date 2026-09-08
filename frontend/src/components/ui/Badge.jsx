import clsx from 'clsx'

const TONES = {
  neutral: 'bg-page text-ink-muted',
  action: 'bg-tint text-action',
  price: 'bg-price text-white',
  save: 'bg-save text-white',
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  danger: 'bg-danger/10 text-danger',
}

/*
 * Order-status tones, matched to the state machine (PRD §15.1). Colour is
 * never the only signal -- the label always carries the status in words.
 */
export const ORDER_STATUS_TONE = {
  pending: 'warning',
  confirmed: 'action',
  packed: 'action',
  shipped: 'action',
  delivered: 'success',
  cancelled: 'danger',
  refunded: 'neutral',
}

export default function Badge({
  tone = 'neutral',
  size = 'md',
  className,
  children,
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-pill font-medium whitespace-nowrap',
        size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs',
        TONES[tone] ?? TONES.neutral,
        className,
      )}
    >
      {children}
    </span>
  )
}

export function OrderStatusBadge({ status, size = 'md' }) {
  return (
    <Badge tone={ORDER_STATUS_TONE[status] ?? 'neutral'} size={size}>
      {status ? status[0].toUpperCase() + status.slice(1) : '—'}
    </Badge>
  )
}
