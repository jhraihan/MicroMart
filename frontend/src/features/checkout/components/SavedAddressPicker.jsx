import clsx from 'clsx'

/*
 * FR-CHK-4: a signed-in shopper picks a saved address or adds a new one.
 *
 * Whichever they pick, the server copies the address onto the order rather
 * than pointing at the address book (FR-ORD-2) -- editing a saved address
 * later must not rewrite a delivered order's label.
 */
export default function SavedAddressPicker({ addresses = [], value, onSelect, error }) {
  const options = [
    ...addresses.map((address) => ({ value: String(address.id), address })),
    { value: 'new', address: null },
  ]

  return (
    <fieldset>
      <legend className="sr-only">Delivery address</legend>
      <div className="flex flex-col gap-2">
        {options.map((option) => {
          const selected = value === option.value
          return (
            <label
              key={option.value}
              className={clsx(
                'flex cursor-pointer items-start gap-3 rounded-card border p-3',
                selected ? 'border-action bg-tint' : 'border-line hover:border-action',
              )}
            >
              <input
                type="radio"
                name="saved-address"
                className="mt-1 h-4 w-4 shrink-0 accent-action"
                checked={selected}
                onChange={() => onSelect(option.value)}
              />
              {option.address ? (
                <span className="min-w-0 text-sm">
                  <span className="block font-medium text-ink">
                    {option.address.recipient_name}
                    {option.address.is_default && (
                      <span className="ml-2 rounded-pill bg-page px-2 py-0.5 text-[11px] font-medium text-ink-muted">
                        Default
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block text-ink-muted">
                    {[
                      option.address.street,
                      option.address.area,
                      option.address.upazila,
                      option.address.district,
                      option.address.division,
                      option.address.postcode,
                    ]
                      .filter(Boolean)
                      .join(', ')}
                  </span>
                  <span className="mt-0.5 block text-ink-muted">{option.address.phone}</span>
                </span>
              ) : (
                <span className="text-sm font-medium text-ink">
                  Deliver somewhere else
                  <span className="mt-0.5 block text-xs font-normal text-ink-muted">
                    Enter a new address below.
                  </span>
                </span>
              )}
            </label>
          )
        })}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </fieldset>
  )
}
