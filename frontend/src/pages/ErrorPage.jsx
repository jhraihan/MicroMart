import { Link, useRouteError } from 'react-router-dom'

import { Button } from '@/components/ui'

export default function ErrorPage() {
  const error = useRouteError()

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-4 text-center">
      <p className="text-5xl font-semibold text-action">Oops</p>
      <h1 className="mt-3 text-xl font-semibold text-ink">Something went wrong</h1>
      <p className="mt-2 max-w-sm text-sm text-ink-muted">
        This page failed to load. Reloading usually fixes it.
      </p>
      <Button className="mt-6" onClick={() => window.location.reload()}>
        Reload the page
      </Button>
      <Link
        to="/"
        className="mt-3 inline-flex min-h-[44px] items-center text-sm font-medium text-action hover:underline"
      >
        Return to the store
      </Link>

      {import.meta.env.DEV && error ? (
        <pre className="mt-8 max-w-full overflow-x-auto rounded-card bg-page p-3 text-left text-xs text-ink-muted">
          {error.stack || error.message || String(error)}
        </pre>
      ) : null}
    </div>
  )
}
