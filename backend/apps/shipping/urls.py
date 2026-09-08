"""
Shipping routes, mounted at /api/v1/shipping/ (PRD 7.2).
"""
from django.urls import path

from . import views

app_name = "shipping"

urlpatterns = [
    path("zones/", views.ShippingZoneListView.as_view(), name="zone-list"),
]
