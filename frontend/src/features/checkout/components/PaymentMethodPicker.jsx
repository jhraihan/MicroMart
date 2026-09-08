import clsx from 'clsx'

/*
 * The payment options come from the quote, not from a constant in this file.
 *
 * Whether Cash on Delivery is offered depends on the order total against the
 * configured cap and on whether the resolved zone permits it (FR-PAY-1,
 * FR-SHP-5). Both are server-side rules with server-side data, so the server
 * decides and sends a reason; this component renders the verdict and disables
 * what it is told to disable. Re-deriving the rule here is how the storefront
 * and the API start disagreeing.
 */

const FALLBACK_DESCRIPTION = {
  cod: 'Pay the courier in cash when your order arrives.',
  online: 'Card, bKash, Nagad or Rocket via SSLCommerz. You will be redirected to pay.',
}

export default function PaymentMethodPicker({
  methods,
  value,
  onChange,
  error,
  isPending = false,
}) {
  if (!methods?.length) {
    return (
      <p className="rounded-card bg-page px-3 py-3 text-sm text-ink-muted">
        {isPending
          ? 'Loading payment options…'
          : 'Choose a delivery district above to see how you can pay.'}
      </p>
    )
  }

  return (
    <fieldset>
      <legend className="sr-only">Payment method</legend>
      <div className="flex flex-col gap-2">
        {methods.map((method) => {
          const selected = value === method.code
          const disabled = !method.available
          return (
            <label
              key={method.code}
              className={clsx(
                'flex items-start gap-3 rounded-card border p-3',
                disabled && 'cursor-not-allowed border-line bg-page opacity-70',
                !disabled && selected && 'cursor-pointer border-action bg-tint',
                !disabled && !selected && 'cursor-pointer border-line hover:border-action',
              )}
            >
              <input
                type="radio"
                name="payment_method"
                value={method.code}
                className="mt-1 h-4 w-4 shrink-0 accent-action"
                checked={selected}
                disabled={disabled}
                onChange={() => onChange(method.code)}
              />
              <span className="min-w-0 text-sm">
                <span className="block font-medium text-ink">{method.label}</span>
                <span className="mt-0.5 block text-xs text-ink-muted">
                  {method.unavailable_reason ??
                    FALLBACK_DESCRIPTION[method.code] ??
                    ''}
                </span>
              </span>
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
