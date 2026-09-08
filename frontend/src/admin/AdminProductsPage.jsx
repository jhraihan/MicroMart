import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  Badge,
  Button,
  EmptyRow,
  Input,
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

import {
  useAdminBrands,
  useAdminCategories,
  useAdminProducts,
  useSetProductActive,
} from './api'
import {
  AdminError,
  AdminPageHeader,
  AdminPager,
  FormAlert,
  LoadingRowNote,
} from './components/AdminUI'

const PAGE_SIZE = 24

const SORTS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'name', label: 'Name A–Z' },
  { value: 'updated', label: 'Recently updated' },
]

/**
 * A price range printed from two decimal strings.
 *
 * Never `Number(min) === Number(max)` -- comparing the strings is exact and
 * costs nothing, and money does not go through a float on this screen
 * (PRD §6.1).
 */
function PriceRange({ min, max }) {
  if (!min) return <span className="text-ink-muted">No active variant</span>
  if (min === max) return <span>{formatMoney(min)}</span>
  return (
    <span>
      {formatMoney(min)} – {formatMoney(max)}
    </span>
  )
}

/**
 * The catalogue list (US-A2): every product, active or not, with the search
 * and filters an owner needs to find one among hundreds.
 */
export default function AdminProductsPage() {
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [brand, setBrand] = useState('')
  const [isActive, setIsActive] = useState('')
  const [lowStock, setLowStock] = useState(false)
  const [sort, setSort] = useState('newest')
  const [page, setPage] = useState(1)

  // Typing is not a query. Settle the box before it becomes a request, the
  // same way the storefront search does.
  const q = useDebouncedValue(search.trim(), 300)

  const params = {
    q,
    category,
    brand,
    is_active: isActive,
    low_stock: lowStock ? 'true' : '',
    sort,
    page,
    page_size: PAGE_SIZE,
  }

  const products = useAdminProducts(params)
  const categories = useAdminCategories()
  const brands = useAdminBrands()
  const setActive = useSetProductActive()

  function changeFilter(setter) {
    return (value) => {
      setter(value)
      // Any filter change invalidates the page number -- staying on page 4 of
      // a two-page result set shows an empty table that looks like a failure.
      setPage(1)
    }
  }

  const rows = products.data?.results ?? []

  return (
    <div>
      <AdminPageHeader
        title="Products"
        description="Create and edit the catalogue. Price and stock live on a product's variants, never on the product itself."
        actions={
          <Link
            to="/admin/products/new"
            className="inline-flex min-h-[44px] items-center rounded-card border-2 border-action bg-action px-4 text-sm font-medium text-white hover:bg-action-hover"
          >
            New product
          </Link>
        }
      />

      <form
        className="mb-4 grid gap-3 rounded-card border border-line bg-white p-4 sm:grid-cols-2 lg:grid-cols-5"
        onSubmit={(event) => event.preventDefault()}
        role="search"
        aria-label="Filter products"
      >
        <Input
          label="Search"
          type="search"
          placeholder="Name, slug or SKU"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
        />
        <Select
          label="Category"
          placeholder="All categories"
          value={category}
          onChange={(event) => changeFilter(setCategory)(event.target.value)}
          options={(categories.data ?? []).map((row) => ({
            value: row.slug,
            label: row.parent_name ? `${row.parent_name} › ${row.name}` : row.name,
          }))}
        />
        <Select
          label="Brand"
          placeholder="All brands"
          value={brand}
          onChange={(event) => changeFilter(setBrand)(event.target.value)}
          options={(brands.data ?? []).map((row) => ({ value: row.slug, label: row.name }))}
        />
        <Select
          label="Status"
          placeholder="Active and inactive"
          value={isActive}
          onChange={(event) => changeFilter(setIsActive)(event.target.value)}
          options={[
            { value: 'true', label: 'Active only' },
            { value: 'false', label: 'Inactive only' },
          ]}
        />
        <Select
          label="Sort"
          value={sort}
          onChange={(event) => changeFilter(setSort)(event.target.value)}
          options={SORTS}
        />
        <label className="flex min-h-[44px] items-center gap-2 self-end text-sm text-ink">
          <input
            type="checkbox"
            className="h-4 w-4 accent-action"
            checked={lowStock}
            onChange={(event) => changeFilter(setLowStock)(event.target.checked)}
          />
          Low stock only
        </label>
      </form>

      {setActive.isError && <FormAlert message={parseApiError(setActive.error).message} />}

      {products.isError ? (
        <AdminError error={products.error} onRetry={() => products.refetch()} />
      ) : products.isPending ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" label="Loading products" />
        </div>
      ) : (
        <>
          <LoadingRowNote show={products.isFetching} label="Updating results" />
          <Table caption="Catalogue products with their price range, stock and status">
            <THead>
              <TR>
                <TH>Product</TH>
                <TH>Category</TH>
                <TH>Brand</TH>
                <TH align="right">Price</TH>
                <TH align="right">Stock</TH>
                <TH align="center">Status</TH>
                <TH align="right">Actions</TH>
              </TR>
            </THead>
            <TBody>
              {rows.length === 0 && (
                <EmptyRow colSpan={7}>
                  No products match these filters.
                </EmptyRow>
              )}
              {rows.map((product) => (
                <TR key={product.id}>
                  <TD>
                    <div className="flex items-center gap-3">
                      {product.primary_image ? (
                        <img
                          src={product.primary_image.url}
                          alt=""
                          className="h-10 w-10 shrink-0 rounded-card border border-line object-cover"
                        />
                      ) : (
                        <span
                          aria-hidden="true"
                          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-card border border-dashed border-line text-[10px] text-ink-muted"
                        >
                          No img
                        </span>
                      )}
                      <div className="min-w-0">
                        <Link
                          to={`/admin/products/${product.id}`}
                          className="inline-flex min-h-[44px] items-center font-medium text-action hover:underline"
                        >
                          {product.name}
                        </Link>
                        <p className="truncate text-xs text-ink-muted">
                          {product.active_variant_count} of {product.variant_count} variants
                          active · {product.image_count} images
                        </p>
                      </div>
                    </div>
                  </TD>
                  <TD>{product.category?.name ?? '—'}</TD>
                  <TD>{product.brand?.name ?? '—'}</TD>
                  <TD align="right">
                    <PriceRange min={product.price_min} max={product.price_max} />
                  </TD>
                  <TD align="right">
                    <span className={product.has_low_stock ? 'font-semibold text-warning' : ''}>
                      {product.total_stock}
                    </span>
                    {product.has_low_stock && (
                      <span className="ml-1 text-xs text-warning">low</span>
                    )}
                  </TD>
                  <TD align="center">
                    <Badge tone={product.is_active ? 'success' : 'neutral'} size="sm">
                      {product.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </TD>
                  <TD align="right">
                    <div className="flex justify-end gap-2">
                      <Link
                        to={`/admin/products/${product.id}`}
                        className="inline-flex min-h-[44px] items-center rounded-card border-2 border-action px-3 text-[13px] font-medium text-action hover:bg-action hover:text-white"
                      >
                        Edit
                      </Link>
                      <Button
                        size="sm"
                        variant={product.is_active ? 'ghost' : 'outline'}
                        loading={
                          setActive.isPending && setActive.variables?.id === product.id
                        }
                        onClick={() =>
                          setActive.mutate({ id: product.id, isActive: !product.is_active })
                        }
                      >
                        {product.is_active ? 'Deactivate' : 'Activate'}
                      </Button>
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>

          <AdminPager
            page={page}
            count={products.data?.count ?? 0}
            pageSize={PAGE_SIZE}
            onChange={setPage}
          />
        </>
      )}

      <p className="mt-4 max-w-prose text-xs text-ink-muted">
        Deactivating withdraws a product from the storefront; it is never
        deleted. Orders already placed carry their own snapshot of the name,
        SKU and price, so nothing here can rewrite one (PRD §6.3).
      </p>
    </div>
  )
}
