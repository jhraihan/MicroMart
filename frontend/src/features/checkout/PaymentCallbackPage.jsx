import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { Badge, Button, OrderStatusBadge, Spinner } from '@/components/ui'
import ErrorState from '@/features/catalog/components/ErrorState'
import { useOrder } from '@/features/orders/api'
import PaymentRetry from '@/features/orders/components/PaymentRetry'
import { paymentStatusLabel, paymentStatusTone } from '@/features/orders/orderDisplay'
import { useAuthStore } from '@/stores/authStore'

import { forgetPendingPayment, isPaymentReference, readPendingPayment } from './paymentReturn'

// Where SSLCommerz sends the browser back (FR-PAY-3).

// ~15 seconds of polling. Long enough for a healthy IPN, short enough that a
// customer is not left staring at a spinner with no explanation.
const MAX_POLL_ATTEMPTS = 6
const POLL_INTERVAL_MS = 2500

// The gateway echoes the reference under `tran_id`; the others are fallbacks
// for however the return is finally wired, and all of them are validated
// before use.
const REFERENCE_PARAMS = ['tran_id', 'reference', 'value_a', 'order']

const EYEBROW_TONE = {
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  neutral: 'text-ink-muted',
}

/*
 * Copy for every return that is not a claimed success. An unrecognised result
 * segment deliberately falls in here too: the safe direction to be wrong in is
 * "we cannot say a payment happened".
 */
const NOT_COMPLETED = {
  cancel: {
    tone: 'neutral',
    eyebrow: 'Payment cancelled',
    title: 'You cancelled the payment',
  },
  fail: {
    tone: 'danger',
    eyebrow: 'Payment failed',
    title: 'The payment did not go through',
  },
}

const UNKNOWN_RETURN = {
  tone: 'neutral',
  eyebrow: 'Payment not completed',
  title: 'The payment was not completed',
}

const PRIMARY_LINK =
  'flex min-h-[44px] w-full items-center justify-center rounded-card bg-action px-4 text-sm font-medium text-white hover:bg-action-hover'
const SECONDARY_LINK =
  'flex min-h-[44px] w-full items-center justify-center rounded-card border-2 border-action px-4 text-sm font-medium text-action hover:bg-action hover:text-white'
const QUIET_LINK =
  'flex min-h-[44px] w-full items-center justify-center rounded-card px-4 text-sm font-medium text-action hover:underline'

function Panel({ tone = 'neutral', eyebrow, title, children }) {
  return (
    <div className="px-4 py-6">
      <div className="mx-auto flex w-full max-w-xl flex-col gap-4 rounded-card border border-line bg-white p-4 sm:p-6">
        <header className="text-center">
          <p className={`text-sm font-medium ${EYEBROW_TONE[tone] ?? EYEBROW_TONE.neutral}`}>
            {eyebrow}
          </p>
          <h1 className="mt-1 text-xl font-semibold text-ink">{title}</h1>
        </header>
        {children}
      </div>
    </div>
  )
}

function ReferenceLine({ reference }) {
  if (!reference) return null
  return (
    <div className="rounded-card bg-page px-3 py-3 text-center">
      <p className="text-xs text-ink-muted">Your order reference</p>
      <p className="text-lg font-bold tracking-tight text-ink tabular-nums select-all">
        {reference}
      </p>
    </div>
  )
}

function StatusRow({ order }) {
  const label = paymentStatusLabel(order.payment_status)
  return (
    <div className="flex flex-wrap items-center justify-center gap-2">
      <OrderStatusBadge status={order.status} />
      {label && (
        <Badge tone={paymentStatusTone(order.payment_status)} size="sm">
          {label}
        </Badge>
      )}
    </div>
  )
}

/** The invariant, said out loud to the person it protects. */
function Footnote() {
  return (
    <p className="text-[11px] text-ink-muted">
      Coming back from the payment page is not by itself proof that a payment
      went through. An order is marked paid only when SSLCommerz confirms the
      transaction with us directly — which happens whether or not this page is
      open.
    </p>
  )
}

function KeepShopping() {
  return (
    <Link to="/" className={QUIET_LINK}>
      Continue shopping
    </Link>
  )
}

export default function PaymentCallbackPage() {
  const params = useParams()
  const [searchParams] = useSearchParams()
  const user = useAuthStore((s) => s.user)
  const isAuthed = Boolean(user)

  const result = String(params.result ?? '').toLowerCase()
  // Only the literal "success" is even treated as a *claim* of payment, and
  // the claim is then checked against the order rather than believed.
  const isSuccessReturn = result === 'success'

  /*
   * The reference comes from the URL when the gateway echoed it, and from the
   * tab's own stash when it did not (paymentReturn.js) -- the handover is a
   * full navigation to another origin, so nothing this app held in memory
   * survives it.
   */
  const reference = useMemo(() => {
    for (const key of REFERENCE_PARAMS) {
      const candidate = (searchParams.get(key) ?? '').trim()
      if (isPaymentReference(candidate)) return candidate
    }
    return readPendingPayment()
  }, [searchParams])

  /*
   * GET /orders/{reference}/ answers for the authenticated customer alone, so
   * a guest genuinely cannot be told the answer here. That is a limit to state
   * plainly, not to paper over with an optimistic screen.
   */
  const canRead = isAuthed && Boolean(reference)
  const { data: order, isError, error, isFetching, refetch } = useOrder(reference, {
    enabled: canRead,
  })

  const [attempts, setAttempts] = useState(0)

  const isPaid = order?.payment_status === 'paid'
  const isClosed = order?.status === 'cancelled' || order?.status === 'refunded'
  const isResolved = Boolean(order) && (isPaid || isClosed)
  const isExhausted = attempts >= MAX_POLL_ATTEMPTS

  const shouldPoll =
    isSuccessReturn &&
    canRead &&
    Boolean(order) &&
    !isResolved &&
    !isExhausted &&
    !isError &&
    !isFetching

  useEffect(() => {
    if (!shouldPoll) return undefined
    const timer = setTimeout(() => {
      setAttempts((n) => n + 1)
      refetch()
    }, POLL_INTERVAL_MS)
    return () => clearTimeout(timer)
  }, [shouldPoll, attempts, refetch])

  // Once the order has actually settled the stash has done its job.
  useEffect(() => {
    if (isResolved) forgetPendingPayment()
  }, [isResolved])

  function checkAgain() {
    setAttempts(0)
    refetch()
  }

  // --- Nothing to look up ---------------------------------------------------
  if (!reference) {
    return (
      <Panel
        tone="neutral"
        eyebrow="Back from the payment page"
        title="We could not tell which order this was"
      >
        <p className="text-sm text-ink-muted">
          The payment page sent you back without an order reference, so there is
          nothing for this screen to look up. Nothing is lost by that: if a
          payment did go through, SSLCommerz confirms it with us directly and
          your confirmation email follows either way.
        </p>
        {isAuthed ? (
          <Link to="/orders" className={PRIMARY_LINK}>
            Open my orders
          </Link>
        ) : (
          <Link to="/login" state={{ from: '/orders' }} className={PRIMARY_LINK}>
            Sign in to see your orders
          </Link>
        )}
        <KeepShopping />
        <Footnote />
      </Panel>
    )
  }

  // --- A guest: the order exists, but this browser may not read it ----------
  if (!canRead) {
    if (isSuccessReturn) {
      return (
        <Panel
          tone="warning"
          eyebrow="Payment submitted"
          title="We are confirming your payment"
        >
          <ReferenceLine reference={reference} />
          <p className="text-sm text-ink-muted" role="status">
            You ordered as a guest, so this browser cannot read the order back
            to check — that needs an account. The confirmation itself does not
            depend on this page: SSLCommerz notifies us server to server, and
            the receipt goes to the email address you ordered with.
          </p>
          <Link
            to="/login"
            state={{ from: `/orders/${reference}` }}
            className={PRIMARY_LINK}
          >
            Sign in to check this order
          </Link>
          <KeepShopping />
          <Footnote />
        </Panel>
      )
    }

    const copy = NOT_COMPLETED[result] ?? UNKNOWN_RETURN
    return (
      <Panel tone={copy.tone} eyebrow={copy.eyebrow} title={copy.title}>
        <ReferenceLine reference={reference} />
        <p className="text-sm text-ink-muted">
          Your order is saved and still pending. Nothing has been charged, and
          no stock has been taken for it — an attempt that fails or is cancelled
          costs you nothing, and you can simply pay again.
        </p>
        {/*
         * FR-PAY-7's "cart intact" clause: the basket became a pending order at
         * placement, so the thing to preserve is the order and the ability to
         * pay for it, which is exactly what this button does. Re-initiating
         * overwrites the gateway session on the same Payment row.
         */}
        <PaymentRetry reference={reference} />
        <KeepShopping />
        <Footnote />
      </Panel>
    )
  }

  // --- Signed in, but the read itself failed --------------------------------
  if (isError && !order) {
    return (
      <Panel
        tone="neutral"
        eyebrow="Back from the payment page"
        title="We could not check this order"
      >
        <ReferenceLine reference={reference} />
        <p className="text-sm text-ink-muted">
          This says nothing about the payment — the order is exactly as it was,
          and reading it is the only thing that failed.
        </p>
        <ErrorState error={error} onRetry={checkAgain} title="Could not read your order" />
        <Link to="/orders" className={SECONDARY_LINK}>
          Open my orders
        </Link>
        <Footnote />
      </Panel>
    )
  }

  if (!order) {
    return (
      <Panel
        tone="neutral"
        eyebrow="Back from the payment page"
        title="Checking your order"
      >
        <ReferenceLine reference={reference} />
        <div className="flex justify-center">
          <Spinner size="lg" label="Reading your order" />
        </div>
        <Footnote />
      </Panel>
    )
  }

  const orderLink = (
    <Link to={`/orders/${order.reference}`} className={SECONDARY_LINK}>
      View this order
    </Link>
  )

  // --- Paid: the order says so, which is the only thing that counts ---------
  if (isPaid) {
    return (
      <Panel tone="success" eyebrow="Payment confirmed" title="Payment confirmed">
        <ReferenceLine reference={order.reference} />
        <StatusRow order={order} />
        <p className="text-sm text-ink-muted">
          SSLCommerz confirmed this transaction with us and the order has moved
          out of pending. A receipt is on its way to{' '}
          <span className="font-medium text-ink">{order.email}</span>.
        </p>
        {orderLink}
        <KeepShopping />
      </Panel>
    )
  }

  // --- Cancelled or refunded: settled, but not by a payment -----------------
  if (isClosed) {
    return (
      <Panel
        tone="neutral"
        eyebrow="Nothing to pay"
        title={
          order.status === 'refunded'
            ? 'This order has been refunded'
            : 'This order has been cancelled'
        }
      >
        <ReferenceLine reference={order.reference} />
        <StatusRow order={order} />
        <p className="text-sm text-ink-muted">
          There is nothing outstanding on it, so no payment is needed and none
          will be taken.
        </p>
        {orderLink}
        <KeepShopping />
      </Panel>
    )
  }

  // --- Claimed success, order still unpaid: confirming, then a timeout ------
  if (isSuccessReturn && !isExhausted) {
    return (
      <Panel
        tone="warning"
        eyebrow="Payment submitted"
        title="Confirming your payment"
      >
        <ReferenceLine reference={order.reference} />
        {/*
          * One live region, not two: <Spinner> already carries role="status"
          * with a label that never changes, so the countdown gets its own
          * polite region rather than being nested inside another one and
          * announced twice.
          */}
        <div className="flex flex-col items-center gap-2">
          <Spinner size="lg" label="Confirming your payment" />
          <p className="text-xs text-ink-muted tabular-nums" aria-live="polite">
            Checking your order — attempt {Math.min(attempts + 1, MAX_POLL_ATTEMPTS)} of{' '}
            {MAX_POLL_ATTEMPTS}
          </p>
        </div>
        <StatusRow order={order} />
        <p className="text-sm text-ink-muted">
          The payment page says you finished paying. We do not take its word for
          it — your order is marked paid only once SSLCommerz confirms the
          transaction with us directly, which usually takes a few seconds. Until
          then it stays pending, and this page updates itself as soon as that
          changes.
        </p>
        <Footnote />
      </Panel>
    )
  }

  if (isSuccessReturn) {
    return (
      <Panel
        tone="warning"
        eyebrow="Still confirming"
        title="This is taking longer than usual"
      >
        <ReferenceLine reference={order.reference} />
        <StatusRow order={order} />
        <p className="text-sm text-ink-muted">
          We have not had confirmation for order{' '}
          <span className="font-medium text-ink tabular-nums">{order.reference}</span>{' '}
          yet. That is not a failure — confirmation can take a moment longer
          than the redirect, and it reaches us whether or not this page is open.
          Your order is safe and stays pending until it arrives.
        </p>
        {/*
         * Deliberately no "pay again" here. The gateway told the browser the
         * payment succeeded, so the likeliest reading of a delay is a
         * confirmation still in flight -- and inviting a second attempt at that
         * moment invites a second charge. "Check again" is the safe action; the
         * order screen offers payment once it is clear none arrived. (The
         * server refuses a second session for an order already paid, so the
         * customer cannot be charged twice either way.)
         */}
        <Button fullWidth loading={isFetching} onClick={checkAgain}>
          Check again
        </Button>
        {orderLink}
        <Footnote />
      </Panel>
    )
  }

  // --- Failed or cancelled, and the order confirms it is still unpaid -------
  const copy = NOT_COMPLETED[result] ?? UNKNOWN_RETURN
  return (
    <Panel tone={copy.tone} eyebrow={copy.eyebrow} title={copy.title}>
      <ReferenceLine reference={order.reference} />
      <StatusRow order={order} />
      <p className="text-sm text-ink-muted">
        Your order is saved and still pending. Nothing has been charged, and no
        stock has been taken for it — your items are not reserved until a
        payment is confirmed, so this attempt has cost you nothing.
      </p>
      <PaymentRetry order={order} />
      {orderLink}
      <KeepShopping />
      <Footnote />
    </Panel>
  )
}
