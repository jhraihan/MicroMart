"""
Coupon management routes for the admin surface (PRD 7.3, US-A5).

Included under admin/ from config/api_urls.py, so these resolve as
/api/v1/admin/coupons/ and /api/v1/admin/coupons/{id}/.

Mounted the same way apps/reviews/admin_urls.py is, and for the same reason:
apps/dashboard/urls.py is still an empty stub, and the endpoints belong next
to the services they call. dashboard/urls.py can absorb this module later by
including it -- both are already at the admin/ prefix, so not a single URL
would change.
"""
from django.urls import path

from . import views

app_name = "promotions_admin"

urlpatterns = [
    path("coupons/", views.AdminCouponListCreateView.as_view(), name="coupon-list"),
    path(
        "coupons/<int:pk>/",
        views.AdminCouponDetailView.as_view(),
        name="coupon-detail",
    ),
]
