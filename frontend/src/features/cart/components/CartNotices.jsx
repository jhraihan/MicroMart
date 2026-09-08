import clsx from 'clsx'

/*
 * FR-CRT-5: a price or stock change since the item was added has to be
 * surfaced before payment, not discovered at placement. Every notice here is
 * server-authored (the cart and quote responses carry a `notices` array) or
 * derived from comparing two server figures -- never invented client-side.
 */

const TONES = {
  warning: 'border-warning/40 bg-warning/10 text-warning',
  danger: 'border-danger/40 bg-danger/10 text-danger',
  info: 'border-action/30 bg-tint text-action',
}

export default function CartNotices({ notices = [], className }) {
  if (!notices.length) return null

  return (
    <ul
      role="status"
      aria-live="polite"
      className={clsx('flex flex-col gap-2', className)}
    >
      {notices.map((notice, index) => (
        <li
          key={`${notice.code ?? 'notice'}-${notice.variant_id ?? index}`}
          className={clsx(
            'rounded-card border px-3 py-2 text-xs font-medium',
            TONES[notice.tone ?? 'warning'],
          )}
        >
          {notice.message}
        </li>
      ))}
    </ul>
  )
}
