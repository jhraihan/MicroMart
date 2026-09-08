import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { PageSpinner } from '@/components/ui'
import { useAuthStore } from '@/stores/authStore'

/*
 * Route guards are a convenience, never the security boundary. The API
 * enforces authorisation on every request (PRD §8.3, §10.2) -- hiding a route
 * here only saves the user a pointless round trip.
 */

export function RequireAuth() {
  const status = useAuthStore((s) => s.status)
  const user = useAuthStore((s) => s.user)
  const location = useLocation()

  if (status === 'idle' || status === 'loading') return <PageSpinner />
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}

export function RequireAdmin() {
  const status = useAuthStore((s) => s.status)
  const user = useAuthStore((s) => s.user)
  const location = useLocation()

  if (status === 'idle' || status === 'loading') return <PageSpinner />
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (!['admin', 'staff'].includes(user.role)) {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}
