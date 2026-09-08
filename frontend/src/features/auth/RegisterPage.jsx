import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'

import { Button, Input } from '@/components/ui'
import { api, parseApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'

import { registerSchema } from './schemas'

export default function RegisterPage() {
  const navigate = useNavigate()
  const signIn = useAuthStore((s) => s.signIn)

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm({ resolver: zodResolver(registerSchema) })

  const mutation = useMutation({
    mutationFn: async ({ confirm_password: _ignored, ...values }) => {
      const { data } = await api.post('/auth/register/', values)
      return data
    },
    onSuccess: (data) => {
      signIn(data)
      navigate('/', { replace: true })
    },
    onError: (error) => {
      const { message, field } = parseApiError(error)
      setError(field ?? 'root', { message })
    },
  })

  return (
    <div className="mx-auto w-full max-w-md px-4 py-10">
      <h1 className="mb-1 text-2xl font-semibold text-ink">Create your account</h1>
      <p className="mb-6 text-sm text-ink-muted">
        Already registered?{' '}
        <Link to="/login" className="font-medium text-action hover:underline">
          Sign in
        </Link>
      </p>

      <form
        noValidate
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
        className="flex flex-col gap-4 rounded-card bg-white p-5 shadow-el-1"
      >
        {errors.root && (
          <p role="alert" className="rounded-card bg-danger/10 px-3 py-2 text-sm text-danger">
            {errors.root.message}
          </p>
        )}

        <Input
          label="Full name"
          autoComplete="name"
          required
          error={errors.full_name?.message}
          {...register('full_name')}
        />
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          required
          error={errors.email?.message}
          {...register('email')}
        />
        <Input
          label="Mobile number"
          type="tel"
          inputMode="numeric"
          autoComplete="tel"
          hint="Optional. Used for delivery updates."
          placeholder="01XXXXXXXXX"
          error={errors.phone?.message}
          {...register('phone')}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          hint="At least 8 characters."
          error={errors.password?.message}
          {...register('password')}
        />
        <Input
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          required
          error={errors.confirm_password?.message}
          {...register('confirm_password')}
        />

        <Button type="submit" fullWidth loading={mutation.isPending}>
          Create account
        </Button>
      </form>
    </div>
  )
}
