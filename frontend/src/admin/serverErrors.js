import { parseApiError } from '@/lib/api'

// Turning the API's error envelope into per-field messages.

export function isForbidden(error) {
  return error?.response?.status === 403
}

export function isNotFound(error) {
  return error?.response?.status === 404
}

/**
 * Restrict which server field names may become form paths.
 *
 * A whitelist rather than a pass-through: `setError` on an unregistered path
 * silently swallows the message, so an unknown field name has to fall back to
 * the root alert or the admin sees nothing at all.
 */
export function pathResolver(allowed) {
  const known = new Set(allowed)
  return (parsed) => (known.has(parsed.field) ? parsed.field : null)
}

/**
 * Attach a failed request to the form.
 *
 * Returns the parsed envelope so a caller can branch on `code` -- codes are
 * stable, messages are not (PRD §7.1).
 */
export function applyServerError(error, setError, resolvePath) {
  const parsed = parseApiError(error)
  const path = parsed.field && typeof resolvePath === 'function' ? resolvePath(parsed) : null
  setError(path || 'root', { type: 'server', message: parsed.message })
  return parsed
}

/*
 * The envelope reports one field name, and for an error inside a nested list
 * the backend contract (docs/api-contract-admin-catalogue.md) says price and
 * stock are validated in the service precisely so the name is `price` rather
 * than `variants`. What it still cannot say is *which* variant, because the
 * service validates them one at a time and raises on the first failure.
 */
const QUOTED = /'([^']+)'/

export function resolveVariantPath(parsed, variants) {
  const field = parsed.field
  if (!field) return null

  const quoted = QUOTED.exec(parsed.message || '')?.[1]
  if (quoted) {
    const index = variants.findIndex(
      (variant) => String(variant?.[field] ?? '').trim() === quoted,
    )
    if (index >= 0) return `variants.${index}.${field}`
  }

  if (variants.length === 1) return `variants.0.${field}`
  return null
}
