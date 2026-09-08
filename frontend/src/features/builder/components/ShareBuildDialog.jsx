import { useEffect, useRef, useState } from 'react'

/*
 * Shown once a build is saved: the share link, ready to copy.
 *
 * The token *is* the capability -- anyone with the link can read the build,
 * which is the point of sharing one. The dialog says so plainly rather than
 * letting someone assume it is private.
 *
 * Clipboard access can be refused (an insecure origin, a permissions policy,
 * an older browser), so the input is always present and pre-selected: the
 * copy button is a convenience over a manual copy, never the only way.
 */
export default function ShareBuildDialog({ token, onClose }) {
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)
  const inputRef = useRef(null)
  const panelRef = useRef(null)

  const url = `${window.location.origin}/builds/${token}`

  useEffect(() => {
    const previouslyFocused = document.activeElement
    inputRef.current?.select()

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus()
    }
  }, [onClose])

  async function copy() {
    setCopyFailed(false)
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      // No clipboard permission. Select the text so a manual copy is one
      // keystroke away rather than leaving the shopper stuck.
      setCopyFailed(true)
      inputRef.current?.select()
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="share-build-heading"
        className="relative w-full max-w-md rounded-card bg-white p-4 shadow-el-4"
      >
        <h2 id="share-build-heading" className="text-base font-semibold text-ink">
          Build saved
        </h2>
        <p className="mt-1 text-sm text-ink-muted">
          Anyone with this link can view the build and its current prices. It
          does not give access to your account.
        </p>

        <div className="mt-3 flex gap-2">
          <label htmlFor="share-url" className="sr-only">
            Share link
          </label>
          <input
            id="share-url"
            ref={inputRef}
            readOnly
            value={url}
            onFocus={(event) => event.target.select()}
            className="h-11 min-w-0 flex-1 rounded-card border border-line px-3 text-sm text-ink"
          />
          <button
            type="button"
            onClick={copy}
            className="flex min-h-[44px] shrink-0 items-center rounded-card bg-action px-4 text-sm font-semibold text-white hover:bg-action-hover"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>

        <p role="status" aria-live="polite" className="mt-2 min-h-[18px] text-xs">
          {copied && <span className="text-success">Link copied to your clipboard.</span>}
          {copyFailed && (
            <span className="text-ink-muted">
              Copying was blocked by your browser &mdash; the link is selected, so
              press Ctrl/Cmd + C.
            </span>
          )}
        </p>

        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="flex min-h-[44px] items-center rounded-card border border-line px-4 text-sm text-ink hover:border-action hover:text-action"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
