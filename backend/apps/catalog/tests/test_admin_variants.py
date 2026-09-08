"""
Admin variant CRUD, and the one column it is not allowed to write
(PRD 4.3 US-A2/US-A4, 7.3 /admin/variants/, FR-CAT-4, FR-INV-1).

The centre of this file is a single claim: **stock is not a field on this
endpoint**. ProductVariant.stock has an append-only InventoryLog behind it, and
that ledger is only worth anything if nothing writes the column without writing
a row. A PATCH that set stock directly would put `sum(InventoryLog.delta)`
permanently out of step with `ProductVariant.stock`, with no record of who
moved it or why -- and the reconciliation check PRD 6.4 describes would start
reporting a discrepancy that no amount of reading the code could explain.

Refusing is deliberately chosen over ignoring. A silently dropped key answers
200, and the admin walks away believing a number that never moved.
"""
import pytest

from apps.catalog.models import InventoryLog, ProductVariant
from apps.catalog.tests import factories

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# The rule this endpoint exists to keep
# ---------------------------------------------------------------------------
def test_patching_stock_is_refused_and_the_column_does_not_move(
    admin_api, admin_variant_url, variant
):
    before = variant.stock
    log_count = InventoryLog.objects.filter(variant=variant).count()

    response = admin_api.patch(
        admin_variant_url(variant.pk), {"stock": 999}, format="json"
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "STOCK_NOT_WRITABLE"
    assert error["field"] == "stock"

    variant.refresh_from_db()
    assert variant.stock == before, "the column must not have moved"
    assert (
        InventoryLog.objects.filter(variant=variant).count() == log_count
    ), "and no ledger row may have appeared either"


def test_a_patch_mixing_stock_with_a_legal_field_is_refused_whole(
    admin_api, admin_variant_url, variant
):
    """
    Partial application would be worse than either outcome: the price would
    change, the stock would not, and the 422 would suggest neither had.
    """
    response = admin_api.patch(
        admin_variant_url(variant.pk),
        {"price": "99999.00", "stock": 42},
        format="json",
    )

    assert response.status_code == 422
    variant.refresh_from_db()
    assert str(variant.price) == "62500.00"
    assert variant.stock == 7


def test_the_variant_endpoint_still_reports_stock_it_just_will_not_take_it(
    admin_api, admin_variant_url, variant
):
    """Read-only, not invisible -- the admin table has to show the number."""
    body = admin_api.get(admin_variant_url(variant.pk)).json()

    assert body["stock"] == 7
    assert body["low_stock_threshold"] == 5


# ---------------------------------------------------------------------------
# POST /admin/variants/
# ---------------------------------------------------------------------------
def test_adding_a_variant_to_an_existing_product(
    admin_api, admin_variants_url, product
):
    response = admin_api.post(
        admin_variants_url,
        {
            "product_id": product.pk,
            "sku": "VIVO-16-1TB",
            "option_label": "16GB / 1TB",
            "price": "74900.00",
            "stock": 4,
            "low_stock_threshold": 2,
        },
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "VIVO-16-1TB"
    assert body["price"] == "74900.00"
    assert body["low_stock_threshold"] == 2
    assert product.variants.count() == 2


def test_a_new_variants_opening_stock_is_written_through_the_ledger(
    admin_api, admin_variants_url, product
):
    admin_api.post(
        admin_variants_url,
        {"product_id": product.pk, "sku": "OPEN-1", "price": "100.00", "stock": 12},
        format="json",
    )

    created = ProductVariant.objects.get(sku="OPEN-1")
    logs = list(InventoryLog.objects.filter(variant=created))
    assert [log.delta for log in logs] == [12]
    assert logs[0].reason == "initial"
    assert created.stock == 12


def test_a_new_variant_created_without_stock_opens_at_zero_with_no_ledger_row(
    admin_api, admin_variants_url, product
):
    """Zero movement, zero rows -- record_movement returns None on a zero delta."""
    admin_api.post(
        admin_variants_url,
        {"product_id": product.pk, "sku": "EMPTY-1", "price": "100.00"},
        format="json",
    )

    created = ProductVariant.objects.get(sku="EMPTY-1")
    assert created.stock == 0
    assert InventoryLog.objects.filter(variant=created).count() == 0


def test_the_opening_stock_records_who_stocked_it(
    admin_api, admin_variants_url, product, admin_user
):
    admin_api.post(
        admin_variants_url,
        {"product_id": product.pk, "sku": "WHO-1", "price": "100.00", "stock": 3},
        format="json",
    )

    log = InventoryLog.objects.get(variant__sku="WHO-1")
    assert log.actor_id == admin_user.pk


def test_adding_a_variant_to_an_unknown_product_is_a_404(
    admin_api, admin_variants_url
):
    response = admin_api.post(
        admin_variants_url,
        {"product_id": 999_999, "sku": "GHOST-1", "price": "1.00"},
        format="json",
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# SKU uniqueness
# ---------------------------------------------------------------------------
def test_a_duplicate_sku_is_a_per_field_error_not_a_500(
    admin_api, admin_variants_url, product, variant
):
    response = admin_api.post(
        admin_variants_url,
        {"product_id": product.pk, "sku": variant.sku, "price": "1.00"},
        format="json",
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "SKU_TAKEN"
    assert error["field"] == "sku"


def test_a_duplicate_sku_on_patch_is_a_per_field_error_too(
    admin_api, admin_variant_url, product, variant
):
    other = factories.make_variant(product, sku="OTHER-1", price="10.00")

    response = admin_api.patch(
        admin_variant_url(other.pk), {"sku": variant.sku}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "sku"
    other.refresh_from_db()
    assert other.sku == "OTHER-1"


def test_a_variant_can_keep_its_own_sku_across_a_patch(
    admin_api, admin_variant_url, variant
):
    """The uniqueness check must exclude the row being edited, or no variant
    could ever be edited twice."""
    response = admin_api.patch(
        admin_variant_url(variant.pk),
        {"sku": variant.sku, "price": "61000.00"},
        format="json",
    )

    assert response.status_code == 200
    variant.refresh_from_db()
    assert str(variant.price) == "61000.00"


def test_a_blank_sku_is_refused_against_the_sku_field(
    admin_api, admin_variants_url, product
):
    response = admin_api.post(
        admin_variants_url,
        {"product_id": product.pk, "sku": "   ", "price": "1.00"},
        format="json",
    )

    assert response.status_code in (400, 422)
    assert response.json()["error"]["field"] == "sku"


# ---------------------------------------------------------------------------
# Every product keeps at least one variant (FR-CAT-4)
# ---------------------------------------------------------------------------
def test_the_last_active_variant_cannot_be_deleted(
    admin_api, admin_variant_url, variant
):
    response = admin_api.delete(admin_variant_url(variant.pk))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LAST_VARIANT"
    variant.refresh_from_db()
    assert variant.is_active is True


def test_the_last_active_variant_cannot_be_deactivated_by_patch_either(
    admin_api, admin_variant_url, variant
):
    """The same rule, reached by the other door. Guarding only DELETE would
    leave PATCH as an unlocked side entrance to the same broken state."""
    response = admin_api.patch(
        admin_variant_url(variant.pk), {"is_active": False}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LAST_VARIANT"
    variant.refresh_from_db()
    assert variant.is_active is True


def test_a_variant_can_be_deleted_while_a_sibling_still_carries_the_price(
    admin_api, admin_variant_url, product, variant
):
    spare = factories.make_variant(product, sku="SPARE-1", price="70000.00")

    response = admin_api.delete(admin_variant_url(spare.pk))

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    spare.refresh_from_db()
    assert spare.is_active is False
    assert ProductVariant.objects.filter(pk=spare.pk).exists(), "deleting deactivates"


def test_deleting_a_variant_leaves_the_product_sellable(
    admin_api, api, admin_variant_url, detail_url, product, variant
):
    spare = factories.make_variant(product, sku="SPARE-2", price="70000.00", stock=3)

    admin_api.delete(admin_variant_url(spare.pk))

    body = api.get(detail_url(product.slug)).json()
    assert [row["sku"] for row in body["variants"]] == [variant.sku]
    assert body["price_min"] == "62500.00"


def test_deactivating_a_variant_never_alters_an_order_already_placed(
    admin_api, admin_variant_url, product, variant
):
    spare = factories.make_variant(product, sku="SOLD-1", price="70000.00", stock=5)
    order = factories.place_order([(spare, 1)])
    snapshot = order.items.get().unit_price

    admin_api.patch(
        admin_variant_url(spare.pk), {"price": "1.00"}, format="json"
    )
    admin_api.delete(admin_variant_url(spare.pk))

    assert order.items.get().unit_price == snapshot


# ---------------------------------------------------------------------------
# Listing and thresholds
# ---------------------------------------------------------------------------
def test_the_variant_list_can_be_narrowed_to_one_product(
    admin_api, admin_variants_url, product, category
):
    other = factories.make_product(category, slug="other", sku="OTHER-SKU")

    body = admin_api.get(admin_variants_url, {"product": product.pk}).json()

    skus = {row["sku"] for row in body["results"]}
    assert skus == {"VIVO-8-512"}
    assert "OTHER-SKU" not in skus


def test_the_low_stock_threshold_is_configurable_per_variant(
    admin_api, admin_variant_url, variant
):
    """US-A4: each variant has a configurable low-stock threshold."""
    response = admin_api.patch(
        admin_variant_url(variant.pk), {"low_stock_threshold": 20}, format="json"
    )

    assert response.status_code == 200
    variant.refresh_from_db()
    assert variant.low_stock_threshold == 20
    assert response.json()["is_low_stock"] is True, "7 on hand is now below 20"
