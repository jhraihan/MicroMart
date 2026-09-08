import clsx from 'clsx'
import { useEffect, useId, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { formatMoney } from '@/lib/money'

import { useSearchSuggestions } from '../api'

// Header keyword search with type-ahead (FR-SRC-1, FR-SRC-5, FR-SRC-6).

// Long enough that a normal typist fires one request per word rather than one
// per character; short enough to feel immediate.
const DEBOUNCE_MS = 180

export default function SearchBar({ className, autoFocus = false }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const urlQuery = searchParams.get('q') ?? ''

  // Draft text until submit, but it follows the URL when that changes
  // underneath us (back button, a category link, a suggestion chip).
  const [draft, setDraft] = useState({ value: urlQuery, seededFrom: urlQuery })
  if (draft.seededFrom !== urlQuery) setDraft({ value: urlQuery, seededFrom: urlQuery })
  const value = draft.value

  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const containerRef = useRef(null)
  const inputRef = useRef(null)
  const listboxId = useId()

  const debounced = useDebouncedValue(value.trim(), DEBOUNCE_MS)
  const { data, isFetching } = useSearchSuggestions(debounced, { enabled: isOpen })

  // One flat list so arrow keys walk products, then categories, then brands,
  // in the order they are painted.
  const options = [
    ...(data?.products ?? []).map((p) => ({
      kind: 'product',
      key: `p-${p.id}`,
      label: p.name,
      to: `/p/${p.slug}`,
      product: p,
    })),
    ...(data?.categories ?? []).map((c) => ({
      kind: 'category',
      key: `c-${c.id}`,
      label: c.name,
      to: `/c/${c.slug}`,
      count: c.product_count,
    })),
    ...(data?.brands ?? []).map((b) => ({
      kind: 'brand',
      key: `b-${b.id}`,
      label: b.name,
      to: `/search?brand=${b.slug}`,
    })),
  ]

  const showPanel = isOpen && value.trim().length >= 2

  useEffect(() => {
    if (!isOpen) return undefined
    function onPointerDown(event) {
      if (!containerRef.current?.contains(event.target)) setIsOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('touchstart', onPointerDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('touchstart', onPointerDown)
    }
  }, [isOpen])

  // A changed result set invalidates whatever was highlighted -- keeping the
  // index would move the highlight onto an unrelated row.
  useEffect(() => setActiveIndex(-1), [debounced])

  function runSearch(term) {
    const trimmed = (term ?? '').trim()
    setIsOpen(false)
    navigate(trimmed ? `/search?q=${encodeURIComponent(trimmed)}` : '/search')
  }

  function choose(option) {
    setIsOpen(false)
    setDraft({ value: '', seededFrom: '' })
    navigate(option.to)
  }

  function onKeyDown(event) {
    if (!showPanel || options.length === 0) {
      if (event.key === 'Escape') setIsOpen(false)
      return
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((i) => (i + 1) % options.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((i) => (i <= 0 ? options.length - 1 : i - 1))
    } else if (event.key === 'Enter') {
      if (activeIndex >= 0) {
        event.preventDefault()
        choose(options[activeIndex])
      }
      // With nothing highlighted, Enter falls through to the form's submit,
      // which runs the keyword search -- the behaviour without a drop-down.
    } else if (event.key === 'Escape') {
      event.preventDefault()
      setIsOpen(false)
      setActiveIndex(-1)
    } else if (event.key === 'Tab') {
      setIsOpen(false)
    }
  }

  function onSubmit(event) {
    event.preventDefault()
    runSearch(value)
  }

  const activeOption = activeIndex >= 0 ? options[activeIndex] : null

  return (
    <div ref={containerRef} className={clsx('relative w-full', className)}>
      <form role="search" onSubmit={onSubmit} className="flex w-full items-center">
        <label htmlFor="site-search" className="sr-only">
          Search products
        </label>
        <input
          id="site-search"
          ref={inputRef}
          type="search"
          name="q"
          value={value}
          autoFocus={autoFocus}
          role="combobox"
          aria-expanded={showPanel && options.length > 0}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeOption ? `${listboxId}-${activeOption.key}` : undefined}
          onChange={(event) => {
            setDraft((prev) => ({ ...prev, value: event.target.value }))
            setIsOpen(true)
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search products, brands and model numbers"
          autoComplete="off"
          className="min-h-[44px] w-full rounded-l-card border-2 border-transparent bg-white px-3 text-base text-ink placeholder:text-ink-muted focus:border-action"
        />
        <button
          type="submit"
          className="flex min-h-[44px] items-center gap-1.5 rounded-r-card bg-action px-3 text-sm font-semibold text-white hover:bg-action-hover"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5"
               fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
          </svg>
          <span className="sr-only">Search</span>
        </button>
      </form>

      {showPanel && (
        <div className="absolute inset-x-0 top-full z-50 mt-1 overflow-hidden rounded-card bg-white shadow-dropdown">
          {/*
            Always rendered while the panel is open, even when empty, so
            `aria-controls` always resolves to a real element.
          */}
          <ul id={listboxId} role="listbox" aria-label="Search suggestions">
            {options.map((option, index) => {
              const isActive = index === activeIndex
              return (
                <li
                  key={option.key}
                  id={`${listboxId}-${option.key}`}
                  role="option"
                  aria-selected={isActive}
                  // Pointer down rather than click: the input blurring on
                  // mousedown would close the panel before the click landed.
                  onMouseDown={(event) => {
                    event.preventDefault()
                    choose(option)
                  }}
                  onMouseEnter={() => setActiveIndex(index)}
                  className={clsx(
                    'flex cursor-pointer items-center gap-3 px-3 py-2 text-left',
                    isActive ? 'bg-tint' : 'bg-white',
                  )}
                >
                  {option.kind === 'product' ? (
                    <>
                      {option.product.primary_image?.url ? (
                        <img
                          src={option.product.primary_image.url}
                          alt=""
                          width={40}
                          height={40}
                          loading="lazy"
                          className="h-10 w-10 shrink-0 rounded border border-line bg-white object-contain"
                        />
                      ) : (
                        <span className="h-10 w-10 shrink-0 rounded border border-line bg-page" />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-ink">
                          {option.label}
                        </span>
                        <span className="block text-xs text-ink-muted">
                          {option.product.brand?.name}
                        </span>
                      </span>
                      <span className="shrink-0 text-sm font-semibold text-price">
                        {formatMoney(option.product.price_min)}
                      </span>
                    </>
                  ) : (
                    <>
                      <span
                        aria-hidden="true"
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded border border-line bg-page text-xs font-semibold uppercase text-ink-muted"
                      >
                        {option.kind === 'category' ? 'Cat' : 'Br'}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-ink">
                          {option.label}
                        </span>
                        <span className="block text-xs text-ink-muted">
                          {option.kind === 'category' ? 'Category' : 'Brand'}
                          {option.count != null ? ` · ${option.count} products` : ''}
                        </span>
                      </span>
                    </>
                  )}
                </li>
              )
            })}
          </ul>

          {options.length === 0 && (
            <div className="px-3 py-4">
              {isFetching ? (
                <p className="text-sm text-ink-muted">Searching&hellip;</p>
              ) : (
                <>
                  <p className="text-sm text-ink">
                    Nothing matched &ldquo;{value.trim()}&rdquo;.
                  </p>
                  <p className="mt-1 text-xs text-ink-muted">
                    Press Enter to search the full catalogue, or try one of these:
                  </p>
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {(data?.popular ?? []).map((term) => (
                      <li key={term}>
                        <button
                          type="button"
                          onMouseDown={(event) => {
                            event.preventDefault()
                            setDraft({ value: term, seededFrom: term })
                            runSearch(term)
                          }}
                          className="flex min-h-[32px] items-center rounded-pill border border-line px-2.5 text-xs text-ink hover:border-action hover:text-action"
                        >
                          {term}
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          {options.length > 0 && (
            <button
              type="button"
              onMouseDown={(event) => {
                event.preventDefault()
                runSearch(value)
              }}
              className="flex min-h-[44px] w-full items-center justify-center border-t border-line bg-page text-sm font-semibold text-action hover:underline"
            >
              See all results for &ldquo;{value.trim()}&rdquo;
            </button>
          )}
        </div>
      )}
    </div>
  )
}
