"""
The invariant this whole module exists to protect: **a cart reserves nothing.**

PRD FR-INV-2 -- stock moves only when an order is confirmed. Nothing in
apps/cart may write ProductVariant.stock or append to the InventoryLog ledger,
so every cart operation is asserted against a snapshot of both taken before the
call. The ledger is seeded with a real opening row first, so "unchanged" is a
meaningful assertion and not just 0 == 0.

The clamp is the part most likely to be misread as a reservation: it trims a
quantity so the customer is not surprised at checkout, but it holds nothing
back -- two shoppers can each hold the entire remaining stock in their carts.
"""
import pytest

from apps.catalog.models import InventoryLog, InventoryReason, ProductVariant
from apps.cart.services import cart as cart_services
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture
def opening_ledger(variant, other_variant):
    """
    The row a real restock would have written, so "unchanged" is a meaningful
    assertion rather than 0 == 0.

    Returns a callable giving the ledger rows that exist for one variant, which
    is what every assertion below compares against.
    """
    for row in (variant, other_variant):
        InventoryLog.objects.create(
            variant=row, delta=row.stock, reason=InventoryReason.INITIAL
        )
    return lambda *variants: InventoryLog.objects.filter(
        variant_id__in=[v.pk for v in variants]
    ).count()


def test_adding_to_the_cart_moves_no_stock_and_writes_no_ledger_row(
    cart, variant, inventory_state, opening_ledger
):
    before = inventory_state(variant)

    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=4)

    assert inventory_state(variant) == before
    assert ProductVariant.objects.get(pk=variant.pk).stock == 10
    assert opening_ledger(variant) == 1  # still just the opening row


def test_adding_the_entire_remaining_stock_still_leaves_it_all_on_the_shelf(
    cart, build_variant, inventory_state
):
    scarce = build_variant(stock=3, name="Scarce", slug="scarce")
    before = inventory_state(scarce)

    cart_services.add_item(cart=cart, variant_id=scarce.pk, quantity=3)

    assert inventory_state(scarce) == before
    assert ProductVariant.objects.get(pk=scarce.pk).stock == 3


def test_a_clamped_add_reserves_nothing_so_a_second_shopper_can_take_the_same_units(
    cart, other_cart, build_variant, inventory_state
):
    scarce = build_variant(stock=3, name="Scarce", slug="scarce")
    before = inventory_state(scarce)

    first = cart_services.add_item(cart=cart, variant_id=scarce.pk, quantity=5)
    second = cart_services.add_item(cart=other_cart, variant_id=scarce.pk, quantity=5)

    # Both carts clamp to the same 3 units, because a cart is a wish.
    assert first.lines[0].quantity == 3
    assert second.lines[0].quantity == 3
    assert inventory_state(scarce) == before


def test_updating_a_cart_line_moves_no_stock_and_writes_no_ledger_row(
    cart, variant, inventory_state, opening_ledger
):
    item = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2).lines[0].item
    before = inventory_state(variant)

    cart_services.update_item(cart=cart, item_id=item.pk, quantity=9)

    assert inventory_state(variant) == before
    assert opening_ledger(variant) == 1


def test_merging_a_guest_cart_moves_no_stock_and_writes_no_ledger_row(
    cart, variant, other_variant, inventory_state, opening_ledger
):
    before = inventory_state(variant, other_variant)

    cart_services.merge_guest_cart(
        cart=cart,
        items=[
            {"variant_id": variant.pk, "quantity": 5},
            {"variant_id": other_variant.pk, "quantity": 99},  # clamped to 3
        ],
    )

    assert inventory_state(variant, other_variant) == before
    assert opening_ledger(variant, other_variant) == 2


def test_removing_and_clearing_move_no_stock_and_write_no_ledger_row(
    cart, variant, other_variant, inventory_state, opening_ledger
):
    item = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2).lines[0].item
    cart_services.add_item(cart=cart, variant_id=other_variant.pk, quantity=1)
    before = inventory_state(variant, other_variant)

    cart_services.remove_item(cart=cart, item_id=item.pk)
    cart_services.clear_cart(cart)

    assert inventory_state(variant, other_variant) == before
    assert opening_ledger(variant, other_variant) == 2


def test_a_rejected_add_moves_no_stock_either(
    cart, build_variant, inventory_state
):
    sold_out = build_variant(stock=0, name="Sold out", slug="sold-out")
    before = inventory_state(sold_out)

    with pytest.raises(DomainError):
        cart_services.add_item(cart=cart, variant_id=sold_out.pk, quantity=1)

    assert inventory_state(sold_out) == before


def test_reading_a_cart_never_writes_stock_even_when_it_reports_a_clamp(
    cart, variant, inventory_state, opening_ledger
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=8)
    variant.stock = 2
    variant.save(update_fields=["stock"])
    before = inventory_state(variant)

    view = cart_services.read_cart(cart)

    assert view.lines[0].effective_quantity == 2
    assert inventory_state(variant) == before
    assert opening_ledger(variant) == 1
