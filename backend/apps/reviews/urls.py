"""
Review and wishlist routes for the storefront (PRD 7.2).

Included at the API root (config/api_urls.py), so these paths are already
/api/v1/-prefixed and must not repeat the app name. The product reviews route
deliberately sits under products/{slug}/ to match the frozen shape of the rest
of the catalogue surface.
"""
from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path(
        "products/<slug:slug>/reviews/",
        views.ProductReviewsView.as_view(),
        name="product-review-list",
    ),
    path("reviews/<int:pk>/", views.ReviewDetailView.as_view(), name="review-detail"),
    path("wishlist/", views.WishlistView.as_view(), name="wishlist"),
    path(
        "wishlist/<int:product_id>/",
        views.WishlistItemView.as_view(),
        name="wishlist-item",
    ),
]
