import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { useSeo } from '@/lib/seo'

import { useBrands } from './api'

/*
 * The brand index.
 *
 * Grouped A-Z with a jump bar, because a flat grid of thirty-five names is a
 * scan rather than a lookup -- someone arriving here usually knows which
 * brand they want.
 *
 * Every tile links into the listing filtered by that brand rather than to a
 * bespoke brand page. `/search?brand=asus` is the same surface as every other
 * listing, so filters, sorting and pagination all work there for free, and
 * there is no second implementation to keep in step.
 */
export default function BrandsPage() {
  useSeo({
    title: 'All brands',
    description:
      'Every brand stocked at MicroMart, from processors and graphics cards to phones, printers and air conditioners.',
    canonical: '/brands',
  })

  const { data: brands = [], isPending, isError } = useBrands()
  const [keyword, setKeyword] = useState('')

  const groups = useMemo(() => {
    const term = keyword.trim().toLowerCase()
    const filtered = term
      ? brands.filter((brand) => brand.name.toLowerCase().includes(term))
      : brands

    const byLetter = new Map()
    for (const brand of filtered) {
      // Anything not starting with a letter files under "#", which keeps
      // "3M"-style names findable instead of dropping them.
      const first = brand.name[0]?.toUpperCase() ?? '#'
      const letter = /[A-Z]/.test(first) ? first : '#'
      if (!byLetter.has(letter)) byLetter.set(letter, [])
      byLetter.get(letter).push(brand)
    }
    return [...byLetter.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [brands, keyword])

  if (isError) {
    return (
      <div className="px-4 py-10 text-center">
        <h1 className="text-xl font-semibold text-ink">Could not load brands</h1>
        <p className="mt-2 text-sm text-ink-muted">Try again in a moment.</p>
      </div>
    )
  }

  return (
    <div className="px-4 py-5">
      <h1 className="text-xl font-semibold text-ink sm:text-2xl">All brands</h1>
      <p className="mt-1 text-sm text-ink-muted">
        {isPending ? 'Loading…' : `${brands.length} brands stocked.`} Pick one to
        see everything we carry from it.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label htmlFor="brand-filter" className="sr-only">
          Filter brands
        </label>
        <input
          id="brand-filter"
          type="search"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="Filter brands"
          className="h-11 w-full max-w-xs rounded-card border border-line px-3 text-base text-ink focus:border-action"
        />

        {!keyword && groups.length > 1 && (
          <nav aria-label="Jump to letter" className="flex flex-wrap gap-1">
            {groups.map(([letter]) => (
              <a
                key={letter}
                href={`#brand-${letter}`}
                className="flex h-9 w-9 items-center justify-center rounded-card border border-line text-sm font-medium text-ink hover:border-action hover:text-action"
              >
                {letter}
              </a>
            ))}
          </nav>
        )}
      </div>

      {isPending ? (
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {Array.from({ length: 18 }, (_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-card bg-white shadow-el-1" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <p className="mt-6 rounded-card bg-white p-6 text-center text-sm text-ink-muted shadow-el-1">
          No brand matches &ldquo;{keyword}&rdquo;.
        </p>
      ) : (
        groups.map(([letter, entries]) => (
          <section
            key={letter}
            id={`brand-${letter}`}
            aria-labelledby={`brand-heading-${letter}`}
            className="mt-6 scroll-mt-32"
          >
            <h2
              id={`brand-heading-${letter}`}
              className="mb-2 border-b border-line pb-1 text-sm font-semibold text-action"
            >
              {letter}
            </h2>
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
              {entries.map((brand) => (
                <li key={brand.id}>
                  <Link
                    to={`/search?brand=${brand.slug}`}
                    className="flex h-24 flex-col items-center justify-center gap-2 rounded-card bg-white p-3 shadow-el-1 transition-shadow hover:shadow-el-2"
                  >
                    {brand.logo ? (
                      <img
                        src={brand.logo}
                        alt=""
                        loading="lazy"
                        className="max-h-10 w-full object-contain"
                      />
                    ) : (
                      <span
                        aria-hidden="true"
                        className="flex h-10 w-10 items-center justify-center rounded-pill bg-tint text-base font-semibold text-action"
                      >
                        {brand.name[0]}
                      </span>
                    )}
                    <span className="text-center text-[13px] font-medium text-ink">
                      {brand.name}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}
