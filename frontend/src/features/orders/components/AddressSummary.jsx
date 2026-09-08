/*
 * The shipping address as it was copied onto the order — not a reference to
 * the address book (FR-ORD-2). Editing a saved address later must never
 * rewrite where a past order went, and this component reads the order only.
 */
export default function AddressSummary({ address }) {
  if (!address) return null

  const lines = [
    address.street,
    [address.area, address.upazila].filter(Boolean).join(', '),
    [address.district, address.division].filter(Boolean).join(', '),
    address.postcode,
  ].filter(Boolean)

  return (
    <address className="text-sm not-italic">
      <p className="font-medium text-ink">{address.recipient_name}</p>
      {lines.map((line, index) => (
        <p key={`${index}-${line}`} className="text-ink-muted">
          {line}
        </p>
      ))}
      {address.phone && (
        <p className="mt-1 text-ink-muted">
          <span className="sr-only">Delivery phone: </span>
          {address.phone}
        </p>
      )}
    </address>
  )
}
