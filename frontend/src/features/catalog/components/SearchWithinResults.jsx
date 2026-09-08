import { useState } from 'react'

// "Search within these results".
export default function SearchWithinResults({ value, onSubmit, scopeLabel }) {
  const [draft, setDraft] = useState(value ?? '')

  // Follow the URL when it changes underneath us (back button, a cleared
  // chip), without fighting the shopper while they type.
  const [seed, setSeed] = useState(value ?? '')
  if (seed !== (value ?? '')) {
    setSeed(value ?? '')
    setDraft(value ?? '')
  }

  function submit(event) {
    event.preventDefault()
    onSubmit(draft.trim())
  }

  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <label htmlFor="search-within" className="sr-only">
        {scopeLabel ? `Search within ${scopeLabel}` : 'Search these results'}
      </label>
      <div className="relative flex-1">
        <input
          id="search-within"
          type="search"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={
            scopeLabel ? `Search within ${scopeLabel}` : 'Refine your search'
          }
          className="h-11 w-full rounded-card border border-line pl-3 pr-9 text-base text-ink focus:border-action"
        />
        {draft && (
          <button
            type="button"
            onClick={() => {
              setDraft('')
              onSubmit('')
            }}
            aria-label="Clear the keyword"
            className="absolute right-1 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-card text-ink-muted hover:text-ink"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4"
                 fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>
      <button
        type="submit"
        className="flex min-h-[44px] shrink-0 items-center rounded-card border-2 border-action px-4 text-sm font-semibold text-action hover:bg-action hover:text-white"
      >
        Search
      </button>
    </form>
  )
}
