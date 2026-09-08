"""Pagination envelope (PRD 7.1): count / next / previous, 24 per page."""
import pytest

from .factories import make_brand, make_category, make_product, result_slugs

pytestmark = pytest.mark.django_db


@pytest.fixture
def twenty_six_products():
    category = make_category("Cables", "cables")
    brand = make_brand("Generic", "generic")
    return [
        make_product(
            category,
            brand=brand,
            name="Cable {0:02d}".format(index),
            slug="cable-{0:02d}".format(index),
            sku="CABLE-{0:02d}".format(index),
            price="{0}.00".format(500 + index),
        )
        for index in range(26)
    ]


def test_first_page_defaults_to_twenty_four_items(
    api, products_url, twenty_six_products
):
    payload = api.get(products_url).json()

    assert payload["count"] == 26
    assert len(payload["results"]) == 24
    assert payload["previous"] is None
    assert "page=2" in payload["next"]


def test_second_page_carries_the_remainder_and_a_previous_link(
    api, products_url, twenty_six_products
):
    payload = api.get(products_url, {"page": "2"}).json()

    assert payload["count"] == 26
    assert len(payload["results"]) == 2
    assert payload["next"] is None
    assert payload["previous"] is not None


def test_pages_do_not_overlap(api, products_url, twenty_six_products):
    first = result_slugs(api.get(products_url).json())
    second = result_slugs(api.get(products_url, {"page": "2"}).json())

    assert set(first) & set(second) == set()
    assert len(set(first) | set(second)) == 26


def test_page_size_can_be_narrowed(api, products_url, twenty_six_products):
    payload = api.get(products_url, {"page_size": "5"}).json()

    assert len(payload["results"]) == 5
    assert payload["count"] == 26


def test_page_size_is_capped_at_one_hundred(api, products_url, twenty_six_products):
    category = make_category("More Cables", "more-cables")
    for index in range(80):
        make_product(
            category,
            name="Extra {0}".format(index),
            slug="extra-{0}".format(index),
            sku="EXTRA-{0}".format(index),
            price="99.00",
        )

    payload = api.get(products_url, {"page_size": "1000"}).json()

    assert payload["count"] == 106
    assert len(payload["results"]) == 100


def test_a_page_beyond_the_end_returns_the_404_envelope(
    api, products_url, twenty_six_products
):
    response = api.get(products_url, {"page": "99"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_the_envelope_carries_facets_alongside_the_page(
    api, products_url, twenty_six_products
):
    payload = api.get(products_url).json()

    assert set(payload) == {"count", "next", "previous", "results", "facets"}
