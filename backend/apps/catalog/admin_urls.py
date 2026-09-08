"""
Admin catalogue and inventory routes (PRD 7.3).

Included under admin/ from config/api_urls.py -- exactly as
apps/reviews/admin_urls.py already is -- so these resolve as
/api/v1/admin/products/, /api/v1/admin/variants/, /api/v1/admin/categories/,
/api/v1/admin/brands/ and /api/v1/admin/inventory/.

**Why they are not in apps/dashboard/urls.py**: that module is still an empty
stub. Keeping the endpoints in the app that owns Product, ProductVariant and
InventoryLog puts them next to the services they call. Both modules are mounted
at the same admin/ prefix, so folding them into dashboard later would not
change a single URL.

Route order matters in one place: `inventory/adjust/` is declared before
`inventory/<int:variant_id>/logs/`, so the literal path can never be captured
as an id.
"""
from django.urls import path

from . import admin_views as views

app_name = "catalog_admin"

urlpatterns = [
    # Products
    path("products/", views.AdminProductListView.as_view(), name="product-list"),
    path(
        "products/<int:pk>/",
        views.AdminProductDetailView.as_view(),
        name="product-detail",
    ),
    path(
        "products/<int:pk>/images/",
        views.AdminProductImagesView.as_view(),
        name="product-images",
    ),
    path(
        "products/<int:pk>/images/<int:image_id>/",
        views.AdminProductImageDetailView.as_view(),
        name="product-image-detail",
    ),
    # Variants
    path("variants/", views.AdminVariantListView.as_view(), name="variant-list"),
    path(
        "variants/<int:pk>/",
        views.AdminVariantDetailView.as_view(),
        name="variant-detail",
    ),
    # Taxonomy
    path("categories/", views.AdminCategoryListView.as_view(), name="category-list"),
    path(
        "categories/<int:pk>/",
        views.AdminCategoryDetailView.as_view(),
        name="category-detail",
    ),
    path("brands/", views.AdminBrandListView.as_view(), name="brand-list"),
    path("brands/<int:pk>/", views.AdminBrandDetailView.as_view(), name="brand-detail"),
    # Inventory
    path("inventory/", views.AdminInventoryView.as_view(), name="inventory-list"),
    path(
        "inventory/adjust/",
        views.AdminInventoryAdjustView.as_view(),
        name="inventory-adjust",
    ),
    path(
        "inventory/<int:variant_id>/logs/",
        views.AdminVariantLedgerView.as_view(),
        name="inventory-ledger",
    ),
]
