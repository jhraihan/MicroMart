import clsx from 'clsx'
import { useCallback, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

/*
 * A dialog that traps focus, closes on Escape, and restores focus to whatever
 * opened it. Without the trap a keyboard user tabs straight out of the dialog
 * into the page behind it (PRD §9.3).
 */
export default function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = 'md',
  className,
}) {
  const panelRef = useRef(null)
  const restoreFocusRef = useRef(null)

  const handleKeyDown = useCallback(
    (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose?.()
        return
      }
      if (event.key !== 'Tab') return

      const nodes = panelRef.current?.querySelectorAll(FOCUSABLE)
      if (!nodes?.length) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    },
    [onClose],
  )

  useEffect(() => {
    if (!open) return

    restoreFocusRef.current = document.activeElement
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'

    const firstFocusable = panelRef.current?.querySelector(FOCUSABLE)
    ;(firstFocusable ?? panelRef.current)?.focus()

    return () => {
      document.body.style.overflow = overflow
      restoreFocusRef.current?.focus?.()
    }
  }, [open])

  if (!open) return null

  const sizes = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl' }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4"
      onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className={clsx(
          'w-full rounded-t-card bg-white shadow-el-4 sm:rounded-card',
          'max-h-[90vh] overflow-y-auto',
          sizes[size],
          className,
        )}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="text-base font-semibold text-ink">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close dialog"
              // 44px: this Modal is also the mobile filter drawer, so the X
              // sits in the hardest corner of a phone to reach (PRD 9.2).
              className="flex h-11 w-11 items-center justify-center rounded-card text-xl leading-none text-ink-muted hover:bg-page hover:text-ink"
            >
              &times;
            </button>
          </div>
        )}
        <div className="px-4 py-4">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-line px-4 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
