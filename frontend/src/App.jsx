import { QueryClientProvider } from '@tanstack/react-query'
import { useEffect } from 'react'
import { RouterProvider } from 'react-router-dom'

import { queryClient } from '@/lib/queryClient'
import { router } from '@/routes'
import { useAuthStore } from '@/stores/authStore'

export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap)

  // On load, try to trade the HttpOnly refresh cookie for an access token.
  // Nothing is read from localStorage -- there is nothing there to read.
  useEffect(() => {
    bootstrap()
  }, [bootstrap])

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
