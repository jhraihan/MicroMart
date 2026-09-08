import { useState } from 'react'

import { Button } from '@/components/ui'
import { addressSchema } from '@/features/auth/schemas'
import ErrorState from '@/features/catalog/components/ErrorState'
import { DIVISIONS } from '@/features/checkout/bdGeo'
import { parseApiError } from '@/lib/api'
import { useSeo } from '@/lib/seo'

import {
  useAddresses,
  useCreateAddress,
  useDeleteAddress,
  useUpdateAddress,
} from './api'

// The address book (FR-AUT-6).

const EMPTY = {
  recipient_name: '',
  phone: '',
  division: '',
  district: '',
  upazila: '',
  area: '',
  street: '',
  postcode: '',
  is_default: false,
}

export default function AddressesPage() {
  useSeo({ title: 'Saved addresses', canonical: '/account/addresses', noIndex: true })

  const {
    data: addresses = [],
    isPending,
    isError,
    error: loadError,
    refetch,
  } = useAddresses()
  const createAddress = useCreateAddress()
  const updateAddress = useUpdateAddress()
  const deleteAddress = useDeleteAddress()

  // `null` = closed, an object = the form's current values. An id inside it
  // means editing; its absence means creating.
  const [draft, setDraft] = useState(null)
  const [error, setError] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState(null)

  const districts =
    DIVISIONS.find((division) => division.name === draft?.division)?.districts ?? []

  async function submit(event) {
    event.preventDefault()
    setError('')

    // Same schema the checkout form uses, so an address saved here and one
    // typed at checkout are held to identical rules.
    const checked = addressSchema.safeParse(draft)
    if (!checked.success) {
      setError(checked.error.issues[0].message)
      return
    }

    try {
      if (draft.id) {
        await updateAddress.mutateAsync(draft)
      } else {
        await createAddress.mutateAsync(draft)
      }
      setDraft(null)
    } catch (err) {
      setError(parseApiError(err).message || 'That address could not be saved.')
    }
  }

  async function remove(id) {
    setError('')
    try {
      await deleteAddress.mutateAsync(id)
      setConfirmingDelete(null)
    } catch (err) {
      setError(parseApiError(err).message || 'That address could not be removed.')
    }
  }

  const isSaving = createAddress.isPending || updateAddress.isPending

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-card bg-white p-4 shadow-el-1">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold text-ink">Saved addresses</h2>
            <p className="mt-0.5 text-sm text-ink-muted">
              Used to prefill checkout. Your order always stores its own copy, so
              editing one here never changes a past order.
            </p>
          </div>
          {!draft && (
            <Button onClick={() => setDraft({ ...EMPTY })}>Add address</Button>
          )}
        </div>

        {error && (
          <p role="alert" className="mb-3 rounded-card bg-danger/5 p-3 text-sm text-danger">
            {error}
          </p>
        )}

        {isPending ? (
          <div className="h-24 animate-pulse rounded-card bg-page" />
        ) : isError ? (
          <ErrorState
            error={loadError}
            onRetry={refetch}
            title="Could not load your addresses"
          />
        ) : addresses.length === 0 && !draft ? (
          <div className="rounded-card bg-page p-6 text-center">
            <p className="text-sm text-ink">No addresses saved yet.</p>
            <p className="mt-1 text-sm text-ink-muted">
              Add one now, or enter it during checkout.
            </p>
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {addresses.map((address) => (
              <li
                key={address.id}
                className="flex flex-col rounded-card border border-line p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium text-ink">{address.recipient_name}</span>
                  {address.is_default && (
                    <span className="rounded-pill bg-tint px-2 py-0.5 text-[11px] font-medium text-action">
                      Default
                    </span>
                  )}
                </div>

                <address className="mt-1 flex-1 text-sm not-italic leading-6 text-ink-muted">
                  {[
                    address.street,
                    address.area,
                    address.upazila,
                    address.district,
                    address.division,
                    address.postcode,
                  ]
                    .filter(Boolean)
                    .join(', ')}
                  <span className="mt-0.5 block">{address.phone}</span>
                </address>

                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setDraft({ ...address })}
                    className="flex min-h-[44px] items-center rounded-card border border-line px-3 text-sm text-ink hover:border-action hover:text-action"
                  >
                    Edit
                  </button>

                  {!address.is_default && (
                    <button
                      type="button"
                      onClick={() =>
                        updateAddress.mutate({ id: address.id, is_default: true })
                      }
                      className="flex min-h-[44px] items-center rounded-card border border-line px-3 text-sm text-ink hover:border-action hover:text-action"
                    >
                      Make default
                    </button>
                  )}

                  {confirmingDelete === address.id ? (
                    /* Destructive, so it asks. An inline confirm rather than a
                       dialog: it is one row, and a modal for this is heavier
                       than the action. */
                    <span className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => remove(address.id)}
                        className="flex min-h-[44px] items-center rounded-card bg-danger px-3 text-sm font-semibold text-white"
                      >
                        Confirm
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingDelete(null)}
                        className="flex min-h-[44px] items-center px-2 text-sm text-ink-muted"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmingDelete(address.id)}
                      className="flex min-h-[44px] items-center px-2 text-sm text-ink-muted hover:text-danger"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {draft && (
        <section className="rounded-card bg-white p-4 shadow-el-1">
          <h2 className="mb-3 text-base font-semibold text-ink">
            {draft.id ? 'Edit address' : 'New address'}
          </h2>

          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Recipient name"
              value={draft.recipient_name}
              onChange={(v) => setDraft({ ...draft, recipient_name: v })}
              required
            />
            <Field
              label="Phone"
              type="tel"
              value={draft.phone}
              onChange={(v) => setDraft({ ...draft, phone: v })}
              required
            />

            <div className="flex flex-col gap-1">
              <label htmlFor="division" className="text-sm font-medium text-ink">
                Division
              </label>
              <select
                id="division"
                required
                value={draft.division}
                onChange={(event) =>
                  // Changing division invalidates the district beneath it.
                  setDraft({ ...draft, division: event.target.value, district: '' })
                }
                className="h-11 rounded-card border border-line bg-white px-3 text-base text-ink focus:border-action"
              >
                <option value="">Select a division</option>
                {DIVISIONS.map((division) => (
                  <option key={division.name} value={division.name}>
                    {division.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1">
              <label htmlFor="district" className="text-sm font-medium text-ink">
                District
              </label>
              <select
                id="district"
                required
                disabled={!draft.division}
                value={draft.district}
                onChange={(event) => setDraft({ ...draft, district: event.target.value })}
                className="h-11 rounded-card border border-line bg-white px-3 text-base text-ink focus:border-action disabled:bg-page"
              >
                <option value="">
                  {draft.division ? 'Select a district' : 'Choose a division first'}
                </option>
                {districts.map((district) => (
                  <option key={district} value={district}>
                    {district}
                  </option>
                ))}
              </select>
            </div>

            <Field
              label="Upazila / Thana"
              value={draft.upazila}
              onChange={(v) => setDraft({ ...draft, upazila: v })}
            />
            <Field
              label="Area"
              value={draft.area}
              onChange={(v) => setDraft({ ...draft, area: v })}
            />

            <div className="sm:col-span-2">
              <Field
                label="Street address"
                value={draft.street}
                onChange={(v) => setDraft({ ...draft, street: v })}
                required
              />
            </div>

            <Field
              label="Postcode"
              value={draft.postcode}
              onChange={(v) => setDraft({ ...draft, postcode: v })}
            />

            <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={draft.is_default}
                onChange={(event) =>
                  setDraft({ ...draft, is_default: event.target.checked })
                }
                className="h-4 w-4 accent-action"
              />
              Use as my default address
            </label>

            <div className="flex flex-wrap gap-2 sm:col-span-2">
              <Button type="submit" disabled={isSaving}>
                {isSaving ? 'Saving…' : draft.id ? 'Save changes' : 'Add address'}
              </Button>
              <button
                type="button"
                onClick={() => {
                  setDraft(null)
                  setError('')
                }}
                className="flex min-h-[44px] items-center rounded-card border border-line px-4 text-sm text-ink hover:border-action hover:text-action"
              >
                Cancel
              </button>
            </div>
          </form>
        </section>
      )}
    </div>
  )
}

function Field({ label, value, onChange, type = 'text', required = false }) {
  const id = label.toLowerCase().replace(/[^a-z]+/g, '-')
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
        {!required && <span className="ml-1 text-xs text-ink-muted">(optional)</span>}
      </label>
      <input
        id={id}
        type={type}
        required={required}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 rounded-card border border-line px-3 text-base text-ink focus:border-action"
      />
    </div>
  )
}
