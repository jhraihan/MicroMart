import clsx from 'clsx'
import { NavLink, Outlet } from 'react-router-dom'

import { useAuthStore } from '@/stores/authStore'

/*
 * Shell for the account area.
 *
 * A sidebar on desktop, a horizontally scrolling tab strip on mobile -- the
 * same links either way. Shrinking a vertical sidebar into a phone viewport
 * either eats a third of the screen or collapses into a menu nobody opens;
 * a tab strip is what the shape of the content actually wants.
 *
 * The guard that gets you here is in routes/guards.jsx. Nothing on these
 * screens depends on it for security: every endpoint behind them answers for
 * the authenticated user alone, so the guard only saves a round trip to a 401.
 */

const LINKS = [
  { to: '/account', label: 'Overview', end: true },
  { to: '/orders', label: 'Orders' },
  { to: '/account/addresses', label: 'Addresses' },
  { to: '/wishlist', label: 'Wishlist' },
  { to: '/account/profile', label: 'Profile' },
  { to: '/account/password', label: 'Password' },
]

export default function AccountLayout() {
  const user = useAuthStore((s) => s.user)
  const signOut = useAuthStore((s) => s.signOut)

  return (
    <div className="px-4 py-5">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-ink sm:text-2xl">My account</h1>
        {user && (
          <p className="mt-1 text-sm text-ink-muted">
            Signed in as <span className="font-medium text-ink">{user.email}</span>
          </p>
        )}
      </header>

      <div className="grid gap-4 lg:grid-cols-[200px_minmax(0,1fr)] lg:items-start">
        <nav aria-label="Account" className="lg:sticky lg:top-32">
          <ul className="flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
            {LINKS.map((link) => (
              <li key={link.to} className="shrink-0 lg:shrink">
                <NavLink
                  to={link.to}
                  end={link.end}
                  className={({ isActive }) =>
                    clsx(
                      'flex min-h-[44px] items-center whitespace-nowrap rounded-card px-3 text-sm lg:w-full',
                      isActive
                        ? 'bg-tint font-semibold text-action'
                        : 'text-ink hover:bg-tint hover:text-action',
                    )
                  }
                >
                  {link.label}
                </NavLink>
              </li>
            ))}
            <li className="shrink-0 lg:shrink lg:pt-2">
              <button
                type="button"
                onClick={signOut}
                className="flex min-h-[44px] w-full items-center whitespace-nowrap rounded-card px-3 text-sm text-ink-muted hover:text-danger lg:border-t lg:border-line"
              >
                Sign out
              </button>
            </li>
          </ul>
        </nav>

        <div className="min-w-0">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
