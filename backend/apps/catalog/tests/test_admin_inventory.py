"""
Admin inventory: the stock list, the low-stock filter, and manual adjustment
(PRD 4.3 US-A4, 7.3 /admin/inventory/, FR-INV-6..8, 6.4).

The invariant under test is the one PRD 6.4 calls "a cheap integrity check":

    sum(InventoryLog.delta) == ProductVariant.stock

It is cheap only because it is *total* -- every movement writes a row, so any
discrepancy is a real bug rather than a known exception to be reasoned around.
The reconciliation test below therefore builds its variant through the admin
API rather than through the test factory: the factory assigns `stock` directly
and writes no ledger row, which is fine for a fixture and fatal for this claim.
"""
import pytest

from apps.catalog.models import InventoryLog, ProductVariant
from apps.catalog.services import inventory as inventory_services
from apps.catalog.tests import factories

pytestmark = pytest.mark.django_db


def ledger_total(variant):
    return inventory_services.logged_stock(variant)


def create_variant_through_the_api(admin_api, url, product, *, sku, stock, price="100.00"):
    """A variant whose whole history is on the record, opening quantity included."""
    response = admin_api.post(
        url,
        {"product_id": product.pk, "sku": sku, "price": price, "stock": stock},
        format="json",
    )
    assert response.status_code == 201, response.json()
    return ProductVariant.objects.get(sku=sku)


# ---------------------------------------------------------------------------
# GET /admin/inventory/
# ---------------------------------------------------------------------------
def test_the_inventory_list_shows_stock_across_variants(
    admin_api, admin_inventory_url, product, category
):
    factories.make_product(category, slug="second", sku="SECOND-1", stock=3)

    body = admin_api.get(admin_inventory_url).json()

    by_sku = {row["sku"]: row for row in body["results"]}
    assert by_sku["VIVO-8-512"]["stock"] == 7
    assert by_sku["SECOND-1"]["stock"] == 3


def test_a_row_carries_what_a_reorder_decision_needs(
    admin_api, admin_inventory_url, product
):
    row = admin_api.get(admin_inventory_url).json()["results"][0]

    assert row["product_name"] == "Asus Vivobook Go 15"
    assert row["category_name"] == "Laptops"
    assert row["brand_name"] == "Asus"
    assert row["low_stock_threshold"] == 5
    assert row["is_low_stock"] is False


def test_the_low_stock_filter_returns_exactly_what_the_digest_would_send(
    admin_api, admin_inventory_url, category
):
    """
    FR-INV-6/7: at or below the variant's *own* threshold. The endpoint and the
    cron digest read the same service function, so the alert count on the
    dashboard and the list on this screen can never disagree.
    """
    plenty = factories.make_product(category, slug="plenty", sku="PLENTY-1", variants=[])
    factories.make_variant(plenty, sku="PLENTY-1", price="10.00", stock=50, low_stock_threshold=5)

    low = factories.make_product(category, slug="low", variants=[])
    factories.make_variant(low, sku="LOW-1", price="10.00", stock=2, low_stock_threshold=5)

    empty = factories.make_product(category, slug="empty", variants=[])
    factories.make_variant(empty, sku="OUT-1", price="10.00", stock=0, low_stock_threshold=5)

    body = admin_api.get(admin_inventory_url, {"low_stock": "true"}).json()

    skus = [row["sku"] for row in body["results"]]
    assert set(skus) == {"LOW-1", "OUT-1"}, "at or below, so zero counts too"
    assert skus[0] == "OUT-1", "the most urgent line sorts first"
    assert set(skus) == {
        variant.sku for variant in inventory_services.low_stock_variants()
    }


def test_a_threshold_is_per_variant_not_a_global_number(
    admin_api, admin_inventory_url, category
):
    """US-A4: *each* variant has a configurable threshold."""
    product = factories.make_product(category, slug="thresholds", variants=[])
    factories.make_variant(product, sku="TIGHT-1", price="10.00", stock=4, low_stock_threshold=10)
    factories.make_variant(product, sku="LOOSE-1", price="10.00", stock=4, low_stock_threshold=1)

    skus = [
        row["sku"]
        for row in admin_api.get(admin_inventory_url, {"low_stock": "true"}).json()["results"]
    ]

    assert skus == ["TIGHT-1"], "same stock, different thresholds, different answers"


def test_the_page_carries_a_summary_counted_over_the_whole_catalogue(
    admin_api, admin_inventory_url, category
):
    for index in range(3):
        product = factories.make_product(category, slug="p{0}".format(index), variants=[])
        factories.make_variant(
            product, sku="S-{0}".format(index), price="10.00", stock=0, low_stock_threshold=2
        )

    body = admin_api.get(admin_inventory_url).json()

    assert body["summary"]["variant_count"] == 3
    assert body["summary"]["low_stock_count"] == 3
    assert body["summary"]["out_of_stock_count"] == 3


def test_withdrawn_variants_are_out_of_the_stock_list_unless_asked_for(
    admin_api, admin_inventory_url, product, variant
):
    spare = factories.make_variant(
        product, sku="GONE-1", price="10.00", stock=9, is_active=False
    )

    default = admin_api.get(admin_inventory_url).json()
    widened = admin_api.get(admin_inventory_url, {"include_inactive": "true"}).json()

    assert "GONE-1" not in {row["sku"] for row in default["results"]}
    assert "GONE-1" in {row["sku"] for row in widened["results"]}


def test_a_nonsense_filter_value_is_a_422_rather_than_being_ignored(
    admin_api, admin_inventory_url
):
    response = admin_api.get(admin_inventory_url, {"low_stock": "perhaps"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FILTER"


# ---------------------------------------------------------------------------
# POST /admin/inventory/adjust/
# ---------------------------------------------------------------------------
def test_an_adjustment_moves_the_stock_and_writes_the_reason(
    admin_api, admin_inventory_adjust_url, variant, admin_user, restock_reason
):
    response = admin_api.post(
        admin_inventory_adjust_url,
        {
            "variant_id": variant.pk,
            "delta": 5,
            "reason": restock_reason,
            "note": "Delivery from supplier",
        },
        format="json",
    )

    assert response.status_code == 200
    variant.refresh_from_db()
    assert variant.stock == 12

    log = InventoryLog.objects.filter(variant=variant).latest("id")
    assert log.delta == 5
    assert log.reason == restock_reason
    assert log.note == "Delivery from supplier"
    assert log.actor_id == admin_user.pk


def test_an_adjustment_without_a_reason_is_refused(
    admin_api, admin_inventory_adjust_url, variant
):
    """FR-INV-8 calls the reason mandatory, and the ledger is worthless without
    it -- a column of deltas with no 'why' cannot be audited."""
    before = variant.stock

    response = admin_api.post(
        admin_inventory_adjust_url, {"variant_id": variant.pk, "delta": 5}, format="json"
    )

    assert response.status_code in (400, 422)
    assert response.json()["error"]["field"] == "reason"
    variant.refresh_from_db()
    assert variant.stock == before


def test_an_order_driven_reason_cannot_be_typed_in_by_hand(
    admin_api, admin_inventory_adjust_url, variant
):
    """
    `order_confirmed` and `order_cancelled` belong to the order state machine.
    A hand-written one would put a movement in the ledger that no order can
    account for, which is exactly the reconciliation nobody could later explain.
    """
    response = admin_api.post(
        admin_inventory_adjust_url,
        {"variant_id": variant.pk, "delta": -1, "reason": "order_confirmed"},
        format="json",
    )

    assert response.status_code in (400, 422)
    assert response.json()["error"]["field"] == "reason"


def test_an_adjustment_of_zero_is_refused_rather_than_logged(
    admin_api, admin_inventory_adjust_url, variant, restock_reason
):
    response = admin_api.post(
        admin_inventory_adjust_url,
        {"variant_id": variant.pk, "delta": 0, "reason": restock_reason},
        format="json",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_DELTA"


def test_an_adjustment_cannot_take_stock_below_zero(
    admin_api, admin_inventory_adjust_url, variant
):
    """The application refuses before the DB CHECK (stock >= 0) has to, so the
    admin gets a sentence rather than an IntegrityError."""
    response = admin_api.post(
        admin_inventory_adjust_url,
        {"variant_id": variant.pk, "delta": -100, "reason": "damage"},
        format="json",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    variant.refresh_from_db()
    assert variant.stock == 7


def test_adjusting_an_unknown_variant_is_refused_against_the_variant_field(
    admin_api, admin_inventory_adjust_url, restock_reason
):
    response = admin_api.post(
        admin_inventory_adjust_url,
        {"variant_id": 999_999, "delta": 1, "reason": restock_reason},
        format="json",
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VARIANT_NOT_FOUND"
    assert error["field"] == "variant_id"


def test_the_response_reports_the_ledger_total_beside_the_column(
    admin_api, admin_inventory_adjust_url, admin_variants_url, product, restock_reason
):
    created = create_variant_through_the_api(
        admin_api, admin_variants_url, product, sku="LEDGER-1", stock=10
    )

    body = admin_api.post(
        admin_inventory_adjust_url,
        {"variant_id": created.pk, "delta": -3, "reason": "damage"},
        format="json",
    ).json()

    assert body["variant"]["stock"] == 7
    assert body["logged_stock"] == 7, "the two numbers are the same number"


# ---------------------------------------------------------------------------
# The ledger invariant
# ---------------------------------------------------------------------------
def test_the_ledger_reconciles_to_the_column_after_a_run_of_adjustments(
    admin_api, admin_variants_url, admin_inventory_adjust_url, product
):
    """
    PRD 6.4: summing deltas must reconcile to current stock. Asserted after a
    sequence rather than a single move, because the failure mode this guards
    against is drift -- one path in ten that writes the column without the row.
    """
    created = create_variant_through_the_api(
        admin_api, admin_variants_url, product, sku="RECON-1", stock=20
    )

    moves = [(5, "restock"), (-3, "damage"), (12, "restock"), (-9, "manual_adjustment")]
    for delta, reason in moves:
        response = admin_api.post(
            admin_inventory_adjust_url,
            {"variant_id": created.pk, "delta": delta, "reason": reason},
            format="json",
        )
        assert response.status_code == 200, response.json()

    created.refresh_from_db()
    assert created.stock == 20 + 5 - 3 + 12 - 9
    assert ledger_total(created) == created.stock
    assert InventoryLog.objects.filter(variant=created).count() == 1 + len(moves)


def test_a_refused_adjustment_leaves_neither_the_column_nor_the_ledger_marked(
    admin_api, admin_variants_url, admin_inventory_adjust_url, product
):
    """A rejection that had already written half of itself is the worst kind."""
    created = create_variant_through_the_api(
        admin_api, admin_variants_url, product, sku="RECON-2", stock=4
    )

    admin_api.post(
        admin_inventory_adjust_url,
        {"variant_id": created.pk, "delta": -50, "reason": "damage"},
        format="json",
    )

    created.refresh_from_db()
    assert created.stock == 4
    assert ledger_total(created) == 4
    assert InventoryLog.objects.filter(variant=created).count() == 1


def test_the_ledger_still_reconciles_when_an_order_moved_the_same_stock(
    admin_api, admin_variants_url, admin_inventory_adjust_url, product, admin_user
):
    """
    The order state machine and the admin adjustment write to the same ledger
    through the same service. If either had its own path, this is where the two
    numbers would part company.
    """
    from apps.orders.models import OrderStatus
    from apps.orders.services import placement

    created = create_variant_through_the_api(
        admin_api, admin_variants_url, product, sku="RECON-3", stock=10
    )
    admin_api.post(
        admin_inventory_adjust_url,
        {"variant_id": created.pk, "delta": 5, "reason": "restock"},
        format="json",
    )

    order = factories.place_order([(created, 4)], status=OrderStatus.PENDING)
    placement.confirm_order(order, actor=admin_user)

    created.refresh_from_db()
    assert created.stock == 10 + 5 - 4
    assert ledger_total(created) == created.stock


# ---------------------------------------------------------------------------
# GET /admin/inventory/{variant_id}/logs/
# ---------------------------------------------------------------------------
def test_the_ledger_endpoint_shows_the_movements_behind_the_number(
    admin_api, admin_variants_url, admin_inventory_adjust_url,
    admin_inventory_ledger_url, product
):
    created = create_variant_through_the_api(
        admin_api, admin_variants_url, product, sku="AUDIT-1", stock=6
    )
    admin_api.post(
        admin_inventory_adjust_url,
        {"variant_id": created.pk, "delta": -2, "reason": "damage", "note": "Dropped"},
        format="json",
    )

    body = admin_api.get(admin_inventory_ledger_url(created.pk)).json()

    assert body["stock"] == 4
    assert body["logged_stock"] == 4
    assert [(row["delta"], row["reason"]) for row in body["logs"]] == [
        (-2, "damage"),
        (6, "initial"),
    ]
    assert body["logs"][0]["note"] == "Dropped"
