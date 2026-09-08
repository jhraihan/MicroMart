"""
The /api/v1/ surface (PRD §7.2, §7.3).

Storefront routes sit at the root; every admin route is namespaced under
admin/ and gated by IsAdminOrStaff.
"""
from django.urls import include, path

urlpatterns = [
    path("auth/", include("apps.accounts.urls")),
    path("", include("apps.accounts.address_urls")),
    path("", include("apps.catalog.urls")),
    path("cart/", include("apps.cart.urls")),
    path("", include("apps.orders.urls")),
    path("payments/", include("apps.payments.urls")),
    path("", include("apps.promotions.urls")),
    path("", include("apps.reviews.urls")),
    path("shipping/", include("apps.shipping.urls")),
    # PC builder and saved builds. Mounted at the root because its two halves
    # sit at different stems (`pc-builder/` for the tool, `builds/` for the
    # saved configurations) and neither belongs under the other.
    path("", include("apps.builds.urls")),
    path("admin/", include("apps.dashboard.urls")),
    # Review moderation (PRD §7.3). Mounted at the same admin/ prefix rather
    # than inside apps.dashboard.urls, which is still an empty stub -- the
    # endpoints live in the app that owns Review and its services. Moving
    # them under dashboard later would not change a URL.
    path("admin/", include("apps.reviews.admin_urls")),
    # Admin catalogue CRUD and inventory (PRD 7.3), mounted the same way and
    # for the same reason: the endpoints live in the app that owns Product,
    # ProductVariant and InventoryLog, beside the services they call.
    path("admin/", include("apps.catalog.admin_urls")),
    # Coupon management (PRD §7.3 CRUD /admin/coupons/, US-A5), mounted the
    # same way and for the same reason as the two above.
    path("admin/", include("apps.promotions.admin_urls")),
]
