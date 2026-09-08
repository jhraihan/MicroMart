import { useState } from 'react'

import { Badge, Button, Input, Spinner } from '@/components/ui'
import useDebouncedValue from '@/lib/useDebouncedValue'

import { useAdminCategories, useAdminProducts } from '../api'

/*
 * What a coupon applies to (US-A5: "product/category scope").
 *
 * `scope_ids` is a list of primary keys, and the server verifies every one of
 * them exists. Two different controls, because the two lists are different
 * sizes: a store has tens of categories and can show them all as checkboxes,
 * and thousands of products, which needs a search.
 *
 * Both keep the chosen ids visible as removable chips, so the answer to
 * "what does this coupon cover" is on screen rather than implied by scroll
 * position in a multi-select.
 */

function Chip({ label, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-pill bg-tint py-1 pl-3 pr-1 text-xs text-action">
      {label}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${label}`}
        className="flex h-8 w-8 items-center justify-center rounded-pill text-base leading-none hover:bg-action hover:text-white"
      >
        &times;
      </button>
    </span>
  )
}

function CategoryScope({ value, onChange, error, describedBy }) {
  const categories = useAdminCategories()

  function toggle(id) {
    const next = value.includes(id) ? value.filter((entry) => entry !== id) : [...value, id]
    onChange(next)
  }

  if (categories.isPending) return <Spinner label="Loading categories" />

  return (
    <fieldset
      className={`rounded-card border p-3 ${error ? 'border-danger' : 'border-line'}`}
      aria-describedby={describedBy}
    >
      <legend className="px-1 text-sm font-medium text-ink">Categories covered</legend>
      <div className="max-h-56 overflow-y-auto">
        <ul className="grid gap-1 sm:grid-cols-2">
          {(categories.data ?? []).map((row) => (
            <li key={row.id}>
              <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-action"
                  checked={value.includes(String(row.id))}
                  onChange={() => toggle(String(row.id))}
                />
                {row.parent_name ? `${row.parent_name} › ${row.name}` : row.name}
              </label>
            </li>
          ))}
        </ul>
      </div>
    </fieldset>
  )
}

function ProductScope({ value, onChange, error, describedBy }) {
  const [search, setSearch] = useState('')
  const q = useDebouncedValue(search.trim(), 300)
  // Only search once there is something to search for -- an unfiltered
  // product list is not a picker.
  const results = useAdminProducts({ q, page_size: 10, sort: 'name' }, { enabled: Boolean(q) })

  function add(id) {
    if (!value.includes(id)) onChange([...value, id])
  }

  const rows = q ? (results.data?.results ?? []) : []

  return (
    <div
      className={`rounded-card border p-3 ${error ? 'border-danger' : 'border-line'}`}
      aria-describedby={describedBy}
    >
      <Input
        label="Find a product"
        type="search"
        placeholder="Name, slug or SKU"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {q && (
        <ul className="mt-2 max-h-56 divide-y divide-line overflow-y-auto">
          {results.isFetching && rows.length === 0 && (
            <li className="py-2">
              <Spinner size="sm" label="Searching" />
            </li>
          )}
          {!results.isFetching && rows.length === 0 && (
            <li className="py-2 text-sm text-ink-muted">No products match “{q}”.</li>
          )}
          {rows.map((product) => (
            <li key={product.id} className="flex items-center justify-between gap-2 py-1">
              <span className="min-w-0 truncate text-sm text-ink">{product.name}</span>
              <Button
                size="sm"
                variant="ghost"
                disabled={value.includes(String(product.id))}
                onClick={() => add(String(product.id))}
              >
                {value.includes(String(product.id)) ? 'Added' : 'Add'}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Chips for ids already chosen.
 *
 * A coupon being edited arrives as bare ids, and the names are only known
 * once the relevant list has loaded — so an id with no name yet prints as
 * `#12` rather than disappearing.
 */
function ChosenChips({ value, onChange, scopeType }) {
  const categories = useAdminCategories()
  const names = new Map()
  if (scopeType === 'category') {
    ;(categories.data ?? []).forEach((row) => names.set(String(row.id), row.name))
  }

  if (value.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2">
      {value.map((id) => (
        <Chip
          key={id}
          label={names.get(id) ?? `#${id}`}
          onRemove={() => onChange(value.filter((entry) => entry !== id))}
        />
      ))}
    </div>
  )
}

export default function ScopePicker({ scopeType, value, onChange, error }) {
  const errorId = 'coupon-scope-error'

  if (scopeType === 'all') {
    return (
      <p className="rounded-card bg-page px-3 py-2 text-sm text-ink-muted">
        This coupon discounts the whole catalogue.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <ChosenChips value={value} onChange={onChange} scopeType={scopeType} />
      {scopeType === 'category' ? (
        <CategoryScope
          value={value}
          onChange={onChange}
          error={error}
          describedBy={error ? errorId : undefined}
        />
      ) : (
        <>
          <ProductScope
            value={value}
            onChange={onChange}
            error={error}
            describedBy={error ? errorId : undefined}
          />
          {value.length > 0 && (
            <p className="text-xs text-ink-muted">
              <Badge tone="action" size="sm">
                {value.length} product{value.length === 1 ? '' : 's'}
              </Badge>{' '}
              covered by this coupon.
            </p>
          )}
        </>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  )
}
