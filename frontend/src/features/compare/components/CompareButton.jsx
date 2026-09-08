import clsx from 'clsx'
import { useEffect, useState } from 'react'

import { MAX_COMPARE, useCompareStore } from '@/stores/compareStore'

/*
 * Add/remove a product from the comparison tray.
 *
 * Lives above the product card's stretched link (z-20, pointer events kept),
 * exactly like the wishlist heart -- a tap here must toggle comparison, not
 * open the product.
 *
 * Refusals are *spoken*, not swallowed. A tray that is already full silently
 * ignoring a tap is the single most confusing thing a compare feature can do,
 * so the button flashes an inline reason and announces it politely to a
 * screen reader.
 */

// Long enough to read, short enough not to linger over the next card.
const MESSAGE_MS = 2600

export default function CompareButton({ product, variant = 'icon' }) {
  const slugs = useCompareStore((s) => s.slugs)
  const toggle = useCompareStore((s) => s.toggle)
  const [message, setMessage] = useState('')

  const inTray = slugs.includes(product.slug)

  useEffect(() => {
    if (!message) return undefined
    const timer = setTimeout(() => setMessage(''), MESSAGE_MS)
    return () => clearTimeout(timer)
  }, [message])

  function onClick(event) {
    // The card is one big link; without this the toggle would also navigate.
    event.preventDefault()
    event.stopPropagation()

    const result = toggle(product.slug)
    if (result.ok) {
      setMessage(result.removed ? 'Removed from compare' : 'Added to compare')
    } else if (result.reason === 'full') {
      setMessage(`Compare holds ${MAX_COMPARE} products`)
    }
  }

  const label = inTray
    ? `Remove ${product.name} from comparison`
    : `Add ${product.name} to comparison`

  if (variant === 'inline') {
    return (
      <div className="relative">
        <button
          type="button"
          onClick={onClick}
          aria-pressed={inTray}
          className={clsx(
            'flex min-h-[44px] w-full items-center justify-center gap-1.5 rounded-card border-2 px-3 text-sm font-medium transition-colors',
            inTray
              ? 'border-action bg-tint text-action'
              : 'border-line text-ink hover:border-action hover:text-action',
          )}
        >
          <CompareGlyph />
          {inTray ? 'In compare' : 'Compare'}
          <span className="sr-only">{label}</span>
        </button>
        <Announcement message={message} />
      </div>
    )
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={onClick}
        aria-pressed={inTray}
        title={inTray ? 'In comparison' : 'Add to comparison'}
        className={clsx(
          'flex h-9 w-9 items-center justify-center rounded-pill border shadow-el-1 transition-colors',
          inTray
            ? 'border-action bg-action text-white'
            : 'border-line bg-white text-ink-muted hover:border-action hover:text-action',
        )}
      >
        <CompareGlyph />
        <span className="sr-only">{label}</span>
      </button>
      <Announcement message={message} />
    </div>
  )
}

function CompareGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4"
         fill="none" stroke="currentColor" strokeWidth="1.9">
      <path d="M9 4v16M15 4v16M4 8h5M15 8h5M4 16h5M15 16h5" strokeLinecap="round" />
    </svg>
  )
}

/*
 * `role="status"` rather than an alert: this is a confirmation, and an alert
 * role would interrupt whatever a screen-reader user was in the middle of.
 * The node is always rendered so the live region exists before it has text --
 * a region inserted *with* its message is often not announced at all.
 */
function Announcement({ message }) {
  return (
    <span role="status" aria-live="polite">
      {message && (
        <span className="absolute right-0 top-full z-30 mt-1 whitespace-nowrap rounded-card bg-ink px-2 py-1 text-[11px] font-medium text-white shadow-el-2">
          {message}
        </span>
      )}
    </span>
  )
}
