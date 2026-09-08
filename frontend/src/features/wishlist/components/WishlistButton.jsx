import clsx from 'clsx'
import { useNavigate, useLocation } from 'react-router-dom'

import { parseApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'

import { useIsWishlisted, useWishlistMutations } from '../api'
import { rememberWishlistIntent } from '../intent'

/*
 * One-click save / unsave, for a product card and the product page
 * (FR-WSH-1).
 */
function Heart({ filled, className }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={filled ? 0 : 1.8}
      strokeLinejoin="round"
    >
      <path d="M12 20.6l-1.4-1.27C5.6 14.86 2.6 12.15 2.6 8.83 2.6 6.12 4.73 4 7.44 4c1.53 0 3 .71 3.96 1.84A5.27 5.27 0 0 1 15.36 4c2.71 0 4.84 2.12 4.84 4.83 0 3.32-3 6.03-8 10.5L12 20.6z" />
    </svg>
  )
}

export default function WishlistButton({ product, variant = 'icon', className }) {
  const user = useAuthStore((s) => s.user)
  const navigate = useNavigate()
  const location = useLocation()

  const saved = useIsWishlisted(product.id)
  const { add, remove } = useWishlistMutations()
  const busy = add.isPending || remove.isPending
  const failure = add.error ?? remove.error

  const label = saved
    ? `Remove ${product.name} from your wishlist`
    : `Save ${product.name} to your wishlist`

  function handleClick(event) {
    // A card wraps this control in a stretched link; without this the tap
    // would navigate to the product instead of saving it.
    event.preventDefault()
    event.stopPropagation()

    if (!user) {
      rememberWishlistIntent(product.id)
      navigate('/login', {
        state: { from: `${location.pathname}${location.search}` },
      })
      return
    }

    if (saved) remove.mutate(product.id)
    else add.mutate(product.id)
  }

  const shared = {
    type: 'button',
    onClick: handleClick,
    disabled: busy,
    'aria-pressed': user ? saved : undefined,
    'aria-label': variant === 'icon' ? label : undefined,
    title: label,
  }

  if (variant === 'icon') {
    return (
      <>
        <button
          {...shared}
          className={clsx(
            'flex h-11 w-11 items-center justify-center rounded-pill bg-white/90 shadow-el-1',
            'transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-55',
            saved ? 'text-price' : 'text-ink-muted hover:text-price',
            className,
          )}
        >
          <Heart filled={saved} className="h-5 w-5" />
        </button>
        <span role="status" aria-live="polite" className="sr-only">
          {failure ? parseApiError(failure).message : ''}
        </span>
      </>
    )
  }

  return (
    <div className={clsx('flex flex-col gap-1', className)}>
      <button
        {...shared}
        className={clsx(
          'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-card px-4 text-sm font-medium',
          'border-2 transition-colors disabled:cursor-not-allowed disabled:opacity-55',
          saved
            ? 'border-price bg-white text-price'
            : 'border-line bg-white text-ink hover:border-action hover:text-action',
        )}
      >
        <Heart filled={saved} className="h-5 w-5" />
        {saved ? 'Saved to wishlist' : 'Save for later'}
      </button>
      <p role="status" aria-live="polite" className="min-h-[16px] text-xs text-danger">
        {failure ? parseApiError(failure).message : ''}
      </p>
    </div>
  )
}
