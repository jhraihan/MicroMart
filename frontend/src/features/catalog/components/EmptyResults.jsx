import { Link } from 'react-router-dom'

import { Button } from '@/components/ui'

/*
 * A zero-result search must never be a bare empty grid. It explains what was
 * searched, offers the two things that actually recover the session (drop the
 * filters, or broaden the keyword), and hands over real category links.
 */
export default function EmptyResults({
  query = '',
  activeFilterCount = 0,
  onClearFilters,
  categories = [],
}) {
  const suggestions = categories.slice(0, 8)

  return (
    <div className="rounded-card border border-line bg-white px-4 py-10 text-center">
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="mx-auto h-12 w-12 text-ink-subtle"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      >
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
      </svg>

      <h2 className="mt-4 text-lg font-semibold text-ink">
        {query ? (
          <>
            No products match <span className="text-action">&ldquo;{query}&rdquo;</span>
          </>
        ) : (
          'No products match these filters'
        )}
      </h2>

      <p className="mx-auto mt-2 max-w-md text-sm text-ink-muted">
        {activeFilterCount > 0
          ? `${activeFilterCount} filter${activeFilterCount === 1 ? '' : 's'} ${
              activeFilterCount === 1 ? 'is' : 'are'
            } narrowing this search. Clearing them usually brings results back.`
          : 'Try a shorter or more general keyword, or check the spelling.'}
      </p>

      <ul className="mx-auto mt-4 max-w-md list-disc space-y-1 pl-5 text-left text-sm text-ink-muted">
        <li>Check the spelling, or try the model number on its own.</li>
        <li>Use fewer words &mdash; &ldquo;laptop&rdquo; finds more than &ldquo;gaming laptop 16gb&rdquo;.</li>
        <li>Widen the price range or turn off &ldquo;In stock only&rdquo;.</li>
      </ul>

      <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
        {activeFilterCount > 0 && (
          <Button onClick={onClearFilters}>Clear all filters</Button>
        )}
        <Link
          to="/search"
          className="inline-flex min-h-[44px] items-center rounded-card border-2 border-action px-4 text-sm font-medium text-action hover:bg-action hover:text-white"
        >
          Browse everything
        </Link>
      </div>

      {suggestions.length > 0 && (
        <div className="mt-8 border-t border-line pt-6">
          <h3 className="text-sm font-semibold text-ink">Popular categories</h3>
          <ul className="mt-3 flex flex-wrap justify-center gap-2">
            {suggestions.map((category) => (
              <li key={category.id}>
                <Link
                  to={`/c/${category.slug}`}
                  className="inline-flex min-h-[44px] items-center rounded-pill bg-page px-4 text-sm text-ink hover:bg-tint hover:text-action"
                >
                  {category.name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
