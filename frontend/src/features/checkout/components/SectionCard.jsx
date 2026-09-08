/*
 * One numbered block of the single-page checkout (FR-CHK-1). Numbering the
 * sections gives a phone user a sense of position without a wizard, and the
 * wizard is what we are avoiding -- every step stays on one scrollable page
 * so nothing is hidden behind a "next" button.
 */
export default function SectionCard({ step, title, description, action, children }) {
  return (
    <section
      aria-labelledby={`checkout-step-${step}`}
      className="rounded-card border border-line bg-white p-4"
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2
            id={`checkout-step-${step}`}
            className="flex items-center gap-2 text-base font-semibold text-ink"
          >
            <span
              aria-hidden="true"
              className="flex h-6 w-6 items-center justify-center rounded-pill bg-tint text-xs font-bold text-action"
            >
              {step}
            </span>
            {title}
          </h2>
          {description && <p className="mt-1 text-xs text-ink-muted">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}
