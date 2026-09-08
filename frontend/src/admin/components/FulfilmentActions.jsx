import { useState } from 'react'

import { Button, Input, Modal, Textarea } from '@/components/ui'
import { parseApiError } from '@/lib/api'

import { orderedTransitions, transitionAction } from '../adminDisplay'
import { useAdvanceOrderStatus, useRecordShipment } from '../ordersApi'

// Moving an order down the pipeline (US-A3, FR-ADM-5, FR-ORD-7).

function ErrorBanner({ error, onDismiss }) {
  if (!error) return null
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-card border border-danger bg-danger/5 px-3 py-2"
    >
      <div className="min-w-0">
        <p className="text-sm font-medium text-danger">{error.message}</p>
        <p className="mt-0.5 text-[11px] text-ink-muted">Reference: {error.code}</p>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss this message"
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-card text-xl leading-none text-ink-muted hover:bg-page hover:text-ink"
      >
        &times;
      </button>
    </div>
  )
}

export default function FulfilmentActions({ order }) {
  const reference = order.reference
  const advance = useAdvanceOrderStatus(reference)
  const shipment = useRecordShipment(reference)

  const [error, setError] = useState(null)
  const [confirming, setConfirming] = useState(null) // a destructive status
  const [note, setNote] = useState('')
  const [shipmentOpen, setShipmentOpen] = useState(false)
  const [shipAfterSaving, setShipAfterSaving] = useState(false)
  const [courier, setCourier] = useState(order.shipment?.courier_name ?? '')
  const [tracking, setTracking] = useState(order.shipment?.tracking_number ?? '')

  const busy = advance.isPending || shipment.isPending
  const transitions = orderedTransitions(order.allowed_transitions ?? [])

  function run(status, transitionNote = '') {
    setError(null)
    advance.mutate(
      { status, note: transitionNote },
      {
        onSuccess: () => {
          setConfirming(null)
          setNote('')
        },
        // Whatever the state machine said, verbatim.
        onError: (err) => setError(parseApiError(err)),
      },
    )
  }

  function handleTransition(status) {
    const action = transitionAction(status)

    if (action.requiresShipment && !order.shipment) {
      // The prerequisite first. The server would refuse the transition with
      // SHIPMENT_REQUIRED, and this is the form that answers it.
      setError(null)
      setShipAfterSaving(true)
      setShipmentOpen(true)
      return
    }

    if (action.destructive) {
      setError(null)
      setConfirming(status)
      return
    }

    run(status)
  }

  function saveShipment(event) {
    event.preventDefault()
    setError(null)
    shipment.mutate(
      { courier_name: courier.trim(), tracking_number: tracking.trim() },
      {
        onSuccess: () => {
          setShipmentOpen(false)
          // The courier record exists now, so the transition the admin
          // actually asked for is legal. If this second call is refused, the
          // shipment still saved and the refusal is shown as-is.
          if (shipAfterSaving) {
            setShipAfterSaving(false)
            run('shipped')
          }
        },
        onError: (err) => setError(parseApiError(err)),
      },
    )
  }

  function closeShipment() {
    if (shipment.isPending) return
    setShipmentOpen(false)
    setShipAfterSaving(false)
  }

  const canEditShipment = Boolean(order.shipment)

  return (
    <div className="flex flex-col gap-3">
      <ErrorBanner error={error} onDismiss={() => setError(null)} />

      {transitions.length === 0 ? (
        <p className="text-sm text-ink-muted">
          This order is {order.status}. The state machine allows no further
          moves from here (PRD §15.1).
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {transitions.map((status) => {
            const action = transitionAction(status)
            return (
              <Button
                key={status}
                variant={action.variant}
                loading={busy && advance.variables?.status === status}
                disabled={busy}
                onClick={() => handleTransition(status)}
                title={action.hint}
              >
                {action.label}
              </Button>
            )
          })}
        </div>
      )}

      {canEditShipment && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => {
              setError(null)
              setShipAfterSaving(false)
              setShipmentOpen(true)
            }}
          >
            Edit courier &amp; tracking
          </Button>
          <span className="text-xs text-ink-muted">
            Correcting these never rewrites when the parcel actually shipped.
          </span>
        </div>
      )}

      {/* --- Courier and tracking (FR-ORD-7) ------------------------------- */}
      <Modal
        open={shipmentOpen}
        onClose={closeShipment}
        title={order.shipment ? 'Courier and tracking' : 'Ship this order'}
        size="sm"
      >
        <form onSubmit={saveShipment} className="flex flex-col gap-3">
          <p className="text-sm text-ink-muted">
            {shipAfterSaving
              ? 'An order cannot be marked shipped without a courier and a tracking number. Add them and it ships in the same step.'
              : 'Both fields are required. A tracking number nobody can track is worse than none at all.'}
          </p>

          <Input
            label="Courier"
            name="courier_name"
            required
            value={courier}
            onChange={(event) => setCourier(event.target.value)}
            placeholder="Sundarban, RedX, Pathao…"
            autoComplete="off"
          />
          <Input
            label="Tracking number"
            name="tracking_number"
            required
            value={tracking}
            onChange={(event) => setTracking(event.target.value)}
            autoComplete="off"
          />

          <ErrorBanner error={error} onDismiss={() => setError(null)} />

          <div className="mt-1 flex justify-end gap-2">
            <Button variant="ghost" onClick={closeShipment} disabled={shipment.isPending}>
              Cancel
            </Button>
            <Button type="submit" loading={busy}>
              {shipAfterSaving ? 'Save and mark shipped' : 'Save'}
            </Button>
          </div>
        </form>
      </Modal>

      {/* --- The two moves that cannot be walked back ---------------------- */}
      <Modal
        open={Boolean(confirming)}
        onClose={() => !busy && setConfirming(null)}
        title={confirming ? transitionAction(confirming).label : ''}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirming(null)} disabled={busy}>
              Keep as is
            </Button>
            <Button
              variant="danger"
              loading={busy}
              onClick={() => run(confirming, note.trim())}
            >
              {confirming ? transitionAction(confirming).label : ''}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">
          {confirming ? transitionAction(confirming).hint : ''}
        </p>
        <p className="mt-1 text-sm text-ink-muted">
          Order{' '}
          <span className="font-medium tabular-nums text-ink">{order.reference}</span> is
          currently {order.status}.
        </p>

        <Textarea
          label="Reason (optional)"
          containerClassName="mt-3"
          rows={3}
          maxLength={255}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          hint="Stored on the audit trail beside your name."
        />

        <div className="mt-3">
          <ErrorBanner error={error} onDismiss={() => setError(null)} />
        </div>
      </Modal>
    </div>
  )
}
