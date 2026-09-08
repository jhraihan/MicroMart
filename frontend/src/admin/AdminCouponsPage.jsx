import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Controller, useForm } from 'react-hook-form'

import {
  Badge,
  Button,
  EmptyRow,
  Input,
  Modal,
  Select,
  Spinner,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from '@/components/ui'
import { parseApiError } from '@/lib/api'
import { formatMoney } from '@/lib/money'
import useDebouncedValue from '@/lib/useDebouncedValue'

import { useAdminCoupons, useRetireCoupon, useSaveCoupon } from './api'
import {
  AdminError,
  AdminPageHeader,
  AdminPager,
  Callout,
  FormAlert,
  LoadingRowNote,
} from './components/AdminUI'
import ScopePicker from './components/ScopePicker'
import { couponSchema } from './schemas'
import { applyServerError, pathResolver } from './serverErrors'

const PAGE_SIZE = 24

const STATUS_TONE = {
  active: 'success',
  scheduled: 'action',
  expired: 'neutral',
  inactive: 'neutral',
}

const STATUS_FILTERS = [
  { value: 'active', label: 'Running now' },
  { value: 'scheduled', label: 'Starts later' },
  { value: 'expired', label: 'Finished' },
  { value: 'inactive', label: 'Switched off' },
]

const COUPON_FIELDS = [
  'code',
  'discount_type',
  'value',
  'max_discount',
  'min_order_value',
  'valid_from',
  'valid_until',
  'usage_limit',
  'per_user_limit',
  'scope_type',
  'scope_ids',
  'is_active',
]

const resolveCouponField = pathResolver(COUPON_FIELDS)

/*
 * Datetime round-tripping.
 *
 * The server stores aware datetimes and renders them in the store's own
 * timezone (Asia/Dhaka), e.g. "2026-08-22T09:00:00+06:00". Taking the first
 * 16 characters gives exactly what a `datetime-local` input wants and exactly
 * what the admin typed -- no re-interpretation through the browser's clock,
 * which would shift a window by six hours for anyone travelling. Sending the
 * naive string back lets DRF re-read it in the same store timezone, so the
 * round trip is lossless.
 */
function toLocalInput(value) {
  return value ? String(value).slice(0, 16) : ''
}

function formatWindow(value) {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function defaultsFor(coupon) {
  return {
    code: coupon?.code ?? '',
    discount_type: coupon?.discount_type ?? 'percent',
    value: coupon?.value ?? '',
    max_discount: coupon?.max_discount ?? '',
    min_order_value: coupon?.min_order_value ?? '',
    valid_from: toLocalInput(coupon?.valid_from),
    valid_until: toLocalInput(coupon?.valid_until),
    usage_limit:
      coupon?.usage_limit === null || coupon?.usage_limit === undefined
        ? ''
        : String(coupon.usage_limit),
    per_user_limit: String(coupon?.per_user_limit ?? 1),
    scope_type: coupon?.scope_type ?? 'all',
    scope_ids: (coupon?.scope_ids ?? []).map(String),
    is_active: coupon ? Boolean(coupon.is_active) : true,
  }
}

function CouponDialog({ coupon, onClose }) {
  const save = useSaveCoupon()
  const isEdit = Boolean(coupon)
  const isRedeemed = (coupon?.redemption_count ?? 0) > 0

  const {
    register,
    control,
    handleSubmit,
    watch,
    setError,
    formState: { errors },
  } = useForm({ resolver: zodResolver(couponSchema), defaultValues: defaultsFor(coupon) })

  const discountType = watch('discount_type')
  const scopeType = watch('scope_type')

  const onSubmit = handleSubmit((values) => {
    const payload = {
      code: values.code.trim(),
      discount_type: values.discount_type,
      value: values.value.trim(),
      max_discount:
        values.discount_type === 'percent' && values.max_discount.trim()
          ? values.max_discount.trim()
          : null,
      min_order_value: values.min_order_value.trim() || '0',
      valid_from: values.valid_from,
      valid_until: values.valid_until,
      usage_limit: values.usage_limit.trim() ? Number(values.usage_limit) : null,
      per_user_limit: Number(values.per_user_limit),
      scope_type: values.scope_type,
      scope_ids: values.scope_type === 'all' ? [] : values.scope_ids.map(Number),
      is_active: values.is_active,
    }

    save.mutate(isEdit ? { id: coupon.id, ...payload } : payload, {
      onSuccess: onClose,
      onError: (error) => applyServerError(error, setError, resolveCouponField),
    })
  })

  return (
    <Modal open onClose={onClose} size="lg" title={isEdit ? `Edit ${coupon.code}` : 'New coupon'}>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        <FormAlert message={errors.root?.message} />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Code"
            required
            readOnly={isRedeemed}
            error={errors.code?.message}
            hint={
              isRedeemed
                ? 'Fixed: this coupon has been redeemed, and orders reference it by code. Switch it off and create a new one instead.'
                : 'Stored in upper case; shoppers can type it in any case.'
            }
            {...register('code')}
          />
          <Select
            label="Discount type"
            required
            error={errors.discount_type?.message}
            options={[
              { value: 'percent', label: 'Percentage off' },
              { value: 'fixed', label: 'Fixed amount off (৳)' },
            ]}
            {...register('discount_type')}
          />
          <Input
            label={discountType === 'percent' ? 'Percentage off (%)' : 'Amount off (৳)'}
            required
            inputMode="decimal"
            error={errors.value?.message}
            {...register('value')}
          />
          <Input
            label="Maximum discount (৳)"
            inputMode="decimal"
            disabled={discountType !== 'percent'}
            error={errors.max_discount?.message}
            hint={
              discountType === 'percent'
                ? 'Caps what a percentage can be worth. Blank means no cap.'
                : 'Only applies to a percentage coupon.'
            }
            {...register('max_discount')}
          />
          <Input
            label="Minimum order value (৳)"
            inputMode="decimal"
            error={errors.min_order_value?.message}
            hint="The basket must reach this before the code applies. Blank means no minimum."
            {...register('min_order_value')}
          />
          <div />
          <Input
            label="Valid from"
            type="datetime-local"
            required
            error={errors.valid_from?.message}
            hint="Store time (Asia/Dhaka)."
            {...register('valid_from')}
          />
          <Input
            label="Valid until"
            type="datetime-local"
            required
            error={errors.valid_until?.message}
            {...register('valid_until')}
          />
          <Input
            label="Total usage cap"
            inputMode="numeric"
            error={errors.usage_limit?.message}
            hint="Across all customers. Blank means unlimited."
            {...register('usage_limit')}
          />
          <Input
            label="Per-customer cap"
            required
            inputMode="numeric"
            error={errors.per_user_limit?.message}
            hint="How many times one account may use it. Minimum 1."
            {...register('per_user_limit')}
          />
        </div>

        <fieldset className="flex flex-col gap-3 border-t border-line pt-4">
          <legend className="text-sm font-medium text-ink">Applies to</legend>
          <Select
            label="Scope"
            error={errors.scope_type?.message}
            options={[
              { value: 'all', label: 'The whole catalogue' },
              { value: 'category', label: 'Selected categories' },
              { value: 'product', label: 'Selected products' },
            ]}
            {...register('scope_type')}
          />
          <Controller
            control={control}
            name="scope_ids"
            render={({ field }) => (
              <ScopePicker
                scopeType={scopeType}
                value={field.value}
                onChange={field.onChange}
                error={errors.scope_ids?.message}
              />
            )}
          />
        </fieldset>

        <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
          <input type="checkbox" className="h-4 w-4 accent-action" {...register('is_active')} />
          Switched on
        </label>

        <Callout tone="info">
          Only one coupon can apply to an order — they never stack. Editing
          what a coupon is worth changes what it does next and never touches an
          order already placed: the discount is copied onto the order at
          checkout.
        </Callout>

        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending}>
            {isEdit ? 'Save coupon' : 'Create coupon'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

/** Coupon CRUD with the redemption count per coupon (US-A5). */
export default function AdminCouponsPage() {
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [dialog, setDialog] = useState(null)

  const debounced = useDebouncedValue(search.trim(), 300)
  const coupons = useAdminCoupons({ status, search: debounced, page, page_size: PAGE_SIZE })
  const retire = useRetireCoupon()
  const reactivate = useSaveCoupon()

  const rows = coupons.data?.results ?? []

  return (
    <div>
      <AdminPageHeader
        title="Coupons"
        description="Percentage or fixed-amount discounts, with a validity window, usage caps and a scope. Redemption counts are read from the redemption rows themselves, never from a stored counter."
        actions={
          <Button onClick={() => setDialog({ coupon: null })}>New coupon</Button>
        }
      />

      <form
        role="search"
        aria-label="Filter coupons"
        onSubmit={(event) => event.preventDefault()}
        className="mb-4 grid gap-3 rounded-card border border-line bg-white p-4 sm:grid-cols-2"
      >
        <Input
          label="Search by code"
          type="search"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
        />
        <Select
          label="Status"
          placeholder="Every coupon"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value)
            setPage(1)
          }}
          options={STATUS_FILTERS}
        />
      </form>

      {(retire.isError || reactivate.isError) && (
        <FormAlert message={parseApiError(retire.error ?? reactivate.error).message} />
      )}

      {coupons.isError ? (
        <AdminError error={coupons.error} onRetry={() => coupons.refetch()} />
      ) : coupons.isPending ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" label="Loading coupons" />
        </div>
      ) : (
        <>
          <LoadingRowNote show={coupons.isFetching} label="Updating results" />
          <Table caption="Coupons with their discount, window, caps and redemption count">
            <THead>
              <TR>
                <TH>Code</TH>
                <TH>Discount</TH>
                <TH align="right">Minimum order</TH>
                <TH>Valid</TH>
                <TH>Scope</TH>
                <TH align="right">Redeemed</TH>
                <TH align="center">Status</TH>
                <TH align="right">Actions</TH>
              </TR>
            </THead>
            <TBody>
              {rows.length === 0 && <EmptyRow colSpan={8}>No coupons match this filter.</EmptyRow>}
              {rows.map((coupon) => (
                <TR key={coupon.id}>
                  <TD>
                    <span className="font-mono font-medium text-ink">{coupon.code}</span>
                  </TD>
                  <TD>
                    {coupon.discount_type === 'percent'
                      ? `${coupon.value}%`
                      : formatMoney(coupon.value)}
                    {coupon.discount_type === 'percent' && coupon.max_discount && (
                      <div className="text-xs text-ink-muted">
                        capped at {formatMoney(coupon.max_discount)}
                      </div>
                    )}
                  </TD>
                  <TD align="right">
                    {coupon.min_order_value && coupon.min_order_value !== '0.00'
                      ? formatMoney(coupon.min_order_value)
                      : '—'}
                  </TD>
                  <TD>
                    <div className="whitespace-nowrap text-xs">
                      {formatWindow(coupon.valid_from)} → {formatWindow(coupon.valid_until)}
                    </div>
                  </TD>
                  <TD className="text-xs">
                    {coupon.scope_type === 'all'
                      ? 'Whole catalogue'
                      : `${coupon.scope_ids?.length ?? 0} ${coupon.scope_type === 'category' ? 'categories' : 'products'}`}
                  </TD>
                  <TD align="right">
                    <div className="font-medium">{coupon.redemption_count}</div>
                    <div className="text-xs text-ink-muted">
                      {coupon.remaining_uses === null
                        ? 'unlimited'
                        : `${coupon.remaining_uses} left`}
                    </div>
                    <div className="text-xs text-ink-muted">
                      {formatMoney(coupon.redeemed_value)} given
                    </div>
                  </TD>
                  <TD align="center">
                    <Badge tone={STATUS_TONE[coupon.status] ?? 'neutral'} size="sm">
                      {coupon.status}
                    </Badge>
                  </TD>
                  <TD align="right">
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => setDialog({ coupon })}>
                        Edit
                      </Button>
                      {coupon.is_active ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={retire.isPending && retire.variables === coupon.id}
                          onClick={() => retire.mutate(coupon.id)}
                        >
                          Retire
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={
                            reactivate.isPending && reactivate.variables?.id === coupon.id
                          }
                          onClick={() =>
                            reactivate.mutate({ id: coupon.id, is_active: true })
                          }
                        >
                          Switch on
                        </Button>
                      )}
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>

          <AdminPager
            page={page}
            count={coupons.data?.count ?? 0}
            pageSize={PAGE_SIZE}
            onChange={setPage}
          />
        </>
      )}

      <Callout tone="info" className="mt-5">
        Retiring a coupon switches it off; it is never deleted. Its redemption
        rows are the record of a promotion that actually ran, and the orders
        that used it still report the code and the discount they were given.
      </Callout>

      {dialog && <CouponDialog coupon={dialog.coupon} onClose={() => setDialog(null)} />}
    </div>
  )
}
