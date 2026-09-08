import { useEffect, useRef, useState } from 'react'

import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { formatMoney } from '@/lib/money'

import { useBuilderComponents } from '../api'

// The part-chooser dialog.
export default function ComponentPicker({
  slot,
  slots = [],
  selectionParam,
  onChoose,
  onClose,
}) {
  const [keyword, setKeyword] = useState('')
  const [compatibleOnly, setCompatibleOnly] = useState(true)
  const debounced = useDebouncedValue(keyword, 250)
  const panelRef = useRef(null)
  const searchRef = useRef(null)

  const { data, isPending, isError } = useBuilderComponents(slot, {
    selection: selectionParam,
    q: debounced,
    compatibleOnly,
  })

  const label = slots.find((entry) => entry.slot === slot)?.label ?? slot
  const results = data?.results ?? []

  useEffect(() => {
    const previouslyFocused = document.activeElement
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'
    searchRef.current?.focus()

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab') return

      const focusable = panelRef.current?.querySelectorAll(
        'a[href], button:not([disabled]), input, [tabindex]:not([tabindex="-1"])',
      )
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      document.body.style.overflow = overflow
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus()
    }
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Choose a ${label.toLowerCase()}`}
        className="relative flex max-h-[92vh] w-full max-w-3xl flex-col rounded-t-card bg-white shadow-el-4 sm:max-h-[85vh] sm:rounded-card"
      >
        <div className="flex items-center justify-between gap-3 border-b border-line p-3">
          <h2 className="text-base font-semibold text-ink">Choose a {label.toLowerCase()}</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center rounded-card text-ink-muted hover:bg-page hover:text-ink"
          >
            <span className="sr-only">Close</span>
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5"
                 fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-b border-line p-3">
          <label htmlFor="picker-search" className="sr-only">
            Search {label.toLowerCase()}s
          </label>
          <input
            id="picker-search"
            ref={searchRef}
            type="search"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder={`Search ${label.toLowerCase()}s`}
            className="h-11 min-w-0 flex-1 rounded-card border border-line px-3 text-base text-ink focus:border-action"
          />
          <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={compatibleOnly}
              onChange={(event) => setCompatibleOnly(event.target.checked)}
              className="h-4 w-4 accent-action"
            />
            Compatible only
          </label>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {isPending ? (
            <ul className="divide-y divide-line">
              {Array.from({ length: 6 }, (_, i) => (
                <li key={i} className="h-20 animate-pulse bg-page/60" />
              ))}
            </ul>
          ) : isError ? (
            <p className="p-6 text-center text-sm text-danger">
              Could not load parts for this slot. Try again in a moment.
            </p>
          ) : results.length === 0 ? (
            <div className="p-6 text-center">
              <p className="text-sm font-medium text-ink">
                No {label.toLowerCase()} matches the current build.
              </p>
              <p className="mt-1 text-sm text-ink-muted">
                {compatibleOnly
                  ? 'Turn off “compatible only” to see every option, or change an earlier part.'
                  : 'Try a different search term.'}
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-line">
              {results.map((option) => (
                <li key={option.variant_id}>
                  <button
                    type="button"
                    onClick={() => onChoose(option)}
                    disabled={!option.in_stock}
                    className="flex w-full items-center gap-3 p-3 text-left hover:bg-tint disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-card border border-line bg-white p-1">
                      {option.image ? (
                        <img
                          src={option.image}
                          alt=""
                          loading="lazy"
                          className="h-full w-full object-contain"
                        />
                      ) : (
                        <span className="text-[10px] text-ink-muted">No image</span>
                      )}
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">
                        {option.name}
                      </span>
                      <span className="block text-xs text-ink-muted">
                        {option.brand}
                        {!option.in_stock && (
                          <span className="ml-2 font-medium text-warning">Out of stock</span>
                        )}
                      </span>
                      {option.attributes && Object.keys(option.attributes).length > 0 && (
                        <span className="mt-1 flex flex-wrap gap-1">
                          {Object.entries(option.attributes).map(([key, value]) => (
                            <span
                              key={key}
                              className="rounded-pill bg-page px-2 py-0.5 text-[11px] text-ink-muted"
                            >
                              {key}: {value}
                            </span>
                          ))}
                        </span>
                      )}
                    </span>

                    <span className="shrink-0 text-sm font-semibold text-price">
                      {formatMoney(option.price)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <p className="border-t border-line p-3 text-xs text-ink-muted">
          {results.length} option{results.length === 1 ? '' : 's'}
          {compatibleOnly ? ' compatible with the current build' : ' in this category'}.
        </p>
      </div>
    </div>
  )
}
