import { useEffect } from 'react'

import { useAuthStore } from '@/stores/authStore'

import { useWishlistMutations } from './api'
import { takeWishlistIntent } from './intent'

/*
 * The second half of FR-WSH-4: complete the parked add once the shopper is
 * authenticated.
 */
export function useWishlistIntentReplay() {
  const user = useAuthStore((s) => s.user)
  const { add } = useWishlistMutations()
  const addToWishlist = add.mutate

  useEffect(() => {
    if (!user) return
    const productId = takeWishlistIntent()
    if (productId != null) addToWishlist(productId)
  }, [user, addToWishlist])
}
