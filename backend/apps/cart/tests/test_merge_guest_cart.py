"""
FR-CRT-2: the guest cart from localStorage folds into the server cart at login.

Two properties matter more than the arithmetic. First, quantities *sum* with
whatever the account already held -- a shopper who added a laptop on their
phone and another on their laptop keeps both. Second, a bad line is dropped
with a notice instead of failing the whole merge: losing one line is a far
better outcome than losing the entire cart because a single product went
inactive overnight.
"""
from decimal import Decimal

import pytest

from apps.cart.models import CartItem
from apps.cart.services import cart as cart_services
from apps.catalog.tests.factories import make_product
from apps.orders.services.totals import MAX_LINE_QUANTITY

pytestmark = pytest.mark.django_db


def codes(view):
    return [notice["code"] for notice in view.notices]


# ---------------------------------------------------------------------------
# The ordinary login merge
# ---------------------------------------------------------------------------
def test_a_guest_cart_merges_into_an_empty_account_cart(cart, variant, other_variant):
    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[
            {"variant_id": variant.pk, "quantity": 2},
            {"variant_id": other_variant.pk, "quantity": 1},
        ],
    )

    assert CartItem.objects.filter(cart=cart).count() == 2
    assert view.item_count == 3
    assert view.subtotal == Decimal("2250.50")  # 2 x 1000.00 + 1 x 250.50
    assert view.notices == []


def test_a_guest_line_defaults_to_one_unit_when_it_carries_no_quantity(cart, variant):
    view = cart_services.merge_guest_cart(
        cart=cart, items=[{"variant_id": variant.pk}]
    )

    assert view.lines[0].quantity == 1


def test_guest_quantities_combine_with_the_line_already_on_the_server(cart, variant):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)

    view = cart_services.merge_guest_cart(
        cart=cart, items=[{"variant_id": variant.pk, "quantity": 3}]
    )

    assert CartItem.objects.filter(cart=cart, variant=variant).count() == 1
    assert view.lines[0].quantity == 5
    assert view.subtotal == Decimal("5000.00")


def test_a_guest_payload_naming_the_same_variant_twice_lands_on_one_line(cart, variant):
    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[
            {"variant_id": variant.pk, "quantity": 1},
            {"variant_id": variant.pk, "quantity": 2},
        ],
    )

    assert CartItem.objects.filter(cart=cart, variant=variant).count() == 1
    assert view.lines[0].quantity == 3


@pytest.mark.parametrize("items", [[], None])
def test_merging_nothing_leaves_the_existing_cart_exactly_as_it_was(
    cart, variant, items
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)

    view = cart_services.merge_guest_cart(cart=cart, items=items)

    assert view.item_count == 2
    assert view.notices == []
    assert CartItem.objects.filter(cart=cart).count() == 1


def test_a_merge_only_ever_writes_to_the_cart_it_was_handed(
    cart, other_cart, variant
):
    cart_services.merge_guest_cart(
        cart=cart, items=[{"variant_id": variant.pk, "quantity": 2}]
    )

    assert CartItem.objects.filter(cart=other_cart).count() == 0


# ---------------------------------------------------------------------------
# Clamping still applies during a merge
# ---------------------------------------------------------------------------
def test_a_merged_quantity_beyond_available_stock_is_clamped_with_a_notice(
    cart, build_variant
):
    scarce = build_variant(price="500.00", stock=2, name="Scarce", slug="scarce")

    view = cart_services.merge_guest_cart(
        cart=cart, items=[{"variant_id": scarce.pk, "quantity": 6}]
    )

    assert view.lines[0].quantity == 2
    assert codes(view) == [cart_services.NOTICE_QUANTITY_CLAMPED]
    assert view.notices[0]["variant_id"] == scarce.pk
    assert view.notices[0]["item_id"] == view.lines[0].item.pk


def test_the_combined_quantity_is_what_gets_clamped_not_the_guest_line_alone(
    cart, build_variant
):
    scarce = build_variant(price="500.00", stock=4, name="Scarce", slug="scarce")
    cart_services.add_item(cart=cart, variant_id=scarce.pk, quantity=3)

    view = cart_services.merge_guest_cart(
        cart=cart, items=[{"variant_id": scarce.pk, "quantity": 3}]
    )

    assert view.lines[0].quantity == 4
    assert codes(view) == [cart_services.NOTICE_QUANTITY_CLAMPED]


def test_a_merge_is_still_capped_at_the_line_maximum(cart, build_variant):
    plentiful = build_variant(price="10.00", stock=500, name="Cable", slug="cable")

    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[
            {"variant_id": plentiful.pk, "quantity": MAX_LINE_QUANTITY},
            {"variant_id": plentiful.pk, "quantity": MAX_LINE_QUANTITY},
        ],
    )

    assert view.lines[0].quantity == MAX_LINE_QUANTITY
    assert codes(view) == [cart_services.NOTICE_QUANTITY_CLAMPED]


# ---------------------------------------------------------------------------
# Bad guest lines are dropped, never fatal
# ---------------------------------------------------------------------------
def test_a_guest_line_whose_variant_went_inactive_is_dropped_with_a_notice(
    cart, variant, category
):
    product = make_product(
        category,
        name="Retired variant",
        slug="retired-variant",
        variants=[{"sku": "RETIRED-9", "price": "900.00", "stock": 5, "is_active": False}],
    )
    retired = product.variants.get()

    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[
            {"variant_id": retired.pk, "quantity": 1},
            {"variant_id": variant.pk, "quantity": 2},
        ],
    )

    assert codes(view) == ["VARIANT_NOT_FOUND"]
    assert view.notices[0]["variant_id"] == retired.pk
    # The good line still merged -- one bad entry does not lose the cart.
    assert [line.variant.pk for line in view.lines] == [variant.pk]
    assert view.item_count == 2


def test_a_guest_line_that_sold_out_is_dropped_with_an_out_of_stock_notice(
    cart, variant, build_variant
):
    sold_out = build_variant(stock=0, name="Sold out", slug="sold-out")

    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[
            {"variant_id": sold_out.pk, "quantity": 1},
            {"variant_id": variant.pk, "quantity": 1},
        ],
    )

    assert codes(view) == ["OUT_OF_STOCK"]
    assert view.notices[0]["variant_id"] == sold_out.pk
    assert [line.variant.pk for line in view.lines] == [variant.pk]


def test_a_guest_line_naming_a_variant_that_no_longer_exists_is_dropped(cart, variant):
    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[
            {"variant_id": 987654321, "quantity": 1},
            {"variant_id": variant.pk, "quantity": 1},
        ],
    )

    assert codes(view) == ["VARIANT_NOT_FOUND"]
    assert view.notices[0]["variant_id"] == 987654321
    assert view.item_count == 1


@pytest.mark.parametrize("quantity", [0, -3, "abc", None])
def test_a_guest_line_with_an_unusable_quantity_is_dropped_with_an_invalid_quantity_notice(
    cart, variant, other_variant, quantity
):
    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[
            {"variant_id": variant.pk, "quantity": quantity},
            {"variant_id": other_variant.pk, "quantity": 1},
        ],
    )

    assert codes(view) == ["INVALID_QUANTITY"]
    assert [line.variant.pk for line in view.lines] == [other_variant.pk]


def test_a_guest_line_over_the_line_maximum_is_dropped_rather_than_clamped(
    cart, build_variant
):
    plentiful = build_variant(stock=500, name="Cable", slug="cable")

    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[{"variant_id": plentiful.pk, "quantity": MAX_LINE_QUANTITY + 1}],
    )

    assert codes(view) == ["QUANTITY_TOO_LARGE"]
    assert view.lines == []


def test_a_guest_line_missing_its_variant_id_entirely_is_dropped_with_a_null_variant(
    cart, variant
):
    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[{"quantity": 2}, {"variant_id": variant.pk, "quantity": 1}],
    )

    assert codes(view) == ["VARIANT_NOT_FOUND"]
    assert view.notices[0]["variant_id"] is None
    assert view.item_count == 1


def test_every_bad_guest_line_is_reported_not_just_the_first(cart, build_variant):
    sold_out = build_variant(stock=0, name="Sold out", slug="sold-out")

    view = cart_services.merge_guest_cart(
        cart=cart,
        items=[
            {"variant_id": sold_out.pk, "quantity": 1},
            {"variant_id": 987654321, "quantity": 1},
            {"variant_id": sold_out.pk, "quantity": 0},
        ],
    )

    assert codes(view) == ["OUT_OF_STOCK", "VARIANT_NOT_FOUND", "INVALID_QUANTITY"]
    assert view.lines == []


def test_merge_notices_are_listed_before_the_notices_the_cart_read_produces(
    cart, variant, build_variant
):
    scarce = build_variant(price="500.00", stock=2, name="Scarce", slug="scarce")
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    variant.stock = 0
    variant.save(update_fields=["stock"])

    view = cart_services.merge_guest_cart(
        cart=cart, items=[{"variant_id": scarce.pk, "quantity": 6}]
    )

    assert codes(view) == [
        cart_services.NOTICE_QUANTITY_CLAMPED,
        cart_services.NOTICE_ITEM_OUT_OF_STOCK,
    ]
