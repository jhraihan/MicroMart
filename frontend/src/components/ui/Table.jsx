import clsx from 'clsx'

/*
 * Admin data table. The wrapper owns the horizontal scroll so a wide table
 * never makes the page body scroll sideways on a phone (PRD §9.2).
 */
export default function Table({ caption, className, children }) {
  return (
    <div className="w-full overflow-x-auto rounded-card border border-line bg-white">
      <table className={clsx('w-full min-w-[640px] border-collapse text-sm', className)}>
        {caption && <caption className="sr-only">{caption}</caption>}
        {children}
      </table>
    </div>
  )
}

export function THead({ children }) {
  return (
    <thead className="border-b border-line bg-page text-left text-xs uppercase tracking-wide text-ink-muted">
      {children}
    </thead>
  )
}

export function TBody({ children }) {
  return <tbody className="divide-y divide-line">{children}</tbody>
}

export function TR({ className, children, ...props }) {
  return (
    <tr className={clsx('hover:bg-tint', className)} {...props}>
      {children}
    </tr>
  )
}

// Tailwind extracts class names statically, so alignment has to be a lookup
// rather than an interpolated `text-${align}` string.
const ALIGN = { left: 'text-left', center: 'text-center', right: 'text-right' }

export function TH({ align = 'left', className, children, ...props }) {
  return (
    <th
      scope="col"
      className={clsx('px-3 py-2.5 font-semibold', ALIGN[align], className)}
      {...props}
    >
      {children}
    </th>
  )
}

export function TD({ align = 'left', className, children, ...props }) {
  return (
    <td className={clsx('px-3 py-3 align-middle', ALIGN[align], className)} {...props}>
      {children}
    </td>
  )
}

export function EmptyRow({ colSpan, children = 'Nothing to show yet.' }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-3 py-10 text-center text-ink-muted">
        {children}
      </td>
    </tr>
  )
}
