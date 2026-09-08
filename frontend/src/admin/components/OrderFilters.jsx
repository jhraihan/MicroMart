import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { Button, Input, Select } from '@/components/ui'
import { useDebouncedValue } from '@/lib/useDebouncedValue'

import {
  AWAITING_ACTION_STATUSES,
  ORDER_STATUSES,
  PAYMENT_METHOD_OPTIONS,
  titleCase,
} from '../adminDisplay'
import { hasActiveFilters } from '../orderFilters'

// The pipeline's filter bar (US-A3, US-T1).
export default function OrderFilters({ filters, onChange, busy = false }) {
  /*
   * The search box types faster than the network, so it is locally controlled
   * and settles before it becomes a URL and a request.
   *
   * `pushedRef` holds the last `q` this component and the URL agreed on. Both
   * effects below compare against it rather than against each other, which is
   * what keeps the two directions from fighting: a URL change that this box
   * did not cause (the back button, a pasted link, "Clear filters") is adopted
   * into the input, while the URL catching up to what the admin already typed
   * is ignored -- otherwise a push landing mid-word would reset the box to the
   * shorter term and eat the rest of the query.
   */
  const [term, setTerm] = useState(filters.q)
  const debounced = useDebouncedValue(term, 350)
  const pushedRef = useRef(filters.q)

  useEffect(() => {
    if (filters.q === pushedRef.current) return
    pushedRef.current = filters.q
    setTerm(filters.q)
  }, [filters.q])

  useEffect(() => {
    // Equal on mount, so deep-linking to ?q=X&page=3 does not reset the page
    // number before anything has settled.
    if (debounced === pushedRef.current) return
    pushedRef.current = debounced
    onChange({ q: debounced })
  }, [debounced, onChange])

  function toggleStatus(status) {
    const next = filters.status.includes(status)
      ? filters.status.filter((value) => value !== status)
      : [...filters.status, status]
    onChange({ status: next })
  }

  const needsActionOn =
    filters.status.length === AWAITING_ACTION_STATUSES.length &&
    AWAITING_ACTION_STATUSES.every((status) => filters.status.includes(status))

  return (
    <div className="flex flex-col gap-4 rounded-card border border-line bg-white p-4">
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <Input
          label="Search"
          type="search"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="Reference, name, email or phone"
          hint="Matches a partial reference."
          containerClassName="lg:col-span-2"
          autoComplete="off"
        />

        <Select
          label="Payment method"
          value={filters.payment_method}
          onChange={(event) => onChange({ payment_method: event.target.value })}
          options={PAYMENT_METHOD_OPTIONS}
        />

        <div className="grid grid-cols-2 gap-2">
          <Input
            label="Placed from"
            type="date"
            value={filters.placed_from}
            max={filters.placed_to || undefined}
            onChange={(event) => onChange({ placed_from: event.target.value })}
          />
          <Input
            label="Placed to"
            type="date"
            value={filters.placed_to}
            min={filters.placed_from || undefined}
            onChange={(event) => onChange({ placed_to: event.target.value })}
          />
        </div>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium text-ink">Status</legend>
        <div className="flex flex-wrap gap-2">
          {ORDER_STATUSES.map((status) => {
            const checked = filters.status.includes(status)
            return (
              <label
                key={status}
                className={clsx(
                  'inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-pill border px-3 text-sm',
                  'has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-action',
                  checked
                    ? 'border-action bg-action text-white'
                    : 'border-line bg-white text-ink hover:border-action hover:text-action',
                )}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={checked}
                  onChange={() => toggleStatus(status)}
                />
                {titleCase(status)}
              </label>
            )
          })}
        </div>
      </fieldset>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant={needsActionOn ? 'primary' : 'outline'}
          aria-pressed={needsActionOn}
          onClick={() =>
            onChange({ status: needsActionOn ? [] : [...AWAITING_ACTION_STATUSES] })
          }
        >
          Needs action
        </Button>

        {hasActiveFilters(filters) && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              onChange({
                q: '',
                status: [],
                payment_method: '',
                placed_from: '',
                placed_to: '',
              })
            }
          >
            Clear filters
          </Button>
        )}

        {busy && (
          <span role="status" className="text-xs text-ink-muted">
            Updating…
          </span>
        )}
      </div>
    </div>
  )
}
