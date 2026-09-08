import { useState } from 'react'

import { Button, Input } from '@/components/ui'
import { formatMoney } from '@/lib/money'

/*
 * Coupon entry lives in the review section and recalculates every total on
 * apply and on remove (FR-CHK-6). "Apply" does not call a validation
 * endpoint: it re-quotes with the code attached, so the discount a shopper
 * sees is produced by the same call that produces the total they will be
 * charged. One computation, one round trip, no chance of the two disagreeing.
 *
 * The quote answers a bad code with `coupon_error` rather than failing, so a
 * typo or a coupon that hit its cap mid-checkout leaves the totals on screen
 * (FR-CPN-7).
 */
export default function CouponField({
  appliedCode,
  coupon,
  errorMessage,
  onApply,
  onRemove,
  isBusy = false,
}) {
  const [code, setCode] = useState('')

  // A code is "applied" as soon as it is attached to the quote; whether it
  // earned a discount is the server's answer, carried in `coupon`.
  if (appliedCode) {
    return (
      <div className="rounded-card border border-line bg-page p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm">
            <span className="font-medium text-ink">{appliedCode}</span>
            {coupon ? (
              <span className="ml-2 text-success">
                &minus;{formatMoney(coupon.discount_total)} applied
              </span>
            ) : (
              <span className="ml-2 text-ink-muted">not applied</span>
            )}
          </div>
          <Button variant="ghost" size="sm" onClick={onRemove} disabled={isBusy}>
            Remove
          </Button>
        </div>
        {errorMessage && (
          <p role="alert" className="mt-2 text-xs font-medium text-danger">
            {errorMessage}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-start gap-2">
      <Input
        label="Coupon code"
        containerClassName="flex-1"
        placeholder="e.g. WELCOME10"
        autoCapitalize="characters"
        value={code}
        onChange={(event) => setCode(event.target.value)}
        error={errorMessage}
        onKeyDown={(event) => {
          if (event.key !== 'Enter') return
          // Inside the checkout form, Enter here must not submit the order.
          event.preventDefault()
          if (code.trim()) onApply(code.trim().toUpperCase())
        }}
      />
      <Button
        variant="outline"
        className="mt-[26px]"
        disabled={!code.trim() || isBusy}
        onClick={() => onApply(code.trim().toUpperCase())}
      >
        Apply
      </Button>
    </div>
  )
}
