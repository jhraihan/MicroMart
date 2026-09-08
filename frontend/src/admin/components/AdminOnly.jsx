import { Link, Outlet } from 'react-router-dom'

import { useAuthStore } from '@/stores/authStore'

// The staff/admin split (PRD §4.3 US-A8, US-T2).
export function AdminForbidden({ title = 'Restricted to the store owner' }) {
  return (
    <div className="mx-auto max-w-xl rounded-card border border-line bg-white p-6 text-center shadow-el-1">
      <h1 className="text-lg font-semibold text-ink">{title}</h1>
      <p className="mt-3 text-sm text-ink-muted">
        Your account can view orders and move them through the fulfilment
        pipeline. Editing the catalogue, stock, coupons, reviews and store
        settings is limited to an admin account, and the server refuses those
        requests regardless of what this screen shows.
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        <Link
          to="/admin/orders"
          className="inline-flex min-h-[44px] items-center rounded-card border-2 border-action bg-action px-4 text-sm font-medium text-white hover:bg-action-hover"
        >
          Go to orders
        </Link>
        <Link
          to="/"
          className="inline-flex min-h-[44px] items-center rounded-card border-2 border-action px-4 text-sm font-medium text-action hover:bg-action hover:text-white"
        >
          View store
        </Link>
      </div>
    </div>
  )
}

/** Route guard for the admin-only half of the dashboard. */
export default function AdminOnly() {
  const role = useAuthStore((s) => s.user?.role)
  return role === 'admin' ? <Outlet /> : <AdminForbidden />
}
