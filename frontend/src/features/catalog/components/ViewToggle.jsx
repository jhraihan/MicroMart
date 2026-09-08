import clsx from 'clsx'

/*
 * Grid / list switch for the listing page.
 *
 * A radiogroup rather than two buttons: these are two states of one setting,
 * and `aria-checked` tells a screen reader which is active. Two independent
 * buttons would announce as two unrelated controls with no indication of the
 * current view.
 *
 * The choice is written to the URL by the caller, so a shared link keeps the
 * layout the sender was looking at.
 */
const OPTIONS = [
  {
    value: 'grid',
    label: 'Grid view',
    icon: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </>
    ),
  },
  {
    value: 'list',
    label: 'List view',
    icon: (
      <>
        <rect x="3" y="4" width="18" height="5" rx="1" />
        <rect x="3" y="15" width="18" height="5" rx="1" />
      </>
    ),
  },
]

export default function ViewToggle({ value, onChange }) {
  return (
    <div
      role="radiogroup"
      aria-label="Result layout"
      className="hidden overflow-hidden rounded-card border border-line sm:flex"
    >
      {OPTIONS.map((option) => {
        const isActive = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={isActive}
            onClick={() => onChange(option.value)}
            className={clsx(
              'flex h-11 w-11 items-center justify-center transition-colors',
              isActive ? 'bg-action text-white' : 'bg-white text-ink-muted hover:text-action',
            )}
          >
            <svg
              viewBox="0 0 24 24"
              aria-hidden="true"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
            >
              {option.icon}
            </svg>
            <span className="sr-only">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}
