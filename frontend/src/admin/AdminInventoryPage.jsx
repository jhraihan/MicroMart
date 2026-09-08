import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router-dom'

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
  Textarea,
} from '@/components/ui'
import useDebouncedValue from '@/lib/useDebouncedValue'

import { useAdminCategories, useAdjustStock, useAdminInventory, useVariantLedger } from './api'
import {
  AdminError,
  AdminPageHeader,
  AdminPager,
  Callout,
  FormAlert,
  LoadingRowNote,
  SuccessNote,
} from './components/AdminUI'
import { ADJUSTMENT_REASONS, adjustmentSchema } from './schemas'
import { applyServerError } from './serverErrors'

const PAGE_SIZE = 24

const REASON_LABEL = Object.fromEntries(
  ADJUSTMENT_REASONS.map((reason) => [reason.value, reason.label.split(' — ')[0]]),
)

/*
 * The order state machine writes its own movements. They can never be typed
 * in by hand, and they are the reason a variant's stock can change without
 * anyone opening this screen.
 */
const SYSTEM_REASON_LABEL = {
  order_confirmed: 'Order confirmed',
  order_cancelled: 'Order cancelled',
  initial: 'Initial stock',
}

function reasonLabel(reason) {
  return REASON_LABEL[reason] ?? SYSTEM_REASON_LABEL[reason] ?? reason
}

function formatWhen(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** A signed delta, with the sign carried in words as well as in colour. */
function Delta({ value }) {
  const positive = value > 0
  return (
    <span className={positive ? 'font-medium text-success' : 'font-medium text-danger'}>
      {positive ? '+' : ''}
      {value}
    </span>
  )
}

/**
 * The movement history behind one variant's number.
 *
 * Shown inside the adjustment dialog rather than on a separate screen,
 * because it is the answer to the question the dialog raises: an admin told
 * "stock only moves with a reason" has to be able to read the reasons.
 * `logged_stock` is `sum(InventoryLog.delta)`; it is printed beside the
 * column so a drift between the two is visible rather than theoretical.
 */
function VariantLedger({ variantId }) {
  const ledger = useVariantLedger(variantId)

  if (ledger.isPending) {
    return (
      <div className="py-4">
        <Spinner label="Loading movement history" />
      </div>
    )
  }
  if (ledger.isError) return <AdminError error={ledger.error} title="Could not load the ledger" />

  const reconciles = ledger.data.stock === ledger.data.logged_stock

  return (
    <div className="mt-4 border-t border-line pt-4">
      <h3 className="text-sm font-semibold text-ink">Movement history</h3>
      <p className="mt-1 text-xs text-ink-muted">
        Stock on record: <strong>{ledger.data.stock}</strong> · sum of every
        logged movement: <strong>{ledger.data.logged_stock}</strong>{' '}
        {reconciles ? (
          <Badge tone="success" size="sm">
            Reconciled
          </Badge>
        ) : (
          <Badge tone="danger" size="sm">
            Does not reconcile
          </Badge>
        )}
      </p>

      <div className="mt-3 max-h-64 overflow-y-auto">
        <Table caption="Every recorded movement for this variant, most recent first">
          <THead>
            <TR>
              <TH>When</TH>
              <TH align="right">Change</TH>
              <TH>Reason</TH>
              <TH>By</TH>
            </TR>
          </THead>
          <TBody>
            {ledger.data.logs.length === 0 && (
              <EmptyRow colSpan={4}>No movements recorded yet.</EmptyRow>
            )}
            {ledger.data.logs.map((log) => (
              <TR key={log.id}>
                <TD>{formatWhen(log.created_at)}</TD>
                <TD align="right">
                  <Delta value={log.delta} />
                </TD>
                <TD>
                  <div>{reasonLabel(log.reason)}</div>
                  {log.note && <div className="text-xs text-ink-muted">{log.note}</div>}
                  {log.order_reference && (
                    <div className="text-xs text-ink-muted">Order {log.order_reference}</div>
                  )}
                </TD>
                <TD className="text-xs text-ink-muted">{log.actor_email ?? 'System'}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
    </div>
  )
}

function AdjustDialog({ row, onClose }) {
  const adjust = useAdjustStock()
  const [result, setResult] = useState(null)

  const {
    register,
    handleSubmit,
    reset,
    setError,
    watch,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(adjustmentSchema),
    defaultValues: { delta: '', reason: '', note: '' },
  })

  const delta = watch('delta')
  const projected =
    delta && /^-?\d+$/.test(delta.trim()) ? row.stock + Number(delta) : null

  const onSubmit = handleSubmit((values) => {
    adjust.mutate(
      {
        variant_id: row.id,
        delta: Number(values.delta),
        reason: values.reason,
        note: values.note.trim(),
      },
      {
        onSuccess: (data) => {
          setResult(data)
          reset({ delta: '', reason: '', note: '' })
        },
        onError: (error) =>
          applyServerError(error, setError, (parsed) => {
            // INSUFFICIENT_STOCK names `items`, which is the service's word
            // for the movement rather than a field on this form.
            if (parsed.field === 'items' || parsed.field === 'delta') return 'delta'
            if (parsed.field === 'reason') return 'reason'
            if (parsed.field === 'note') return 'note'
            return null
          }),
      },
    )
  })

  return (
    <Modal open onClose={onClose} size="lg" title={`Adjust stock — ${row.sku}`}>
      <p className="text-sm text-ink-muted">
        {row.product_name}
        {row.option_label ? ` · ${row.option_label}` : ''}
      </p>

      <form noValidate onSubmit={onSubmit} className="mt-4 flex flex-col gap-4">
        <FormAlert message={errors.root?.message} />
        {result && (
          <SuccessNote
            message={`Recorded ${result.log.delta > 0 ? '+' : ''}${result.log.delta} for ${reasonLabel(result.log.reason)}. Stock is now ${result.variant.stock}.`}
          />
        )}

        <div className="rounded-card bg-page px-3 py-2 text-sm">
          Current stock: <strong>{result ? result.variant.stock : row.stock}</strong>
          {projected !== null && !result && (
            <span className="ml-2 text-ink-muted">→ after this adjustment: {projected}</span>
          )}
        </div>

        <Input
          label="Change in units"
          required
          inputMode="numeric"
          error={errors.delta?.message}
          hint="Positive to add, negative to remove. e.g. 12 or -3."
          {...register('delta')}
        />

        <Select
          label="Reason"
          required
          placeholder="Choose a reason"
          error={errors.reason?.message}
          options={ADJUSTMENT_REASONS}
          hint="Mandatory (FR-INV-8). Order-driven movements are written by the order itself and cannot be chosen here."
          {...register('reason')}
        />

        <Textarea
          label="Note"
          rows={2}
          error={errors.note?.message}
          hint="Optional, but it is what someone reading this ledger in six months will have."
          {...register('note')}
        />

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button type="submit" loading={adjust.isPending}>
            Record adjustment
          </Button>
        </div>
      </form>

      <VariantLedger variantId={row.id} />
    </Modal>
  )
}

/**
 * Stock across every variant (US-A4), with the low-stock reorder list and the
 * one endpoint that may move a number.
 */
export default function AdminInventoryPage() {
  // `q` lives in the URL so the variant editor can link straight to a SKU.
  const [searchParams, setSearchParams] = useSearchParams()
  const search = searchParams.get('q') ?? ''
  const [category, setCategory] = useState('')
  // Seeded from the URL so the dashboard's low-stock tile opens the list it
  // counted rather than the unfiltered one (US-A1: a tile links to its rows).
  const [lowStock, setLowStock] = useState(searchParams.get('low_stock') === 'true')
  const [includeInactive, setIncludeInactive] = useState(false)
  const [page, setPage] = useState(1)
  const [adjusting, setAdjusting] = useState(null)

  const q = useDebouncedValue(search.trim(), 300)

  const inventory = useAdminInventory({
    q,
    category,
    low_stock: lowStock ? 'true' : '',
    include_inactive: includeInactive ? 'true' : '',
    page,
    page_size: PAGE_SIZE,
  })
  const categories = useAdminCategories()

  function setSearch(value) {
    setSearchParams(value ? { q: value } : {}, { replace: true })
    setPage(1)
  }

  const rows = inventory.data?.results ?? []
  const summary = inventory.data?.summary

  return (
    <div>
      <AdminPageHeader
        title="Inventory"
        description="Stock levels across every variant. A number only changes through an adjustment that records how many and why."
      />

      {summary && (
        <dl className="mb-4 grid gap-3 sm:grid-cols-3">
          {[
            { label: 'Variants tracked', value: summary.variant_count, tone: 'text-ink' },
            { label: 'At or below threshold', value: summary.low_stock_count, tone: 'text-warning' },
            { label: 'Out of stock', value: summary.out_of_stock_count, tone: 'text-danger' },
          ].map((tile) => (
            <div key={tile.label} className="rounded-card border border-line bg-white p-4">
              <dt className="text-sm text-ink-muted">{tile.label}</dt>
              <dd className={`mt-1 text-2xl font-semibold ${tile.tone}`}>{tile.value}</dd>
            </div>
          ))}
        </dl>
      )}

      <form
        role="search"
        aria-label="Filter inventory"
        onSubmit={(event) => event.preventDefault()}
        className="mb-4 grid gap-3 rounded-card border border-line bg-white p-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <Input
          label="Search"
          type="search"
          placeholder="SKU or product name"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Select
          label="Category"
          placeholder="All categories"
          value={category}
          onChange={(event) => {
            setCategory(event.target.value)
            setPage(1)
          }}
          options={(categories.data ?? []).map((row) => ({
            value: row.slug,
            label: row.parent_name ? `${row.parent_name} › ${row.name}` : row.name,
          }))}
        />
        <label className="flex min-h-[44px] items-center gap-2 self-end text-sm text-ink">
          <input
            type="checkbox"
            className="h-4 w-4 accent-action"
            checked={lowStock}
            onChange={(event) => {
              setLowStock(event.target.checked)
              setPage(1)
            }}
          />
          Low stock only (the reorder list)
        </label>
        <label className="flex min-h-[44px] items-center gap-2 self-end text-sm text-ink">
          <input
            type="checkbox"
            className="h-4 w-4 accent-action"
            checked={includeInactive}
            onChange={(event) => {
              setIncludeInactive(event.target.checked)
              setPage(1)
            }}
          />
          Include inactive variants
        </label>
      </form>

      {inventory.isError ? (
        <AdminError error={inventory.error} onRetry={() => inventory.refetch()} />
      ) : inventory.isPending ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" label="Loading inventory" />
        </div>
      ) : (
        <>
          <LoadingRowNote show={inventory.isFetching} label="Updating results" />
          <Table caption="Stock, thresholds and status for every variant">
            <THead>
              <TR>
                <TH>SKU</TH>
                <TH>Product</TH>
                <TH>Category</TH>
                <TH align="right">Stock</TH>
                <TH align="right">Threshold</TH>
                <TH align="center">Status</TH>
                <TH align="right">Actions</TH>
              </TR>
            </THead>
            <TBody>
              {rows.length === 0 && (
                <EmptyRow colSpan={7}>
                  {lowStock
                    ? 'Nothing is at or below its low-stock threshold.'
                    : 'No variants match these filters.'}
                </EmptyRow>
              )}
              {rows.map((row) => (
                <TR key={row.id}>
                  <TD>
                    <span className="font-medium text-ink">{row.sku}</span>
                    {row.option_label && (
                      <div className="text-xs text-ink-muted">{row.option_label}</div>
                    )}
                  </TD>
                  <TD>
                    <Link
                      to={`/admin/products/${row.product_id}`}
                      className="inline-flex min-h-[44px] items-center text-action hover:underline"
                    >
                      {row.product_name}
                    </Link>
                    {!row.product_is_active && (
                      <div className="text-xs text-ink-muted">Product inactive</div>
                    )}
                  </TD>
                  <TD>{row.category_name ?? '—'}</TD>
                  <TD align="right">
                    <span
                      className={
                        row.stock === 0
                          ? 'font-semibold text-danger'
                          : row.is_low_stock
                            ? 'font-semibold text-warning'
                            : 'font-medium'
                      }
                    >
                      {row.stock}
                    </span>
                  </TD>
                  <TD align="right">{row.low_stock_threshold}</TD>
                  <TD align="center">
                    {row.stock === 0 ? (
                      <Badge tone="danger" size="sm">
                        Out of stock
                      </Badge>
                    ) : row.is_low_stock ? (
                      <Badge tone="warning" size="sm">
                        Low
                      </Badge>
                    ) : (
                      <Badge tone="success" size="sm">
                        In stock
                      </Badge>
                    )}
                  </TD>
                  <TD align="right">
                    <Button size="sm" variant="outline" onClick={() => setAdjusting(row)}>
                      Adjust
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>

          <AdminPager
            page={page}
            count={inventory.data?.count ?? 0}
            pageSize={PAGE_SIZE}
            onChange={setPage}
          />
        </>
      )}

      <Callout tone="info" className="mt-5">
        Every movement — an adjustment made here, a confirmed order, a
        cancellation — writes one append-only ledger row. Summing those rows
        must equal the stock on record, which is why stock is not an editable
        field anywhere else in this dashboard. Open any variant&rsquo;s
        adjustment dialog to read its history.
      </Callout>

      {adjusting && <AdjustDialog row={adjusting} onClose={() => setAdjusting(null)} />}
    </div>
  )
}
