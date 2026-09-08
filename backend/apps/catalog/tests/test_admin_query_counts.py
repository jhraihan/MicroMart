"""
N+1 guard for the admin catalogue lists (PRD 9.1).

Same bar as apps/cart/tests/test_query_counts.py and this app's own
test_query_counts.py: not "few queries" but a *constant* number. A page of one
product and a page of twelve must cost the same, or the admin table gets slower
exactly as the catalogue it manages gets bigger -- and the admin list is the
screen a shop owner leaves open all day.

The admin rows are the easy ones to lose this on, because each renders a price
range, a stock total and a low-stock flag derived from the product's variants,
plus its primary image. All four come from prefetches and annotations settled
in services/administration.admin_products; the moment one of them walks a
relation in the serializer instead, this file fails.
"""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.tests import factories

pytestmark = pytest.mark.django_db


def fill(category, count, *, variants_each=2, images_each=2, start=0):
    for index in range(start, start + count):
        product = factories.make_product(
            category,
            name="Product {0:02d}".format(index),
            slug="product-{0:02d}".format(index),
            variants=[],
        )
        for option in range(variants_each):
            factories.make_variant(
                product,
                sku="SKU-{0:02d}-{1}".format(index, option),
                price="{0}.00".format(1000 + option),
                stock=5,
            )
        for shot in range(images_each):
            factories.make_image(product, sort_order=shot, is_primary=shot == 0)


def count_queries(client, url, params=None):
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url, params or {})
        assert response.status_code == 200
        # Touch the rendered body, so anything lazy is forced inside the window.
        assert response.json() is not None
    return len(captured.captured_queries)


def test_the_admin_product_list_costs_the_same_for_one_product_as_for_twelve(
    admin_api, admin_products_url, category
):
    fill(category, 1)
    small = count_queries(admin_api, admin_products_url)

    fill(category, 11, start=1)
    large = count_queries(admin_api, admin_products_url)

    assert large == small, (
        "the admin list grew by {0} queries between 1 and 12 products".format(
            large - small
        )
    )


def test_the_admin_product_list_does_not_pay_per_variant_either(
    admin_api, admin_products_url, category
):
    """
    Price range, stock total and the low-stock flag are all per-variant. A
    serializer that reached for `product.variants.all()` without the prefetch
    would cost one query per row here and look fine on a one-row fixture.
    """
    fill(category, 4, variants_each=1)
    thin = count_queries(admin_api, admin_products_url)

    factories.make_category("Second", "second")
    fill(factories.make_category("Third", "third"), 4, variants_each=6, start=100)
    fat = count_queries(admin_api, admin_products_url)

    assert fat == thin


def test_the_inventory_list_costs_the_same_for_one_variant_as_for_twenty(
    admin_api, admin_inventory_url, category
):
    fill(category, 1, variants_each=1, images_each=0)
    small = count_queries(admin_api, admin_inventory_url)

    fill(category, 10, variants_each=2, images_each=0, start=1)
    large = count_queries(admin_api, admin_inventory_url)

    assert large == small, (
        "the inventory list grew by {0} queries between 1 and 21 variants".format(
            large - small
        )
    )
