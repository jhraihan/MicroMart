"""Shared fixtures for the catalogue API suite."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.catalog.models import InventoryReason
from apps.catalog.tests import factories


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def products_url():
    return reverse("catalog:product-list")


@pytest.fixture
def categories_url():
    return reverse("catalog:category-list")


@pytest.fixture
def brands_url():
    return reverse("catalog:brand-list")


@pytest.fixture
def detail_url():
    return lambda slug: reverse("catalog:product-detail", kwargs={"slug": slug})


@pytest.fixture
def related_url():
    return lambda slug: reverse("catalog:product-related", kwargs={"slug": slug})


# ---------------------------------------------------------------------------
# Admin surface (PRD 7.3, US-A2/US-A4/US-A8)
#
# The storefront fixtures above need no people: every catalogue read is public.
# Everything below does, because the whole point of these endpoints is who is
# refused. Three roles, and all three appear in the matrix: an anonymous caller
# (401), a signed-in customer (403), a staff user (403 -- PRD 7.3 gives staff
# orders and order status, nothing here), and an admin (200).
# ---------------------------------------------------------------------------
PASSWORD = "Str0ngPass!2026"


@pytest.fixture
def customer(db):
    return User.objects.create_user(email="shopper@example.com", password=PASSWORD)


@pytest.fixture
def staff_member(db):
    """
    Staff, not admin. US-A8: "staff may view orders and update order status
    only; every other admin endpoint rejects staff with 403". Every route in
    apps/catalog/admin_urls.py is one of the others.
    """
    return User.objects.create_user(
        email="helper@example.com", password=PASSWORD, role=Role.STAFF
    )


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="owner@example.com", password=PASSWORD, role=Role.ADMIN
    )


@pytest.fixture
def as_user(api):
    """Re-point the shared client at whoever the test needs next."""

    def _as(user):
        api.force_authenticate(user=user)
        return api

    return _as


@pytest.fixture
def admin_api(api, admin_user):
    api.force_authenticate(user=admin_user)
    return api


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_products_url():
    return reverse("catalog_admin:product-list")


@pytest.fixture
def admin_product_url():
    return lambda pk: reverse("catalog_admin:product-detail", kwargs={"pk": pk})


@pytest.fixture
def admin_product_images_url():
    return lambda pk: reverse("catalog_admin:product-images", kwargs={"pk": pk})


@pytest.fixture
def admin_product_image_url():
    return lambda pk, image_id: reverse(
        "catalog_admin:product-image-detail", kwargs={"pk": pk, "image_id": image_id}
    )


@pytest.fixture
def admin_variants_url():
    return reverse("catalog_admin:variant-list")


@pytest.fixture
def admin_variant_url():
    return lambda pk: reverse("catalog_admin:variant-detail", kwargs={"pk": pk})


@pytest.fixture
def admin_categories_url():
    return reverse("catalog_admin:category-list")


@pytest.fixture
def admin_category_url():
    return lambda pk: reverse("catalog_admin:category-detail", kwargs={"pk": pk})


@pytest.fixture
def admin_brands_url():
    return reverse("catalog_admin:brand-list")


@pytest.fixture
def admin_brand_url():
    return lambda pk: reverse("catalog_admin:brand-detail", kwargs={"pk": pk})


@pytest.fixture
def admin_inventory_url():
    return reverse("catalog_admin:inventory-list")


@pytest.fixture
def admin_inventory_adjust_url():
    return reverse("catalog_admin:inventory-adjust")


@pytest.fixture
def admin_inventory_ledger_url():
    return lambda variant_id: reverse(
        "catalog_admin:inventory-ledger", kwargs={"variant_id": variant_id}
    )


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def product_payload():
    """
    A complete US-A2 product form: name, description, category, brand, specs,
    warranty, and one variant carrying its own price, SKU and stock.
    """

    def _payload(category, **overrides):
        payload = {
            "name": "Asus Vivobook Go 15",
            "description": "A 15-inch everyday laptop.",
            "category_id": category.pk,
            "warranty_months": 24,
            "specs": [
                {"key": "Processor", "value": "AMD Ryzen 5 7520U"},
                {"key": "RAM", "value": "8GB LPDDR5"},
            ],
            "variants": [
                {
                    "sku": "VIVO-8-512",
                    "option_label": "8GB / 512GB",
                    "price": "62500.00",
                    "stock": 7,
                    "low_stock_threshold": 3,
                }
            ],
        }
        payload.update(overrides)
        return payload

    return _payload


@pytest.fixture
def png_upload():
    """
    A real PNG, encoded by Pillow.

    A handful of bytes named .png would pass a filename check and fail
    ImageField, which is the point -- the upload path has to be exercised with
    something Pillow can actually open, or the test proves only that the
    refusal works.
    """
    from PIL import Image

    def _upload(name="shot.png", size=(8, 8), colour=(200, 30, 11)):
        buffer = io.BytesIO()
        Image.new("RGB", size, colour).save(buffer, format="PNG")
        buffer.seek(0)
        return SimpleUploadedFile(name, buffer.read(), content_type="image/png")

    return _upload


@pytest.fixture
def media_root(settings, tmp_path):
    """Uploads land in a temp directory, never in the repo's media/."""
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.fixture
def restock_reason():
    return InventoryReason.RESTOCK.value


# ---------------------------------------------------------------------------
# Catalogue rows the admin suite edits
#
# Built through apps/catalog/tests/factories so the storefront suite and the
# admin suite are asserting on the same kind of row. Note the factory writes
# `stock` directly and writes no InventoryLog: that is correct for a fixture,
# and it is why the ledger-reconciliation tests build their variants through
# the admin API instead.
# ---------------------------------------------------------------------------
@pytest.fixture
def category(db):
    return factories.make_category("Laptops", "laptops")


@pytest.fixture
def child_category(category):
    return factories.make_category("Gaming Laptops", "gaming-laptops", parent=category)


@pytest.fixture
def brand(db):
    return factories.make_brand("Asus", "asus")


@pytest.fixture
def product(category, brand):
    return factories.make_product(
        category,
        brand=brand,
        name="Asus Vivobook Go 15",
        slug="asus-vivobook-go-15",
        sku="VIVO-8-512",
        price="62500.00",
        stock=7,
    )


@pytest.fixture
def variant(product):
    return product.variants.get()
