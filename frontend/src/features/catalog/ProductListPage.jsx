import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Button, Modal } from '@/components/ui'
import { parseApiError } from '@/lib/api'
import { breadcrumbJsonLd, itemListJsonLd, useJsonLd, useSeo } from '@/lib/seo'

import { findCategory, useCategories, useProducts } from './api'
import ActiveFilters from './components/ActiveFilters'
import Breadcrumbs from './components/Breadcrumbs'
import EmptyResults from './components/EmptyResults'
import ErrorState from './components/ErrorState'
import FacetFilters from './components/FacetFilters'
import Pagination from './components/Pagination'
import ProductGrid from './components/ProductGrid'
import SearchWithinResults from './components/SearchWithinResults'
import SortSelect from './components/SortSelect'
import ViewToggle from './components/ViewToggle'
import { useCatalogParams } from './useCatalogParams'

/*
 * The listing surface, shared by /search and /c/:slug.
 *
 * The two differ only in where the category scope comes from: the path on a
 * category page, the query string on search. Everything else -- keyword,
 * facets, sort, page -- is read from and written to the URL by
 * useCatalogParams, so pasting a URL into a new tab reproduces exactly the
 * same result set (FR-SRC-5).
 */
export default function ProductListPage({ mode = 'search' }) {
  const { slug } = useParams()
  const lockedCategory = mode === 'category' ? slug : null

  const params = useCatalogParams({ lockedCategory })
  const { state, apiQuery, effectiveSort, activeFilterCount, view } = params

  const { data, isPending, isFetching, isError, error, refetch } = useProducts(apiQuery)
  const { data: categoryTree } = useCategories()

  const [filtersOpen, setFiltersOpen] = useState(false)

  const match = findCategory(categoryTree, lockedCategory)
  const category = match?.category ?? null
  const parentCategory = match?.parent ?? null

  const products = data?.results ?? []
  const facets = data?.facets ?? null
  const count = data?.count ?? 0

  const heading =
    mode === 'category'
      ? (category?.name ?? slug)
      : state.q
        ? `Results for "${state.q}"`
        : 'All products'

  const breadcrumbs = [{ label: 'Home', to: '/' }]
  if (mode === 'category') {
    if (parentCategory) breadcrumbs.push({ label: parentCategory.name, to: `/c/${parentCategory.slug}` })
    breadcrumbs.push({ label: category?.name ?? slug })
  } else {
    breadcrumbs.push({ label: state.q ? `Search: ${state.q}` : 'All products' })
  }

  /*
   * A category page is a real, linkable destination and gets a canonical URL.
   * A search-results page is not: `?q=` produces effectively unlimited
   * near-duplicate pages, which is exactly what `noindex` exists for. Both
   * still get a title and description, because those show in a shared link.
   */
  useSeo({
    title: mode === 'category' ? (category?.name ?? slug) : state.q ? `Search: ${state.q}` : 'All products',
    description:
      mode === 'category'
        ? `Buy ${category?.name ?? slug} in Bangladesh. ${count} products with official warranty, cash on delivery nationwide.`
        : state.q
          ? `Search results for "${state.q}" at MicroMart.`
          : 'Browse every product at MicroMart.',
    canonical: mode === 'category' ? `/c/${slug}` : '/search',
    noIndex: mode !== 'category',
  })

  const crumbLd = useMemo(
    () =>
      breadcrumbJsonLd(
        breadcrumbs.map((crumb) => ({
          name: crumb.label,
          path: crumb.to ?? (mode === 'category' ? `/c/${slug}` : '/search'),
        })),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, slug, category?.name, parentCategory?.name, state.q],
  )
  const listLd = useMemo(
    () => itemListJsonLd(products, { name: heading }),
    [products, heading],
  )
  useJsonLd(crumbLd)
  useJsonLd(listLd)

  const facetPanel = (idPrefix) => (
    <FacetFilters
      idPrefix={idPrefix}
      facets={facets}
      state={state}
      toggleValue={params.toggleValue}
      setParams={params.setParams}
      clearFilters={params.clearFilters}
      activeFilterCount={activeFilterCount}
    />
  )

  // A hand-typed page past the end 404s server-side; offer the way back
  // rather than a dead end.
  const apiError = isError ? parseApiError(error) : null
  const isPageOverflow = apiError?.status === 404 && state.page > 1

  return (
    <div className="px-4 py-5">
      <Breadcrumbs items={breadcrumbs} />

      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h1 className="text-xl font-semibold text-ink">{heading}</h1>
        {/* aria-live so a filter change is announced, not just repainted. */}
        <p role="status" aria-live="polite" className="text-sm text-ink-muted">
          {isPending
            ? 'Loading products'
            : isError
              ? 'Could not load products'
              : `${count} ${count === 1 ? 'product' : 'products'}`}
          {!isPending && isFetching && ' · updating'}
        </p>
      </div>

      {mode === 'category' && (category?.children?.length ?? 0) > 0 && (
        <nav aria-label="Subcategories" className="mb-4">
          <ul className="flex flex-wrap gap-2">
            {category.children.map((child) => (
              <li key={child.id}>
                <Link
                  to={`/c/${child.slug}`}
                  className="flex min-h-[44px] items-center rounded-pill bg-white px-4 text-sm text-ink shadow-el-1 hover:bg-tint hover:text-action"
                >
                  {child.name}
                  <span className="ml-1.5 text-xs text-ink-muted">{child.product_count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}

      {/*
        Refining within a scope only means something when there *is* an outer
        scope. On /search the keyword is the scope, so this control is the
        keyword box itself and is labelled accordingly by the component.
      */}
      <div className="mb-3 rounded-card bg-white px-3 py-2 shadow-el-1">
        <SearchWithinResults
          value={state.q}
          scopeLabel={mode === 'category' ? (category?.name ?? slug) : null}
          onSubmit={(keyword) => params.setParams({ q: keyword || null })}
        />
      </div>

      <div className="mb-4 flex items-center justify-between gap-3 rounded-card bg-white px-3 py-2 shadow-el-1">
        <Button
          variant="outline"
          size="sm"
          className="lg:hidden"
          onClick={() => setFiltersOpen(true)}
          aria-haspopup="dialog"
        >
          Filters
          {activeFilterCount > 0 && (
            <span className="rounded-pill bg-action px-1.5 text-[11px] text-white">
              {activeFilterCount}
            </span>
          )}
        </Button>

        <div className="ml-auto flex items-center gap-2">
          <ViewToggle
            value={view}
            onChange={(next) => params.setParams({ view: next === 'grid' ? null : next })}
          />
          <SortSelect
            value={effectiveSort}
            hasQuery={Boolean(state.q)}
            onChange={(value) => params.setParams({ sort: value })}
          />
        </div>
      </div>

      <ActiveFilters
        state={state}
        facets={facets}
        toggleValue={params.toggleValue}
        setParams={params.setParams}
        clearFilters={params.clearFilters}
      />

      <div className="flex gap-5">
        <aside className="hidden w-64 shrink-0 lg:block">
          <div className="sticky top-20 rounded-card bg-white px-3 py-2 shadow-el-1">
            {facetPanel('desktop')}
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          {/*
            The results region needs a heading of its own, and not only as a
            label: a ProductCard's title is an <h3>, so without an <h2> here
            the listing jumps h1 -> h3 and a screen reader user tabbing by
            heading loses the level. The facet panel's own <h2> is inside the
            `hidden lg:block` aside, so it does not fill the gap at 360px.
          */}
          <h2 className="sr-only">
            {isPending ? 'Products' : `${count} ${count === 1 ? 'product' : 'products'}`}
          </h2>
          {isError ? (
            isPageOverflow ? (
              <div className="rounded-card border border-line bg-white px-4 py-10 text-center">
                <h2 className="text-base font-semibold text-ink">That page is empty</h2>
                <p className="mt-2 text-sm text-ink-muted">
                  There are only {count || 'a few'} results for these filters.
                </p>
                <Link
                  to={{ search: params.hrefForPage(1) }}
                  className="mt-4 inline-flex min-h-[44px] items-center rounded-card border-2 border-action px-4 text-sm font-medium text-action hover:bg-action hover:text-white"
                >
                  Back to the first page
                </Link>
              </div>
            ) : (
              <ErrorState
                error={error}
                onRetry={refetch}
                title="Could not load these products"
              />
            )
          ) : isPending ? (
            <ProductGrid
              loading
              layout={view}
              skeletonCount={state.page_size > 12 ? 12 : state.page_size}
            />
          ) : products.length === 0 ? (
            <EmptyResults
              query={state.q}
              activeFilterCount={activeFilterCount}
              onClearFilters={params.clearFilters}
              categories={categoryTree ?? []}
            />
          ) : (
            <>
              <ProductGrid products={products} layout={view} />
              <Pagination
                page={state.page}
                count={count}
                pageSize={state.page_size}
                hrefForPage={params.hrefForPage}
              />
            </>
          )}
        </div>
      </div>

      {/* The mobile panel reuses the Modal primitive, which traps focus and
          closes on Escape, so the filters are fully keyboard operable. */}
      <Modal open={filtersOpen} onClose={() => setFiltersOpen(false)} title="Filters">
        {facetPanel('mobile')}
        <div className="sticky bottom-0 mt-4 bg-white pt-3">
          <Button fullWidth onClick={() => setFiltersOpen(false)}>
            Show {count} {count === 1 ? 'result' : 'results'}
          </Button>
        </div>
      </Modal>
    </div>
  )
}
