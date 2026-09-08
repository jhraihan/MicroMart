import { useEffect, useState } from 'react'

import { Button } from '@/components/ui'
import { parseApiError } from '@/lib/api'
import { useSeo } from '@/lib/seo'

import { useMe, useUpdateProfile } from './api'

/*
 * Name and phone only.
 *
 * Email is shown but not editable, and that is a decision rather than an
 * omission: changing the address an account is identified by is a
 * re-verification flow, not a field edit, and the API refuses it
 * (`read_only_fields` on UserSerializer). Rendering a disabled input with the
 * reason beside it is more honest than hiding the field and leaving someone
 * hunting for it.
 */
export default function ProfilePage() {
  useSeo({ title: 'Profile', canonical: '/account/profile', noIndex: true })

  const { data: me, isPending } = useMe()
  const updateProfile = useUpdateProfile()

  const [form, setForm] = useState({ full_name: '', phone: '' })
  const [status, setStatus] = useState({ kind: 'idle', message: '' })

  // Seeded once the profile arrives. Keyed on the fetched values rather than
  // running on every render, so typing is never overwritten by a refetch.
  useEffect(() => {
    if (me) setForm({ full_name: me.full_name ?? '', phone: me.phone ?? '' })
  }, [me])

  async function submit(event) {
    event.preventDefault()
    setStatus({ kind: 'idle', message: '' })
    try {
      await updateProfile.mutateAsync(form)
      setStatus({ kind: 'success', message: 'Profile updated.' })
    } catch (err) {
      setStatus({
        kind: 'error',
        message: parseApiError(err).message || 'Those details could not be saved.',
      })
    }
  }

  if (isPending) {
    return <div className="h-64 animate-pulse rounded-card bg-white shadow-el-1" />
  }

  return (
    <section className="rounded-card bg-white p-4 shadow-el-1">
      <h2 className="text-base font-semibold text-ink">Profile</h2>
      <p className="mt-0.5 text-sm text-ink-muted">
        The name and number we use on deliveries.
      </p>

      <form onSubmit={submit} className="mt-4 flex max-w-md flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="email" className="text-sm font-medium text-ink">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={me?.email ?? ''}
            disabled
            className="h-11 rounded-card border border-line bg-page px-3 text-base text-ink-muted"
          />
          <p className="text-xs text-ink-muted">
            Your email identifies the account and cannot be changed here.
            Contact support if you need it moved.
          </p>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="full_name" className="text-sm font-medium text-ink">
            Full name
          </label>
          <input
            id="full_name"
            value={form.full_name}
            maxLength={150}
            onChange={(event) => setForm({ ...form, full_name: event.target.value })}
            className="h-11 rounded-card border border-line px-3 text-base text-ink focus:border-action"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="phone" className="text-sm font-medium text-ink">
            Phone
          </label>
          <input
            id="phone"
            type="tel"
            value={form.phone}
            maxLength={20}
            onChange={(event) => setForm({ ...form, phone: event.target.value })}
            className="h-11 rounded-card border border-line px-3 text-base text-ink focus:border-action"
          />
          <p className="text-xs text-ink-muted">
            Couriers call this number, so keep it one you answer.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={updateProfile.isPending}>
            {updateProfile.isPending ? 'Saving…' : 'Save changes'}
          </Button>
          <p role="status" aria-live="polite" className="text-sm">
            <span
              className={status.kind === 'error' ? 'text-danger' : 'text-success'}
            >
              {status.message}
            </span>
          </p>
        </div>
      </form>
    </section>
  )
}
