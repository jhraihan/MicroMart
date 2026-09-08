import { Link } from 'react-router-dom'

/**
 * @param {{items: {label: string, to?: string}[]}} props
 * The final item is the current page and is never a link.
 *
 * Each crumb is a 44px-tall tap target (PRD §9.2). A breadcrumb rendered at
 * its text height is a 16px link, and on a phone it is the main way back up
 * the catalogue -- so the row is padded rather than the type enlarged, which
 * keeps the trail visually quiet while making it hittable. The bottom margin
 * is trimmed to pay for most of the extra height.
 */
export default function Breadcrumbs({ items }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-1 overflow-x-auto">
      <ol className="flex items-center gap-1 whitespace-nowrap text-xs text-ink-muted">
        {items.map((item, index) => {
          const isLast = index === items.length - 1
          return (
            <li key={`${item.label}-${index}`} className="flex items-center gap-1">
              {index > 0 && <span aria-hidden="true">/</span>}
              {isLast || !item.to ? (
                <span
                  aria-current={isLast ? 'page' : undefined}
                  className="inline-flex min-h-[44px] items-center"
                >
                  {item.label}
                </span>
              ) : (
                <Link
                  to={item.to}
                  className="inline-flex min-h-[44px] items-center text-ink hover:text-action hover:underline"
                >
                  {item.label}
                </Link>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
