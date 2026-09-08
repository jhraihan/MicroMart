import { Link, useLocation } from 'react-router-dom'

/*
 * What a signed-out visitor sees where an order would be.
 *
 * The server answers an unauthenticated order read with 401 and an
 * unauthorised one with 404, never 403 — a 403 would confirm the reference is
 * real (PRD §10.2). This screen therefore never claims the order does or does
 * not exist; it only says who is allowed to look.
 */
export default function SignInPrompt({
  title = 'Sign in to see your orders',
  message = 'Your order history is tied to your account.',
  children,
}) {
  const location = useLocation()

  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-card border border-line bg-white px-4 py-12 text-center">
      <h1 className="text-xl font-semibold text-ink">{title}</h1>
      <p className="text-sm text-ink-muted">{message}</p>
      {children}
      <Link
        to="/login"
        state={{ from: location.pathname }}
        className="inline-flex min-h-[44px] items-center rounded-card bg-action px-6 text-sm font-medium text-white hover:bg-action-hover"
      >
        Sign in
      </Link>
      <Link
        to="/"
        className="inline-flex min-h-[44px] items-center rounded-card px-4 text-sm font-medium text-action hover:underline"
      >
        Continue shopping
      </Link>
    </div>
  )
}
