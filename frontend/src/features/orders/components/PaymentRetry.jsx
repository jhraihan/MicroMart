import { useState } from 'react'

import { Button } from '@/components/ui'
import { rememberPendingPayment } from '@/features/checkout/paymentReturn'
import { parseApiError } from '@/lib/api'
import { formatMoney } from '@/lib/money'

import { initiatePayment } from '../api'

// Retry an unpaid online order (FR-PAY-7).
export default function PaymentRetry({
  order = null,
  reference = order?.reference,
  amount = order?.grand_total ?? null,
}) {
  const [isBusy, setIsBusy] = useState(false)
  const [message, setMessage] = useState('')

  async function pay() {
    setIsBusy(true)
    setMessage('')
    try {
      const session = await initiatePayment(reference)
      if (session?.redirect_url) {
        // The handover is a navigation to another origin, so remember which
        // order left before leaving (features/checkout/paymentReturn.js).
        rememberPendingPayment(reference)
        // Leaving the page: deliberately stays busy so a second tap on a slow
        // handover cannot open two gateway sessions.
        window.location.assign(session.redirect_url)
        return
      }
      setMessage('The gateway did not return a payment link. Please try again in a moment.')
    } catch (error) {
      setMessage(parseApiError(error).message)
    }
    setIsBusy(false)
  }

  return (
    <div className="rounded-card border border-warning/40 bg-warning/10 p-3">
      <h3 className="text-sm font-semibold text-ink">Payment not confirmed yet</h3>
      <p className="mt-1 text-xs text-ink-muted">
        {amount != null
          ? `Nothing has been charged and no stock is held. Pay ${formatMoney(amount)} to confirm this order — your items are not reserved until it is.`
          : 'Nothing has been charged and no stock is held. Pay for this order to confirm it — your items are not reserved until it is.'}
      </p>
      <Button className="mt-3" fullWidth loading={isBusy} disabled={!reference} onClick={pay}>
        Pay now
      </Button>
      {message && (
        <p role="alert" className="mt-2 text-xs font-medium text-danger">
          {message}
        </p>
      )}
    </div>
  )
}
