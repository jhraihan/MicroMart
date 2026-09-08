"""
Search suggestions, comparison and the offers filter.

The three surfaces added for discovery. Each has one property that matters
more than the rest, and that is what these pin:

  * **suggest** must not be the ranked full-text search -- it is a prefix
    lookup, and it must answer for a two-character fragment that full-text
    cannot index;
  * **compare** must preserve the order asked for and report a missing spec
    as absent rather than blank;
  * **has_discount** must agree with the badge, because a product filtered in
    here and rendered without a discount badge is a visible contradiction.
"""
import pytest
from django.urls import reverse

from apps.catalog.tests.factories import (
    make_category,
    make_product,
    make_spec,
    make_variant,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def suggest_url():
    return reverse("catalog:search-suggest")


@pytest.fixture
def compare_url():
    return reverse("catalog:product-compare")


@pytest.fixture
def category():
    return make_category(name="Components", slug="components")


@pytest.fixture
def product(category):
    """A product builder bound to one category, so tests stay one-liners."""

    def build(**kwargs):
        return make_product(category, **kwargs)

    return build


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------
def test_a_two_character_fragment_still_suggests(api, suggest_url, product):
    """
    The whole point of type-ahead. InnoDB will not index a token this short,
    so a suggestion endpoint built on MATCH would return nothing here.
    """
    product(name="Ryzen 5 5600X", slug="ryzen-5-5600x")

    rows = api.get(suggest_url, {"q": "ry"}).json()["products"]

    assert [row["slug"] for row in rows] == ["ryzen-5-5600x"]


def test_below_two_characters_nothing_is_suggested(api, suggest_url, product):
    """One character matches most of the catalogue, which is noise."""
    product(name="Ryzen 5 5600X", slug="ryzen-5-5600x")
    payload = api.get(suggest_url, {"q": "r"}).json()
    assert payload["products"] == []


def test_a_name_that_starts_with_the_fragment_outranks_one_that_merely_contains_it(
    api, suggest_url, product
):
    product(name="Corsair Vengeance", slug="corsair-vengeance")
    product(name="Vengeance LPX Memory", slug="vengeance-lpx-memory")

    rows = api.get(suggest_url, {"q": "vengeance"}).json()["products"]

    assert rows[0]["slug"] == "vengeance-lpx-memory"


def test_a_sku_is_searchable(api, suggest_url, product):
    board = product(name="Some Board", slug="some-board", variants=[])
    make_variant(board, sku="TT-BOARD-XYZ", price="100.00", stock=1)

    rows = api.get(suggest_url, {"q": "BOARD-XYZ"}).json()["products"]

    assert [row["slug"] for row in rows] == ["some-board"]


def test_a_model_number_is_searchable(api, suggest_url, product):
    product(name="A Laptop", slug="a-laptop", model_number="FX507ZC4")

    rows = api.get(suggest_url, {"q": "FX507"}).json()["products"]

    assert [row["slug"] for row in rows] == ["a-laptop"]


def test_suggestions_carry_categories_brands_and_popular_terms(api, suggest_url, product):
    product(name="Ryzen 5", slug="ryzen-5")
    payload = api.get(suggest_url, {"q": "ryzen"}).json()

    assert set(payload) == {"query", "products", "categories", "brands", "popular"}
    # Popular terms are offered even on a hit, so an empty result set below
    # two characters still has somewhere to go.
    assert payload["popular"]


def test_an_inactive_product_is_never_suggested(api, suggest_url, product):
    product(name="Retired Ryzen", slug="retired-ryzen", is_active=False)
    assert api.get(suggest_url, {"q": "ryzen"}).json()["products"] == []


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def test_compare_returns_products_in_the_order_asked_for(api, compare_url, product):
    """
    The table's columns are the order the shopper added them in. Re-sorting
    server-side would shuffle the table under them on every reload.
    """
    for slug in ("alpha", "beta", "gamma"):
        product(name=slug.title(), slug=slug)

    payload = api.get(compare_url, {"slugs": "gamma,alpha,beta"}).json()

    assert [p["slug"] for p in payload["products"]] == ["gamma", "alpha", "beta"]


def test_compare_caps_the_set(api, compare_url, product):
    slugs = []
    for index in range(6):
        product(name=f"P{index}", slug=f"p{index}")
        slugs.append(f"p{index}")

    payload = api.get(compare_url, {"slugs": ",".join(slugs)}).json()

    assert payload["count"] == payload["max"] == 4


def test_a_spec_one_product_lacks_is_null_not_blank(api, compare_url, product):
    """
    In a comparison, "this product does not list a refresh rate" is
    information. Collapsing it into an empty string loses that.
    """
    first = product(name="First", slug="first")
    second = product(name="Second", slug="second")
    make_spec(first, "Refresh Rate", "144Hz", group="Display")
    make_spec(second, "Panel Type", "IPS", group="Display")

    payload = api.get(compare_url, {"slugs": "first,second"}).json()
    rows = {
        row["key"]: row
        for group in payload["spec_matrix"]
        for row in group["rows"]
    }

    assert rows["Refresh Rate"]["values"] == ["144Hz", None]
    assert rows["Panel Type"]["values"] == [None, "IPS"]


def test_a_row_where_every_product_agrees_is_marked_as_not_differing(
    api, compare_url, product
):
    first = product(name="First", slug="first")
    second = product(name="Second", slug="second")
    make_spec(first, "Socket", "AM4", group="General")
    make_spec(second, "Socket", "AM4", group="General")
    make_spec(first, "Cores", "6", group="General")
    make_spec(second, "Cores", "8", group="General")

    payload = api.get(compare_url, {"slugs": "first,second"}).json()
    rows = {
        row["key"]: row["differs"]
        for group in payload["spec_matrix"]
        for row in group["rows"]
    }

    assert rows["Socket"] is False
    assert rows["Cores"] is True


def test_comparing_nothing_is_an_empty_answer_not_an_error(api, compare_url):
    response = api.get(compare_url)
    assert response.status_code == 200
    assert response.json()["products"] == []


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------
def test_has_discount_keeps_only_genuinely_marked_down_products(api, products_url, product):
    product(
        name="On Offer", slug="on-offer",
        price="900.00", compare_at_price="1200.00", stock=3,
    )
    product(name="Full Price", slug="full-price", price="900.00", stock=3)

    payload = api.get(products_url, {"has_discount": "true"}).json()

    assert [row["slug"] for row in payload["results"]] == ["on-offer"]


def test_a_compare_at_price_below_the_price_is_not_a_discount(api, products_url, product):
    """
    Mirrors FR-CAT-8 and the badge: a compare-at that does not exceed the
    price is not a markdown, so the filter must not admit it either.
    """
    product(
        name="Not Really", slug="not-really",
        price="900.00", compare_at_price="800.00", stock=3,
    )

    payload = api.get(products_url, {"has_discount": "true"}).json()

    assert payload["results"] == []


def test_a_discount_on_an_inactive_variant_does_not_count(api, products_url, product):
    """The filter asks whether a *sellable* variant is marked down."""
    hidden = product(name="Hidden Deal", slug="hidden-deal", variants=[])
    make_variant(hidden, sku="HD-LIVE", price="900.00", stock=3)
    make_variant(
        hidden,
        sku="HD-DEAD",
        price="500.00",
        compare_at_price="1500.00",
        stock=3,
        is_active=False,
    )

    payload = api.get(products_url, {"has_discount": "true"}).json()

    assert payload["results"] == []


def test_featured_filters_to_the_merchandising_flag(api, products_url, product):
    product(name="Picked", slug="picked", is_featured=True)
    product(name="Ordinary", slug="ordinary")

    payload = api.get(products_url, {"featured": "true"}).json()

    assert [row["slug"] for row in payload["results"]] == ["picked"]
