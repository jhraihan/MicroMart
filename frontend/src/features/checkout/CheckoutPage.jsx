import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { Button, Input, PageSpinner, Select, Textarea } from '@/components/ui'
import { cartKeys, useCheckoutQuote } from '@/features/cart/api'
import OrderTotals from '@/features/cart/components/OrderTotals'
import { useCart } from '@/features/cart/useCart'
import { initiatePayment, newIdempotencyKey, usePlaceOrder } from '@/features/orders/api'
import { parseApiError } from '@/lib/api'
import { formatMoney } from '@/lib/money'
import { useAuthStore } from '@/stores/authStore'

import { useAddresses, useShippingZones } from './api'
import { DIVISION_NAMES, districtsFor } from './bdGeo'
import CouponField from './components/CouponField'
import PaymentMethodPicker from './components/PaymentMethodPicker'
import ReviewLines from './components/ReviewLines'
import SavedAddressPicker from './components/SavedAddressPicker'
import SectionCard from './components/SectionCard'
import { rememberPendingPayment } from './paymentReturn'
import { checkoutSchema, toOrderPayload } from './schemas'

// Single-page checkout (PRD §5.4).

function fieldFromApi(field) {
  if (!field) return null
  const map = {
    'shipping_address.recipient_name': 'recipient_name',
    'shipping_address.phone': 'ship_phone',
    'shipping_address.division': 'division',
    'shipping_address.district': 'district',
    'shipping_address.street': 'street',
    email: 'email',
    phone: 'phone',
    payment_method: 'payment_method',
    address_id: 'address_id',
  }
  return map[field] ?? null
}

export default function CheckoutPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const user = useAuthStore((s) => s.user)
  const isAuthed = Boolean(user)

  const cart = useCart()
  const addresses = useAddresses(isAuthed)
  const zones = useShippingZones()
  const placeOrder = usePlaceOrder()

  const [appliedCode, setAppliedCode] = useState('')
  const [couponError, setCouponError] = useState('')
  const [stockError, setStockError] = useState('')

  // One key per attempt, held across retries of that attempt (FR-CHK-7).
  const idempotencyKeyRef = useRef(null)
  // Set the instant an order exists, so the "empty cart" redirect below does
  // not fire while we are navigating to the confirmation page.
  const placedRef = useRef(false)
  const addressInitRef = useRef(false)

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    getValues,
    setError,
    formState: { errors, dirtyFields },
  } = useForm({
    resolver: zodResolver(checkoutSchema),
    defaultValues: {
      email: '',
      phone: '',
      address_mode: 'new',
      address_id: '',
      recipient_name: '',
      ship_phone: '',
      division: '',
      district: '',
      upazila: '',
      area: '',
      street: '',
      postcode: '',
      save_address: false,
      payment_method: 'cod',
      note: '',
    },
  })

  const addressMode = watch('address_mode')
  const addressId = watch('address_id')
  const division = watch('division')
  const contactPhone = watch('phone')
  const paymentMethod = watch('payment_method')

  const savedAddresses = addresses.data ?? []
  const selectedAddress = savedAddresses.find((a) => String(a.id) === String(addressId))

  // The district the quote is priced against: from the saved address when one
  // is chosen, otherwise from the form.
  const district =
    addressMode === 'saved' ? (selectedAddress?.district ?? '') : watch('district')

  const quoteQuery = useCheckoutQuote({
    items: cart.quoteItems,
    district: district || undefined,
    couponCode: appliedCode || undefined,
  })
  const quote = quoteQuery.data
  const quoteBusy = quoteQuery.isFetching || cart.isSettling

  // --- Prefill from the signed-in profile, once it has loaded. ---
  useEffect(() => {
    if (!user) return
    if (!getValues('email')) setValue('email', user.email ?? '')
    if (!getValues('phone')) setValue('phone', user.phone ?? '')
    if (!getValues('recipient_name')) setValue('recipient_name', user.full_name ?? '')
  }, [user, getValues, setValue])

  // --- Default to the saved default address (FR-CHK-4), once only. ---
  useEffect(() => {
    if (addressInitRef.current || !savedAddresses.length) return
    addressInitRef.current = true
    const preferred = savedAddresses.find((a) => a.is_default) ?? savedAddresses[0]
    setValue('address_mode', 'saved')
    setValue('address_id', String(preferred.id))
  }, [savedAddresses, setValue])

  // The courier calls the delivery number, which is usually the contact one.
  // Mirror it until the shopper edits it themselves.
  useEffect(() => {
    if (dirtyFields.ship_phone) return
    setValue('ship_phone', contactPhone ?? '')
  }, [contactPhone, dirtyFields.ship_phone, setValue])

  /*
   * Keep the selection on a method the server says is available. COD can fall
   * away mid-checkout -- add an item and the total crosses the cap, or the
   * district resolves to a zone that refuses it (FR-PAY-1, FR-SHP-5).
   */
  useEffect(() => {
    const methods = quote?.payment_methods
    if (!methods?.length) return
    const current = getValues('payment_method')
    if (methods.some((m) => m.code === current && m.available)) return
    const fallback = methods.find((m) => m.available)
    if (fallback) setValue('payment_method', fallback.code)
  }, [quote, getValues, setValue])

  const blockedLines = useMemo(
    () => (quote?.lines ?? []).filter((line) => !line.is_available),
    [quote],
  )

  const selectedMethod = quote?.payment_methods?.find((m) => m.code === paymentMethod)
  const canPlace =
    Boolean(quote?.can_place_order) &&
    Boolean(selectedMethod?.available) &&
    !quoteBusy &&
    !placeOrder.isPending &&
    !cart.isEmpty

  function blockedReason() {
    if (cart.isEmpty) return 'Your cart is empty.'
    if (!quote) return 'Waiting for the server to confirm your totals…'
    if (blockedLines.length)
      return `${blockedLines.map((l) => l.product_name).join(', ')} cannot be ordered right now. Adjust your cart to continue.`
    if (!district) return 'Choose a delivery district so we can calculate delivery.'
    if (quote.grand_total == null)
      return (
        quote.notices?.[0]?.message ??
        'We could not calculate delivery for this address.'
      )
    if (!selectedMethod?.available)
      return selectedMethod?.unavailable_reason ?? 'Choose an available payment method.'
    if (quoteBusy) return 'Updating your totals…'
    return null
  }

  function handlePlacementError(error) {
    const { code, message, field } = parseApiError(error)

    if (code === 'OUT_OF_STOCK') {
      // Name the offending line and re-quote, which marks it on the review
      // list too (FR-CHK acceptance criterion).
      setStockError(message)
      quoteQuery.refetch()
      return
    }
    if (field === 'coupon_code' || code.startsWith('COUPON_')) {
      setCouponError(message)
      return
    }
    const formField = fieldFromApi(field)
    if (formField) setError(formField, { message })
    else setError('root', { message })
  }

  const onSubmit = handleSubmit((values) => {
    if (placeOrder.isPending) return
    setStockError('')
    setCouponError('')

    if (!idempotencyKeyRef.current) idempotencyKeyRef.current = newIdempotencyKey()

    const payload = toOrderPayload(values, {
      items: cart.lines.map((line) => ({
        variant_id: line.variantId,
        quantity: line.quantity,
      })),
      couponCode: appliedCode,
      idempotencyKey: idempotencyKeyRef.current,
      isAuthenticated: isAuthed,
    })

    placeOrder.mutate(payload, {
      onSuccess: async (order) => {
        placedRef.current = true
        // This attempt is finished; a future order is a new attempt and gets
        // a new key.
        idempotencyKeyRef.current = null
        cart.clear()
        queryClient.invalidateQueries({ queryKey: cartKeys.cart() })

        if (order.payment_method === 'online') {
          try {
            const session = await initiatePayment(order.reference)
            if (session?.redirect_url) {
              // The handover is a full navigation to another origin, so
              // nothing held in memory survives it. Remember which order left
              // so the return screen can read its real status back
              // (features/checkout/paymentReturn.js).
              rememberPendingPayment(order.reference)
              window.location.assign(session.redirect_url)
              return
            }
          } catch {
            // The order exists and is pending with stock untouched
            // (FR-PAY-7). The confirmation page offers the retry.
          }
        }

        navigate(`/order/${order.reference}`, {
          replace: true,
          state: { justPlaced: true, email: order.email },
        })
      },
      onError: handlePlacementError,
    })
  })

  if (cart.isPending) return <PageSpinner label="Loading checkout" />
  if (cart.isEmpty && !placedRef.current) return <Navigate to="/cart" replace />

  const districtOptions = districtsFor(division)

  return (
    <div className="px-4 py-5">
      <h1 className="mb-4 text-xl font-semibold text-ink">Checkout</h1>

      {!isAuthed && (
        <p className="mb-4 rounded-card border border-line bg-white px-4 py-3 text-sm text-ink-muted">
          Checking out as a guest.{' '}
          <Link
            to="/login"
            state={{ from: '/checkout' }}
            className="font-medium text-action hover:underline"
          >
            Sign in
          </Link>{' '}
          to use a saved address and keep this order in your history — or just
          carry on below.
        </p>
      )}

      <form noValidate onSubmit={onSubmit}>
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
          <div className="flex flex-col gap-4">
            <SectionCard
              step={1}
              title="Contact"
              description="Where we send the order confirmation and the courier calls you."
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Input
                  label="Email"
                  type="email"
                  autoComplete="email"
                  required
                  error={errors.email?.message}
                  {...register('email')}
                />
                <Input
                  label="Mobile number"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="01XXXXXXXXX"
                  required
                  error={errors.phone?.message}
                  {...register('phone')}
                />
              </div>
            </SectionCard>

            <SectionCard
              step={2}
              title="Shipping address"
              description="Delivery is priced from the district you choose."
            >
              {isAuthed && savedAddresses.length > 0 && (
                <div className="mb-4">
                  <SavedAddressPicker
                    addresses={savedAddresses}
                    value={addressMode === 'saved' ? String(addressId ?? '') : 'new'}
                    error={errors.address_id?.message}
                    onSelect={(value) => {
                      if (value === 'new') {
                        setValue('address_mode', 'new')
                        setValue('address_id', '')
                      } else {
                        setValue('address_mode', 'saved')
                        setValue('address_id', value)
                      }
                    }}
                  />
                </div>
              )}

              {addressMode === 'new' && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Input
                    label="Recipient name"
                    autoComplete="name"
                    required
                    error={errors.recipient_name?.message}
                    {...register('recipient_name')}
                  />
                  <Input
                    label="Delivery phone"
                    type="tel"
                    inputMode="tel"
                    placeholder="01XXXXXXXXX"
                    required
                    hint="The courier will call this number."
                    error={errors.ship_phone?.message}
                    {...register('ship_phone')}
                  />
                  <Select
                    label="Division"
                    required
                    placeholder="Select a division"
                    options={DIVISION_NAMES}
                    error={errors.division?.message}
                    {...register('division', {
                      onChange: () => setValue('district', ''),
                    })}
                  />
                  <Select
                    label="District"
                    required
                    placeholder={division ? 'Select a district' : 'Choose a division first'}
                    options={districtOptions}
                    disabled={!division}
                    error={errors.district?.message}
                    {...register('district')}
                  />
                  <Input
                    label="Upazila / Thana"
                    error={errors.upazila?.message}
                    {...register('upazila')}
                  />
                  <Input label="Area" error={errors.area?.message} {...register('area')} />
                  <Input
                    label="Street address"
                    containerClassName="sm:col-span-2"
                    autoComplete="street-address"
                    required
                    placeholder="House, road, landmark"
                    error={errors.street?.message}
                    {...register('street')}
                  />
                  <Input
                    label="Postcode"
                    inputMode="numeric"
                    error={errors.postcode?.message}
                    {...register('postcode')}
                  />

                  {isAuthed && (
                    <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink sm:col-span-2">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-action"
                        {...register('save_address')}
                      />
                      Save this address to my address book
                    </label>
                  )}
                </div>
              )}
            </SectionCard>

            <SectionCard
              step={3}
              title="Delivery"
              description="Resolved from your district — there is one delivery option per zone."
            >
              {quote?.zone ? (
                <div className="flex flex-wrap items-baseline justify-between gap-2 rounded-card border border-line bg-page px-3 py-3">
                  <div>
                    <p className="text-sm font-medium text-ink">{quote.zone.name}</p>
                    {quote.zone.free_shipping_threshold && (
                      <p className="text-xs text-ink-muted">
                        Free above {formatMoney(quote.zone.free_shipping_threshold)}.
                      </p>
                    )}
                  </div>
                  <p className="text-sm font-semibold text-ink tabular-nums">
                    {quote.shipping_total != null && Number(quote.shipping_total) === 0
                      ? 'Free'
                      : formatMoney(quote.shipping_total)}
                  </p>
                </div>
              ) : (
                <div className="rounded-card bg-page px-3 py-3 text-sm text-ink-muted">
                  {district
                    ? (quote?.notices?.[0]?.message ??
                      'We could not find a delivery zone for that district yet.')
                    : 'Choose a district above and the delivery charge appears here.'}
                  {zones.data?.length > 0 && (
                    <ul className="mt-2 flex flex-col gap-1 text-xs">
                      {zones.data.map((zone) => (
                        <li key={zone.id} className="flex justify-between gap-3">
                          <span>{zone.name}</span>
                          <span className="tabular-nums">{formatMoney(zone.flat_rate)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </SectionCard>

            <SectionCard step={4} title="Payment">
              <PaymentMethodPicker
                methods={quote?.payment_methods}
                value={paymentMethod}
                isPending={quoteQuery.isPending}
                error={errors.payment_method?.message}
                onChange={(code) => setValue('payment_method', code)}
              />
              <p className="mt-3 text-[11px] text-ink-muted">
                Card and wallet details are entered on SSLCommerz's own page —
                they never reach this site.
              </p>
            </SectionCard>
          </div>

          {/* --- Review & pay --------------------------------------------- */}
          <aside className="flex flex-col gap-4 lg:sticky lg:top-20">
            <SectionCard step={5} title="Review & pay">
              <ReviewLines lines={quote?.lines} isBusy={quoteBusy} />

              <div className="mt-4 border-t border-line pt-4">
                <CouponField
                  appliedCode={appliedCode}
                  coupon={quote?.coupon}
                  errorMessage={quote?.coupon_error?.message || couponError}
                  isBusy={quoteBusy || placeOrder.isPending}
                  onApply={(code) => {
                    setCouponError('')
                    setAppliedCode(code)
                  }}
                  onRemove={() => {
                    setCouponError('')
                    setAppliedCode('')
                  }}
                />
              </div>

              <div className="mt-4 border-t border-line pt-4">
                <Textarea
                  label="Order note (optional)"
                  rows={2}
                  placeholder="Delivery instructions, a landmark, anything the courier should know."
                  error={errors.note?.message}
                  {...register('note')}
                />
              </div>

              <div className="mt-4 border-t border-line pt-3">
                <OrderTotals
                  quote={quote}
                  isFetching={quoteQuery.isFetching}
                  isSettling={cart.isSettling}
                  isError={quoteQuery.isError}
                  placeholderSubtotal={cart.placeholderSubtotal}
                  shippingHint="Enter your district"
                />
              </div>

              {stockError && (
                <p
                  role="alert"
                  className="mt-3 rounded-card bg-danger/10 px-3 py-2 text-sm font-medium text-danger"
                >
                  {stockError}
                </p>
              )}
              {errors.root && (
                <p
                  role="alert"
                  className="mt-3 rounded-card bg-danger/10 px-3 py-2 text-sm font-medium text-danger"
                >
                  {errors.root.message}
                </p>
              )}

              <Button
                type="submit"
                size="lg"
                fullWidth
                className="mt-4"
                loading={placeOrder.isPending}
                disabled={!canPlace}
              >
                {paymentMethod === 'online' ? 'Pay now' : 'Place order'}
              </Button>

              {!canPlace && !placeOrder.isPending && (
                <p className="mt-2 text-xs text-ink-muted" role="status">
                  {blockedReason()}
                </p>
              )}

              <p className="mt-3 text-[11px] text-ink-muted">
                Placing this order confirms the totals above, which were
                calculated by the server. Stock is only reserved once the order
                is confirmed.
              </p>

              <Link
                to="/cart"
                className="mt-2 flex min-h-[44px] items-center justify-center text-sm font-medium text-action hover:underline"
              >
                Back to cart
              </Link>
            </SectionCard>
          </aside>
        </div>
      </form>
    </div>
  )
}
