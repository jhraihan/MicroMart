import clsx from 'clsx'

// The verdict panel.

const LEVEL_STYLES = {
  error: {
    wrap: 'border-danger/30 bg-danger/5',
    dot: 'bg-danger',
    label: 'Problem',
  },
  warning: {
    wrap: 'border-warning/30 bg-warning/5',
    dot: 'bg-warning',
    label: 'Worth checking',
  },
  info: {
    wrap: 'border-line bg-page',
    dot: 'bg-ink-subtle',
    label: 'Note',
  },
}

export default function CompatibilityPanel({ report, isFetching, slots = [] }) {
  if (!report) {
    return (
      <div className="rounded-card bg-white p-4 shadow-el-1">
        <h2 className="text-base font-semibold text-ink">Compatibility</h2>
        <p className="mt-2 text-sm text-ink-muted">
          Choose a processor to start. We will check each part you add against
          the ones already in the build.
        </p>
      </div>
    )
  }

  const labelFor = (slot) =>
    slots.find((entry) => entry.slot === slot)?.label ?? slot

  const errors = report.findings.filter((f) => f.level === 'error')
  const warnings = report.findings.filter((f) => f.level === 'warning')
  const notes = report.findings.filter((f) => f.level === 'info')

  return (
    <div className="rounded-card bg-white p-4 shadow-el-1">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-ink">Compatibility</h2>
        {isFetching && <span className="text-xs text-ink-muted">Checking…</span>}
      </div>

      {/* One headline banner, and it reflects the worse of the two states. */}
      <div
        role="status"
        aria-live="polite"
        className={clsx(
          'mt-3 flex items-start gap-2 rounded-card border p-3 text-sm',
          errors.length > 0
            ? 'border-danger/30 bg-danger/5 text-danger'
            : 'border-success/30 bg-success/5 text-success',
        )}
      >
        <span aria-hidden="true" className="mt-0.5">
          {errors.length > 0 ? '✕' : '✓'}
        </span>
        <span className="font-medium">
          {errors.length > 0
            ? `${errors.length} compatibility problem${errors.length > 1 ? 's' : ''} to fix`
            : 'No compatibility problems found'}
        </span>
      </div>

      {report.missing_slots.length > 0 && (
        <div className="mt-2 rounded-card border border-line bg-page p-3 text-sm">
          <p className="font-medium text-ink">Still needed</p>
          <p className="mt-0.5 text-ink-muted">
            {report.missing_slots.map(labelFor).join(', ')}
          </p>
        </div>
      )}

      {(errors.length > 0 || warnings.length > 0 || notes.length > 0) && (
        <ul className="mt-3 flex flex-col gap-2">
          {[...errors, ...warnings, ...notes].map((finding) => {
            const style = LEVEL_STYLES[finding.level] ?? LEVEL_STYLES.info
            return (
              <li
                key={`${finding.code}-${finding.slots.join('-')}`}
                className={clsx('flex gap-2 rounded-card border p-3 text-sm', style.wrap)}
              >
                <span
                  aria-hidden="true"
                  className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-pill', style.dot)}
                />
                <span className="min-w-0">
                  <span className="block text-xs font-semibold uppercase tracking-wide text-ink-muted">
                    {style.label}
                  </span>
                  <span className="block text-ink">{finding.message}</span>
                </span>
              </li>
            )
          })}
        </ul>
      )}

      {report.power_is_estimated && (
        <p className="mt-3 text-xs text-ink-muted">
          Some parts carry no published power figure, so typical values were
          used. Treat the wattage as an estimate.
        </p>
      )}

      <p className="mt-3 border-t border-line pt-3 text-xs leading-relaxed text-ink-muted">
        {report.advisory}
      </p>
    </div>
  )
}
