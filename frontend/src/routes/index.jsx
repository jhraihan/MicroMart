import { lazy, Suspense } from 'react'
import { createBrowserRouter } from 'react-router-dom'

import { PageSpinner } from '@/components/ui'
import AccountLayout from '@/features/account/AccountLayout'
import AccountOverviewPage from '@/features/account/AccountOverviewPage'
import AddressesPage from '@/features/account/AddressesPage'
import ChangePasswordPage from '@/features/account/ChangePasswordPage'
import ProfilePage from '@/features/account/ProfilePage'
import ForgotPasswordPage from '@/features/auth/ForgotPasswordPage'
import LoginPage from '@/features/auth/LoginPage'
import RegisterPage from '@/features/auth/RegisterPage'
import CartPage from '@/features/cart/CartPage'
import BrandsPage from '@/features/catalog/BrandsPage'
import HomePage from '@/features/catalog/HomePage'
import OffersPage from '@/features/catalog/OffersPage'
import ProductDetailPage from '@/features/catalog/ProductDetailPage'
import ProductListPage from '@/features/catalog/ProductListPage'
import ComparePage from '@/features/compare/ComparePage'
import CheckoutPage from '@/features/checkout/CheckoutPage'
import PaymentCallbackPage from '@/features/checkout/PaymentCallbackPage'
import OrderConfirmationPage from '@/features/orders/OrderConfirmationPage'
import OrderDetailPage from '@/features/orders/OrderDetailPage'
import OrderHistoryPage from '@/features/orders/OrderHistoryPage'
import WishlistPage from '@/features/wishlist/WishlistPage'
import AdminLayout from '@/layouts/AdminLayout'
import StorefrontLayout from '@/layouts/StorefrontLayout'
import ErrorPage from '@/pages/ErrorPage'
import NotFoundPage from '@/pages/NotFoundPage'

import { RequireAdmin, RequireAuth } from './guards'

/*
 * Storefront and admin are route groups in one build (PRD §8.3). The admin
 * group is lazy so a shopper never downloads it -- that is the whole reason
 * the split exists. The catalogue is eager: it is the first thing almost
 * every visitor sees, so deferring it would only add a round trip. Cart,
 * checkout and the order screens are eager for the same reason -- they are
 * the buying path, and a chunk fetch between "Place order" and the receipt
 * is a round trip spent exactly where a shopper is least willing to wait.
 */
/*
 * The PC builder is code-split for the same reason the admin group is: it is
 * a substantial feature (picker dialog, compatibility panel, share dialog)
 * that most visits never open, so it should not sit in the bundle every
 * shopper downloads to look at a product.
 */
const PCBuilderPage = lazy(() => import('@/features/builder/PCBuilderPage'))
const SharedBuildPage = lazy(() => import('@/features/builder/SharedBuildPage'))

const AdminOverviewPage = lazy(() => import('@/admin/AdminOverviewPage'))
const AdminOrdersPage = lazy(() => import('@/admin/AdminOrdersPage'))
const AdminOrderDetailPage = lazy(() => import('@/admin/AdminOrderDetailPage'))
/*
 * The admin-only half of the dashboard. Catalogue, inventory, coupons,
 * review moderation and store settings are all `IsAdminRole` server-side
 * (PRD §4.3 US-A8), so they sit behind AdminOnly: a staff member who reaches
 * one by URL gets the same explanation the 403 would carry, once, instead of
 * a screen that fails one request at a time.
 */
const AdminOnly = lazy(() => import('@/admin/components/AdminOnly'))
const AdminProductsPage = lazy(() => import('@/admin/AdminProductsPage'))
const AdminProductFormPage = lazy(() => import('@/admin/AdminProductFormPage'))
const AdminInventoryPage = lazy(() => import('@/admin/AdminInventoryPage'))
const AdminTaxonomyPage = lazy(() => import('@/admin/AdminTaxonomyPage'))
const AdminCouponsPage = lazy(() => import('@/admin/AdminCouponsPage'))
const AdminReviewsPage = lazy(() => import('@/admin/AdminReviewsPage'))
const AdminSettingsPage = lazy(() => import('@/admin/AdminSettingsPage'))

function lazyRoute(element) {
  return <Suspense fallback={<PageSpinner />}>{element}</Suspense>
}

export const router = createBrowserRouter([
  {
    element: <StorefrontLayout />,
    errorElement: <ErrorPage />,
    children: [
      { path: '/', element: <HomePage /> },
      // Category browse and keyword search are the same listing surface; only
      // the source of the category scope differs (path vs query string).
      { path: '/c/:slug', element: <ProductListPage mode="category" /> },
      { path: '/search', element: <ProductListPage mode="search" /> },
      { path: '/p/:slug', element: <ProductDetailPage /> },
      { path: '/login', element: <LoginPage /> },
      { path: '/register', element: <RegisterPage /> },
      { path: '/forgot-password', element: <ForgotPasswordPage /> },
      // Merchandising surfaces. All three are ordinary listings underneath,
      // so nothing here reimplements filtering or pagination.
      { path: '/offers', element: <OffersPage /> },
      { path: '/brands', element: <BrandsPage /> },
      // Comparison is a client-side tray, so it works signed out.
      { path: '/compare', element: <ComparePage /> },
      { path: '/pc-builder', element: lazyRoute(<PCBuilderPage />) },
      // A share link must open for whoever received it -- they are, by
      // definition, not signed in as the person who sent it. The token is the
      // capability; see apps/builds/views.py.
      { path: '/builds/:token', element: lazyRoute(<SharedBuildPage />) },
      // The buying path is public from end to end: a guest fills a cart, pays
      // and reads their own receipt without ever holding an account
      // (FR-CRT-1, FR-CHK-5). Guarding any of these three is precisely what
      // would break guest checkout.
      { path: '/cart', element: <CartPage /> },
      { path: '/checkout', element: <CheckoutPage /> },
      // Singular /order/ is the just-placed receipt CheckoutPage redirects to;
      // plural /orders/ below is the account's own history. They differ in
      // segment count as well as in stem, so neither can shadow the other.
      { path: '/order/:reference', element: <OrderConfirmationPage /> },
      // Where SSLCommerz hands the browser back (FR-PAY-3). Public, and it has
      // to be: a guest pays too, and the gateway returns the customer with no
      // session of ours in play. Public is safe here because the page decides
      // nothing -- `success` in the path is a claim, not proof, so the screen
      // reads the order back and reports the status the server holds.
      { path: '/payments/callback/:result', element: <PaymentCallbackPage /> },
      {
        // Past orders are account-only -- GET /orders/ answers for the
        // authenticated user alone, so the guard only saves a round trip to a
        // 401 the API would return anyway (guards.jsx). It hands /login the
        // path to come back to, which LoginPage honours.
        element: <RequireAuth />,
        children: [
          { path: '/orders', element: <OrderHistoryPage /> },
          { path: '/orders/:reference', element: <OrderDetailPage /> },
          {
            // The account area. Every endpoint behind these answers for the
            // authenticated user alone, so the guard only saves a round trip
            // to the 401 the API would return anyway.
            path: '/account',
            element: <AccountLayout />,
            children: [
              { index: true, element: <AccountOverviewPage /> },
              { path: 'addresses', element: <AddressesPage /> },
              { path: 'profile', element: <ProfilePage /> },
              { path: 'password', element: <ChangePasswordPage /> },
            ],
          },
          // The wishlist is account-only end to end -- GET /wishlist/ is
          // IsAuthenticated and there is no guest wishlist -- so the guard
          // only saves a round trip to the 401 the API would return anyway.
          { path: '/wishlist', element: <WishlistPage /> },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
  {
    element: <RequireAdmin />,
    children: [
      {
        path: '/admin',
        element: <AdminLayout />,
        errorElement: <ErrorPage />,
        children: [
          { index: true, element: lazyRoute(<AdminOverviewPage />) },
          // The pipeline. `orders/:reference` is the fulfilment screen, so
          // it is one click from the row and one click from a dashboard tile
          // (PRD §3.2 asks for an order to be fulfilled in under a minute).
          { path: 'orders', element: lazyRoute(<AdminOrdersPage />) },
          { path: 'orders/:reference', element: lazyRoute(<AdminOrderDetailPage />) },
          {
            // Owner-only screens. Nothing under here is reachable by a staff
            // account, and none of its endpoints would answer one.
            element: lazyRoute(<AdminOnly />),
            children: [
              { path: 'products', element: lazyRoute(<AdminProductsPage />) },
              // One component serves both: the API is two calls (POST takes
              // the first variant inline, PATCH refuses variants entirely),
              // but it is one screen to whoever is filling it in.
              { path: 'products/new', element: lazyRoute(<AdminProductFormPage />) },
              { path: 'products/:id', element: lazyRoute(<AdminProductFormPage />) },
              { path: 'inventory', element: lazyRoute(<AdminInventoryPage />) },
              { path: 'taxonomy', element: lazyRoute(<AdminTaxonomyPage />) },
              { path: 'coupons', element: lazyRoute(<AdminCouponsPage />) },
              { path: 'reviews', element: lazyRoute(<AdminReviewsPage />) },
              { path: 'settings', element: lazyRoute(<AdminSettingsPage />) },
            ],
          },
          // A nav link whose screen has not landed yet answers with the 404
          // page rather than an empty admin shell. A concrete path added
          // later still wins over this one -- React Router ranks by
          // specificity, not by declaration order.
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])
