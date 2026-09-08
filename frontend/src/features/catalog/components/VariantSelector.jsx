import clsx from 'clsx'

import { formatMoney } from '@/lib/money'

/*
 * Variant picker for the detail page.
 *
 * Price and stock live on the variant, never on the product, so selecting one
 * is what resolves price, stock, SKU and gallery -- all of it client-side,
 * with no page reload and no refetch (the detail response already carries
 * every variant).
 *
 * Out-of-stock variants stay selectable rather than being hidden: a shopper
 * needs to be able to see that the 32GB model exists and is sold out.
 */
export default function VariantSelector({ variants, selectedId, onSelect }) {
  if (!variants || variants.length <= 1) return null

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1.5 text-sm font-semibold text-ink">
        Options
        <span className="ml-1.5 font-normal text-ink-muted">
          ({variants.length} available)
        </span>
      </legend>

      <div className="flex flex-wrap gap-2">
        {variants.map((variant) => {
          const isSelected = variant.id === selectedId
          const inputId = `variant-${variant.id}`

          return (
            <div key={variant.id} className="relative">
              <input
                type="radio"
                id={inputId}
                name="variant"
                value={variant.id}
                checked={isSelected}
                onChange={() => onSelect(variant)}
                className="peer sr-only"
              />
              <label
                htmlFor={inputId}
                className={clsx(
                  'flex min-h-[44px] cursor-pointer flex-col justify-center rounded-card border-2 px-3 py-1.5 text-sm transition-colors',
                  'peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-action',
                  isSelected
                    ? 'border-action bg-tint text-action'
                    : 'border-line bg-white text-ink hover:border-action',
                  !variant.in_stock && 'opacity-70',
                )}
              >
                <span className="font-medium">{variant.option_label || 'Standard'}</span>
                <span className="text-xs text-ink-muted">
                  {formatMoney(variant.price)}
                  {!variant.in_stock && ' · Out of stock'}
                </span>
              </label>
            </div>
          )
        })}
      </div>
    </fieldset>
  )
}
