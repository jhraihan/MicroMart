import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useState } from 'react'
import { useFieldArray, useForm } from 'react-hook-form'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'

import { Badge, Button, Input, Select, Spinner, Textarea } from '@/components/ui'
import { formatMoney } from '@/lib/money'

import {
  useAdminBrands,
  useAdminCategories,
  useAdminProduct,
  useCreateProduct,
  useUpdateProduct,
} from './api'
import {
  AdminError,
  AdminPageHeader,
  Callout,
  FormAlert,
  SuccessNote,
} from './components/AdminUI'
import ImageManager from './components/ImageManager'
import VariantManager from './components/VariantManager'
import { productCreateSchema, productEditSchema } from './schemas'
import { applyServerError, resolveVariantPath } from './serverErrors'
import { variantPayload } from './variantPayload'

// The US-A2 product form.

const PRODUCT_FIELDS = [
  'name',
  'slug',
  'description',
  'category_id',
  'brand_id',
  'warranty_months',
  'is_active',
  'specs',
  'variants',
]

// Names the service uses for a failure inside the nested variants list.
const VARIANT_FIELDS = [
  'sku',
  'option_label',
  'price',
  'compare_at_price',
  'stock',
  'low_stock_threshold',
  'weight_grams',
]

function blankVariantRow() {
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

function emptySpecRow() {
  return { key: '', value: '' }
}

function productDefaults(product) {
  return {
    name: product?.name ?? '',
    slug: product?.slug ?? '',
    description: product?.description ?? '',
    category_id: product?.category?.id ? String(product.category.id) : '',
    brand_id: product?.brand?.id ? String(product.brand.id) : '',
    warranty_months:
      product?.warranty_months === null || product?.warranty_months === undefined
        ? ''
        : String(product.warranty_months),
    is_active: product ? Boolean(product.is_active) : true,
    specs: product?.specs?.length
      ? product.specs.map((row) => ({ key: row.key, value: row.value }))
      : [emptySpecRow()],
  }
}

function buildProductPayload(values) {
  const payload = {
    name: values.name.trim(),
    slug: values.slug.trim(),
    description: values.description,
    category_id: Number(values.category_id),
    brand_id: values.brand_id ? Number(values.brand_id) : null,
    is_active: values.is_active,
    // Replace-the-whole-table, per the contract. An empty list genuinely
    // clears the spec table, which is why blank rows are dropped first --
    // an admin who left a row empty did not ask to keep an empty spec.
    specs: values.specs
      .filter((row) => row.key.trim())
      .map((row, index) => ({
        key: row.key.trim(),
        value: row.value.trim(),
        sort_order: index,
      })),
  }
  if (values.warranty_months.trim()) {
    payload.warranty_months = Number(values.warranty_months)
  }
  return payload
}

export default function AdminProductFormPage() {
  const { id } = useParams()
  const isCreate = !id
  const navigate = useNavigate()
  const location = useLocation()

  const product = useAdminProduct(id)
  const categories = useAdminCategories()
  const brands = useAdminBrands()
  const create = useCreateProduct()
  const update = useUpdateProduct(id)

  const [variantDialog, setVariantDialog] = useState(null)

  const {
    control,
    register,
    handleSubmit,
    reset,
    setError,
    getValues,
    formState: { errors, isDirty },
  } = useForm({
    resolver: zodResolver(isCreate ? productCreateSchema : productEditSchema),
    defaultValues: isCreate
      ? { ...productDefaults(null), variants: [blankVariantRow()] }
      : productDefaults(null),
  })

  const specs = useFieldArray({ control, name: 'specs' })
  const variants = useFieldArray({ control, name: 'variants' })

  // Fill the form once the product arrives. Keyed on updated_at so a refetch
  // that changed nothing does not stamp over an edit in progress.
  const loadedAt = product.data?.updated_at
  useEffect(() => {
    if (!isCreate && product.data) reset(productDefaults(product.data))
  }, [isCreate, loadedAt, product.data, reset])

  function resolveField(parsed) {
    if (PRODUCT_FIELDS.includes(parsed.field)) return parsed.field
    if (isCreate && VARIANT_FIELDS.includes(parsed.field)) {
      return resolveVariantPath(parsed, getValues('variants') ?? [])
    }
    return null
  }

  const onSubmit = handleSubmit((values) => {
    const payload = buildProductPayload(values)

    if (isCreate) {
      create.mutate(
        { ...payload, variants: values.variants.map((row) => variantPayload(row, { withStock: true })) },
        {
          onSuccess: (created) =>
            navigate(`/admin/products/${created.id}`, {
              replace: true,
              state: { created: true },
            }),
          onError: (error) => applyServerError(error, setError, resolveField),
        },
      )
      return
    }

    update.mutate(payload, {
      onSuccess: (saved) => reset(productDefaults(saved)),
      onError: (error) => applyServerError(error, setError, resolveField),
    })
  })

  if (!isCreate && product.isError) {
    return <AdminError error={product.error} onRetry={() => product.refetch()} />
  }
  if (!isCreate && product.isPending) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size="lg" label="Loading product" />
      </div>
    )
  }

  const detail = product.data
  const categoryOptions = (categories.data ?? []).map((row) => ({
    value: String(row.id),
    label: row.parent_name ? `${row.parent_name} › ${row.name}` : row.name,
    disabled: !row.is_active,
  }))
  const brandOptions = (brands.data ?? []).map((row) => ({
    value: String(row.id),
    label: row.name,
  }))

  return (
    <div className="pb-10">
      <AdminPageHeader
        title={isCreate ? 'New product' : detail.name}
        description={
          isCreate
            ? 'A product needs a category and at least one variant. Price and stock belong to the variant.'
            : `Slug ${detail.slug} · ${detail.active_variant_count} of ${detail.variant_count} variants active`
        }
        actions={
          <Link
            to="/admin/products"
            className="inline-flex min-h-[44px] items-center rounded-card border-2 border-action px-4 text-sm font-medium text-action hover:bg-action hover:text-white"
          >
            Back to products
          </Link>
        }
      />

      {location.state?.created && (
        <SuccessNote message="Product created. Add its images below — uploads attach to a product that exists." />
      )}

      <div className="flex flex-col gap-5">
        <form
          noValidate
          onSubmit={onSubmit}
          className="flex flex-col gap-5 rounded-card border border-line bg-white p-4"
        >
          <FormAlert message={errors.root?.message} />

          <section aria-labelledby="basics-heading" className="flex flex-col gap-4">
            <h2 id="basics-heading" className="text-base font-semibold text-ink">
              Details
            </h2>

            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="Name"
                required
                error={errors.name?.message}
                containerClassName="sm:col-span-2"
                {...register('name')}
              />
              <Input
                label="URL slug"
                error={errors.slug?.message}
                hint="Leave blank to derive it from the name. The server de-duplicates."
                {...register('slug')}
              />
              <Input
                label="Warranty (months)"
                inputMode="numeric"
                error={errors.warranty_months?.message}
                {...register('warranty_months')}
              />
              <Select
                label="Category"
                required
                placeholder="Choose a category"
                error={errors.category_id?.message}
                options={categoryOptions}
                hint={
                  categories.isError
                    ? 'Categories could not be loaded.'
                    : 'Deactivating a category withdraws everything inside it from the storefront.'
                }
                {...register('category_id')}
              />
              <Select
                label="Brand"
                placeholder="No brand"
                error={errors.brand_id?.message}
                options={brandOptions}
                {...register('brand_id')}
              />
              <Textarea
                label="Description"
                rows={6}
                error={errors.description?.message}
                containerClassName="sm:col-span-2"
                {...register('description')}
              />
            </div>

            <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
              <input type="checkbox" className="h-4 w-4 accent-action" {...register('is_active')} />
              Active — listed on the storefront
            </label>
          </section>

          <section aria-labelledby="specs-heading" className="flex flex-col gap-3 border-t border-line pt-5">
            <div>
              <h2 id="specs-heading" className="text-base font-semibold text-ink">
                Specifications
              </h2>
              <p className="mt-1 max-w-prose text-sm text-ink-muted">
                Key and value pairs shown in the spec table on the product
                page. Saving replaces the whole table, in the order below.
              </p>
            </div>

            <ul className="flex flex-col gap-3">
              {specs.fields.map((field, index) => (
                <li key={field.id} className="grid gap-3 sm:grid-cols-[1fr_1.5fr_auto]">
                  <Input
                    label={`Specification ${index + 1} label`}
                    placeholder="Processor"
                    error={errors.specs?.[index]?.key?.message}
                    {...register(`specs.${index}.key`)}
                  />
                  <Input
                    label={`Specification ${index + 1} value`}
                    placeholder="AMD Ryzen 5 7520U"
                    error={errors.specs?.[index]?.value?.message}
                    {...register(`specs.${index}.value`)}
                  />
                  <div className="flex items-end">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove specification ${index + 1}`}
                      onClick={() => specs.remove(index)}
                    >
                      Remove
                    </Button>
                  </div>
                </li>
              ))}
            </ul>

            <div>
              <Button variant="outline" size="sm" onClick={() => specs.append(emptySpecRow())}>
                Add specification
              </Button>
            </div>
          </section>

          {isCreate && (
            <section
              aria-labelledby="new-variants-heading"
              className="flex flex-col gap-3 border-t border-line pt-5"
            >
              <div>
                <h2 id="new-variants-heading" className="text-base font-semibold text-ink">
                  Variants
                </h2>
                <p className="mt-1 max-w-prose text-sm text-ink-muted">
                  Every product has at least one, each with its own price, SKU
                  and stock. A product with no real options takes one variant
                  with a blank option label.
                </p>
              </div>

              <FormAlert message={errors.variants?.message ?? errors.variants?.root?.message} />

              <ul className="flex flex-col gap-4">
                {variants.fields.map((field, index) => (
                  <li key={field.id} className="rounded-card border border-line p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <h3 className="text-sm font-semibold text-ink">Variant {index + 1}</h3>
                      {variants.fields.length > 1 && (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Remove variant ${index + 1}`}
                          onClick={() => variants.remove(index)}
                        >
                          Remove
                        </Button>
                      )}
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      <Input
                        label="SKU"
                        required
                        error={errors.variants?.[index]?.sku?.message}
                        {...register(`variants.${index}.sku`)}
                      />
                      <Input
                        label="Option label"
                        placeholder="8GB / 512GB"
                        error={errors.variants?.[index]?.option_label?.message}
                        {...register(`variants.${index}.option_label`)}
                      />
                      <Input
                        label="Price (৳)"
                        required
                        inputMode="decimal"
                        error={errors.variants?.[index]?.price?.message}
                        {...register(`variants.${index}.price`)}
                      />
                      <Input
                        label="Compare-at price (৳)"
                        inputMode="decimal"
                        error={errors.variants?.[index]?.compare_at_price?.message}
                        {...register(`variants.${index}.compare_at_price`)}
                      />
                      <Input
                        label="Opening stock"
                        inputMode="numeric"
                        hint="Recorded in the inventory ledger as an initial movement."
                        error={errors.variants?.[index]?.stock?.message}
                        {...register(`variants.${index}.stock`)}
                      />
                      <Input
                        label="Low-stock threshold"
                        inputMode="numeric"
                        error={errors.variants?.[index]?.low_stock_threshold?.message}
                        {...register(`variants.${index}.low_stock_threshold`)}
                      />
                      <Input
                        label="Weight (grams)"
                        inputMode="numeric"
                        error={errors.variants?.[index]?.weight_grams?.message}
                        {...register(`variants.${index}.weight_grams`)}
                      />
                    </div>
                    <label className="mt-2 flex min-h-[44px] items-center gap-2 text-sm text-ink">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-action"
                        {...register(`variants.${index}.is_active`)}
                      />
                      Active
                    </label>
                  </li>
                ))}
              </ul>

              <div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => variants.append(blankVariantRow())}
                >
                  Add another variant
                </Button>
              </div>

              <Callout tone="info">
                Opening stock is the only stock number this form accepts, and
                the server records it as an <strong>initial</strong> ledger
                movement. After this, stock changes go through Inventory with a
                mandatory reason, so a count can always be explained by its
                movement history.
              </Callout>
            </section>
          )}

          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line pt-4">
            {!isCreate && update.isSuccess && !isDirty && <SuccessNote message="Saved." />}
            <Button type="submit" loading={create.isPending || update.isPending}>
              {isCreate ? 'Create product' : 'Save changes'}
            </Button>
          </div>
        </form>

        {!isCreate && (
          <>
            <div className="flex flex-wrap items-center gap-3 rounded-card border border-line bg-white p-4 text-sm">
              <Badge tone={detail.is_active ? 'success' : 'neutral'}>
                {detail.is_active ? 'Active' : 'Inactive'}
              </Badge>
              <span className="text-ink-muted">
                Price{' '}
                {detail.price_min
                  ? `${formatMoney(detail.price_min)} – ${formatMoney(detail.price_max)}`
                  : 'not set — no active variant'}
              </span>
              <span className="text-ink-muted">Stock {detail.total_stock}</span>
              <span className="text-ink-muted">
                Rating {detail.rating_avg ?? '—'} from {detail.rating_count} approved reviews
              </span>
              <Link
                to={`/p/${detail.slug}`}
                className="ml-auto min-h-[44px] font-medium leading-[44px] text-action hover:underline"
              >
                View on storefront
              </Link>
            </div>

            <VariantManager
              product={detail}
              dialog={variantDialog}
              onOpenDialog={setVariantDialog}
              onCloseDialog={() => setVariantDialog(null)}
            />

            <ImageManager product={detail} />
          </>
        )}
      </div>
    </div>
  )
}
