"""
Payment routes. Included at payments/ by config/api_urls.py, so these are
already /api/v1/payments/-prefixed.

The three have three different callers -- a shopper's browser, SSLCommerz's
servers, and a shopper's browser again on the way back -- and only the middle
one is allowed to change anything (PRD 5.5, FR-PAY-3, FR-PAY-4).
"""
from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("initiate/", views.PaymentInitiateView.as_view(), name="initiate"),
    path("ipn/", views.PaymentIPNView.as_view(), name="ipn"),
    # `result` is validated in the service, which 404s anything that is not
    # success, fail or cancel -- the URL pattern is not the allowlist.
    path(
        "callback/<str:result>/",
        views.PaymentCallbackView.as_view(),
        name="callback",
    ),
]
