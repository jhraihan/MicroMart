"""
Catalogue routes. Included at the API root (config/api_urls.py), so these
paths are already /api/v1/-prefixed and must not repeat the app name.
"""
from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="category-list"),
    path("brands/", views.BrandListView.as_view(), name="brand-list"),
    path("search/suggest/", views.SearchSuggestView.as_view(), name="search-suggest"),
    path("products/", views.ProductListView.as_view(), name="product-list"),
    # Declared before the <slug> route on purpose: Django matches in source
    # order, so with these reversed "compare" would be swallowed as a product
    # slug and the endpoint would 404.
    path("products/compare/", views.ProductCompareView.as_view(), name="product-compare"),
    path("products/<slug:slug>/", views.ProductDetailView.as_view(), name="product-detail"),
    path(
        "products/<slug:slug>/related/",
        views.ProductRelatedView.as_view(),
        name="product-related",
    ),
    path(
        "products/<slug:slug>/bought-together/",
        views.ProductBoughtTogetherView.as_view(),
        name="product-bought-together",
    ),
]
