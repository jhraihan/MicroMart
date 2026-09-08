import { NavLink, Outlet } from 'react-router-dom'

import { useAuthStore } from '@/stores/authStore'

/*
 * `adminOnly` mirrors the per-view role gating in the API (PRD §4.3 US-A8):
 * staff may read orders and move their status, and every other admin endpoint
 * answers them 403. Leaving those links visible would offer a staff member six
 * sections that all dead-end in a refusal.
 *
 * This is a convenience on top of that 403, never the access control. The
 * server refuses the request whether or not the link was drawn.
 */
const NAV = [
  { to: '/admin', label: 'Overview', end: true },
  { to: '/admin/orders', label: 'Orders' },
  { to: '/admin/products', label: 'Products', adminOnly: true },
  { to: '/admin/inventory', label: 'Inventory', adminOnly: true },
  { to: '/admin/taxonomy', label: 'Categories', adminOnly: true },
  { to: '/admin/coupons', label: 'Coupons', adminOnly: true },
  { to: '/admin/reviews', label: 'Reviews', adminOnly: true },
  { to: '/admin/customers', label: 'Customers', adminOnly: true },
  { to: '/admin/settings', label: 'Settings', adminOnly: true },
]

export default function AdminLayout() {
  const user = useAuthStore((s) => s.user)
  const sections = NAV.filter((item) => !item.adminOnly || user?.role === 'admin')

  return (
    <div className="flex min-h-screen flex-col bg-page">
      <a href="#admin-main" className="skip-link">
        Skip to main content
      </a>

      <header className="bg-chrome text-white">
        <div className="mx-auto flex min-h-14 max-w-7xl items-center gap-3 px-4">
          <NavLink
            to="/admin"
            className="flex min-h-[44px] items-center whitespace-nowrap text-lg font-semibold"
          >
            MicroMart Admin
          </NavLink>
          {/* Identity is useful, not load-bearing: at 360px the bar has room
              for the store link or the email, and the link is the one that
              does something. */}
          <span className="ml-auto hidden truncate text-sm text-ink-inverse sm:block">
            {user?.email}
          </span>
          <NavLink
            to="/"
            className="ml-auto min-h-[44px] whitespace-nowrap px-3 text-sm leading-[44px] hover:text-brand sm:ml-0"
          >
            View store
          </NavLink>
        </div>
        <nav aria-label="Admin sections" className="border-t border-white/10">
          <ul className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-2">
            {sections.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    [
                      'inline-flex min-h-[44px] items-center whitespace-nowrap px-3 text-sm',
                      isActive
                        ? 'border-b-2 border-brand font-medium text-white'
                        : 'text-ink-inverse hover:text-white',
                    ].join(' ')
                  }
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <main id="admin-main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
