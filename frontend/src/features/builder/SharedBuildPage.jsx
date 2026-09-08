import { Link, useNavigate, useParams } from 'react-router-dom'

import { Button, PageSpinner } from '@/components/ui'
import { formatMoney } from '@/lib/money'
import { useSeo } from '@/lib/seo'
import { useBuilderStore } from '@/stores/builderStore'

import { useBuilderSlots, useSavedBuild } from './api'
import CompatibilityPanel from './components/CompatibilityPanel'

/*
 * A shared build, opened from its link.
 *
 * Public on purpose: a link you send someone has to work when they open it,
 * and they are by definition not signed in as you. The token is unguessable
 * (132 bits) and grants nothing but reading this build.
 *
 * **Prices and stock are re-read, never replayed.** The saved build stores
 * variant ids only, so this page shows today's prices and today's
 * availability -- and re-runs the compatibility rules, because the catalogue
 * may have moved since it was saved.
 */
export default function SharedBuildPage() {
  const { token } = useParams()
  const navigate = useNavigate()
  const { data: build, isPending, isError } = useSavedBuild(token)
  const { data: slots = [] } = useBuilderSlots()
  const load = useBuilderStore((s) => s.load)

  useSeo({
    title: build?.name ? `${build.name} — shared PC build` : 'Shared PC build',
    description: 'A PC build shared from MicroMart, with live prices and compatibility checks.',
    canonical: token ? `/builds/${token}` : undefined,
    // Unguessable per-user URLs have no business in a search index.
    noIndex: true,
  })

  if (isPending) return <PageSpinner label="Loading build" />

  if (isError || !build) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center px-4 py-10 text-center">
        <h1 className="text-xl font-semibold text-ink">That build link is not valid</h1>
        <p className="mt-2 max-w-md text-sm text-ink-muted">
          It may have been deleted, or the link may be incomplete.
        </p>
        <Link
          to="/pc-builder"
          className="mt-5 inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-semibold text-white hover:bg-action-hover"
        >
          Start your own build
        </Link>
      </div>
    )
  }

  function copyToMyBuilder() {
    const selection = {}
    for (const line of build.lines) {
      // A part that no longer exists cannot be copied; the rest still can.
      if (line.product) {
        selection[line.slot] = { variantId: line.variant_id, quantity: line.quantity }
      }
    }
    load(selection, `${build.name} (copy)`)
    navigate('/pc-builder')
  }

  return (
    <div className="px-4 py-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-action">
            Shared build
          </p>
          <h1 className="mt-1 text-xl font-semibold text-ink sm:text-2xl">{build.name}</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Prices and availability shown are current, not the ones from when
            this build was saved.
          </p>
        </div>
        <Button onClick={copyToMyBuilder}>Open in PC Builder</Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-start">
        <div className="overflow-hidden rounded-card bg-white shadow-el-1">
          <ul className="divide-y divide-line">
            {build.lines.map((line) => (
              <li key={line.slot} className="flex items-center gap-3 p-3">
                <span className="w-28 shrink-0 text-sm font-medium text-ink">
                  {slots.find((s) => s.slot === line.slot)?.label ?? line.slot}
                </span>

                {line.product ? (
                  <>
                    <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-card border border-line bg-white p-1">
                      {line.product.image ? (
                        <img
                          src={line.product.image}
                          alt=""
                          loading="lazy"
                          className="h-full w-full object-contain"
                        />
                      ) : (
                        <span className="text-[10px] text-ink-muted">No image</span>
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <Link
                        to={`/p/${line.product.slug}`}
                        className="block truncate text-sm text-ink hover:text-action hover:underline"
                      >
                        {line.product.name}
                      </Link>
                      <span className="block text-xs text-ink-muted">
                        {formatMoney(line.product.price)}
                        {line.quantity > 1 ? ` × ${line.quantity}` : ''}
                        {line.issue === 'out_of_stock' && (
                          <span className="ml-2 font-medium text-warning">Out of stock</span>
                        )}
                      </span>
                    </span>
                  </>
                ) : (
                  <span className="flex-1 text-sm text-ink-muted">
                    This part is no longer sold.
                  </span>
                )}
              </li>
            ))}
          </ul>

          <div className="flex items-center justify-between border-t border-line p-3">
            <span className="text-sm font-semibold text-ink">Subtotal</span>
            <span className="text-lg font-semibold text-price">
              {formatMoney(build.subtotal)}
            </span>
          </div>
        </div>

        <CompatibilityPanel report={build} isFetching={false} slots={slots} />
      </div>
    </div>
  )
}
