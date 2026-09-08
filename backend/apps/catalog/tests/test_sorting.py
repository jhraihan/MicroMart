"""
Sorting (FR-SRC-3).

Price sorts order on the *cheapest active* variant, which is the price the
card actually shows. Sorting a multi-variant product by anything else makes
the grid disagree with its own labels.
"""
import pytest

from apps.orders.models import OrderStatus

from .factories import (
    make_brand,
    make_category,
    make_product,
    place_order,
    result_slugs,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def priced_catalogue():
    category = make_category("Laptops", "laptops")
    brand = make_brand("Asus", "asus")

    # Cheapest variant 5,000 but a 200,000 variant too: a sort that used the
    # maximum would put this last in price_asc and first in price_desc.
    spread = make_product(
        category,
        brand=brand,
        name="Spread",
        slug="spread",
        variants=[
            {"sku": "SPREAD-LOW", "price": "5000.00", "stock": 2},
            {"sku": "SPREAD-HIGH", "price": "200000.00", "stock": 2},
        ],
    )
    mid = make_product(
        category, brand=brand, name="Mid", slug="mid", sku="MID-1", price="10000.00"
    )
    # The 1,000 variant is inactive, so it must not drag this product to the
    # front of price_asc.
    trap = make_product(
        category,
        brand=brand,
        name="Trap",
        slug="trap",
        variants=[
            {"sku": "TRAP-ACTIVE", "price": "15000.00", "stock": 2},
            {"sku": "TRAP-RETIRED", "price": "1000.00", "stock": 2, "is_active": False},
        ],
    )
    return {"spread": spread, "mid": mid, "trap": trap}


def test_price_ascending_orders_on_the_cheapest_active_variant(
    api, products_url, priced_catalogue
):
    payload = api.get(products_url, {"sort": "price_asc"}).json()

    assert result_slugs(payload) == ["spread", "mid", "trap"]


def test_price_descending_is_the_exact_reverse(api, products_url, priced_catalogue):
    payload = api.get(products_url, {"sort": "price_desc"}).json()

    # If this ordered on the highest variant, "spread" (200,000) would lead.
    assert result_slugs(payload) == ["trap", "mid", "spread"]


def test_price_sorts_use_the_same_figure_the_card_displays(
    api, products_url, priced_catalogue
):
    rows = api.get(products_url, {"sort": "price_asc"}).json()["results"]

    prices = [row["price_min"] for row in rows]
    assert prices == ["5000.00", "10000.00", "15000.00"]


def test_default_sort_without_a_keyword_is_newest_first(
    api, products_url, priced_catalogue
):
    payload = api.get(products_url).json()

    assert result_slugs(payload) == ["trap", "mid", "spread"]
    assert result_slugs(payload) == result_slugs(
        api.get(products_url, {"sort": "newest"}).json()
    )


def test_rating_sort_orders_on_the_denormalised_average(api, products_url):
    category = make_category("Keyboards", "keyboards")
    make_product(category, name="Loved", slug="loved-kb", rating_avg="4.80", rating_count=40)
    make_product(category, name="Liked", slug="liked-kb", rating_avg="4.10", rating_count=6)
    make_product(category, name="Unrated", slug="unrated-kb", rating_avg="0.00")

    payload = api.get(products_url, {"sort": "rating"}).json()

    assert result_slugs(payload) == ["loved-kb", "liked-kb", "unrated-kb"]


def test_best_selling_counts_units_from_orders_that_were_not_cancelled(
    api, products_url
):
    category = make_category("Mice", "mice")
    hot = make_product(category, name="Hot", slug="hot-mouse", sku="MOUSE-HOT", price="3000.00")
    mild = make_product(category, name="Mild", slug="mild-mouse", sku="MOUSE-MILD", price="3000.00")
    ghost = make_product(
        category, name="Ghost", slug="ghost-mouse", sku="MOUSE-GHOST", price="3000.00"
    )

    place_order([(hot.variants.first(), 5)], status=OrderStatus.DELIVERED)
    place_order([(mild.variants.first(), 2)], status=OrderStatus.CONFIRMED)
    # A cancelled order sold nothing, however large it was.
    place_order([(ghost.variants.first(), 99)], status=OrderStatus.CANCELLED)
    place_order([(ghost.variants.first(), 99)], status=OrderStatus.REFUNDED)

    payload = api.get(products_url, {"sort": "best_selling"}).json()

    assert result_slugs(payload) == ["hot-mouse", "mild-mouse", "ghost-mouse"]


def test_sort_is_applied_before_pagination(api, products_url):
    category = make_category("Cables", "cables")
    for index in range(30):
        make_product(
            category,
            name="Cable {0}".format(index),
            slug="cable-{0}".format(index),
            sku="CABLE-{0}".format(index),
            price="{0}.00".format(100 + index),
        )

    first_page = api.get(products_url, {"sort": "price_asc"}).json()
    second_page = api.get(products_url, {"sort": "price_asc", "page": "2"}).json()

    assert result_slugs(first_page)[0] == "cable-0"
    assert result_slugs(second_page) == ["cable-24", "cable-25", "cable-26", "cable-27", "cable-28", "cable-29"]
