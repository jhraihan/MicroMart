import clsx from 'clsx'
import { useRef, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'

import { useCart } from '@/features/cart/useCart'
import MegaMenu from '@/features/catalog/components/MegaMenu'
import MobileNavDrawer from '@/features/catalog/components/MobileNavDrawer'
import SearchBar from '@/features/catalog/components/SearchBar'
import { useWishlistIntentReplay } from '@/features/wishlist/useWishlistIntentReplay'
import { useAuthStore } from '@/stores/authStore'
import { useCompareStore } from '@/stores/compareStore'

import StorefrontFooter from './StorefrontFooter'

/*
 * Mobile-first chrome (PRD §9.2 -- fully usable one-handed at 360px).
 *
 * The header is three rows on a phone and two on a desktop:
 *   row 1  burger + logo + icon actions
 *   row 2  search, full width on mobile so it stays thumb-reachable
 *   row 3  the mega-menu, desktop only -- phones get the drawer instead
 *
 * Icon buttons carry a visible label from `sm` up and a `sr-only` one below
 * it, so a small screen keeps its 44px targets without an unlabelled icon row.
 */

function IconAction({ to, label, badge, hideOnMobile = false, children }) {
  return (
    <NavLink
      to={to}
      className={clsx(
        'relative min-h-[44px] min-w-[44px] flex-col items-center justify-center gap-0.5 rounded-card px-1.5 text-[11px] hover:text-brand sm:px-2',
        // Five icon buttons plus the burger and the wordmark come to 374px,
        // which overflows a 360px viewport and makes the whole document
        // scroll sideways -- exactly what PRD §9.2 forbids. Offers, Builder
        // and Compare are therefore desktop-only here; the mobile drawer
        // carries all three, which is where a phone user looks for them.
        hideOnMobile ? 'hidden sm:flex' : 'flex',
      )}
    >
      <span aria-hidden="true" className="flex h-5 w-5 items-center justify-center">
        {children}
      </span>
      <span className="hidden sm:inline">{label}</span>
      <span className="sr-only sm:hidden">{label}</span>
      {badge > 0 && (
        /*
          White on `price` is 5.36:1, so the count stays readable. This badge
          carries a number a shopper is meant to read, so it needs real
          contrast rather than a decorative tint.
        */
        <span
          className="absolute right-0 top-0.5 rounded-pill bg-price px-1.5 py-0.5 text-[10px] font-semibold leading-tight text-white"
          aria-hidden="true"
        >
          {badge}
        </span>
      )}
    </NavLink>
  )
}

export default function StorefrontLayout() {
  const user = useAuthStore((s) => s.user)
  const signOut = useAuthStore((s) => s.signOut)
  /*
   * Counted through the cart facade, not the guest store. Reading
   * useCartStore directly meant the badge showed 0 for every signed-in
   * shopper, whose cart lives on the server.
   */
  const { itemCount } = useCart()
  const compareCount = useCompareStore((s) => s.slugs.length)

  const [navOpen, setNavOpen] = useState(false)
  const burgerRef = useRef(null)

  // FR-WSH-4: a heart tapped while signed out parked its product; sign-in
  // lands back here, and this completes the add. Mounted on the layout
  // because the card that recorded the intent is long unmounted by then.
  useWishlistIntentReplay()

  return (
    <div className="flex min-h-screen flex-col bg-page">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>

      <header className="sticky top-0 z-40 bg-chrome text-white shadow-el-4">
        {/* Row 1 -- brand and actions */}
        <div className="mx-auto flex max-w-7xl items-center gap-2 px-3 py-2 sm:px-4 lg:h-14 lg:py-0">
          <button
            type="button"
            ref={burgerRef}
            onClick={() => setNavOpen(true)}
            aria-expanded={navOpen}
            aria-haspopup="dialog"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-card hover:text-brand lg:hidden"
          >
            <span className="sr-only">Browse categories</span>
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-6 w-6"
                 fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
            </svg>
          </button>

          <Link
            to="/"
            className="flex min-h-[44px] shrink-0 items-center gap-1.5 text-lg font-semibold tracking-tight"
          >
            {/* Original mark: a hex outline with an M. */}
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-6 w-6 text-brand"
                 fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M12 2.5l8 4.6v9.8l-8 4.6-8-4.6V7.1z" strokeLinejoin="round" />
              <path d="M8 15V9l4 4 4-4v6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Micro<span className="text-brand">Mart</span>
          </Link>

          {/* Desktop search sits inline; mobile gets its own row below. */}
          <div className="mx-4 hidden max-w-xl flex-1 lg:block">
            <SearchBar />
          </div>

          <nav
            aria-label="Primary"
            className="ml-auto flex items-center gap-0.5 sm:gap-1"
          >
            <IconAction to="/offers" label="Offers" hideOnMobile>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                   className="h-5 w-5">
                <path d="M12 3l2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4L4.2 8.7l5.4-.8z"
                      strokeLinejoin="round" />
              </svg>
            </IconAction>

            <IconAction to="/pc-builder" label="Builder" hideOnMobile>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                   className="h-5 w-5">
                <rect x="4" y="3" width="16" height="18" rx="2" />
                <path d="M8 7h8M8 11h8M8 15h4" strokeLinecap="round" />
              </svg>
            </IconAction>

            <IconAction to="/compare" label="Compare" badge={compareCount} hideOnMobile>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                   className="h-5 w-5">
                <path d="M9 4v16M15 4v16M4 8h5M15 8h5M4 16h5M15 16h5" strokeLinecap="round" />
              </svg>
            </IconAction>

            <IconAction to="/cart" label="Cart" badge={itemCount}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                   className="h-5 w-5">
                <path d="M4 5h2l2.2 10.2a1.5 1.5 0 001.5 1.2h7.4a1.5 1.5 0 001.5-1.2L20 8H7"
                      strokeLinecap="round" strokeLinejoin="round" />
                <circle cx="10" cy="20" r="1.2" />
                <circle cx="18" cy="20" r="1.2" />
              </svg>
            </IconAction>

            {user ? (
              <div className="group relative">
                <NavLink
                  to="/account"
                  className="flex min-h-[44px] min-w-[44px] flex-col items-center justify-center gap-0.5 rounded-card px-1.5 text-[11px] hover:text-brand sm:px-2"
                >
                  <span aria-hidden="true" className="flex h-5 w-5 items-center justify-center">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                         className="h-5 w-5">
                      <circle cx="12" cy="8" r="3.5" />
                      <path d="M5 20a7 7 0 0114 0" strokeLinecap="round" />
                    </svg>
                  </span>
                  <span className="hidden sm:inline">Account</span>
                  <span className="sr-only sm:hidden">Account</span>
                </NavLink>

                {/*
                  Opens on hover and on keyboard focus within, so it is not a
                  pointer-only affordance. Every destination inside it is also
                  reachable from /account itself, so nothing depends on this
                  menu working.
                */}
                <div className="invisible absolute right-0 top-full z-50 w-48 rounded-card bg-white py-1 text-ink opacity-0 shadow-dropdown transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
                  <NavLink to="/account" className="block px-3 py-2 text-sm hover:bg-tint">
                    My account
                  </NavLink>
                  <NavLink to="/orders" className="block px-3 py-2 text-sm hover:bg-tint">
                    My orders
                  </NavLink>
                  <NavLink to="/wishlist" className="block px-3 py-2 text-sm hover:bg-tint">
                    Wishlist
                  </NavLink>
                  <NavLink to="/account/addresses" className="block px-3 py-2 text-sm hover:bg-tint">
                    Addresses
                  </NavLink>
                  {['admin', 'staff'].includes(user.role) && (
                    <NavLink
                      to="/admin"
                      className="block border-t border-line px-3 py-2 text-sm font-semibold hover:bg-tint"
                    >
                      Admin dashboard
                    </NavLink>
                  )}
                  <button
                    type="button"
                    onClick={signOut}
                    className="block w-full border-t border-line px-3 py-2 text-left text-sm hover:bg-tint"
                  >
                    Sign out
                  </button>
                </div>
              </div>
            ) : (
              <IconAction to="/login" label="Sign in">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                     className="h-5 w-5">
                  <circle cx="12" cy="8" r="3.5" />
                  <path d="M5 20a7 7 0 0114 0" strokeLinecap="round" />
                </svg>
              </IconAction>
            )}
          </nav>
        </div>

        {/* Row 2 -- mobile search, full width */}
        <div className="px-3 pb-2 sm:px-4 lg:hidden">
          <SearchBar />
        </div>
      </header>

      <MegaMenu />
      <MobileNavDrawer
        open={navOpen}
        onClose={() => setNavOpen(false)}
        triggerRef={burgerRef}
      />

      <main id="main" className="mx-auto w-full max-w-7xl flex-1">
        <Outlet />
      </main>

      <StorefrontFooter />
    </div>
  )
}
