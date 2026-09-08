import clsx from 'clsx'

import ProductCard, { ProductCardSkeleton } from './ProductCard'

/*
 * Two columns at 360px, widening with the viewport. `items-stretch` keeps
 * every card the same height so the price line does not wander row to row.
 *
 * `layout="list"` switches to a single stacked column of horizontal rows --
 * the same products, arranged for scanning specs rather than comparing
 * images.
 */
const COLUMNS = {
  grid: 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4',
  wide: 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5',
}

export default function ProductGrid({
  products = [],
  loading = false,
  skeletonCount = 8,
  variant = 'grid',
  layout = 'grid',
  className,
}) {
  const isList = layout === 'list'
  const columns = isList ? 'grid-cols-1' : (COLUMNS[variant] ?? COLUMNS.grid)

  return (
    <div className={clsx('grid items-stretch gap-3', columns, className)}>
      {loading
        ? Array.from({ length: skeletonCount }, (_, i) => (
            <ProductCardSkeleton key={i} layout={layout} />
          ))
        : products.map((product) => (
            <ProductCard key={product.id} product={product} layout={layout} />
          ))}
    </div>
  )
}
