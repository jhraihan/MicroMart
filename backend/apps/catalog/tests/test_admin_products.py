"""
Admin product CRUD (PRD 4.3 US-A2, 7.3 /admin/products/).

US-A2's acceptance criterion is a list of things the form must carry -- name,
description, category, brand, specs, warranty, images, variants with
independent price/SKU/stock -- plus "validation errors are shown per field".
Each clause has a test here.

Two rules dominate and are the reason this file is longer than a CRUD suite
usually needs:

* **DELETE deactivates.** A hard delete would be the wrong answer twice over:
  Product.category is PROTECT, and OrderItem keeps a variant FK for reporting.
  What matters more is that a deactivation cannot reach backwards -- an order
  placed yesterday reads from its own snapshot, and the test below proves the
  snapshot survives the product being withdrawn.
* **A product always has at least one variant** (FR-CAT-4). Price and stock
  live on the variant, so a product with none has no price at all -- it would
  vanish from every aggregate in services/catalogue.py while still looking
  present in the admin table.
"""
import pytest

from apps.catalog.models import InventoryLog, Product, ProductSpec
from apps.catalog.tests import factories

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# GET /admin/products/
# ---------------------------------------------------------------------------
def test_the_admin_list_shows_deactivated_products_the_storefront_hides(
    admin_api, api, admin_products_url, products_url, category
):
    factories.make_product(category, name="Live", slug="live")
    factories.make_product(category, name="Withdrawn", slug="withdrawn", is_active=False)

    admin_slugs = {row["slug"] for row in admin_api.get(admin_products_url).json()["results"]}
    public_slugs = {row["slug"] for row in api.get(products_url).json()["results"]}

    assert admin_slugs == {"live", "withdrawn"}
    assert public_slugs == {"live"}


def test_the_admin_list_can_be_narrowed_to_inactive_products(
    admin_api, admin_products_url, category
):
    factories.make_product(category, name="Live", slug="live")
    factories.make_product(category, name="Withdrawn", slug="withdrawn", is_active=False)

    body = admin_api.get(admin_products_url, {"is_active": "false"}).json()

    assert [row["slug"] for row in body["results"]] == ["withdrawn"]


def test_the_admin_list_searches_by_name_and_by_sku(
    admin_api, admin_products_url, category
):
    factories.make_product(category, name="Vivobook", slug="vivobook", sku="VIVO-1")
    factories.make_product(category, name="Macbook", slug="macbook", sku="MBP-14")

    by_name = admin_api.get(admin_products_url, {"q": "vivo"}).json()
    by_sku = admin_api.get(admin_products_url, {"q": "MBP"}).json()

    assert [row["slug"] for row in by_name["results"]] == ["vivobook"]
    assert [row["slug"] for row in by_sku["results"]] == ["macbook"]


def test_the_admin_list_can_be_narrowed_to_products_with_low_stock(
    admin_api, admin_products_url, category
):
    factories.make_product(
        category, name="Plenty", slug="plenty", stock=50, variants=None
    )
    low = factories.make_product(category, name="Nearly out", slug="nearly-out", variants=[])
    factories.make_variant(low, sku="LOW-1", price="100.00", stock=2, low_stock_threshold=5)

    body = admin_api.get(admin_products_url, {"low_stock": "true"}).json()

    assert [row["slug"] for row in body["results"]] == ["nearly-out"]


def test_a_nonsense_sort_is_a_422_rather_than_being_ignored(
    admin_api, admin_products_url
):
    response = admin_api.get(admin_products_url, {"sort": "cheapest"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SORT"


def test_a_row_carries_the_price_range_and_stock_the_table_renders(
    admin_api, admin_products_url, category
):
    product = factories.make_product(category, name="Two options", slug="two", variants=[])
    factories.make_variant(product, sku="A-1", price="1000.00", stock=3)
    factories.make_variant(product, sku="A-2", price="1500.00", stock=4)

    row = admin_api.get(admin_products_url).json()["results"][0]

    assert row["price_min"] == "1000.00", "money is a decimal string, never a float"
    assert row["price_max"] == "1500.00"
    assert row["total_stock"] == 7
    assert row["variant_count"] == 2


# ---------------------------------------------------------------------------
# POST /admin/products/
# ---------------------------------------------------------------------------
def test_creating_a_product_stores_every_field_the_form_offers(
    admin_api, admin_products_url, category, brand, product_payload
):
    payload = product_payload(category, brand_id=brand.pk)

    response = admin_api.post(admin_products_url, payload, format="json")

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Asus Vivobook Go 15"
    assert body["description"] == "A 15-inch everyday laptop."
    assert body["category"]["id"] == category.pk
    assert body["brand"]["id"] == brand.pk
    assert body["warranty_months"] == 24
    assert [spec["key"] for spec in body["specs"]] == ["Processor", "RAM"]
    assert len(body["variants"]) == 1


def test_a_created_variant_carries_its_own_price_sku_and_stock(
    admin_api, admin_products_url, category, product_payload
):
    """US-A2: variants with independent price, SKU, and stock."""
    payload = product_payload(
        category,
        variants=[
            {"sku": "A-8-256", "option_label": "8GB", "price": "62500.00", "stock": 7},
            {"sku": "A-16-512", "option_label": "16GB", "price": "74900.00", "stock": 2},
        ],
    )

    body = admin_api.post(admin_products_url, payload, format="json").json()

    by_sku = {row["sku"]: row for row in body["variants"]}
    assert by_sku["A-8-256"]["price"] == "62500.00"
    assert by_sku["A-8-256"]["stock"] == 7
    assert by_sku["A-16-512"]["price"] == "74900.00"
    assert by_sku["A-16-512"]["stock"] == 2


def test_opening_stock_arrives_through_the_ledger_not_around_it(
    admin_api, admin_products_url, category, product_payload
):
    """
    The one place a variant's stock is set from a payload is creation, and even
    there it goes through inventory.record_movement -- so the very first thing
    in a variant's ledger is the row explaining where its opening quantity came
    from. Without this, `sum(delta) == stock` would be false from birth.
    """
    admin_api.post(admin_products_url, product_payload(category), format="json")

    log = InventoryLog.objects.get(variant__sku="VIVO-8-512")
    assert log.delta == 7
    assert log.reason == "initial"


def test_a_product_created_with_no_variants_is_refused_not_silently_accepted(
    admin_api, admin_products_url, category, product_payload
):
    """
    FR-CAT-4 decision, documented in services/administration.create_product:
    the caller supplies the default variant rather than the server inventing
    one. A server-invented SKU and price would be a placeholder that could
    eventually be snapshotted onto a real order line.
    """
    response = admin_api.post(
        admin_products_url, product_payload(category, variants=[]), format="json"
    )

    assert response.status_code in (400, 422)
    assert Product.objects.filter(name="Asus Vivobook Go 15").count() == 0


def test_a_missing_name_is_reported_against_the_name_field(
    admin_api, admin_products_url, category, product_payload
):
    """US-A2: validation errors are shown per field."""
    payload = product_payload(category)
    payload.pop("name")

    response = admin_api.post(admin_products_url, payload, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "name"


def test_an_unknown_category_is_reported_against_the_category_field(
    admin_api, admin_products_url, category, product_payload
):
    response = admin_api.post(
        admin_products_url, product_payload(category, category_id=999_999), format="json"
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "CATEGORY_NOT_FOUND"
    assert error["field"] == "category_id"


def test_a_negative_price_is_reported_against_the_price_field(
    admin_api, admin_products_url, category, product_payload
):
    payload = product_payload(
        category, variants=[{"sku": "NEG-1", "price": "-1.00", "stock": 1}]
    )

    response = admin_api.post(admin_products_url, payload, format="json")

    assert response.status_code in (400, 422)
    assert response.json()["error"]["field"] == "price"


def test_the_slug_is_derived_from_the_name_when_the_form_leaves_it_blank(
    admin_api, admin_products_url, category, product_payload
):
    body = admin_api.post(
        admin_products_url, product_payload(category), format="json"
    ).json()

    assert body["slug"] == "asus-vivobook-go-15"


def test_a_second_product_with_the_same_name_gets_a_distinct_slug(
    admin_api, admin_products_url, category, product_payload
):
    first = admin_api.post(admin_products_url, product_payload(category), format="json")
    second = admin_api.post(
        admin_products_url,
        product_payload(category, variants=[{"sku": "VIVO-16-1TB", "price": "1.00"}]),
        format="json",
    )

    assert first.json()["slug"] == "asus-vivobook-go-15"
    assert second.json()["slug"] == "asus-vivobook-go-15-2"


def test_creating_a_product_is_all_or_nothing(
    admin_api, admin_products_url, category, product_payload
):
    """
    The second variant collides on SKU. If creation were not atomic the product
    and its first variant would survive as a half-built row that the admin
    never asked for.
    """
    factories.make_variant(
        factories.make_product(category, slug="incumbent", variants=[]),
        sku="TAKEN-1",
        price="10.00",
    )
    payload = product_payload(
        category,
        variants=[
            {"sku": "FRESH-1", "price": "100.00"},
            {"sku": "TAKEN-1", "price": "200.00"},
        ],
    )

    response = admin_api.post(admin_products_url, payload, format="json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SKU_TAKEN"
    assert not Product.objects.filter(name="Asus Vivobook Go 15").exists()


# ---------------------------------------------------------------------------
# PATCH /admin/products/{id}/
# ---------------------------------------------------------------------------
def test_patching_a_product_changes_only_what_the_payload_names(
    admin_api, admin_product_url, product
):
    response = admin_api.patch(
        admin_product_url(product.pk), {"warranty_months": 36}, format="json"
    )

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.warranty_months == 36
    assert product.name == "Asus Vivobook Go 15", "an unnamed field is left alone"


def test_sending_specs_replaces_the_whole_table(admin_api, admin_product_url, product):
    factories.make_spec(product, key="Old", value="Value")

    admin_api.patch(
        admin_product_url(product.pk),
        {"specs": [{"key": "Display", "value": "15.6in FHD"}]},
        format="json",
    )

    assert [
        (row.key, row.value) for row in ProductSpec.objects.filter(product=product)
    ] == [("Display", "15.6in FHD")]


def test_omitting_specs_leaves_the_existing_table_alone(
    admin_api, admin_product_url, product
):
    factories.make_spec(product, key="Keep", value="Me")

    admin_api.patch(admin_product_url(product.pk), {"name": "Renamed"}, format="json")

    assert ProductSpec.objects.filter(product=product, key="Keep").exists()


def test_an_empty_spec_list_is_how_the_table_is_cleared(
    admin_api, admin_product_url, product
):
    factories.make_spec(product, key="Remove", value="Me")

    admin_api.patch(admin_product_url(product.pk), {"specs": []}, format="json")

    assert ProductSpec.objects.filter(product=product).count() == 0


def test_a_patch_can_put_a_deactivated_product_back_on_sale(
    admin_api, admin_product_url, product
):
    product.is_active = False
    product.save(update_fields=["is_active"])

    admin_api.patch(admin_product_url(product.pk), {"is_active": True}, format="json")

    product.refresh_from_db()
    assert product.is_active is True


def test_patching_an_unknown_product_is_a_404(admin_api, admin_product_url):
    assert admin_api.patch(
        admin_product_url(999_999), {"name": "Ghost"}, format="json"
    ).status_code == 404


# ---------------------------------------------------------------------------
# DELETE /admin/products/{id}/
# ---------------------------------------------------------------------------
def test_deleting_a_product_deactivates_it_rather_than_removing_the_row(
    admin_api, admin_product_url, product
):
    response = admin_api.delete(admin_product_url(product.pk))

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert Product.objects.filter(pk=product.pk).exists(), "the row is still there"


def test_a_deleted_product_disappears_from_the_storefront(
    admin_api, api, admin_product_url, products_url, detail_url, product
):
    admin_api.delete(admin_product_url(product.pk))

    assert api.get(products_url).json()["count"] == 0
    assert api.get(detail_url(product.slug)).status_code == 404


def test_deactivating_a_product_never_alters_an_order_already_placed(
    admin_api, admin_product_url, product, variant
):
    """
    The load-bearing consequence of snapshotting (PRD 6.3). An order copies
    product name, variant label, SKU and unit price at purchase time, so
    withdrawing the product afterwards -- or renaming it, or repricing it --
    must leave the order reading exactly as it did.
    """
    order = factories.place_order([(variant, 2)])
    before = order.items.get()
    snapshot = (before.product_name, before.variant_label, before.sku, before.unit_price)

    admin_api.patch(
        admin_product_url(product.pk), {"name": "Renamed after the sale"}, format="json"
    )
    admin_api.delete(admin_product_url(product.pk))

    after = order.items.get()
    assert (after.product_name, after.variant_label, after.sku, after.unit_price) == snapshot
    assert after.variant_id == variant.pk, "the analytics FK survives a deactivation"


def test_deleting_an_already_deactivated_product_is_a_no_op_not_an_error(
    admin_api, admin_product_url, product
):
    admin_api.delete(admin_product_url(product.pk))
    response = admin_api.delete(admin_product_url(product.pk))

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_deleting_an_unknown_product_is_a_404(admin_api, admin_product_url):
    assert admin_api.delete(admin_product_url(999_999)).status_code == 404
