import { useShippingZones } from '@/features/checkout/api'
import { formatMoney } from '@/lib/money'

// Delivery and warranty panel for the detail page.
export default function DeliveryInfo({ product }) {
  const { data: zones = [], isPending } = useShippingZones()
  const codZone = zones.find((zone) => zone.cod_allowed)

  return (
    <section
      aria-labelledby="delivery-heading"
      className="rounded-card bg-white p-4 shadow-el-1"
    >
      <h2 id="delivery-heading" className="mb-3 text-base font-semibold text-ink">
        Delivery &amp; warranty
      </h2>

      <ul className="flex flex-col gap-3 text-sm">
        <Row
          title="Delivery charge"
          body={
            isPending
              ? 'Loading rates…'
              : zones.length
                ? zones
                    .map((zone) => `${zone.name}: from ${formatMoney(zone.flat_rate)}`)
                    .join(' · ')
                : 'Calculated at checkout from your district.'
          }
          note="Final charge depends on weight and destination, and is shown before you pay."
        />

        <Row
          title="Cash on delivery"
          body={
            codZone
              ? 'Available. Pay the courier when your order arrives.'
              : 'Not available for this destination.'
          }
        />

        <Row
          title="Warranty"
          body={
            product.warranty_months > 0
              ? `${product.warranty_months} months official warranty`
              : 'No manufacturer warranty on this item.'
          }
          note={
            product.warranty_months > 0
              ? 'Claims are handled through us with your invoice.'
              : undefined
          }
        />

        <Row
          title="Returns"
          body="Report a dead-on-arrival or wrong item within 3 days of delivery."
        />
      </ul>
    </section>
  )
}

function Row({ title, body, note }) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-pill bg-tint text-action"
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none"
             stroke="currentColor" strokeWidth="2">
          <path d="M4 12.5l5 5L20 6.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <span className="min-w-0">
        <span className="block font-medium text-ink">{title}</span>
        <span className="block text-ink-muted">{body}</span>
        {note && <span className="mt-0.5 block text-xs text-ink-muted">{note}</span>}
      </span>
    </li>
  )
}
