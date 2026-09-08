import { formatMoney } from '@/lib/money'

/*
 * A chip per active filter, each removable in one tap. Without this the only
 * way to see what is narrowing a result set is to open the panel and read the
 * checkboxes, which is exactly what a shopper on a 360px screen cannot do.
 *
 * Every control here is >=44px tall (PRD 9.2), and "Clear all" carries real
 * horizontal padding: it wipes the whole filter set, so its hit area must not
 * be just the text run sitting a few pixels from the last chip.
 */
function Chip({ label, onRemove }) {
  return (
    <li>
      <button
        type="button"
        onClick={onRemove}
        className="flex min-h-[44px] items-center gap-1.5 rounded-pill bg-tint px-3 text-xs font-medium text-action hover:bg-action hover:text-white"
      >
        <span>{label}</span>
        <span aria-hidden="true" className="text-sm leading-none">
          &times;
        </span>
        <span className="sr-only">Remove this filter</span>
      </button>
    </li>
  )
}

function nameFor(list, slug) {
  return list?.find((entry) => entry.slug === slug)?.name ?? slug
}

export default function ActiveFilters({ state, facets, toggleValue, setParams, clearFilters }) {
  const chips = []

  for (const slug of state.category) {
    chips.push({
      key: `category-${slug}`,
      label: `Category: ${nameFor(facets?.categories, slug)}`,
      onRemove: () => toggleValue('category', slug),
    })
  }

  for (const slug of state.brand) {
    chips.push({
      key: `brand-${slug}`,
      label: `Brand: ${nameFor(facets?.brands, slug)}`,
      onRemove: () => toggleValue('brand', slug),
    })
  }

  if (state.min_price) {
    chips.push({
      key: 'min-price',
      label: `From ${formatMoney(state.min_price)}`,
      onRemove: () => setParams({ min_price: null }),
    })
  }

  if (state.max_price) {
    chips.push({
      key: 'max-price',
      label: `Up to ${formatMoney(state.max_price)}`,
      onRemove: () => setParams({ max_price: null }),
    })
  }

  if (state.in_stock) {
    chips.push({
      key: 'in-stock',
      label: 'In stock only',
      onRemove: () => setParams({ in_stock: null }),
    })
  }

  if (state.has_discount) {
    chips.push({
      key: 'has-discount',
      label: 'Discounted only',
      onRemove: () => setParams({ has_discount: null }),
    })
  }

  if (state.min_rating) {
    chips.push({
      key: 'min-rating',
      label: `${state.min_rating} stars & up`,
      onRemove: () => setParams({ min_rating: null }),
    })
  }

  if (chips.length === 0) return null

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <h2 className="sr-only">Active filters</h2>
      <ul className="flex flex-wrap items-center gap-2">
        {chips.map((chip) => (
          <Chip key={chip.key} label={chip.label} onRemove={chip.onRemove} />
        ))}
      </ul>
      <button
        type="button"
        onClick={clearFilters}
        className="inline-flex min-h-[44px] items-center rounded-card px-2 text-xs font-semibold text-action underline hover:text-action-hover"
      >
        Clear all
      </button>
    </div>
  )
}
