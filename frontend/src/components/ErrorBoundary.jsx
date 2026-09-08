import { Component } from 'react'

/*
 * The last safety net. React unmounts the whole tree when a render throws, so
 * without this the user gets a blank white page.
 *
 * The router has its own errorElement, which is nicer because it keeps the
 * header and nav in place. This one catches what happens outside the router.
 *
 * It has to be a class -- React has no hook version of componentDidCatch.
 */
export default class ErrorBoundary extends Component {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    console.error('Unhandled render error:', error, info)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="flex min-h-screen flex-col items-center justify-center px-4 text-center">
        <h1 className="text-xl font-semibold text-ink">Something went wrong</h1>
        <p className="mt-2 max-w-sm text-sm text-ink-muted">
          The page failed to load. Reloading usually fixes it.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-6 inline-flex min-h-[44px] items-center rounded-card bg-action px-4 text-sm font-medium text-white hover:bg-action-hover"
        >
          Reload the page
        </button>
      </div>
    )
  }
}
