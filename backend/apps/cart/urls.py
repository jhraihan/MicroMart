"""
Cart routes, mounted at /api/v1/cart/ (PRD 7.2).
"""
from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.CartView.as_view(), name="detail"),
    path("items/", views.CartItemsView.as_view(), name="item-list"),
    path("items/<int:pk>/", views.CartItemDetailView.as_view(), name="item-detail"),
    path("merge/", views.CartMergeView.as_view(), name="merge"),
]
