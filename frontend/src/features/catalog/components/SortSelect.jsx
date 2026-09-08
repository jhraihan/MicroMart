import { SORT_OPTIONS } from '../searchParams'

/*
 * Sort is URL state, so a sorted listing is shareable (FR-SRC-4/5).
 * `relevance` is only offered while a keyword is present -- it is meaningless
 * without one, and the API's default sort switches to `newest` in that case.
 */
export default function SortSelect({ value, hasQuery, onChange, id = 'sort' }) {
  const options = SORT_OPTIONS.filter((option) => hasQuery || !option.searchOnly)

  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-sm whitespace-nowrap text-ink-muted">
        Sort by
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-[44px] rounded-card border border-line bg-white px-2 text-sm text-ink focus:border-action"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}
