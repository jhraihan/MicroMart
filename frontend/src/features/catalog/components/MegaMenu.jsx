import clsx from 'clsx'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Link, NavLink, useParams } from 'react-router-dom'

import { useCategories, useProducts } from '../api'

// The category mega-menu.

// Long enough to cross the gap between the trigger row and the panel,
// short enough that the menu never feels stuck open.
const CLOSE_DELAY_MS = 180

// How many brands the panel offers as shortcuts. The full list is one click
// further on, at /brands.
const BRANDS_IN_PANEL = 8

export default function MegaMenu() {
  const { data: categories, isPending, isError } = useCategories()
  const { slug: activeSlug } = useParams()

  const [openId, setOpenId] = useState(null)
  const [isPointerNav, setIsPointerNav] = useState(false)
  const containerRef = useRef(null)
  const triggerRefs = useRef(new Map())
  const closeTimer = useRef(null)
  const panelId = useId()

  const cancelClose = useCallback(() => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }, [])

  const scheduleClose = useCallback(() => {
    cancelClose()
    closeTimer.current = setTimeout(() => setOpenId(null), CLOSE_DELAY_MS)
  }, [cancelClose])

  const close = useCallback(
    (restoreFocus = false) => {
      cancelClose()
      if (restoreFocus && openId != null) {
        triggerRefs.current.get(openId)?.focus()
      }
      setOpenId(null)
    },
    [cancelClose, openId],
  )

  useEffect(() => cancelClose, [cancelClose])

  // Escape closes and hands focus back to the trigger; a click outside just
  // closes. Both are only bound while something is open.
  useEffect(() => {
    if (openId == null) return undefined

    function onKeyDown(event) {
      if (event.key === 'Escape') close(true)
    }
    function onPointerDown(event) {
      if (!containerRef.current?.contains(event.target)) close()
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('touchstart', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('touchstart', onPointerDown)
    }
  }, [openId, close])

  const roots = categories ?? []

  function onTriggerKeyDown(event, index) {
    const last = roots.length - 1
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      const next =
        event.key === 'ArrowRight'
          ? index === last
            ? 0
            : index + 1
          : index === 0
            ? last
            : index - 1
      triggerRefs.current.get(roots[next].id)?.focus()
      // Only track the highlight when a panel is already open, so arrowing
      // along a closed menu bar does not start popping panels open.
      if (openId != null) setOpenId(roots[next].id)
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpenId(roots[index].id)
    }
  }

  if (isError) return null

  if (isPending) {
    return (
      <div className="hidden border-b border-line bg-white lg:block">
        <div className="mx-auto flex max-w-7xl gap-2 px-4 py-2">
          {Array.from({ length: 8 }, (_, i) => (
            <span key={i} className="h-9 w-24 animate-pulse rounded-pill bg-page" />
          ))}
        </div>
      </div>
    )
  }

  if (roots.length === 0) return null

  const open = roots.find((c) => c.id === openId) ?? null

  return (
    <div
      ref={containerRef}
      className="relative hidden border-b border-line bg-white lg:block"
      onMouseLeave={scheduleClose}
      onMouseEnter={cancelClose}
    >
      <nav aria-label="Product categories" className="mx-auto max-w-7xl px-4">
        {/*
          Eighteen departments do not fit a 1024px viewport, and without this
          the whole document scrolled sideways. The strip scrolls inside
          itself instead.

          `overflow-x: auto` computes the visible y axis to `auto` as well
          (CSS Overflow 3), so a scroller clips on *both* axes and nothing
          positioned inside it can escape. That is survivable here only
          because the dropdown panel is rendered as a sibling of this `nav`,
          absolutely positioned against the outer container -- not inside this
          `ul`. Moving the panel in here would silently clip it.
        */}
        <ul className="flex items-stretch gap-0.5 overflow-x-auto">
          {roots.map((category, index) => {
            const isOpen = openId === category.id
            const hasChildren = (category.children ?? []).length > 0
            const isCurrent =
              activeSlug === category.slug ||
              (category.children ?? []).some((c) => c.slug === activeSlug)

            return (
              <li key={category.id} className="flex">
                {/*
                  One element, not a button wrapping a link.
                  
                  An earlier version nested a <Link> inside a <button> so that
                  a click could navigate while the button carried the
                  disclosure state. axe flagged it as `nested-interactive`
                  (serious) across all eighteen departments, and rightly so:
                  screen readers do not reliably announce a control inside
                  another control, so the department was reachable but its
                  name and destination were not dependable.
                  
                  A link is the right element -- it goes somewhere -- and
                  `aria-expanded` is a supported state on role="link", so the
                  disclosure can live on the anchor itself.
                */}
                <Link
                  to={`/c/${category.slug}`}
                  ref={(node) => {
                    if (node) triggerRefs.current.set(category.id, node)
                    else triggerRefs.current.delete(category.id)
                  }}
                  aria-expanded={hasChildren ? isOpen : undefined}
                  aria-controls={hasChildren ? panelId : undefined}
                  onMouseEnter={() => {
                    setIsPointerNav(true)
                    cancelClose()
                    setOpenId(category.id)
                  }}
                  onFocus={() => setOpenId(category.id)}
                  onKeyDown={(event) => onTriggerKeyDown(event, index)}
                  onClick={(event) => {
                    /*
                     * A mouse click follows the link -- the panel is already
                     * open from hover, so making the shopper click twice to
                     * reach the department page buys nothing. Touch and pen
                     * have no hover, so there the first tap must open the
                     * panel instead of navigating past it.
                     */
                    if (event.nativeEvent.pointerType === 'mouse' || isPointerNav) return
                    if (!hasChildren) return
                    event.preventDefault()
                    setOpenId(isOpen ? null : category.id)
                  }}
                  className={clsx(
                    'flex min-h-[44px] items-center gap-1 whitespace-nowrap px-3 text-sm transition-colors',
                    isOpen || isCurrent
                      ? 'bg-tint font-semibold text-action'
                      : 'text-ink hover:bg-tint hover:text-action',
                  )}
                >
                  {category.name}
                  {hasChildren && (
                    <svg
                      viewBox="0 0 12 12"
                      aria-hidden="true"
                      className={clsx(
                        'h-3 w-3 transition-transform',
                        isOpen && 'rotate-180',
                      )}
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.75"
                    >
                      <path d="M2.5 4.5L6 8l3.5-3.5" strokeLinecap="round" />
                    </svg>
                  )}
                </Link>
              </li>
            )
          })}

          <li className="ml-auto flex">
            <NavLink
              to="/brands"
              className="flex min-h-[44px] items-center px-3 text-sm text-ink hover:bg-tint hover:text-action"
            >
              All brands
            </NavLink>
          </li>
        </ul>
      </nav>

      {/*
        One panel, populated from whichever department is open. Rendering a
        panel per department would put 55 categories' worth of links in the
        DOM on every page.
      */}
      {open && (open.children ?? []).length > 0 && (
        <div
          id={panelId}
          className="absolute inset-x-0 top-full z-40 border-b border-line bg-white shadow-dropdown"
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
        >
          <div className="mx-auto grid max-w-7xl gap-6 px-4 py-5 lg:grid-cols-[1fr_240px]">
            <div>
              <div className="mb-3 flex items-baseline justify-between gap-3">
                <h2 className="text-sm font-semibold text-ink">{open.name}</h2>
                <Link
                  to={`/c/${open.slug}`}
                  onClick={() => close()}
                  className="text-xs font-semibold text-action hover:underline"
                >
                  View all {open.product_count} products
                </Link>
              </div>

              <ul className="grid grid-cols-2 gap-x-6 gap-y-0.5 xl:grid-cols-3">
                {open.children.map((child) => (
                  <li key={child.id}>
                    <Link
                      to={`/c/${child.slug}`}
                      onClick={() => close()}
                      className="flex min-h-[36px] items-center justify-between gap-2 rounded-card px-2 text-sm text-ink hover:bg-tint hover:text-action"
                    >
                      <span>{child.name}</span>
                      <span className="text-xs text-ink-muted">{child.product_count}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>

            <div className="border-t border-line pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
              <DepartmentBrands category={open} onNavigate={() => close()} />

              <div className="mt-4 rounded-card bg-page p-3">
                <p className="text-xs font-semibold text-ink">Not sure what fits?</p>
                <p className="mt-1 text-xs text-ink-muted">
                  The PC Builder checks socket, memory and power for you.
                </p>
                <Link
                  to="/pc-builder"
                  onClick={() => close()}
                  className="mt-2 inline-flex min-h-[36px] items-center text-xs font-semibold text-action hover:underline"
                >
                  Open PC Builder &rarr;
                </Link>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


// Brands that actually appear in this department, with their counts.
function DepartmentBrands({ category, onNavigate }) {
  const { data, isPending } = useProducts(`category=${category.slug}&page_size=1`)
  const brands = (data?.facets?.brands ?? []).slice(0, BRANDS_IN_PANEL)

  return (
    <>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
        Brands in {category.name}
      </h3>

      {isPending ? (
        <ul className="flex flex-wrap gap-1">
          {Array.from({ length: 6 }, (_, i) => (
            <li key={i} className="h-8 w-16 animate-pulse rounded-pill bg-page" />
          ))}
        </ul>
      ) : brands.length === 0 ? (
        <p className="text-xs text-ink-muted">No brands to filter by here yet.</p>
      ) : (
        <ul className="flex flex-wrap gap-1">
          {brands.map((brand) => (
            <li key={brand.slug}>
              <Link
                to={`/c/${category.slug}?brand=${brand.slug}`}
                onClick={onNavigate}
                className="flex min-h-[32px] items-center gap-1.5 rounded-pill border border-line px-2.5 text-xs text-ink hover:border-action hover:text-action"
              >
                {brand.name}
                <span className="text-ink-muted">{brand.count}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
