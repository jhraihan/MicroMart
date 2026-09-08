import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { useBrands, useCategories } from '../api'

// Category navigation for phones and small tablets.
export default function MobileNavDrawer({ open, onClose, triggerRef }) {
  const { data: categories } = useCategories()
  const { data: brands } = useBrands()
  const [expanded, setExpanded] = useState(null)
  const panelRef = useRef(null)
  const location = useLocation()

  // Any navigation closes the drawer -- otherwise tapping a category leaves it
  // covering the page the shopper just asked for.
  useEffect(() => {
    if (open) onClose()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, location.search])

  useEffect(() => {
    if (!open) return undefined

    const previouslyFocused = document.activeElement
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'

    // Focus the panel itself rather than the first link, so a screen reader
    // announces the dialog before its contents.
    panelRef.current?.focus()

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab') return

      const focusable = panelRef.current?.querySelectorAll(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
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
      const target = triggerRef?.current ?? previouslyFocused
      if (target instanceof HTMLElement) target.focus()
    }
  }, [open, onClose, triggerRef])

  if (!open) return null

  const roots = categories ?? []

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Browse categories"
        tabIndex={-1}
        className="absolute inset-y-0 left-0 flex w-[85%] max-w-sm flex-col bg-white shadow-el-4 outline-none"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <span className="text-base font-semibold text-ink">Browse</span>
          <button
            type="button"
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center rounded-card text-ink-muted hover:bg-page hover:text-ink"
          >
            <span className="sr-only">Close menu</span>
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5"
                 fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <nav aria-label="Categories" className="flex-1 overflow-y-auto overscroll-contain">
          {/*
            Offers and Compare live here on a phone because the header cannot
            carry them: five icon actions overflow a 360px viewport. They are
            not "extra" links -- this is where they exist on mobile, so they
            sit above the category list rather than buried under it.
          */}
          <ul className="divide-y divide-line border-b border-line">
            <li>
              <Link
                to="/offers"
                className="flex min-h-[48px] items-center gap-3 px-4 text-sm font-medium text-ink"
              >
                <span aria-hidden="true" className="text-price">
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none"
                       stroke="currentColor" strokeWidth="1.8">
                    <path d="M12 3l2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4L4.2 8.7l5.4-.8z"
                          strokeLinejoin="round" />
                  </svg>
                </span>
                Today’s offers
              </Link>
            </li>
            <li>
              <Link
                to="/compare"
                className="flex min-h-[48px] items-center gap-3 px-4 text-sm font-medium text-ink"
              >
                <span aria-hidden="true" className="text-action">
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none"
                       stroke="currentColor" strokeWidth="1.8">
                    <path d="M9 4v16M15 4v16M4 8h5M15 8h5M4 16h5M15 16h5" strokeLinecap="round" />
                  </svg>
                </span>
                Compare products
              </Link>
            </li>
          </ul>

          <ul className="divide-y divide-line">
            {roots.map((category) => {
              const children = category.children ?? []
              const isOpen = expanded === category.id

              return (
                <li key={category.id}>
                  <div className="flex items-stretch">
                    <Link
                      to={`/c/${category.slug}`}
                      className="flex min-h-[48px] flex-1 items-center gap-2 px-4 text-sm font-medium text-ink"
                    >
                      {category.name}
                      <span className="text-xs font-normal text-ink-muted">
                        {category.product_count}
                      </span>
                    </Link>

                    {children.length > 0 && (
                      <button
                        type="button"
                        aria-expanded={isOpen}
                        aria-label={`${isOpen ? 'Hide' : 'Show'} ${category.name} subcategories`}
                        onClick={() => setExpanded(isOpen ? null : category.id)}
                        className="flex w-12 shrink-0 items-center justify-center border-l border-line text-ink-muted"
                      >
                        <svg
                          viewBox="0 0 12 12" aria-hidden="true"
                          className={clsx('h-3.5 w-3.5 transition-transform', isOpen && 'rotate-180')}
                          fill="none" stroke="currentColor" strokeWidth="1.75"
                        >
                          <path d="M2.5 4.5L6 8l3.5-3.5" strokeLinecap="round" />
                        </svg>
                      </button>
                    )}
                  </div>

                  {isOpen && children.length > 0 && (
                    <ul className="bg-page pb-1">
                      {children.map((child) => (
                        <li key={child.id}>
                          <Link
                            to={`/c/${child.slug}`}
                            className="flex min-h-[44px] items-center justify-between px-6 text-sm text-ink"
                          >
                            <span>{child.name}</span>
                            <span className="text-xs text-ink-muted">
                              {child.product_count}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>

          <div className="border-t border-line px-4 py-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
              Popular brands
            </h3>
            <ul className="flex flex-wrap gap-1.5">
              {(brands ?? []).slice(0, 10).map((brand) => (
                <li key={brand.id}>
                  <Link
                    to={`/search?brand=${brand.slug}`}
                    className="flex min-h-[36px] items-center rounded-pill border border-line px-3 text-xs text-ink"
                  >
                    {brand.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </nav>

        <div className="border-t border-line p-3">
          <Link
            to="/pc-builder"
            className="flex min-h-[44px] items-center justify-center rounded-card bg-action px-4 text-sm font-semibold text-white"
          >
            Open PC Builder
          </Link>
        </div>
      </div>
    </div>
  )
}
