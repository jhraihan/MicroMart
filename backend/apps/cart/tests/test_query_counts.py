"""
N+1 guard for the cart read path.

The bar, as in apps/catalog/tests/test_query_counts.py, is not "few queries"
but a *constant* number: reading a cart of one line and a cart of six must
cost the same, or the cost grows with the basket the shopper is most likely
to be staring at.

This file exists because that guarantee was silently lost once. Availability
moved into inventory.is_sellable(), which walks
variant -> product -> category -> parent for every line to decide whether a
deactivated category has withdrawn the item. Nothing preloaded that chain, so
a six-line cart issued a fresh pair of category queries per line. Measured
before the fix: five lines cost ten queries, seven of them category lookups.
"""
import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.cart.services import cart as cart_services
from apps.catalog.tests.factories import make_category, make_product

pytestmark = pytest.mark.django_db

# Measured, not guessed: the items page, plus its two prefetches.
READ_CART_QUERY_BUDGET = 3


def fill(cart, count, *, category, start=0):
    """
    `count` distinct single-variant products, one line each.

    `start` offsets the slugs so a test can top the same cart up twice without
    colliding on catalog_product.slug.
    """
    for index in range(start, start + count):
        product = make_product(
            category,
            name="Product {0:02d}".format(index),
            slug="product-{0:02d}".format(index),
            sku="SKU-{0:02d}".format(index),
            price="1000.00",
            stock=10,
        )
        cart_services.add_item(
            cart=cart, variant_id=product.variants.get().pk, quantity=1
        )


def read_cart_queries(cart):
    """Queries to read the cart *and* settle availability on every line."""
    with CaptureQueriesContext(connection) as captured:
        view = cart_services.read_cart(cart)
        for line in view.lines:
            # The serializer touches all three; each is a separate property, so
            # a missing select_related would surface here rather than in
            # read_cart() itself.
            _ = line.line.available_stock
            _ = line.line.is_available
            _ = line.line.issue
    return len(captured)


def test_reading_a_cart_costs_a_constant_number_of_queries(cart, category):
    fill(cart, 1, category=category)
    one_line = read_cart_queries(cart)

    fill(cart, 5, category=category, start=1)
    six_lines = read_cart_queries(cart)

    assert six_lines == one_line, (
        "Reading a cart got more expensive as lines were added: "
        "{0} queries for one line, {1} for six. Something on the line is "
        "lazy-loading -- check the select_related in cart.services._items.".format(
            one_line, six_lines
        )
    )
    assert six_lines <= READ_CART_QUERY_BUDGET


def test_availability_does_not_re_query_the_category_chain_per_line(cart, category):
    """
    The specific regression: is_sellable() reads category.parent.is_active, and
    a nested category is the case where a missing preload actually costs.
    """
    child = make_category("Gaming Laptops", "gaming-laptops", parent=category)
    fill(cart, 6, category=child)

    with CaptureQueriesContext(connection) as captured:
        view = cart_services.read_cart(cart)
        for line in view.lines:
            _ = line.line.is_available

    category_queries = [
        query
        for query in captured.captured_queries
        if "catalog_category" in query["sql"]
    ]
    assert len(view.lines) == 6
    assert len(category_queries) <= 1, (
        "is_sellable() walked to the parent category per line: "
        "{0} category queries for six lines.".format(len(category_queries))
    )
