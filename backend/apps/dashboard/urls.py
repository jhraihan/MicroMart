"""
Admin routes (PRD 7.3). Included at the admin/ prefix from config/api_urls.py,
so these resolve as /api/v1/admin/....

Review moderation is mounted from apps/reviews/admin_urls.py at the same
prefix, deliberately: those endpoints live next to the Review services they
call. Both modules answer under admin/, so nothing about a URL depends on
which file holds it.
"""
from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("dashboard/", views.AdminDashboardView.as_view(), name="dashboard"),
    path("orders/", views.AdminOrderListView.as_view(), name="order-list"),
    path(
        "orders/<str:reference>/",
        views.AdminOrderDetailView.as_view(),
        name="order-detail",
    ),
    path(
        "orders/<str:reference>/status/",
        views.AdminOrderStatusView.as_view(),
        name="order-status",
    ),
    path(
        "orders/<str:reference>/shipment/",
        views.AdminOrderShipmentView.as_view(),
        name="order-shipment",
    ),
    path("customers/", views.AdminCustomerListView.as_view(), name="customer-list"),
    path("settings/", views.AdminStoreSettingsView.as_view(), name="store-settings"),
]
