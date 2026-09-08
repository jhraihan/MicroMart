"""
Editing and emptying a cart.

The rule worth the most attention here is object-level authorisation: every
lookup is scoped to the caller's own cart, so another customer's line is a
**404, never a 403** -- a 403 would confirm the row exists and leak the ID
space (PRD 10.2).
"""
from decimal import Decimal

import pytest

from apps.cart.models import CartItem
from apps.cart.services import cart as cart_services
from apps.orders.services.totals import MAX_LINE_QUANTITY
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture
def line(cart, variant):
    """One line of two, so a test always has something to edit."""
    view = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    return view.lines[0].item


@pytest.fixture
def other_customers_line(other_cart, variant):
    view = cart_services.add_item(cart=other_cart, variant_id=variant.pk, quantity=7)
    return view.lines[0].item


# ---------------------------------------------------------------------------
# update_item
# ---------------------------------------------------------------------------
def test_updating_a_line_sets_the_new_quantity_and_returns_the_whole_cart(
    cart, line, variant
):
    view = cart_services.update_item(cart=cart, item_id=line.pk, quantity=5)

    assert CartItem.objects.get(pk=line.pk).quantity == 5
    (returned,) = view.lines
    assert returned.quantity == 5
    assert view.item_count == 5
    assert view.subtotal == Decimal("5000.00")
    assert view.notices == []


def test_updating_a_line_accepts_the_item_id_as_a_string_from_the_url(cart, line):
    view = cart_services.update_item(cart=cart, item_id=str(line.pk), quantity=4)

    assert view.lines[0].quantity == 4


def test_updating_above_available_stock_clamps_the_line_and_reports_the_clamp(
    cart, build_variant
):
    scarce = build_variant(price="500.00", stock=2, name="Scarce", slug="scarce")
    item = cart_services.add_item(cart=cart, variant_id=scarce.pk, quantity=1).lines[0].item

    view = cart_services.update_item(cart=cart, item_id=item.pk, quantity=9)

    assert CartItem.objects.get(pk=item.pk).quantity == 2
    assert view.notices[0]["code"] == cart_services.NOTICE_QUANTITY_CLAMPED
    assert view.notices[0]["item_id"] == item.pk
    assert view.notices[0]["variant_id"] == scarce.pk


def test_updating_a_line_replaces_the_quantity_rather_than_adding_to_it(cart, line):
    cart_services.update_item(cart=cart, item_id=line.pk, quantity=3)
    cart_services.update_item(cart=cart, item_id=line.pk, quantity=3)

    assert CartItem.objects.get(pk=line.pk).quantity == 3


@pytest.mark.parametrize("quantity", [0, -4, "abc", None])
def test_updating_to_a_quantity_below_one_is_rejected_because_removal_is_a_delete(
    cart, line, quantity
):
    with pytest.raises(DomainError) as exc:
        cart_services.update_item(cart=cart, item_id=line.pk, quantity=quantity)

    assert exc.value.code == "INVALID_QUANTITY"
    assert exc.value.field == "quantity"
    assert CartItem.objects.filter(pk=line.pk).exists()
    assert CartItem.objects.get(pk=line.pk).quantity == 2


def test_updating_above_the_line_maximum_is_rejected_and_leaves_the_line_alone(
    cart, line
):
    with pytest.raises(DomainError) as exc:
        cart_services.update_item(
            cart=cart, item_id=line.pk, quantity=MAX_LINE_QUANTITY + 1
        )

    assert exc.value.code == "QUANTITY_TOO_LARGE"
    assert CartItem.objects.get(pk=line.pk).quantity == 2


def test_updating_a_line_whose_variant_has_since_sold_out_is_rejected_as_out_of_stock(
    cart, line, variant
):
    variant.stock = 0
    variant.save(update_fields=["stock"])

    with pytest.raises(DomainError) as exc:
        cart_services.update_item(cart=cart, item_id=line.pk, quantity=1)

    assert exc.value.code == "OUT_OF_STOCK"


def test_updating_another_customers_line_is_a_404_shaped_not_found_and_never_a_403(
    cart, other_customers_line
):
    with pytest.raises(DomainError) as exc:
        cart_services.update_item(
            cart=cart, item_id=other_customers_line.pk, quantity=1
        )

    assert exc.value.code == "NOT_FOUND"
    assert exc.value.status_code == 404
    assert exc.value.status_code != 403


def test_another_customers_line_is_not_modified_by_a_failed_cross_cart_update(
    cart, other_customers_line
):
    with pytest.raises(DomainError):
        cart_services.update_item(
            cart=cart, item_id=other_customers_line.pk, quantity=1
        )

    assert CartItem.objects.get(pk=other_customers_line.pk).quantity == 7


@pytest.mark.parametrize("item_id", [987654321, "not-an-id", None])
def test_an_unknown_item_id_is_indistinguishable_from_another_customers_line(
    cart, item_id
):
    with pytest.raises(DomainError) as exc:
        cart_services.update_item(cart=cart, item_id=item_id, quantity=1)

    assert exc.value.code == "NOT_FOUND"
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# remove_item
# ---------------------------------------------------------------------------
def test_removing_a_line_deletes_it_and_returns_what_is_left_of_the_cart(
    cart, variant, other_variant
):
    keep = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)
    drop = cart_services.add_item(
        cart=cart, variant_id=other_variant.pk, quantity=1
    ).lines[0].item

    view = cart_services.remove_item(cart=cart, item_id=drop.pk)

    assert not CartItem.objects.filter(pk=drop.pk).exists()
    assert [line.variant.pk for line in view.lines] == [variant.pk]
    assert view.subtotal == Decimal("1000.00")
    assert keep.lines[0].item.pk in CartItem.objects.values_list("pk", flat=True)


def test_removing_the_last_line_leaves_an_empty_cart_rather_than_no_cart(cart, line):
    view = cart_services.remove_item(cart=cart, item_id=line.pk)

    assert view.lines == []
    assert view.item_count == 0
    assert view.subtotal == Decimal("0.00")
    assert view.cart.pk == cart.pk


def test_removing_another_customers_line_is_a_404_and_leaves_that_line_in_place(
    cart, other_customers_line
):
    with pytest.raises(DomainError) as exc:
        cart_services.remove_item(cart=cart, item_id=other_customers_line.pk)

    assert exc.value.code == "NOT_FOUND"
    assert exc.value.status_code == 404
    assert CartItem.objects.filter(pk=other_customers_line.pk).exists()


def test_removing_an_already_removed_line_is_a_404_rather_than_a_silent_success(
    cart, line
):
    cart_services.remove_item(cart=cart, item_id=line.pk)

    with pytest.raises(DomainError) as exc:
        cart_services.remove_item(cart=cart, item_id=line.pk)

    assert exc.value.code == "NOT_FOUND"


def test_removing_an_unavailable_line_still_works_so_a_dead_line_is_not_stuck(
    cart, line, variant
):
    variant.is_active = False
    variant.save(update_fields=["is_active"])

    view = cart_services.remove_item(cart=cart, item_id=line.pk)

    assert view.lines == []


# ---------------------------------------------------------------------------
# clear_cart
# ---------------------------------------------------------------------------
def test_clearing_a_cart_deletes_every_line_and_returns_the_cart_itself(
    cart, variant, other_variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    cart_services.add_item(cart=cart, variant_id=other_variant.pk, quantity=1)

    returned = cart_services.clear_cart(cart)

    assert returned.pk == cart.pk
    assert CartItem.objects.filter(cart=cart).count() == 0
    assert cart_services.read_cart(cart).item_count == 0


def test_clearing_an_already_empty_cart_is_a_no_op(cart):
    returned = cart_services.clear_cart(cart)

    assert returned.pk == cart.pk
    assert CartItem.objects.filter(cart=cart).count() == 0


def test_clearing_one_cart_never_touches_another_customers_cart(
    cart, variant, other_cart, other_customers_line
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)

    cart_services.clear_cart(cart)

    assert CartItem.objects.filter(cart=cart).count() == 0
    assert CartItem.objects.filter(cart=other_cart).count() == 1
