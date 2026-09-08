"""
The role matrix for the admin catalogue surface (PRD 4.3 US-A8, 7.3, 10.2).

US-A8 is the acceptance criterion this file exists for, and it is unusually
precise: "roles are admin and staff; staff may view orders and update order
status only; **every other admin endpoint rejects staff with 403**". Every
route in apps/catalog/admin_urls.py is one of the others, so every one of them
is asserted here -- not a sample. A permission class attached to eight of nine
views is exactly the shape this bug takes in real code.

The matrix is written against pk=1 with nothing in the database on purpose.
DRF settles permissions in `initial()`, before the handler ever looks a row up,
so a refusal that depends on the object existing would be a refusal that leaks
whether it exists. A 403 that turned into a 404 when the row was missing would
show up here as a failure.
"""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

# Every (route, method) pair apps/catalog/admin_urls.py registers.
ADMIN_ROUTES = [
    ("catalog_admin:product-list", {}, "get"),
    ("catalog_admin:product-list", {}, "post"),
    ("catalog_admin:product-detail", {"pk": 1}, "get"),
    ("catalog_admin:product-detail", {"pk": 1}, "patch"),
    ("catalog_admin:product-detail", {"pk": 1}, "delete"),
    ("catalog_admin:product-images", {"pk": 1}, "get"),
    ("catalog_admin:product-images", {"pk": 1}, "post"),
    ("catalog_admin:product-images", {"pk": 1}, "patch"),
    ("catalog_admin:product-image-detail", {"pk": 1, "image_id": 1}, "delete"),
    ("catalog_admin:variant-list", {}, "get"),
    ("catalog_admin:variant-list", {}, "post"),
    ("catalog_admin:variant-detail", {"pk": 1}, "get"),
    ("catalog_admin:variant-detail", {"pk": 1}, "patch"),
    ("catalog_admin:variant-detail", {"pk": 1}, "delete"),
    ("catalog_admin:category-list", {}, "get"),
    ("catalog_admin:category-list", {}, "post"),
    ("catalog_admin:category-detail", {"pk": 1}, "get"),
    ("catalog_admin:category-detail", {"pk": 1}, "patch"),
    ("catalog_admin:category-detail", {"pk": 1}, "delete"),
    ("catalog_admin:brand-list", {}, "get"),
    ("catalog_admin:brand-list", {}, "post"),
    ("catalog_admin:brand-detail", {"pk": 1}, "get"),
    ("catalog_admin:brand-detail", {"pk": 1}, "patch"),
    ("catalog_admin:brand-detail", {"pk": 1}, "delete"),
    ("catalog_admin:inventory-list", {}, "get"),
    ("catalog_admin:inventory-adjust", {}, "post"),
    ("catalog_admin:inventory-ledger", {"variant_id": 1}, "get"),
]

ROUTE_IDS = [
    "{0}-{1}".format(method.upper(), name.split(":")[1]) for name, _, method in ADMIN_ROUTES
]


def call(client, route, method):
    name, kwargs, verb = route
    url = reverse(name, kwargs=kwargs)
    if verb in ("post", "patch"):
        return getattr(client, verb)(url, {}, format="json")
    return getattr(client, verb)(url)


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=ROUTE_IDS)
def test_an_anonymous_caller_is_refused_every_admin_catalogue_route_with_401(api, route):
    assert call(api, route, route[2]).status_code == 401


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=ROUTE_IDS)
def test_a_signed_in_customer_is_refused_every_admin_catalogue_route_with_403(
    as_user, customer, route
):
    assert call(as_user(customer), route, route[2]).status_code == 403


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=ROUTE_IDS)
def test_a_staff_user_is_refused_every_admin_catalogue_route_with_403(
    as_user, staff_member, route
):
    """
    US-A8, stated as literally as it can be: staff get orders and order status,
    and 403 on everything else. A staff user who could edit a variant could
    change a price by accident, which is the exact failure the story names.
    """
    assert call(as_user(staff_member), route, route[2]).status_code == 403


def test_an_admin_is_admitted_where_the_others_were_refused(
    admin_api,
    admin_products_url,
    admin_variants_url,
    admin_categories_url,
    admin_brands_url,
    admin_inventory_url,
):
    """
    The other three tests would all pass if the routes 404'd or 500'd, so one
    of them has to prove the door opens for the role that owns it.
    """
    for url in (
        admin_products_url,
        admin_variants_url,
        admin_categories_url,
        admin_brands_url,
        admin_inventory_url,
    ):
        assert admin_api.get(url).status_code == 200, url


def test_the_storefront_catalogue_stays_public_and_shows_no_admin_fields(
    api, products_url, category
):
    """
    The admin serializers expose stock, thresholds and inactive rows. This
    pins that adding them did not widen the public surface by accident.
    """
    from apps.catalog.tests import factories

    factories.make_product(category, name="Public", slug="public", stock=4)

    row = api.get(products_url).json()["results"][0]

    assert "low_stock_threshold" not in row
    assert "active_variant_count" not in row
