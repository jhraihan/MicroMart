"""
Checkout and order routes. Included at the API root (config/api_urls.py), so
these paths are already /api/v1/-prefixed.

/checkout/quote/ lives in this app rather than one of its own because the
totals engine it calls is apps/orders/services/totals.py -- the same function
order placement uses. Splitting the route away from the code that answers it
would be the first step towards two definitions of a total.
"""
from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("checkout/quote/", views.CheckoutQuoteView.as_view(), name="checkout-quote"),
    path("orders/", views.OrderListCreateView.as_view(), name="order-list"),
    path("orders/<str:reference>/", views.OrderDetailView.as_view(), name="order-detail"),
    path(
        "orders/<str:reference>/cancel/",
        views.OrderCancelView.as_view(),
        name="order-cancel",
    ),
]
