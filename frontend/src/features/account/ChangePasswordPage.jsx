import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import { Button, Input } from '@/components/ui'
import { changePasswordSchema } from '@/features/auth/schemas'
import { parseApiError } from '@/lib/api'
import { useSeo } from '@/lib/seo'

import { useChangePassword } from './api'

/*
 * Change password.
 *
 * The current password is required, which is what stops a borrowed unlocked
 * browser from becoming a permanent account takeover.
 *
 * Changing the password also signs the account out everywhere else:
 * `change_password` in accounts/services/auth.py blacklists every refresh
 * token the user still holds. The note below says so, because someone who
 * thinks their account is compromised needs to know this already worked.
 */
export default function ChangePasswordPage() {
  useSeo({ title: 'Change password', canonical: '/account/password', noIndex: true })

  const changePassword = useChangePassword()
  const [saved, setSaved] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(changePasswordSchema) })

  async function onSubmit(values) {
    setSaved(false)
    try {
      await changePassword.mutateAsync({
        current_password: values.current_password,
        new_password: values.new_password,
      })
      reset()
      setSaved(true)
    } catch (err) {
      const { message, field } = parseApiError(err)
      // The server checks things the client cannot, such as whether the
      // password is on its common-password list. Put the message on the field
      // it belongs to when the API names one.
      setError(field && field in values ? field : 'root', { message })
    }
  }

  return (
    <section className="rounded-card bg-white p-4 shadow-el-1">
      <h2 className="text-base font-semibold text-ink">Change password</h2>
      <p className="mt-0.5 text-sm text-ink-muted">
        Use at least 8 characters. A password of only numbers is not accepted.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="mt-4 flex max-w-md flex-col gap-3">
        {errors.root && (
          <p role="alert" className="text-sm text-danger">
            {errors.root.message}
          </p>
        )}

        <Input
          label="Current password"
          type="password"
          autoComplete="current-password"
          required
          error={errors.current_password?.message}
          {...register('current_password')}
        />
        <Input
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          error={errors.new_password?.message}
          {...register('new_password')}
        />
        <Input
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          required
          error={errors.confirm_password?.message}
          {...register('confirm_password')}
        />

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : 'Change password'}
          </Button>
          {saved && (
            <p role="status" className="text-sm text-success">
              Password changed. You have been signed out on all other devices.
            </p>
          )}
        </div>
      </form>

      <p className="mt-4 rounded-card bg-page p-3 text-xs leading-relaxed text-ink-muted">
        Changing your password signs you out on every other device. You will
        stay signed in here, so this is the quickest way to remove anyone else
        who has access to your account.
      </p>
    </section>
  )
}
