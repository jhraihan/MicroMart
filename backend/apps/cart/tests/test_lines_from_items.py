"""
`lines_from_items` prices an arbitrary [{variant_id, quantity}] payload -- the
guest checkout path, where the browser holds the cart and the server prices it.

The security property under test: nothing but the variant id and the quantity
is read from the client. The price comes from the variant row every time, so a
client that names its own price is priced at the catalogue's price anyway.
"""
from decimal import Decimal

import pytest

from apps.cart.services import cart as cart_services
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


def test_each_entry_is_priced_from_the_variant_row_not_from_the_payload(
    variant, other_variant
):
    lines = cart_services.lines_from_items(
        [
            {"variant_id": variant.pk, "quantity": 2, "unit_price": "1.00"},
            {"variant_id": other_variant.pk, "quantity": 1},
        ]
    )

    assert [line.unit_price for line in lines] == [
        Decimal("1000.00"),
        Decimal("250.50"),
    ]
    assert [line.quantity for line in lines] == [2, 1]
    assert [line.line_total for line in lines] == [
        Decimal("2000.00"),
        Decimal("250.50"),
    ]


def test_a_line_snapshots_the_name_label_and_sku_it_was_priced_with(variant):
    (line,) = cart_services.lines_from_items([{"variant_id": variant.pk}])

    assert line.quantity == 1
    assert line.product_name == "Asus Vivobook Go 15"
    assert line.sku == "VIVO-8-512"
    assert line.variant_label == variant.label


def test_a_payload_naming_the_same_variant_twice_is_one_line_with_the_summed_quantity(
    variant
):
    lines = cart_services.lines_from_items(
        [
            {"variant_id": variant.pk, "quantity": 2},
            {"variant_id": variant.pk, "quantity": 3},
        ]
    )

    assert len(lines) == 1
    assert lines[0].quantity == 5


@pytest.mark.parametrize("items", [[], None])
def test_an_empty_payload_prices_to_no_lines_at_all(items):
    assert cart_services.lines_from_items(items) == []


def test_an_unknown_variant_is_a_404_shaped_not_found(db):
    with pytest.raises(DomainError) as exc:
        cart_services.lines_from_items([{"variant_id": 987654321, "quantity": 1}])

    assert exc.value.code == "VARIANT_NOT_FOUND"
    assert exc.value.status_code == 404


def test_an_unpurchasable_variant_is_a_404_shaped_not_found(build_variant):
    hidden = build_variant(name="Unreleased", slug="unreleased", is_active=False)

    with pytest.raises(DomainError) as exc:
        cart_services.lines_from_items([{"variant_id": hidden.pk, "quantity": 1}])

    assert exc.value.code == "VARIANT_NOT_FOUND"


@pytest.mark.parametrize("quantity", [0, -1, "abc"])
def test_an_unusable_quantity_is_rejected_rather_than_coerced(variant, quantity):
    with pytest.raises(DomainError) as exc:
        cart_services.lines_from_items(
            [{"variant_id": variant.pk, "quantity": quantity}]
        )

    assert exc.value.code == "INVALID_QUANTITY"


def test_pricing_does_not_check_stock_because_availability_is_settled_at_placement(
    build_variant
):
    # purchasable_variants() deliberately excludes stock from its predicate so
    # a sold-out variant still resolves; the oversell guard lives in order
    # placement, under SELECT ... FOR UPDATE.
    sold_out = build_variant(price="750.00", stock=0, name="Sold out", slug="sold-out")

    (line,) = cart_services.lines_from_items([{"variant_id": sold_out.pk}])

    assert line.unit_price == Decimal("750.00")
    assert line.quantity == 1
