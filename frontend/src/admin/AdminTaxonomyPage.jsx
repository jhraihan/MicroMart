import { useState } from 'react'

import { Button } from '@/components/ui'
import { parseApiError } from '@/lib/api'

import {
  useAdminBrands,
  useAdminCategories,
  useDeleteBrand,
  useDeleteCategory,
  useSaveBrand,
  useSaveCategory,
} from './api'
import { AdminError, AdminPageHeader, FormAlert, SuccessNote } from './components/AdminUI'

// Categories and brands.
export default function AdminTaxonomyPage() {
  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Categories &amp; brands"
        description="The shelves products sit on. Categories are navigation; brands are labels on stock."
      />
      <CategorySection />
      <BrandSection />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Categories
// ---------------------------------------------------------------------------
const EMPTY_CATEGORY = {
  name: '',
  slug: '',
  parent_id: '',
  sort_order: 0,
  is_active: true,
}

function CategorySection() {
  const { data: categories = [], isPending, isError, error, refetch } = useAdminCategories()
  const saveCategory = useSaveCategory()
  const deleteCategory = useDeleteCategory()

  const [draft, setDraft] = useState(null)
  const [message, setMessage] = useState('')
  const [failure, setFailure] = useState('')
  const [confirming, setConfirming] = useState(null)

  const roots = categories.filter((c) => c.parent_id == null)

  async function submit(event) {
    event.preventDefault()
    setFailure('')
    setMessage('')
    try {
      await saveCategory.mutateAsync({
        ...draft,
        // An empty select value means "no parent", which the API expects as
        // null rather than "".
        parent_id: draft.parent_id === '' ? null : Number(draft.parent_id),
        sort_order: Number(draft.sort_order) || 0,
      })
      setMessage(draft.id ? 'Category updated.' : 'Category created.')
      setDraft(null)
    } catch (err) {
      setFailure(parseApiError(err).message || 'That category could not be saved.')
    }
  }

  async function deactivate(id) {
    setFailure('')
    try {
      await deleteCategory.mutateAsync(id)
      setMessage('Category deactivated. Its products are now hidden from the storefront.')
      setConfirming(null)
    } catch (err) {
      setFailure(parseApiError(err).message || 'That category could not be deactivated.')
    }
  }

  if (isError) return <AdminError error={error} onRetry={refetch} />

  return (
    <section className="rounded-card bg-white p-4 shadow-el-1">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-ink">Categories</h2>
          <p className="mt-0.5 text-sm text-ink-muted">
            {isPending ? 'Loading…' : `${categories.length} categories, two levels deep.`}
          </p>
        </div>
        {!draft && (
          <Button onClick={() => setDraft({ ...EMPTY_CATEGORY })}>New category</Button>
        )}
      </div>

      <FormAlert message={failure} />
      <SuccessNote message={message} />

      {draft && (
        <form onSubmit={submit} className="mb-4 grid gap-3 rounded-card bg-page p-3 sm:grid-cols-2">
          <Text
            label="Name"
            value={draft.name}
            onChange={(v) => setDraft({ ...draft, name: v })}
            required
          />
          <Text
            label="Slug"
            value={draft.slug}
            onChange={(v) => setDraft({ ...draft, slug: v })}
            hint="Leave blank to derive it from the name. Changing it breaks saved links."
          />

          <div className="flex flex-col gap-1">
            <label htmlFor="cat-parent" className="text-sm font-medium text-ink">
              Parent
            </label>
            <select
              id="cat-parent"
              value={draft.parent_id ?? ''}
              onChange={(event) => setDraft({ ...draft, parent_id: event.target.value })}
              className="h-11 rounded-card border border-line bg-white px-3 text-base text-ink focus:border-action"
            >
              <option value="">No parent (a top-level department)</option>
              {roots
                // A category cannot be its own parent.
                .filter((root) => root.id !== draft.id)
                .map((root) => (
                  <option key={root.id} value={root.id}>
                    {root.name}
                  </option>
                ))}
            </select>
            <p className="text-xs text-ink-muted">
              Only top-level categories are offered — the taxonomy is two levels deep.
            </p>
          </div>

          <Text
            label="Sort order"
            type="number"
            value={draft.sort_order}
            onChange={(v) => setDraft({ ...draft, sort_order: v })}
            hint="Lower numbers appear first in the navigation."
          />

          <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={draft.is_active}
              onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}
              className="h-4 w-4 accent-action"
            />
            Visible in the storefront
          </label>

          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button type="submit" disabled={saveCategory.isPending}>
              {saveCategory.isPending ? 'Saving…' : draft.id ? 'Save changes' : 'Create category'}
            </Button>
            <button
              type="button"
              onClick={() => {
                setDraft(null)
                setFailure('')
              }}
              className="flex min-h-[44px] items-center rounded-card border border-line px-4 text-sm text-ink hover:border-action hover:text-action"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="sr-only">Categories</caption>
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-muted">
              <th scope="col" className="py-2 pr-3">Name</th>
              <th scope="col" className="py-2 pr-3">Parent</th>
              <th scope="col" className="py-2 pr-3">Products</th>
              <th scope="col" className="py-2 pr-3">Order</th>
              <th scope="col" className="py-2 pr-3">Status</th>
              <th scope="col" className="py-2">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {categories.map((category) => (
              <tr key={category.id}>
                <td className="py-2 pr-3">
                  <span className={category.parent_id ? 'pl-4 text-ink-muted' : 'font-medium text-ink'}>
                    {category.parent_id ? '— ' : ''}
                    {category.name}
                  </span>
                  <span className="block text-xs text-ink-muted">{category.slug}</span>
                </td>
                <td className="py-2 pr-3 text-ink-muted">{category.parent_name ?? '—'}</td>
                <td className="py-2 pr-3 text-ink">{category.product_count}</td>
                <td className="py-2 pr-3 text-ink-muted">{category.sort_order}</td>
                <td className="py-2 pr-3">
                  <StatusPill active={category.is_active} />
                </td>
                <td className="py-2">
                  <div className="flex flex-wrap gap-1">
                    <RowButton onClick={() => setDraft({ ...category })}>Edit</RowButton>
                    {category.is_active &&
                      (confirming === category.id ? (
                        <>
                          <button
                            type="button"
                            onClick={() => deactivate(category.id)}
                            className="flex min-h-[44px] items-center rounded-card bg-danger px-3 text-xs font-semibold text-white"
                          >
                            Hide it and its products
                          </button>
                          <RowButton onClick={() => setConfirming(null)}>Cancel</RowButton>
                        </>
                      ) : (
                        <RowButton danger onClick={() => setConfirming(category.id)}>
                          Deactivate
                        </RowButton>
                      ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Brands
// ---------------------------------------------------------------------------
function BrandSection() {
  const { data: brands = [], isPending, isError, error, refetch } = useAdminBrands()
  const saveBrand = useSaveBrand()
  const deleteBrand = useDeleteBrand()

  const [draft, setDraft] = useState(null)
  const [message, setMessage] = useState('')
  const [failure, setFailure] = useState('')

  async function submit(event) {
    event.preventDefault()
    setFailure('')
    setMessage('')
    try {
      await saveBrand.mutateAsync(draft)
      setMessage(draft.id ? 'Brand updated.' : 'Brand created.')
      setDraft(null)
    } catch (err) {
      setFailure(parseApiError(err).message || 'That brand could not be saved.')
    }
  }

  if (isError) return <AdminError error={error} onRetry={refetch} />

  return (
    <section className="rounded-card bg-white p-4 shadow-el-1">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-ink">Brands</h2>
          <p className="mt-0.5 text-sm text-ink-muted">
            {isPending ? 'Loading…' : `${brands.length} brands.`} Deactivating one
            removes it from the brand filter but leaves its products on sale.
          </p>
        </div>
        {!draft && (
          <Button onClick={() => setDraft({ name: '', slug: '', is_active: true })}>
            New brand
          </Button>
        )}
      </div>

      <FormAlert message={failure} />
      <SuccessNote message={message} />

      {draft && (
        <form onSubmit={submit} className="mb-4 grid gap-3 rounded-card bg-page p-3 sm:grid-cols-2">
          <Text
            label="Brand name"
            value={draft.name}
            onChange={(v) => setDraft({ ...draft, name: v })}
            required
          />
          <Text
            label="Slug"
            value={draft.slug}
            onChange={(v) => setDraft({ ...draft, slug: v })}
            hint="Leave blank to derive it from the name."
          />
          <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={draft.is_active}
              onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}
              className="h-4 w-4 accent-action"
            />
            Offer as a filter in the storefront
          </label>
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button type="submit" disabled={saveBrand.isPending}>
              {saveBrand.isPending ? 'Saving…' : draft.id ? 'Save changes' : 'Create brand'}
            </Button>
            <button
              type="button"
              onClick={() => {
                setDraft(null)
                setFailure('')
              }}
              className="flex min-h-[44px] items-center rounded-card border border-line px-4 text-sm text-ink hover:border-action hover:text-action"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {brands.map((brand) => (
          <li
            key={brand.id}
            className="flex items-center gap-3 rounded-card border border-line p-2"
          >
            <span className="flex h-12 w-16 shrink-0 items-center justify-center rounded border border-line bg-white p-1">
              {brand.logo ? (
                <img src={brand.logo} alt="" loading="lazy" className="h-full w-full object-contain" />
              ) : (
                <span className="text-[10px] text-ink-muted">No logo</span>
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-ink">{brand.name}</span>
              <span className="block text-xs text-ink-muted">
                {brand.product_count} products
              </span>
            </span>
            <span className="flex shrink-0 flex-col items-end gap-1">
              <StatusPill active={brand.is_active} />
              <span className="flex gap-1">
                <RowButton onClick={() => setDraft({ ...brand })}>Edit</RowButton>
                {brand.is_active && (
                  <RowButton danger onClick={() => deleteBrand.mutate(brand.id)}>
                    Deactivate
                  </RowButton>
                )}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Small shared bits
// ---------------------------------------------------------------------------
function Text({ label, value, onChange, type = 'text', required = false, hint }) {
  const id = `tax-${label.toLowerCase().replace(/[^a-z]+/g, '-')}`
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
      {hint && <p className="text-xs text-ink-muted">{hint}</p>}
    </div>
  )
}

function StatusPill({ active }) {
  return (
    <span
      className={
        'rounded-pill px-2 py-0.5 text-[11px] font-medium ' +
        (active ? 'bg-success/10 text-success' : 'bg-page text-ink-muted')
      }
    >
      {active ? 'Active' : 'Inactive'}
    </span>
  )
}

function RowButton({ children, onClick, danger = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        'flex min-h-[44px] items-center rounded-card border px-3 text-xs font-medium ' +
        (danger
          ? 'border-line text-ink-muted hover:border-danger hover:text-danger'
          : 'border-action text-action hover:bg-action hover:text-white')
      }
    >
      {children}
    </button>
  )
}
