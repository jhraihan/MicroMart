import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'

import { Button, Input, Spinner, Textarea } from '@/components/ui'
import { formatMoney } from '@/lib/money'

import { useShippingZones, useStoreSettings, useUpdateStoreSettings } from './api'
import {
  AdminError,
  AdminPageHeader,
  Callout,
  FormAlert,
  SuccessNote,
} from './components/AdminUI'
import { settingsSchema } from './schemas'
import { applyServerError, pathResolver } from './serverErrors'

const SETTINGS_FIELDS = [
  'store_name',
  'support_email',
  'support_phone',
  'tax_rate',
  'tax_inclusive_pricing',
  'cod_enabled',
  'cod_max_order_value',
  'low_stock_digest_recipients',
]

const resolveSettingsField = pathResolver(SETTINGS_FIELDS)

function defaultsFor(settings) {
  return {
    store_name: settings?.store_name ?? '',
    support_email: settings?.support_email ?? '',
    support_phone: settings?.support_phone ?? '',
    tax_rate: settings?.tax_rate ?? '0.00',
    tax_inclusive_pricing: Boolean(settings?.tax_inclusive_pricing),
    cod_enabled: settings?.cod_enabled ?? true,
    cod_max_order_value: settings?.cod_max_order_value ?? '',
    low_stock_digest_recipients: (settings?.low_stock_digest_recipients ?? []).join('\n'),
  }
}

/**
 * Store settings — one row, and it is a singleton by construction
 * (`StoreSettings.save()` pins pk=1 and `delete()` raises).
 *
 * The screen's job beyond the form is to be honest about reach: these values
 * are read at checkout and **snapshotted onto the order**. `tax_rate_applied`
 * is a column on the order, not a lookup back through this row, so raising
 * VAT tomorrow cannot re-price an order placed today. That is a guarantee the
 * backend holds with a test; saying so here is what stops an owner from
 * believing they must not correct a wrong rate.
 */
export default function AdminSettingsPage() {
  const settings = useStoreSettings()
  const zones = useShippingZones()
  const update = useUpdateStoreSettings()

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isDirty },
  } = useForm({ resolver: zodResolver(settingsSchema), defaultValues: defaultsFor(null) })

  const loadedAt = settings.data?.updated_at
  useEffect(() => {
    if (settings.data) reset(defaultsFor(settings.data))
  }, [loadedAt, settings.data, reset])

  const onSubmit = handleSubmit((values) => {
    update.mutate(
      {
        store_name: values.store_name.trim(),
        support_email: values.support_email.trim(),
        support_phone: values.support_phone.trim(),
        tax_rate: values.tax_rate.trim(),
        tax_inclusive_pricing: values.tax_inclusive_pricing,
        cod_enabled: values.cod_enabled,
        // Null disables the cap -- an empty box means "no ceiling", not zero.
        cod_max_order_value: values.cod_max_order_value.trim() || null,
        low_stock_digest_recipients: values.low_stock_digest_recipients
          .split(/[\n,]/)
          .map((entry) => entry.trim())
          .filter(Boolean),
      },
      {
        onSuccess: (saved) => reset(defaultsFor(saved)),
        onError: (error) => applyServerError(error, setError, resolveSettingsField),
      },
    )
  })

  if (settings.isError) {
    return <AdminError error={settings.error} onRetry={() => settings.refetch()} />
  }
  if (settings.isPending) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size="lg" label="Loading store settings" />
      </div>
    )
  }

  return (
    <div className="pb-10">
      <AdminPageHeader
        title="Store settings"
        description="The store's own details, the VAT rate and the Cash on Delivery ceiling. There is exactly one of this record."
      />

      <Callout tone="warning" className="mb-5" title="These apply to new orders only">
        Every order copies the tax rate, the delivery charge and the discount
        it was actually given at the moment it was placed. Changing anything
        here affects the <strong>next</strong> checkout and cannot reach an
        order that already exists — a receipt printed last week will still show
        the rate that was live last week, and nothing on this page can rewrite
        it.
      </Callout>

      <form
        noValidate
        onSubmit={onSubmit}
        className="flex flex-col gap-6 rounded-card border border-line bg-white p-4"
      >
        <FormAlert message={errors.root?.message} />

        <section aria-labelledby="store-heading" className="flex flex-col gap-4">
          <h2 id="store-heading" className="text-base font-semibold text-ink">
            Store details
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input
              label="Store name"
              required
              error={errors.store_name?.message}
              {...register('store_name')}
            />
            <Input
              label="Support email"
              type="email"
              error={errors.support_email?.message}
              hint="Printed on order confirmations."
              {...register('support_email')}
            />
            <Input
              label="Support phone"
              type="tel"
              error={errors.support_phone?.message}
              {...register('support_phone')}
            />
          </div>
        </section>

        <section aria-labelledby="tax-heading" className="flex flex-col gap-4 border-t border-line pt-5">
          <h2 id="tax-heading" className="text-base font-semibold text-ink">
            VAT
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input
              label="VAT rate (%)"
              required
              inputMode="decimal"
              error={errors.tax_rate?.message}
              hint="Between 0 and 100. Snapshotted onto every order as tax_rate_applied."
              {...register('tax_rate')}
            />
          </div>
          <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
            <input type="checkbox" className="h-4 w-4 accent-action" {...register('tax_inclusive_pricing')} />
            Catalogue prices already include VAT
          </label>
        </section>

        <section aria-labelledby="cod-heading" className="flex flex-col gap-4 border-t border-line pt-5">
          <h2 id="cod-heading" className="text-base font-semibold text-ink">
            Cash on Delivery
          </h2>
          <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
            <input type="checkbox" className="h-4 w-4 accent-action" {...register('cod_enabled')} />
            Offer Cash on Delivery at checkout
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input
              label="Maximum order value for COD (৳)"
              inputMode="decimal"
              error={errors.cod_max_order_value?.message}
              hint="Orders above this must be paid online. Leave blank for no ceiling."
              {...register('cod_max_order_value')}
            />
          </div>
        </section>

        <section aria-labelledby="digest-heading" className="flex flex-col gap-4 border-t border-line pt-5">
          <h2 id="digest-heading" className="text-base font-semibold text-ink">
            Low-stock digest
          </h2>
          <Textarea
            label="Recipients"
            rows={3}
            error={errors.low_stock_digest_recipients?.message}
            hint="One email address per line. The digest is sent by a scheduled command and lists everything at or below its threshold."
            {...register('low_stock_digest_recipients')}
          />
        </section>

        <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line pt-4">
          {update.isSuccess && !isDirty && <SuccessNote message="Settings saved." />}
          <Button type="submit" loading={update.isPending}>
            Save settings
          </Button>
        </div>
      </form>

      <section aria-labelledby="shipping-heading" className="mt-6 rounded-card border border-line bg-white p-4">
        <h2 id="shipping-heading" className="text-base font-semibold text-ink">
          Free-shipping thresholds
        </h2>
        <p className="mt-1 max-w-prose text-sm text-ink-muted">
          The free-shipping threshold is not a store-wide setting: it belongs to
          each delivery zone, because &ldquo;free over ৳5,000&rdquo; is a
          different promise inside Dhaka than it is for a courier run to Sylhet.
          The live values are below. Editing them needs a zone endpoint that PRD
          §7.3 does not define yet, so they are read-only here — change them in
          Django Admin under Shipping zones until that endpoint exists.
        </p>

        {zones.isPending ? (
          <div className="py-4">
            <Spinner label="Loading shipping zones" />
          </div>
        ) : zones.isError ? (
          <AdminError error={zones.error} title="Could not load shipping zones" />
        ) : (
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            {(zones.data ?? []).map((zone) => (
              <div key={zone.id} className="rounded-card border border-line p-3">
                <dt className="text-sm font-medium text-ink">{zone.name}</dt>
                <dd className="mt-1 text-sm text-ink-muted">
                  Flat rate {formatMoney(zone.flat_rate)}
                  {zone.per_kg_rate && zone.per_kg_rate !== '0.00'
                    ? ` + ${formatMoney(zone.per_kg_rate)}/kg above ${zone.base_weight_grams}g`
                    : ''}
                </dd>
                <dd className="mt-1 text-sm">
                  {zone.free_shipping_threshold ? (
                    <>Free over {formatMoney(zone.free_shipping_threshold)}</>
                  ) : (
                    <span className="text-ink-muted">No free-shipping threshold</span>
                  )}
                </dd>
                <dd className="mt-1 text-xs text-ink-muted">
                  Cash on Delivery {zone.cod_allowed ? 'allowed' : 'not allowed'} in this zone
                </dd>
              </div>
            ))}
            {(zones.data ?? []).length === 0 && (
              <p className="text-sm text-ink-muted">No active shipping zones are configured.</p>
            )}
          </dl>
        )}
      </section>
    </div>
  )
}
