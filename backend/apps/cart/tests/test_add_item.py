"""
FR-CRT-3: adding a variant the cart already holds sums onto that one line, and
a quantity beyond what is on hand is trimmed with a notice rather than refused
-- a 422 here would throw away the add the customer just made.

Errors are asserted by `code`, never by message: codes are the stable contract
(PRD 7.1), messages are copy.
"""
from decimal import Decimal

import pytest

from apps.cart.models import CartItem
from apps.cart.services import cart as cart_services
from apps.catalog.tests.factories import make_product
from apps.orders.services.totals import MAX_LINE_QUANTITY
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_adding_a_variant_creates_one_line_at_the_requested_quantity(cart, variant):
    view = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=3)

    assert CartItem.objects.filter(cart=cart).count() == 1
    (line,) = view.lines
    assert line.variant.pk == variant.pk
    assert line.quantity == 3
    assert view.item_count == 3
    assert view.subtotal == Decimal("3000.00")
    assert view.notices == []


def test_adding_without_a_quantity_adds_a_single_unit(cart, variant):
    view = cart_services.add_item(cart=cart, variant_id=variant.pk)

    (line,) = view.lines
    assert line.quantity == 1


def test_adding_the_same_variant_twice_accumulates_onto_one_line_rather_than_duplicating_it(
    cart, variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    view = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=3)

    assert CartItem.objects.filter(cart=cart, variant=variant).count() == 1
    (line,) = view.lines
    assert line.quantity == 5
    assert view.item_count == 5
    assert view.subtotal == Decimal("5000.00")


def test_adding_a_second_variant_opens_a_second_line(cart, variant, other_variant):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)
    view = cart_services.add_item(cart=cart, variant_id=other_variant.pk, quantity=1)

    assert CartItem.objects.filter(cart=cart).count() == 2
    assert {line.variant.pk for line in view.lines} == {variant.pk, other_variant.pk}


def test_adding_touches_only_the_callers_own_cart(cart, other_cart, variant):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)

    assert CartItem.objects.filter(cart=other_cart).count() == 0
    assert cart_services.read_cart(other_cart).item_count == 0


# ---------------------------------------------------------------------------
# Clamping (_clamp)
# ---------------------------------------------------------------------------
def test_a_quantity_above_available_stock_is_clamped_to_stock_instead_of_rejected(
    cart, build_variant
):
    scarce = build_variant(price="500.00", stock=3, name="Scarce", slug="scarce")

    view = cart_services.add_item(cart=cart, variant_id=scarce.pk, quantity=10)

    (line,) = view.lines
    assert line.quantity == 3
    assert view.subtotal == Decimal("1500.00")
    assert CartItem.objects.get(cart=cart, variant=scarce).quantity == 3


def test_a_clamped_add_reports_a_quantity_clamped_notice_first_naming_the_line(
    cart, build_variant
):
    scarce = build_variant(price="500.00", stock=3, name="Scarce", slug="scarce")

    view = cart_services.add_item(cart=cart, variant_id=scarce.pk, quantity=10)

    (line,) = view.lines
    assert view.notices[0]["code"] == cart_services.NOTICE_QUANTITY_CLAMPED
    assert view.notices[0]["variant_id"] == scarce.pk
    assert view.notices[0]["item_id"] == line.item.pk


def test_accumulating_past_available_stock_clamps_the_combined_quantity(
    cart, build_variant
):
    scarce = build_variant(price="500.00", stock=4, name="Scarce", slug="scarce")
    cart_services.add_item(cart=cart, variant_id=scarce.pk, quantity=3)

    view = cart_services.add_item(cart=cart, variant_id=scarce.pk, quantity=3)

    (line,) = view.lines
    assert line.quantity == 4
    assert view.notices[0]["code"] == cart_services.NOTICE_QUANTITY_CLAMPED


def test_an_add_within_stock_produces_no_notice_at_all(cart, variant):
    view = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=10)

    assert view.lines[0].quantity == 10
    assert view.notices == []


def test_a_single_line_is_capped_at_the_line_maximum_even_when_stock_runs_deeper(
    cart, build_variant
):
    plentiful = build_variant(price="10.00", stock=500, name="Cable", slug="cable")
    cart_services.add_item(cart=cart, variant_id=plentiful.pk, quantity=MAX_LINE_QUANTITY)

    view = cart_services.add_item(cart=cart, variant_id=plentiful.pk, quantity=5)

    (line,) = view.lines
    assert line.quantity == MAX_LINE_QUANTITY
    assert view.notices[0]["code"] == cart_services.NOTICE_QUANTITY_CLAMPED


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------
def test_adding_a_variant_with_nothing_left_on_the_shelf_is_rejected_as_out_of_stock(
    cart, build_variant
):
    sold_out = build_variant(stock=0, name="Sold out", slug="sold-out")

    with pytest.raises(DomainError) as exc:
        cart_services.add_item(cart=cart, variant_id=sold_out.pk, quantity=1)

    assert exc.value.code == "OUT_OF_STOCK"
    assert exc.value.field == "variant_id"
    assert exc.value.status_code == 422
    assert CartItem.objects.filter(cart=cart).count() == 0


def test_adding_more_than_the_line_maximum_in_one_call_is_rejected_outright(
    cart, build_variant
):
    plentiful = build_variant(stock=500, name="Cable", slug="cable")

    with pytest.raises(DomainError) as exc:
        cart_services.add_item(
            cart=cart, variant_id=plentiful.pk, quantity=MAX_LINE_QUANTITY + 1
        )

    assert exc.value.code == "QUANTITY_TOO_LARGE"
    assert exc.value.field == "quantity"
    assert CartItem.objects.filter(cart=cart).count() == 0


@pytest.mark.parametrize("quantity", [0, -1, -99, "abc", "", None, [1]])
def test_a_quantity_that_is_not_a_whole_number_of_at_least_one_is_rejected(
    cart, variant, quantity
):
    with pytest.raises(DomainError) as exc:
        cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=quantity)

    assert exc.value.code == "INVALID_QUANTITY"
    assert exc.value.field == "quantity"
    assert CartItem.objects.filter(cart=cart).count() == 0


def test_a_rejected_quantity_never_leaves_a_half_written_line_behind(cart, variant):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)

    with pytest.raises(DomainError):
        cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=0)

    assert CartItem.objects.get(cart=cart, variant=variant).quantity == 2


def test_adding_an_unknown_variant_id_is_a_404_shaped_not_found(cart):
    with pytest.raises(DomainError) as exc:
        cart_services.add_item(cart=cart, variant_id=987654321, quantity=1)

    assert exc.value.code == "VARIANT_NOT_FOUND"
    assert exc.value.field == "variant_id"
    assert exc.value.status_code == 404


@pytest.mark.parametrize("variant_id", ["not-a-number", None, ""])
def test_a_variant_id_that_is_not_an_id_at_all_is_the_same_404_shaped_not_found(
    cart, variant_id
):
    with pytest.raises(DomainError) as exc:
        cart_services.add_item(cart=cart, variant_id=variant_id, quantity=1)

    assert exc.value.code == "VARIANT_NOT_FOUND"
    assert exc.value.status_code == 404


def test_adding_a_deactivated_variant_is_a_404_and_never_reveals_that_it_exists(
    cart, category
):
    product = make_product(
        category,
        name="Retired variant",
        slug="retired-variant",
        variants=[{"sku": "RETIRED-1", "price": "900.00", "stock": 5, "is_active": False}],
    )
    retired = product.variants.get()

    with pytest.raises(DomainError) as exc:
        cart_services.add_item(cart=cart, variant_id=retired.pk, quantity=1)

    assert exc.value.code == "VARIANT_NOT_FOUND"
    assert exc.value.status_code == 404


def test_adding_a_variant_of_a_deactivated_product_is_a_404(cart, build_variant):
    hidden = build_variant(name="Unreleased", slug="unreleased", is_active=False)

    with pytest.raises(DomainError) as exc:
        cart_services.add_item(cart=cart, variant_id=hidden.pk, quantity=1)

    assert exc.value.code == "VARIANT_NOT_FOUND"
    assert exc.value.status_code == 404


def test_adding_a_variant_from_a_deactivated_category_is_a_404(cart, variant, category):
    category.is_active = False
    category.save(update_fields=["is_active"])

    with pytest.raises(DomainError) as exc:
        cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)

    assert exc.value.code == "VARIANT_NOT_FOUND"
    assert exc.value.status_code == 404
