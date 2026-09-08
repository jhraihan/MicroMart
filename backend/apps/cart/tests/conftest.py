"""
Shared fixtures for the cart suite.

Written in the style of apps/catalog/tests/conftest.py: every test builds the
rows it asserts on, and price and stock -- the two values most of these tests
turn on -- are stated in the test that depends on them rather than inherited
from a fixture library.

`inventory_state` is the fixture that matters most. Adding to a cart must never
move stock or write to the append-only ledger (PRD FR-INV-2), and the cheapest
way to prove that is to snapshot both before the call under test and assert the
pair is byte-identical afterwards.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.cart.services import cart as cart_services
from apps.catalog.models import InventoryLog, ProductVariant
from apps.catalog.tests.factories import make_category, make_product


# ---------------------------------------------------------------------------
# Clients and people
# ---------------------------------------------------------------------------
@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="shopper@example.com", password="Str0ngPass!2026"
    )


@pytest.fixture
def other_customer(db):
    """A second shopper, so cross-account leaks have somewhere to leak from."""
    return User.objects.create_user(
        email="someone-else@example.com", password="Str0ngPass!2026"
    )


@pytest.fixture
def cart(customer):
    return cart_services.get_cart(customer)


@pytest.fixture
def other_cart(other_customer):
    return cart_services.get_cart(other_customer)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@pytest.fixture
def category(db):
    return make_category("Laptops", "laptops")


@pytest.fixture
def variant(category):
    """A purchasable variant: 1000.00 BDT a unit, 10 on hand."""
    product = make_product(
        category,
        name="Asus Vivobook Go 15",
        slug="asus-vivobook-go-15",
        sku="VIVO-8-512",
        price="1000.00",
        stock=10,
    )
    return product.variants.get()


@pytest.fixture
def other_variant(category):
    """A second purchasable variant on its own product: 250.50 BDT, 3 on hand."""
    product = make_product(
        category,
        name="Logitech MX Master 3S",
        slug="logitech-mx-master-3s",
        sku="MX-MASTER-3S",
        price="250.50",
        stock=3,
    )
    return product.variants.get()


@pytest.fixture
def build_variant(category):
    """
    Build a purchasable variant with the price and stock a test needs.

    Kept as a factory rather than more fixtures because the tests that use it
    are testing what happens at a particular stock level, so the number has to
    be visible in the test body.
    """

    def build(*, price="1000.00", stock=10, **product_kwargs):
        product = make_product(category, price=price, stock=stock, **product_kwargs)
        return product.variants.get()

    return build


# ---------------------------------------------------------------------------
# The invariant under everything: a cart holds nothing back
# ---------------------------------------------------------------------------
@pytest.fixture
def inventory_state():
    """
    Stock on hand for the named variants, plus their ledger rows.

    Re-read from the database rather than from the passed instances, so a
    service that wrote stock behind the test's back is still caught.

    The ledger count is scoped to these variants deliberately. "No row was
    written for this variant" is the actual invariant -- a global count would
    also be asserting that nothing else in the process wrote inventory
    anywhere, which is a different claim and a flaky one on a shared test
    database.
    """

    def snapshot(*variants):
        ids = [variant.pk for variant in variants]
        return {
            "stock": {
                variant.pk: ProductVariant.objects.get(pk=variant.pk).stock
                for variant in variants
            },
            "ledger_rows": InventoryLog.objects.filter(variant_id__in=ids).count(),
        }

    return snapshot


# ---------------------------------------------------------------------------
# Routes (apps/cart/urls.py)
# ---------------------------------------------------------------------------
@pytest.fixture
def cart_url():
    return reverse("cart:detail")


@pytest.fixture
def items_url():
    return reverse("cart:item-list")


@pytest.fixture
def item_url():
    return lambda pk: reverse("cart:item-detail", kwargs={"pk": pk})


@pytest.fixture
def merge_url():
    return reverse("cart:merge")


@pytest.fixture
def quote_url():
    """
    POST /checkout/quote/ -- not a cart route, but the cart page renders
    every line from the cart payload and every figure from this one, so the
    two payloads have to agree about what a line is called.
    """
    return reverse("orders:checkout-quote")
