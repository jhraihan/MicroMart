import { create } from 'zustand'

import { api, setAccessToken, refreshAccessToken } from '@/lib/api'

/*
 * Auth state is deliberately NOT persisted. The access token lives in memory
 * (lib/api.js) and the refresh token in an HttpOnly cookie; on a page reload
 * the app calls bootstrap() and silently re-authenticates from that cookie.
 *
 * `user.role` here drives route guards only. It is a convenience, never the
 * security boundary -- the API enforces authorisation (PRD §10.2).
 */
export const useAuthStore = create((set, get) => ({
  user: null,
  status: 'idle', // idle | loading | authenticated | anonymous

  isAuthenticated: () => get().user !== null,
  isAdminOrStaff: () => ['admin', 'staff'].includes(get().user?.role),
  isAdmin: () => get().user?.role === 'admin',

  async bootstrap() {
    if (get().status === 'loading') return
    set({ status: 'loading' })
    try {
      await refreshAccessToken()
      const { data } = await api.get('/auth/me/')
      set({ user: data, status: 'authenticated' })
    } catch {
      setAccessToken(null)
      set({ user: null, status: 'anonymous' })
    }
  },

  signIn({ access, user }) {
    setAccessToken(access)
    set({ user, status: 'authenticated' })
  },

  setUser(user) {
    set({ user })
  },

  async signOut() {
    try {
      await api.post('/auth/logout/')
    } catch {
      // Logout is idempotent server-side; a failure here still clears locally.
    }
    setAccessToken(null)
    set({ user: null, status: 'anonymous' })
  },
}))
