// Seeded demo logins, offered as one-tap fill.
const ACCOUNTS = [
  {
    role: 'Customer',
    email: 'shopper@example.com',
    password: 'Str0ngPass!2026',
    note: 'Normal storefront account.',
  },
  {
    role: 'Admin',
    email: 'admin@example.com',
    password: 'ChangeMe!2026',
    note: 'Unlocks /admin and Django admin.',
  },
]

export default function DemoCredentials({ onPick }) {
  // Compared as a string: Vite exposes env vars verbatim, so an unset
  // variable is undefined and anything other than the exact opt-in is off.
  if (import.meta.env.VITE_SHOW_DEMO_CREDENTIALS !== 'true') return null

  return (
    <section
      aria-labelledby="demo-accounts-heading"
      className="mt-5 rounded-card border border-dashed border-line bg-tint p-4"
    >
      <h2
        id="demo-accounts-heading"
        className="text-xs font-semibold uppercase tracking-wide text-ink-muted"
      >
        Demo accounts &mdash; try the store
      </h2>

      <ul className="mt-3 flex flex-col gap-2">
        {ACCOUNTS.map((account) => (
          <li
            key={account.email}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-card bg-white px-3 py-2"
          >
            <span className="text-xs font-semibold text-action">{account.role}</span>

            <span className="min-w-0 flex-1 break-all font-mono text-xs text-ink">
              {account.email}
              <span className="text-ink-muted"> / </span>
              {account.password}
            </span>

            <button
              type="button"
              onClick={() => onPick(account)}
              className="inline-flex min-h-[44px] items-center rounded-card px-3 text-xs font-medium text-action hover:bg-tint"
            >
              Use this
              <span className="sr-only"> {account.role} account</span>
            </button>

            <span className="sr-only">{account.note}</span>
          </li>
        ))}
      </ul>

      <p className="mt-2 text-xs text-ink-muted">
        Shared demo accounts on a demonstration store &mdash; anyone can sign in with
        them, so treat anything you enter here as public.
      </p>
    </section>
  )
}
