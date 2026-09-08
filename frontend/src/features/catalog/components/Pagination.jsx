import clsx from 'clsx'
import { Link } from 'react-router-dom'

/*
 * Real <Link>s, not buttons: the page number is URL state (FR-SRC-5), so a
 * page must be openable in a new tab and reachable with the back button.
 */
function pageWindow(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)

  const pages = new Set([1, total, current, current - 1, current + 1])
  if (current <= 3) [2, 3, 4].forEach((p) => pages.add(p))
  if (current >= total - 2) [total - 3, total - 2, total - 1].forEach((p) => pages.add(p))

  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b)

  const withGaps = []
  let previous = 0
  for (const page of sorted) {
    // A string marks an elided range; numbers are real pages.
    if (page - previous > 1) withGaps.push(`ellipsis-${page}`)
    withGaps.push(page)
    previous = page
  }
  return withGaps
}

const BASE =
  'inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-card px-3 text-sm font-semibold'

export default function Pagination({ page, count, pageSize, hrefForPage }) {
  const totalPages = Math.max(1, Math.ceil((count ?? 0) / (pageSize || 24)))
  if (totalPages <= 1) return null

  const current = Math.min(Math.max(1, page), totalPages)
  const items = pageWindow(current, totalPages)

  return (
    <nav aria-label="Pagination" className="mt-6 flex justify-center">
      <ul className="flex flex-wrap items-center gap-1.5">
        <li>
          {current > 1 ? (
            <Link
              to={{ search: hrefForPage(current - 1) }}
              rel="prev"
              className={clsx(BASE, 'bg-page text-ink hover:bg-action hover:text-white')}
            >
              <span aria-hidden="true">&larr;</span>
              <span className="sr-only">Previous page</span>
            </Link>
          ) : (
            <span className={clsx(BASE, 'cursor-default bg-page text-ink-muted')} aria-disabled="true">
              <span aria-hidden="true">&larr;</span>
              <span className="sr-only">Previous page, unavailable</span>
            </span>
          )}
        </li>

        {items.map((item) =>
          typeof item === 'string' ? (
            <li key={item} className="px-1 text-ink-muted" aria-hidden="true">
              &hellip;
            </li>
          ) : (
            <li key={item}>
              {item === current ? (
                <span aria-current="page" className={clsx(BASE, 'bg-price text-white')}>
                  {item}
                </span>
              ) : (
                <Link
                  to={{ search: hrefForPage(item) }}
                  aria-label={`Page ${item}`}
                  className={clsx(BASE, 'bg-page text-ink hover:bg-action hover:text-white')}
                >
                  {item}
                </Link>
              )}
            </li>
          ),
        )}

        <li>
          {current < totalPages ? (
            <Link
              to={{ search: hrefForPage(current + 1) }}
              rel="next"
              className={clsx(BASE, 'bg-page text-ink hover:bg-action hover:text-white')}
            >
              <span aria-hidden="true">&rarr;</span>
              <span className="sr-only">Next page</span>
            </Link>
          ) : (
            <span className={clsx(BASE, 'cursor-default bg-page text-ink-muted')} aria-disabled="true">
              <span aria-hidden="true">&rarr;</span>
              <span className="sr-only">Next page, unavailable</span>
            </span>
          )}
        </li>
      </ul>
    </nav>
  )
}
