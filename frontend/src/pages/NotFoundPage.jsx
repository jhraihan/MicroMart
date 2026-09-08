import { Link } from 'react-router-dom'

import { Button } from '@/components/ui'

export default function NotFoundPage() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-4 text-center">
      <p className="text-5xl font-semibold text-action">404</p>
      <h1 className="mt-3 text-xl font-semibold text-ink">Page not found</h1>
      <p className="mt-2 text-sm text-ink-muted">
        That page does not exist, or it has moved.
      </p>
      <Button className="mt-6" onClick={() => window.history.back()}>
        Go back
      </Button>
      <Link
        to="/"
        className="mt-3 inline-flex min-h-[44px] items-center text-sm font-medium text-action hover:underline"
      >
        Return to the store
      </Link>
    </div>
  )
}
