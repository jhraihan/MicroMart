import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { Button } from '@/components/ui'
import { useCart } from '@/features/cart/useCart'
import { parseApiError } from '@/lib/api'
import { formatMoney } from '@/lib/money'
import { useSeo } from '@/lib/seo'
import { useAuthStore } from '@/stores/authStore'
import { useBuilderStore } from '@/stores/builderStore'

import { useBuildValidation, useBuilderSlots, useSaveBuild } from './api'
import ComponentPicker from './components/ComponentPicker'
import CompatibilityPanel from './components/CompatibilityPanel'
import ShareBuildDialog from './components/ShareBuildDialog'

// The PC Builder.
export default function PCBuilderPage() {
  useSeo({
    title: 'PC Builder',
    description:
      'Build a custom PC with automatic compatibility checks for socket, memory, case size and power draw.',
    canonical: '/pc-builder',
  })

  const [searchParams, setSearchParams] = useSearchParams()
  const { data: slots = [], isPending: slotsPending } = useBuilderSlots()

  const selection = useBuilderStore((s) => s.selection)
  const buildName = useBuilderStore((s) => s.name)
  const setName = useBuilderStore((s) => s.setName)
  const select = useBuilderStore((s) => s.select)
  const clearSlot = useBuilderStore((s) => s.clearSlot)
  const clearBuild = useBuilderStore((s) => s.clear)

  // Reading these through the store's own helpers keeps the wire shapes in
  // one place; `useMemo` on `selection` because both walk the whole object.
  const items = useMemo(
    () =>
      Object.entries(selection).map(([slot, row]) => ({
        slot,
        variant_id: row.variantId,
        quantity: row.quantity,
      })),
    [selection],
  )
  const selectionParam = useMemo(
    () =>
      Object.entries(selection)
        .map(([slot, row]) => `${slot}:${row.variantId}`)
        .sort()
        .join(','),
    [selection],
  )

  const { data: report, isFetching } = useBuildValidation(items)
  const user = useAuthStore((s) => s.user)
  const saveBuild = useSaveBuild()
  const { add: addToCart } = useCart()

  // The picker is a dialog keyed by slot, and its open state lives in the URL
  // so the browser Back button closes it rather than leaving the page.
  const openSlot = searchParams.get('slot')
  const [addState, setAddState] = useState({ status: 'idle', message: '' })
  const [shareToken, setShareToken] = useState(null)

  function openPicker(slot) {
    const next = new URLSearchParams(searchParams)
    next.set('slot', slot)
    setSearchParams(next)
  }

  function closePicker() {
    const next = new URLSearchParams(searchParams)
    next.delete('slot')
    next.delete('variant')
    setSearchParams(next, { replace: true })
  }

  function choose(slot, option) {
    select(slot, option.variant_id, 1)
    closePicker()
  }

  const linesBySlot = useMemo(() => {
    const map = {}
    for (const line of report?.lines ?? []) map[line.slot] = line
    return map
  }, [report])

  async function addBuildToCart() {
    const buyable = (report?.lines ?? []).filter(
      (line) => line.product && line.issue == null,
    )
    if (buyable.length === 0) return

    setAddState({ status: 'saving', message: '' })
    try {
      for (const line of buyable) {
        // Sequential rather than parallel: each add is a write against the
        // same cart, and firing them together races on the cart row.
        // eslint-disable-next-line no-await-in-loop
        await addToCart(
          {
            variantId: line.variant_id,
            productSlug: line.product.slug,
            productName: line.product.name,
            variantLabel: line.product.variant_label || 'Default',
            sku: line.product.sku,
            unitPrice: line.product.price,
            image: line.product.image,
            maxStock: line.product.stock,
          },
          line.quantity,
        )
      }
      setAddState({
        status: 'done',
        message: `${buyable.length} parts added to your cart.`,
      })
    } catch (err) {
      setAddState({
        status: 'error',
        message: parseApiError(err).message || 'Some parts could not be added.',
      })
    }
  }

  async function handleSave() {
    const saved = await saveBuild.mutateAsync({ name: buildName, items })
    setShareToken(saved.share_token)
  }

  const chosenCount = Object.keys(selection).length

  return (
    <div className="px-4 py-5">
      <div className="mb-4">
        <h1 className="text-xl font-semibold text-ink sm:text-2xl">PC Builder</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-muted">
          Pick a processor and we narrow the motherboards to the ones that fit.
          Socket, memory type, board size and power draw are checked as you go.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-start">
        <div className="rounded-card bg-white shadow-el-1">
          <ul className="divide-y divide-line">
            {slotsPending
              ? Array.from({ length: 8 }, (_, i) => (
                  <li key={i} className="h-20 animate-pulse bg-page/60" />
                ))
              : slots.map((slot) => (
                  <SlotRow
                    key={slot.slot}
                    slot={slot}
                    line={linesBySlot[slot.slot]}
                    onChoose={() => openPicker(slot.slot)}
                    onRemove={() => clearSlot(slot.slot)}
                  />
                ))}
          </ul>
        </div>

        <div className="flex flex-col gap-4 lg:sticky lg:top-32">
          <div className="rounded-card bg-white p-4 shadow-el-1">
            <label htmlFor="build-name" className="text-sm font-medium text-ink">
              Build name
            </label>
            <input
              id="build-name"
              value={buildName}
              onChange={(event) => setName(event.target.value)}
              maxLength={120}
              className="mt-1 h-11 w-full rounded-card border border-line px-3 text-base text-ink focus:border-action"
            />

            <dl className="mt-4 flex flex-col gap-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-muted">Parts chosen</dt>
                <dd className="font-medium text-ink">{chosenCount}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-muted">Estimated draw</dt>
                <dd className="font-medium text-ink">
                  {report ? `${report.estimated_watts} W` : '—'}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-muted">Suggested PSU</dt>
                <dd className="font-medium text-ink">
                  {report ? `${report.recommended_psu_watts} W` : '—'}
                </dd>
              </div>
              <div className="flex justify-between border-t border-line pt-2 text-base">
                <dt className="font-semibold text-ink">Subtotal</dt>
                <dd className="font-semibold text-price">
                  {report ? formatMoney(report.subtotal) : formatMoney('0')}
                </dd>
              </div>
            </dl>

            <div className="mt-4 flex flex-col gap-2">
              <Button
                onClick={addBuildToCart}
                disabled={chosenCount === 0 || addState.status === 'saving'}
              >
                {addState.status === 'saving' ? 'Adding…' : 'Add all parts to cart'}
              </Button>

              {user ? (
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={chosenCount === 0 || saveBuild.isPending}
                  className="flex min-h-[44px] items-center justify-center rounded-card border-2 border-action text-sm font-semibold text-action hover:bg-action hover:text-white disabled:opacity-60"
                >
                  {saveBuild.isPending ? 'Saving…' : 'Save & share build'}
                </button>
              ) : (
                <Link
                  to="/login"
                  state={{ from: '/pc-builder' }}
                  className="flex min-h-[44px] items-center justify-center rounded-card border-2 border-line text-sm font-medium text-ink hover:border-action hover:text-action"
                >
                  Sign in to save this build
                </Link>
              )}

              <button
                type="button"
                onClick={clearBuild}
                disabled={chosenCount === 0}
                className="flex min-h-[44px] items-center justify-center text-sm text-ink-muted hover:text-danger disabled:opacity-50"
              >
                Start over
              </button>
            </div>

            <p role="status" aria-live="polite" className="mt-2 min-h-[20px] text-sm">
              <span
                className={
                  addState.status === 'error' ? 'text-danger' : 'text-success'
                }
              >
                {addState.message}
              </span>
            </p>

            {saveBuild.isError && (
              <p role="alert" className="text-sm text-danger">
                {parseApiError(saveBuild.error).message ||
                  'That build could not be saved.'}
              </p>
            )}
          </div>

          <CompatibilityPanel report={report} isFetching={isFetching} slots={slots} />
        </div>
      </div>

      {openSlot && (
        <ComponentPicker
          slot={openSlot}
          slots={slots}
          selectionParam={selectionParam}
          onChoose={(option) => choose(openSlot, option)}
          onClose={closePicker}
        />
      )}

      {shareToken && (
        <ShareBuildDialog token={shareToken} onClose={() => setShareToken(null)} />
      )}
    </div>
  )
}

function SlotRow({ slot, line, onChoose, onRemove }) {
  const product = line?.product

  return (
    <li className="flex items-center gap-3 p-3">
      <span className="flex w-28 shrink-0 flex-col">
        <span className="text-sm font-medium text-ink">{slot.label}</span>
        {slot.required && (
          <span className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">
            Required
          </span>
        )}
      </span>

      {product ? (
        <>
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-card border border-line bg-white p-1">
            {product.image ? (
              <img
                src={product.image}
                alt=""
                loading="lazy"
                className="h-full w-full object-contain"
              />
            ) : (
              <span className="text-[10px] text-ink-muted">No image</span>
            )}
          </span>

          <span className="min-w-0 flex-1">
            <Link
              to={`/p/${product.slug}`}
              className="block truncate text-sm text-ink hover:text-action hover:underline"
            >
              {product.name}
            </Link>
            <span className="block text-xs text-ink-muted">
              {formatMoney(product.price)}
              {line.quantity > 1 ? ` × ${line.quantity}` : ''}
              {line.issue === 'out_of_stock' && (
                <span className="ml-2 font-medium text-warning">Out of stock</span>
              )}
              {line.issue === 'unavailable' && (
                <span className="ml-2 font-medium text-danger">No longer sold</span>
              )}
            </span>
          </span>

          <span className="flex shrink-0 gap-1">
            <button
              type="button"
              onClick={onChoose}
              className="flex min-h-[44px] items-center rounded-card border border-line px-3 text-xs font-medium text-ink hover:border-action hover:text-action"
            >
              Change
            </button>
            <button
              type="button"
              onClick={onRemove}
              aria-label={`Remove ${slot.label}`}
              className="flex h-11 w-11 items-center justify-center rounded-card text-ink-muted hover:text-danger"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4"
                   fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
              </svg>
            </button>
          </span>
        </>
      ) : (
        <>
          <span className="flex-1 text-sm text-ink-muted">Not selected</span>
          <button
            type="button"
            onClick={onChoose}
            className="flex min-h-[44px] shrink-0 items-center rounded-card border-2 border-action px-4 text-sm font-semibold text-action hover:bg-action hover:text-white"
          >
            Choose
          </button>
        </>
      )}
    </li>
  )
}
