import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'

import {
  Badge,
  Button,
  EmptyRow,
  Input,
  Modal,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from '@/components/ui'
import { parseApiError } from '@/lib/api'
import { formatMoney } from '@/lib/money'

import { useCreateVariant, useSetVariantActive, useUpdateVariant } from '../api'
import { newVariantSchema, variantFieldsSchema } from '../schemas'
import { variantPayload } from '../variantPayload'
import { applyServerError, pathResolver } from '../serverErrors'
import { Callout, FormAlert } from './AdminUI'

// Variants on an existing product.

const EDITABLE_FIELDS = [
  'sku',
  'option_label',
  'price',
  'compare_at_price',
  'low_stock_threshold',
  'weight_grams',
  'is_active',
]

const resolveVariantField = pathResolver([...EDITABLE_FIELDS, 'stock', 'variant_id', 'product_id'])

function blankVariant() {
  return {
    sku: '',
    option_label: '',
    price: '',
    compare_at_price: '',
    stock: '',
    low_stock_threshold: '5',
    weight_grams: '',
    is_active: true,
  }
}

function toForm(variant) {
  return {
    sku: variant.sku ?? '',
    option_label: variant.option_label ?? '',
    price: variant.price ?? '',
    compare_at_price: variant.compare_at_price ?? '',
    low_stock_threshold: String(variant.low_stock_threshold ?? ''),
    weight_grams: String(variant.weight_grams ?? ''),
    is_active: Boolean(variant.is_active),
  }
}

function VariantDialog({ mode, productId, variant, onClose }) {
  const isCreate = mode === 'create'
  const create = useCreateVariant(productId)
  const update = useUpdateVariant(productId)
  const mutation = isCreate ? create : update

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(isCreate ? newVariantSchema : variantFieldsSchema),
    defaultValues: isCreate ? blankVariant() : toForm(variant),
  })

  const onSubmit = handleSubmit((values) => {
    const payload = variantPayload(values, { withStock: isCreate })
    mutation.mutate(isCreate ? payload : { id: variant.id, ...payload }, {
      onSuccess: onClose,
      onError: (error) => applyServerError(error, setError, resolveVariantField),
    })
  })

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={isCreate ? 'Add a variant' : `Edit ${variant.sku}`}
    >
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        <FormAlert message={errors.root?.message} />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="SKU"
            required
            error={errors.sku?.message}
            hint="Unique across the whole catalogue."
            {...register('sku')}
          />
          <Input
            label="Option label"
            error={errors.option_label?.message}
            hint="e.g. 8GB / 512GB. Leave blank if this product has no options."
            {...register('option_label')}
          />
          <Input
            label="Price (৳)"
            required
            inputMode="decimal"
            error={errors.price?.message}
            {...register('price')}
          />
          <Input
            label="Compare-at price (৳)"
            inputMode="decimal"
            error={errors.compare_at_price?.message}
            hint="The struck-through price. Leave blank for no discount badge."
            {...register('compare_at_price')}
          />
          <Input
            label="Low-stock threshold"
            inputMode="numeric"
            error={errors.low_stock_threshold?.message}
            hint="At or below this, the variant shows on the reorder list."
            {...register('low_stock_threshold')}
          />
          <Input
            label="Weight (grams)"
            inputMode="numeric"
            error={errors.weight_grams?.message}
            hint="Used to price delivery above the zone's base weight."
            {...register('weight_grams')}
          />
        </div>

        {isCreate ? (
          <div className="grid gap-2">
            <Input
              label="Opening stock"
              inputMode="numeric"
              error={errors.stock?.message}
              containerClassName="sm:max-w-[16rem]"
              {...register('stock')}
            />
            <Callout tone="info">
              This is the only place a stock number can be typed onto a
              variant. It is recorded as an <strong>initial</strong> movement in
              the inventory ledger, so the variant&rsquo;s stock reconciles to
              its movement history from day one. Every change after this goes
              through Inventory, with a reason.
            </Callout>
          </div>
        ) : (
          <Callout tone="warning" title="Stock is not edited here">
            <p>
              {variant.sku} currently holds <strong>{variant.stock}</strong> units.
              Stock only moves through an adjustment that records
              <em> how many</em> and <em>why</em>, so a count can always be
              reconciled against its ledger — a field on this form would let a
              number change with no explanation attached.
            </p>
            <Link
              to={`/admin/inventory?q=${encodeURIComponent(variant.sku)}`}
              className="mt-2 inline-flex min-h-[44px] items-center font-medium text-action hover:underline"
            >
              Adjust stock for {variant.sku}
            </Link>
          </Callout>
        )}

        <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
          <input type="checkbox" className="h-4 w-4 accent-action" {...register('is_active')} />
          Active — offered for sale on the storefront
        </label>

        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={mutation.isPending}>
            {isCreate ? 'Add variant' : 'Save variant'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

export default function VariantManager({ product, dialog, onOpenDialog, onCloseDialog }) {
  const setActive = useSetVariantActive(product.id)
  const variants = product.variants ?? []

  return (
    <section aria-labelledby="variants-heading" className="rounded-card border border-line bg-white p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="variants-heading" className="text-base font-semibold text-ink">
            Variants
          </h2>
          <p className="mt-1 max-w-prose text-sm text-ink-muted">
            Price and stock live here, never on the product. A product with no
            options still has exactly one variant, and its last active variant
            cannot be deactivated.
          </p>
        </div>
        <Button size="sm" onClick={() => onOpenDialog({ mode: 'create' })}>
          Add variant
        </Button>
      </div>

      <FormAlert message={setActive.isError ? parseApiError(setActive.error).message : null} />

      <Table caption={`Variants of ${product.name}`}>
        <THead>
          <TR>
            <TH>SKU</TH>
            <TH>Option</TH>
            <TH align="right">Price</TH>
            <TH align="right">Stock</TH>
            <TH align="center">Status</TH>
            <TH align="right">Actions</TH>
          </TR>
        </THead>
        <TBody>
          {variants.length === 0 && <EmptyRow colSpan={6}>No variants yet.</EmptyRow>}
          {variants.map((variant) => (
            <TR key={variant.id}>
              <TD>
                <span className="font-medium text-ink">{variant.sku}</span>
              </TD>
              <TD>{variant.option_label || <span className="text-ink-muted">—</span>}</TD>
              <TD align="right">
                <div>{formatMoney(variant.price)}</div>
                {variant.compare_at_price && (
                  <div className="text-xs text-ink-muted line-through">
                    {formatMoney(variant.compare_at_price)}
                  </div>
                )}
              </TD>
              <TD align="right">
                <span className={variant.is_low_stock ? 'font-semibold text-warning' : ''}>
                  {variant.stock}
                </span>
                <div className="text-xs">
                  <Link
                    to={`/admin/inventory?q=${encodeURIComponent(variant.sku)}`}
                    className="inline-flex min-h-[44px] items-center text-action hover:underline"
                  >
                    Adjust
                  </Link>
                </div>
              </TD>
              <TD align="center">
                <Badge tone={variant.is_active ? 'success' : 'neutral'} size="sm">
                  {variant.is_active ? 'Active' : 'Inactive'}
                </Badge>
              </TD>
              <TD align="right">
                <div className="flex justify-end gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onOpenDialog({ mode: 'edit', variant })}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={setActive.isPending && setActive.variables?.id === variant.id}
                    onClick={() =>
                      setActive.mutate({ id: variant.id, isActive: !variant.is_active })
                    }
                  >
                    {variant.is_active ? 'Deactivate' : 'Activate'}
                  </Button>
                </div>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>

      {dialog && (
        <VariantDialog
          mode={dialog.mode}
          productId={product.id}
          variant={dialog.variant}
          onClose={onCloseDialog}
        />
      )}
    </section>
  )
}
