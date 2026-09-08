"""
FR-CRT-5: a cart is a wish, not a promise, so availability is re-derived on
every read and a line that went bad is reported rather than quietly dropped.

These tests pin the shape read_cart returns -- CartView and its CartLine rows --
because both the serializer and the checkout services read those attributes.

A line's `issue` is the catalogue's vocabulary (`inventory_services.ISSUE_*`,
lowercase), not the cart's own `notices` vocabulary (`NOTICE_*`, uppercase).
They are asserted against different constants on purpose: the frozen contract
fixes `issue` so a cart line and a quote line describe the same condition with
the same string, while a notice is the cart's own "here is what changed"
message and nothing outside this app branches on it.
"""
from decimal import Decimal

import pytest

from apps.cart.models import Cart, CartItem
from apps.cart.services import cart as cart_services
from apps.catalog.services import inventory as inventory_services
from apps.catalog.tests.factories import make_category, make_product

pytestmark = pytest.mark.django_db


def test_a_customer_with_no_cart_yet_gets_one_created_on_first_read(customer):
    assert Cart.objects.filter(user=customer).count() == 0

    cart = cart_services.get_cart(customer)

    assert cart.pk is not None
    assert cart.user_id == customer.pk
    assert Cart.objects.filter(user=customer).count() == 1


def test_get_cart_returns_the_same_cart_every_time_and_never_makes_a_second_one(
    customer,
):
    first = cart_services.get_cart(customer)
    second = cart_services.get_cart(customer)

    assert first.pk == second.pk
    assert Cart.objects.filter(user=customer).count() == 1


def test_a_fresh_cart_reads_as_no_lines_no_notices_and_a_zero_subtotal(cart):
    view = cart_services.read_cart(cart)

    assert view.cart == cart
    assert view.lines == []
    assert view.notices == []
    assert view.item_count == 0
    assert view.subtotal == Decimal("0.00")
    assert view.purchasable_lines == []


def test_a_cart_line_reports_quantity_unit_price_and_line_total_from_the_variant_row(
    cart, variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=3)

    (line,) = cart_services.read_cart(cart).lines

    assert line.item.pk is not None
    assert line.variant.pk == variant.pk
    assert line.quantity == 3
    assert line.effective_quantity == 3
    assert line.unit_price == Decimal("1000.00")
    assert line.line_total == Decimal("3000.00")
    assert line.available_stock == 10
    assert line.is_available is True
    assert line.issue is None


def test_the_subtotal_and_item_count_are_summed_across_every_available_line(
    cart, variant, other_variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    cart_services.add_item(cart=cart, variant_id=other_variant.pk, quantity=2)

    view = cart_services.read_cart(cart)

    assert view.item_count == 4
    assert view.subtotal == Decimal("2501.00")  # 2 x 1000.00 + 2 x 250.50
    assert len(view.purchasable_lines) == 2


def test_the_most_recently_added_line_is_listed_first(cart, variant, other_variant):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)
    cart_services.add_item(cart=cart, variant_id=other_variant.pk, quantity=1)

    view = cart_services.read_cart(cart)

    assert [line.variant.pk for line in view.lines] == [other_variant.pk, variant.pk]


def test_a_line_whose_variant_was_deactivated_is_kept_but_left_out_of_the_total(
    cart, variant, other_variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    cart_services.add_item(cart=cart, variant_id=other_variant.pk, quantity=1)

    variant.is_active = False
    variant.save(update_fields=["is_active"])
    view = cart_services.read_cart(cart)

    dead = next(line for line in view.lines if line.variant.pk == variant.pk)
    assert dead.is_available is False
    assert dead.issue == inventory_services.ISSUE_UNAVAILABLE
    assert dead.available_stock == 0
    assert dead.line is None
    # Still listed, so the customer can see what vanished and decide.
    assert len(view.lines) == 2
    assert view.subtotal == Decimal("250.50")
    assert view.item_count == 1


def test_a_deactivated_line_reports_an_item_unavailable_notice_naming_the_row(
    cart, variant
):
    view = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)
    (item_id,) = [line.item.pk for line in view.lines]

    variant.is_active = False
    variant.save(update_fields=["is_active"])
    notices = cart_services.read_cart(cart).notices

    assert [notice["code"] for notice in notices] == [
        cart_services.NOTICE_ITEM_UNAVAILABLE
    ]
    assert notices[0]["item_id"] == item_id
    assert notices[0]["variant_id"] == variant.pk


def test_a_line_whose_product_was_deactivated_is_reported_unavailable(cart, variant):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)

    product = variant.product
    product.is_active = False
    product.save(update_fields=["is_active"])
    (line,) = cart_services.read_cart(cart).lines

    assert line.is_available is False
    assert line.issue == inventory_services.ISSUE_UNAVAILABLE


def test_a_line_whose_category_was_deactivated_is_reported_unavailable(
    cart, variant, category
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)

    category.is_active = False
    category.save(update_fields=["is_active"])
    (line,) = cart_services.read_cart(cart).lines

    assert line.is_available is False
    assert line.issue == inventory_services.ISSUE_UNAVAILABLE


def test_a_line_whose_parent_category_was_deactivated_is_reported_unavailable(
    cart, category
):
    child = make_category("Gaming laptops", "gaming-laptops", parent=category)
    product = make_product(
        child, name="Asus TUF F15", slug="asus-tuf-f15", sku="TUF-F15", stock=5
    )
    child_variant = product.variants.get()
    cart_services.add_item(cart=cart, variant_id=child_variant.pk, quantity=1)

    category.is_active = False
    category.save(update_fields=["is_active"])
    (line,) = cart_services.read_cart(cart).lines

    assert line.is_available is False
    assert line.issue == inventory_services.ISSUE_UNAVAILABLE


def test_a_line_that_has_since_sold_out_is_reported_out_of_stock_and_not_priced(
    cart, variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)

    variant.stock = 0
    variant.save(update_fields=["stock"])
    view = cart_services.read_cart(cart)

    (line,) = view.lines
    assert line.is_available is False
    assert line.issue == inventory_services.ISSUE_OUT_OF_STOCK
    assert line.available_stock == 0
    assert view.subtotal == Decimal("0.00")
    assert view.item_count == 0
    assert [notice["code"] for notice in view.notices] == [
        cart_services.NOTICE_ITEM_OUT_OF_STOCK
    ]


def test_a_line_holding_more_than_is_left_is_priced_at_what_is_left_and_says_so(
    cart, variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=6)

    variant.stock = 2
    variant.save(update_fields=["stock"])
    view = cart_services.read_cart(cart)

    (line,) = view.lines
    assert line.is_available is True
    assert line.issue == inventory_services.ISSUE_INSUFFICIENT_STOCK
    assert line.quantity == 6  # what the customer asked for, untouched
    assert line.effective_quantity == 2  # what can actually be bought
    assert line.line_total == Decimal("2000.00")
    assert view.item_count == 2
    assert view.subtotal == Decimal("2000.00")
    assert [notice["code"] for notice in view.notices] == [
        cart_services.NOTICE_QUANTITY_CLAMPED
    ]


def test_re_reading_a_clamped_line_never_rewrites_the_stored_quantity(cart, variant):
    view = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=6)
    (item_id,) = [line.item.pk for line in view.lines]

    variant.stock = 2
    variant.save(update_fields=["stock"])
    cart_services.read_cart(cart)
    cart_services.read_cart(cart)

    # Reading is not a mutation: if stock is restocked the customer still
    # wanted six.
    assert CartItem.objects.get(pk=item_id).quantity == 6


def test_every_money_figure_on_a_cart_is_a_two_decimal_place_decimal_never_a_float(
    cart, variant, other_variant
):
    # The type check is the point: a float that happens to compare equal is
    # still one arithmetic step away from charging 2500.9999999999995.
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    cart_services.add_item(cart=cart, variant_id=other_variant.pk, quantity=2)

    view = cart_services.read_cart(cart)

    figures = [view.subtotal]
    for line in view.lines:
        figures += [line.unit_price, line.line_total]
    for figure in figures:
        assert type(figure) is Decimal, figure
    assert view.subtotal.as_tuple().exponent == -2
