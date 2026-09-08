import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { Button, Input } from '@/components/ui'
import { api, parseApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useCartStore } from '@/stores/cartStore'

import DemoCredentials from './DemoCredentials'
import { loginSchema } from './schemas'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const signIn = useAuthStore((s) => s.signIn)
  const cartItems = useCartStore((s) => s.items)
  const mergePayload = useCartStore((s) => s.mergePayload)
  const clearCart = useCartStore((s) => s.clear)

  const {
    register,
    handleSubmit,
    setError,
    setValue,
    formState: { errors },
  } = useForm({ resolver: zodResolver(loginSchema) })

  const mutation = useMutation({
    mutationFn: async (values) => {
      const { data } = await api.post('/auth/login/', values)
      return data
    },
    onSuccess: async (data) => {
      signIn(data)
      // Hand the guest cart to the server, then drop the local copy so the
      // two can't drift (PRD §5.3).
      if (cartItems.length) {
        try {
          await api.post('/cart/merge/', { items: mergePayload() })
          clearCart()
        } catch {
          // A failed merge must not block sign-in; the local cart survives.
        }
      }
      navigate(location.state?.from ?? '/', { replace: true })
    },
    onError: (error) => {
      const { message, field } = parseApiError(error)
      setError(field && field in errors ? field : 'root', { message })
    },
  })

  return (
    <div className="mx-auto w-full max-w-md px-4 py-10">
      <h1 className="mb-1 text-2xl font-semibold text-ink">Sign in</h1>
      <p className="mb-6 text-sm text-ink-muted">
        New here?{' '}
        <Link to="/register" className="font-medium text-action hover:underline">
          Create an account
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
          label="Email"
          type="email"
          autoComplete="email"
          required
          error={errors.email?.message}
          {...register('email')}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          error={errors.password?.message}
          {...register('password')}
        />

        <div className="text-right">
          <Link
            to="/forgot-password"
            className="inline-flex min-h-[44px] items-center text-sm font-medium text-action hover:underline"
          >
            Forgot password?
          </Link>
        </div>

        <Button type="submit" fullWidth loading={mutation.isPending}>
          Sign in
        </Button>
      </form>

      <DemoCredentials
        onPick={(account) => {
          // shouldValidate clears any stale error left from a failed attempt.
          setValue('email', account.email, { shouldValidate: true })
          setValue('password', account.password, { shouldValidate: true })
        }}
      />
    </div>
  )
}
