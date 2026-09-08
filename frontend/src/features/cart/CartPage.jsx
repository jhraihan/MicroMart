import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { PageSpinner } from '@/components/ui'
import ErrorState from '@/features/catalog/components/ErrorState'
import { formatMoney } from '@/lib/money'
import { useCartStore } from '@/stores/cartStore'

import { quoteLinesByVariant, useCheckoutQuote } from './api'
import CartLine from './components/CartLine'
import CartNotices from './components/CartNotices'
import OrderTotals from './components/OrderTotals'
import { useCart } from './useCart'

/*
 * The cart (PRD §5.3).
 *
 * Opening the cart re-validates prices and stock against the server
 * (FR-CRT-5), which is what the quote call does: it returns the live unit
 * price, the live available stock and an availability verdict per line. The
 * stored guest snapshot is realigned to that answer and any price movement is
 * announced rather than silently applied.
 *
 * Guests get here without an account (FR-CRT-1) and stay anonymous all the
 * way to placement -- sign-in is offered at checkout, never required.
 */
export default function CartPage() {
  const cart = useCart()
  const syncFromServer = useCartStore((s) => s.syncFromServer)
  const [priceChanges, setPriceChanges] = useState([])

  const quoteQuery = useCheckoutQuote({ items: cart.quoteItems })
  const quote = quoteQuery.data
  const quoteLines = useMemo(() => quoteLinesByVariant(quote), [quote])

  /*
   * Fold the server's prices and stock back into the guest snapshot. Both
   * numbers being compared came from the server -- the client is not deciding
   * a price here, only noticing that the one it was given has moved.
   */
  useEffect(() => {
    if (cart.mode !== 'guest' || !quote?.lines?.length) return
    const changed = syncFromServer(quote.lines)
    if (changed.length) setPriceChanges(changed)
  }, [cart.mode, quote, syncFromServer])

  const priceNotices = priceChanges
    .filter((change) => quoteLines.has(change.variantId))
    .map((change) => ({
      code: 'PRICE_CHANGED',
      variant_id: change.variantId,
      tone: 'info',
      message: `${change.productName}${
        change.variantLabel ? ` (${change.variantLabel})` : ''
      } is now ${formatMoney(change.now)}, was ${formatMoney(change.was)}.`,
    }))

  const blockedLines = (quote?.lines ?? []).filter((line) => !line.is_available)
  const notices = [...cart.notices, ...(quote?.notices ?? []), ...priceNotices]

  if (cart.isPending) return <PageSpinner label="Loading your cart" />

  if (cart.isError) {
    return (
      <div className="px-4 py-6">
        <ErrorState
          error={cart.error}
          onRetry={cart.refetch}
          title="Could not load your cart"
        />
      </div>
    )
  }

  if (cart.isEmpty) {
    return (
      <div className="px-4 py-16">
        <div className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-card border border-line bg-white px-4 py-12 text-center">
          <h1 className="text-xl font-semibold text-ink">Your cart is empty</h1>
          <p className="text-sm text-ink-muted">
            Browse the catalogue and add something you like — nothing is reserved
            until you place an order.
          </p>
          <Link
            to="/"
            className="inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-medium text-white hover:bg-action-hover"
          >
            Continue shopping
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="px-4 py-5">
      <h1 className="mb-4 text-xl font-semibold text-ink">
        Your cart{' '}
        <span className="text-sm font-normal text-ink-muted">
          ({cart.itemCount} {cart.itemCount === 1 ? 'item' : 'items'})
        </span>
      </h1>

      <CartNotices notices={notices} className="mb-4" />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        <section aria-label="Cart items" className="rounded-card border border-line bg-white">
          <ul>
            {cart.lines.map((line) => (
              <CartLine
                key={line.key}
                line={line}
                quoteLine={quoteLines.get(line.variantId)}
                disabled={cart.isMutating}
                onQuantityChange={cart.setQuantity}
                onRemove={cart.remove}
              />
            ))}
          </ul>
        </section>

        <aside className="rounded-card border border-line bg-white p-4 lg:sticky lg:top-20">
          <h2 className="mb-2 text-base font-semibold text-ink">Order summary</h2>

          <OrderTotals
            quote={quote}
            isFetching={quoteQuery.isFetching}
            isSettling={cart.isSettling}
            isError={quoteQuery.isError}
            placeholderSubtotal={cart.placeholderSubtotal}
            shippingHint="Calculated at checkout"
          />

          {blockedLines.length > 0 && (
            <p role="alert" className="mt-3 rounded-card bg-danger/10 px-3 py-2 text-xs font-medium text-danger">
              {blockedLines.length === 1
                ? `${blockedLines[0].product_name} cannot be ordered right now.`
                : `${blockedLines.length} items cannot be ordered right now.`}{' '}
              Adjust or remove them to continue.
            </p>
          )}

          <Link
            to="/checkout"
            aria-disabled={blockedLines.length > 0 || undefined}
            onClick={(event) => {
              if (blockedLines.length > 0) event.preventDefault()
            }}
            className={`mt-4 flex min-h-[52px] w-full items-center justify-center rounded-card px-6 text-base font-medium text-white ${
              blockedLines.length > 0
                ? 'pointer-events-none bg-ink-muted opacity-55'
                : 'bg-action hover:bg-action-hover'
            }`}
          >
            Proceed to checkout
          </Link>

          <Link
            to="/"
            className="mt-2 flex min-h-[44px] w-full items-center justify-center rounded-card px-4 text-sm font-medium text-action hover:underline"
          >
            Continue shopping
          </Link>

          <p className="mt-3 text-[11px] text-ink-muted">
            Adding to your cart does not reserve stock. Items are only held once
            an order is confirmed.
          </p>
        </aside>
      </div>
    </div>
  )
}
