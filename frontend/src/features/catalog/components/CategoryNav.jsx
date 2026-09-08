import clsx from 'clsx'
import { useEffect, useId, useRef, useState } from 'react'
import { NavLink, useParams } from 'react-router-dom'

import { useCategories } from '../api'

/*
 * Category strip under the header.
 *
 * The source theme opens its mega-nav on hover only, which is unusable by
 * keyboard (design-system.md §8). Here each parent is a real link and its
 * children sit behind an explicit disclosure button with aria-expanded, so
 * the whole thing works with Tab and Escape and does not depend on a pointer.
 */
export default function CategoryNav() {
  const { data: categories, isPending, isError } = useCategories()
  const { slug: activeSlug } = useParams()
  const [openId, setOpenId] = useState(null)
  const containerRef = useRef(null)
  const panelIdPrefix = useId()

  // Close the disclosure on Escape or on a click outside the strip.
  useEffect(() => {
    if (openId == null) return

    function onPointerDown(event) {
      if (!containerRef.current?.contains(event.target)) setOpenId(null)
    }
    function onKeyDown(event) {
      if (event.key === 'Escape') setOpenId(null)
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [openId])

  if (isError) return null

  if (isPending) {
    return (
      <div className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-7xl gap-2 overflow-hidden px-4 py-2">
          {Array.from({ length: 6 }, (_, i) => (
            <span key={i} className="h-9 w-24 shrink-0 animate-pulse rounded-pill bg-page" />
          ))}
        </div>
      </div>
    )
  }

  const roots = categories ?? []
  if (roots.length === 0) return null

  return (
    <div ref={containerRef} className="border-b border-line bg-white">
      <nav aria-label="Product categories" className="mx-auto max-w-7xl px-4">
        {/*
         * The strip scrolls sideways, and per CSS Overflow 3 an `overflow-x`
         * of `auto` computes the visible y axis to `auto` as well -- so the
         * scroller clips on BOTH axes and nothing positioned inside it can
         * escape, whatever its z-index. The subcategory panel therefore lives
         * *outside* the scroller as a static disclosure region below the
         * strip, which is also far easier to reach one-handed at 360px than
         * an overlay anchored to a chip that may be scrolled half off-screen.
         */}
        <ul className="flex items-center gap-0.5 overflow-x-auto py-1.5">
          {roots.map((category) => {
            const children = category.children ?? []
            const panelId = `${panelIdPrefix}-${category.id}`
            const isOpen = openId === category.id

            return (
              <li key={category.id} className="flex shrink-0 items-center gap-0.5">
                <NavLink
                  to={`/c/${category.slug}`}
                  className={({ isActive }) =>
                    clsx(
                      'flex min-h-[44px] items-center rounded-pill px-2 text-sm whitespace-nowrap',
                      isActive || activeSlug === category.slug
                        ? 'bg-tint font-semibold text-action'
                        : 'text-ink hover:bg-tint hover:text-action',
                    )
                  }
                >
                  {category.name}
                  <span className="ml-1.5 text-xs text-ink-muted">
                    {category.product_count}
                  </span>
                </NavLink>

                {children.length > 0 && (
                  // A full 44x44 target: at 28px wide a thumb aimed here lands
                  // on the link instead and navigates away (PRD 9.2).
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    aria-controls={panelId}
                    aria-label={`${isOpen ? 'Hide' : 'Show'} subcategories of ${category.name}`}
                    onClick={() => setOpenId(isOpen ? null : category.id)}
                    className={clsx(
                      'flex h-11 w-11 shrink-0 items-center justify-center rounded-pill',
                      isOpen ? 'bg-tint text-action' : 'text-ink-muted hover:bg-tint hover:text-action',
                    )}
                  >
                    <span aria-hidden="true">&#9662;</span>
                  </button>
                )}
              </li>
            )
          })}
        </ul>

        {/* Every panel stays in the DOM so each aria-controls always resolves;
            only the open one is exposed and painted. */}
        {roots.map((category) => {
          const children = category.children ?? []
          if (children.length === 0) return null

          return (
            <div
              key={category.id}
              id={`${panelIdPrefix}-${category.id}`}
              hidden={openId !== category.id}
              className="border-t border-line py-1.5"
            >
              <ul
                aria-label={`Subcategories of ${category.name}`}
                className="flex flex-wrap gap-1"
              >
                {children.map((child) => (
                  <li key={child.id}>
                    <NavLink
                      to={`/c/${child.slug}`}
                      onClick={() => setOpenId(null)}
                      className="flex min-h-[44px] items-center gap-2 rounded-pill px-3 text-sm text-ink hover:bg-tint hover:text-action"
                    >
                      <span>{child.name}</span>
                      <span className="text-xs text-ink-muted">{child.product_count}</span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </nav>
    </div>
  )
}
