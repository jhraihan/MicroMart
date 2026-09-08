import axios from 'axios'

/*
 * The access token is held in a module-scoped variable -- in memory only.
 * The refresh token lives in an HttpOnly cookie the browser sends automatically
 * and JavaScript cannot read. Neither ever goes into localStorage (PRD §10.1).
 */
let accessToken = null
const subscribers = new Set()

export function setAccessToken(token) {
  accessToken = token
  subscribers.forEach((fn) => fn(token))
}

export function getAccessToken() {
  return accessToken
}

export function onAccessTokenChange(fn) {
  subscribers.add(fn)
  return () => subscribers.delete(fn)
}

export const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true, // send the refresh cookie
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

/*
 * A single in-flight refresh shared by every 401. Without this, a page that
 * fires six queries on mount would kick off six rotations and blacklist five
 * of its own tokens.
 */
let refreshPromise = null

function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = axios
      .post(`${API_BASE}/auth/refresh/`, {}, { withCredentials: true })
      .then((res) => {
        setAccessToken(res.data.access)
        return res.data.access
      })
      .catch((err) => {
        setAccessToken(null)
        throw err
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error
    const isRefreshCall = config?.url?.includes('/auth/refresh/')

    if (response?.status === 401 && !config?._retried && !isRefreshCall) {
      config._retried = true
      try {
        const token = await refreshAccessToken()
        config.headers.Authorization = `Bearer ${token}`
        return api(config)
      } catch {
        return Promise.reject(error)
      }
    }
    return Promise.reject(error)
  },
)

export { refreshAccessToken }

/**
 * Unwrap the API's error envelope (PRD §7.1):
 *   {"error": {"code": "COUPON_EXPIRED", "message": "...", "field": "..."}}
 * Codes are stable and safe to branch on; messages are not.
 */
export function parseApiError(error) {
  const envelope = error?.response?.data?.error
  if (envelope) {
    return {
      code: envelope.code || 'ERROR',
      message: envelope.message || 'Something went wrong.',
      field: envelope.field || null,
      status: error.response.status,
    }
  }
  if (error?.code === 'ERR_NETWORK') {
    return {
      code: 'NETWORK_ERROR',
      message: 'Could not reach the server. Check your connection.',
      field: null,
      status: 0,
    }
  }
  return {
    code: 'ERROR',
    message: 'Something went wrong. Please try again.',
    field: null,
    status: error?.response?.status ?? 0,
  }
}
