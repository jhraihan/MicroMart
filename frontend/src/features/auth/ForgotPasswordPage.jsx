import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { Button } from '@/components/ui'
import {
  useConfirmPasswordReset,
  useRequestPasswordReset,
} from '@/features/account/api'
import { parseApiError } from '@/lib/api'
import { useSeo } from '@/lib/seo'

// Password reset, both halves in one route.
export default function ForgotPasswordPage() {
  const [searchParams] = useSearchParams()
  const uid = searchParams.get('uid')
  const token = searchParams.get('token')
  const isConfirming = Boolean(uid && token)

  useSeo({
    title: isConfirming ? 'Set a new password' : 'Reset your password',
    canonical: '/forgot-password',
    noIndex: true,
  })

  return (
    <div className="mx-auto w-full max-w-md px-4 py-10">
      <h1 className="text-xl font-semibold text-ink">
        {isConfirming ? 'Set a new password' : 'Reset your password'}
      </h1>

      {isConfirming ? (
        <ConfirmForm uid={uid} token={token} />
      ) : (
        <RequestForm />
      )}

      <p className="mt-6 text-sm text-ink-muted">
        Remembered it?{' '}
        <Link to="/login" className="font-semibold text-action hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  )
}

function RequestForm() {
  const requestReset = useRequestPasswordReset()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)

  async function submit(event) {
    event.preventDefault()
    try {
      await requestReset.mutateAsync({ email })
    } catch {
      // Swallowed on purpose. A failure here is either "no such account" or a
      // transient error, and distinguishing them for the caller is exactly
      // the enumeration leak this flow avoids. A genuine outage still shows
      // up in the server logs.
    }
    setSent(true)
  }

  if (sent) {
    return (
      <div className="mt-4 rounded-card bg-white p-4 shadow-el-1">
        <p className="text-sm text-ink">
          If an account exists for <span className="font-medium">{email}</span>,
          we have sent it a link to reset the password.
        </p>
        <p className="mt-2 text-sm text-ink-muted">
          The link is valid for a short time. Check your spam folder if it does
          not arrive within a few minutes.
        </p>
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="mt-4 flex flex-col gap-3">
      <p className="text-sm text-ink-muted">
        Enter the email address on your account and we will send a reset link.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="reset-email" className="text-sm font-medium text-ink">
          Email
        </label>
        <input
          id="reset-email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="h-11 rounded-card border border-line px-3 text-base text-ink focus:border-action"
        />
      </div>

      <Button type="submit" disabled={requestReset.isPending}>
        {requestReset.isPending ? 'Sending…' : 'Send reset link'}
      </Button>
    </form>
  )
}

function ConfirmForm({ uid, token }) {
  const confirmReset = useConfirmPasswordReset()
  const [form, setForm] = useState({ next: '', confirm: '' })
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')

    if (form.next !== form.confirm) {
      setError('The two passwords do not match.')
      return
    }

    try {
      await confirmReset.mutateAsync({ uid, token, new_password: form.next })
      setDone(true)
    } catch (err) {
      setError(
        parseApiError(err).message ||
          'That reset link is no longer valid. Request a new one.',
      )
    }
  }

  if (done) {
    return (
      <div className="mt-4 rounded-card bg-white p-4 shadow-el-1">
        <p className="text-sm text-ink">Your password has been reset.</p>
        <Link
          to="/login"
          className="mt-4 inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-semibold text-white hover:bg-action-hover"
        >
          Sign in
        </Link>
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="mt-4 flex flex-col gap-3">
      <p className="text-sm text-ink-muted">
        Choose a new password of at least 8 characters.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="new-password" className="text-sm font-medium text-ink">
          New password
        </label>
        <input
          id="new-password"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={form.next}
          onChange={(event) => setForm({ ...form, next: event.target.value })}
          className="h-11 rounded-card border border-line px-3 text-base text-ink focus:border-action"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="confirm-password" className="text-sm font-medium text-ink">
          Confirm new password
        </label>
        <input
          id="confirm-password"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={form.confirm}
          onChange={(event) => setForm({ ...form, confirm: event.target.value })}
          className="h-11 rounded-card border border-line px-3 text-base text-ink focus:border-action"
        />
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <Button type="submit" disabled={confirmReset.isPending}>
        {confirmReset.isPending ? 'Saving…' : 'Set new password'}
      </Button>
    </form>
  )
}
