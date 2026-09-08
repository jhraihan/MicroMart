import { useState } from 'react'

import { Button } from '@/components/ui'
import { formatMoney } from '@/lib/money'

import { RATING_OPTIONS } from '../searchParams'
import StarRating from './StarRating'

// Facet panel (FR-SRC-2, FR-SRC-3).

function Section({ title, children, defaultOpen = true }) {
  return (
    <details open={defaultOpen} className="border-b border-line py-1 last:border-b-0">
      <summary className="flex min-h-[44px] cursor-pointer list-none items-center justify-between text-sm font-semibold text-ink [&::-webkit-details-marker]:hidden">
        {title}
        <span aria-hidden="true" className="text-ink-muted">
          &#9662;
        </span>
      </summary>
      <div className="pb-3">{children}</div>
    </details>
  )
}

function CheckRow({ id, name, checked, onChange, label, count }) {
  return (
    <label
      htmlFor={id}
      className="flex min-h-[44px] cursor-pointer items-center gap-2.5 rounded-card px-1 text-sm text-ink hover:bg-tint"
    >
      <input
        id={id}
        name={name}
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="h-4 w-4 shrink-0 accent-action"
      />
      <span className="flex-1">{label}</span>
      {count != null && <span className="text-xs text-ink-muted">{count}</span>}
    </label>
  )
}

export default function FacetFilters({
  facets,
  state,
  toggleValue,
  setParams,
  clearFilters,
  activeFilterCount = 0,
  idPrefix = 'facet',
}) {
  const priceFacet = facets?.price ?? null

  /*
   * The price box is the one control that is not written straight to the URL:
   * two half-typed numbers are not a filter yet. It stays draft state until
   * "Apply", and re-seeds from the URL whenever the committed value changes
   * (back button, "clear all", a chip being removed). Adjusting during render
   * rather than in an effect keeps the fields correct in the same paint.
   */
  const committedPrice = `${state.min_price}|${state.max_price}`
  const [priceDraft, setPriceDraft] = useState({
    min: state.min_price,
    max: state.max_price,
    seededFrom: committedPrice,
  })

  if (priceDraft.seededFrom !== committedPrice) {
    setPriceDraft({ min: state.min_price, max: state.max_price, seededFrom: committedPrice })
  }

  function applyPrice(event) {
    event.preventDefault()
    setParams({ min_price: priceDraft.min || null, max_price: priceDraft.max || null })
  }

  const brands = facets?.brands ?? []
  const categories = facets?.categories ?? []
  const ratings = facets?.ratings ?? []
  const inStockCount = facets?.in_stock?.['true'] ?? null

  function ratingCountFor(value) {
    return ratings.find((r) => r.value === value)?.count ?? null
  }

  return (
    <div className="flex flex-col">
      <div className="flex min-h-[44px] items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Filters
        </h2>
        {activeFilterCount > 0 && (
          <button
            type="button"
            onClick={clearFilters}
            className="min-h-[44px] px-1 text-sm font-medium text-action hover:underline"
          >
            Clear all
          </button>
        )}
      </div>

      {categories.length > 0 && (
        <Section title="Category">
          <ul>
            {categories.map((facet) => (
              <li key={facet.slug}>
                <CheckRow
                  id={`${idPrefix}-category-${facet.slug}`}
                  name="category"
                  checked={state.category.includes(facet.slug)}
                  onChange={() => toggleValue('category', facet.slug)}
                  label={facet.name}
                  count={facet.count}
                />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {brands.length > 0 && (
        <Section title="Brand">
          <ul className="max-h-72 overflow-y-auto">
            {brands.map((facet) => (
              <li key={facet.slug}>
                <CheckRow
                  id={`${idPrefix}-brand-${facet.slug}`}
                  name="brand"
                  checked={state.brand.includes(facet.slug)}
                  onChange={() => toggleValue('brand', facet.slug)}
                  label={facet.name}
                  count={facet.count}
                />
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Price">
        <form onSubmit={applyPrice} className="flex flex-col gap-2 pt-1">
          {priceFacet && (
            <p className="text-xs text-ink-muted">
              Available range {formatMoney(priceFacet.min)} &ndash;{' '}
              {formatMoney(priceFacet.max)}
            </p>
          )}
          <div className="flex items-end gap-2">
            <div className="flex flex-1 flex-col gap-1">
              <label htmlFor={`${idPrefix}-min-price`} className="text-xs font-medium text-ink">
                Min price
              </label>
              <input
                id={`${idPrefix}-min-price`}
                type="number"
                inputMode="numeric"
                min="0"
                step="1"
                value={priceDraft.min}
                onChange={(event) => {
                  const next = event.target.value
                  setPriceDraft((draft) => ({ ...draft, min: next }))
                }}
                placeholder={priceFacet ? String(Math.floor(Number(priceFacet.min))) : '0'}
                className="min-h-[44px] w-full rounded-card border border-line bg-white px-2 text-base text-ink focus:border-action"
              />
            </div>
            <div className="flex flex-1 flex-col gap-1">
              <label htmlFor={`${idPrefix}-max-price`} className="text-xs font-medium text-ink">
                Max price
              </label>
              <input
                id={`${idPrefix}-max-price`}
                type="number"
                inputMode="numeric"
                min="0"
                step="1"
                value={priceDraft.max}
                onChange={(event) => {
                  const next = event.target.value
                  setPriceDraft((draft) => ({ ...draft, max: next }))
                }}
                placeholder={priceFacet ? String(Math.ceil(Number(priceFacet.max))) : '0'}
                className="min-h-[44px] w-full rounded-card border border-line bg-white px-2 text-base text-ink focus:border-action"
              />
            </div>
          </div>
          <Button type="submit" variant="outline" size="sm">
            Apply price
          </Button>
        </form>
      </Section>

      <Section title="Availability">
        <CheckRow
          id={`${idPrefix}-in-stock`}
          name="in_stock"
          checked={state.in_stock}
          onChange={() => setParams({ in_stock: !state.in_stock })}
          label="In stock only"
          count={inStockCount}
        />
      </Section>

      <Section title="Offers">
        {/*
          No count: the API returns no facet for this dimension, and inventing
          one client-side from the current page would be wrong the moment the
          result set spans more than one page.
        */}
        <CheckRow
          id={`${idPrefix}-has-discount`}
          name="has_discount"
          checked={state.has_discount}
          onChange={() => setParams({ has_discount: !state.has_discount })}
          label="Discounted only"
          count={null}
        />
      </Section>

      <Section title="Customer rating">
        <fieldset>
          <legend className="sr-only">Minimum customer rating</legend>
          <label
            htmlFor={`${idPrefix}-rating-any`}
            className="flex min-h-[44px] cursor-pointer items-center gap-2.5 rounded-card px-1 text-sm hover:bg-tint"
          >
            <input
              id={`${idPrefix}-rating-any`}
              type="radio"
              name={`${idPrefix}-min-rating`}
              checked={state.min_rating === ''}
              onChange={() => setParams({ min_rating: null })}
              className="h-4 w-4 accent-action"
            />
            <span>Any rating</span>
          </label>

          {RATING_OPTIONS.map((value) => (
            <label
              key={value}
              htmlFor={`${idPrefix}-rating-${value}`}
              className="flex min-h-[44px] cursor-pointer items-center gap-2.5 rounded-card px-1 text-sm hover:bg-tint"
            >
              <input
                id={`${idPrefix}-rating-${value}`}
                type="radio"
                name={`${idPrefix}-min-rating`}
                checked={state.min_rating === String(value)}
                onChange={() => setParams({ min_rating: value })}
                className="h-4 w-4 accent-action"
              />
              {/* Here the stars are a threshold, not a product's score, so the
                  default "Rated ... out of 5" wording is overridden. */}
              <StarRating value={value} showCount={false} label={`${value} stars`} />
              <span className="flex-1">&amp; up</span>
              {ratingCountFor(value) != null && (
                <span className="text-xs text-ink-muted">{ratingCountFor(value)}</span>
              )}
            </label>
          ))}
        </fieldset>
      </Section>
    </div>
  )
}
