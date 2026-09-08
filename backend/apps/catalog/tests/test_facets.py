"""
Facet counts (FR-SRC-2).

Two rules pull against each other and both have to hold:

1. Counts describe the current result set, not the whole catalogue.
2. A dimension is blind to its own filter, so picking Asus still reports how
   many Lenovo products the *other* filters allow. Without the carve-out every
   unselected value reads zero and the filter can never be widened.
"""
import pytest

from .factories import make_brand, make_category, make_product, result_slugs

pytestmark = pytest.mark.django_db


@pytest.fixture
def faceted_catalogue():
    laptops = make_category("Laptops", "laptops")
    gaming = make_category("Gaming Laptops", "gaming-laptops", parent=laptops)
    ultrabooks = make_category("Ultrabooks", "ultrabooks", parent=laptops)
    monitors = make_category("Monitors", "monitors")

    asus = make_brand("Asus", "asus")
    lenovo = make_brand("Lenovo", "lenovo")
    hp = make_brand("HP", "hp")

    make_product(
        gaming,
        brand=asus,
        name="Asus Gaming",
        slug="asus-gaming",
        price="100000.00",
        stock=5,
        rating_avg="4.50",
        rating_count=12,
    )
    make_product(
        ultrabooks,
        brand=asus,
        name="Asus Ultrabook",
        slug="asus-ultrabook",
        price="80000.00",
        stock=0,
        rating_avg="3.00",
        rating_count=4,
    )
    make_product(
        gaming,
        brand=lenovo,
        name="Lenovo Legion",
        slug="lenovo-legion",
        price="120000.00",
        stock=3,
        rating_avg="0.00",
    )
    make_product(
        monitors,
        brand=hp,
        name="HP Monitor",
        slug="hp-monitor",
        price="25000.00",
        stock=7,
        rating_avg="5.00",
        rating_count=2,
    )
    return {"laptops": laptops, "gaming": gaming, "monitors": monitors}


def test_facets_describe_the_filtered_set_not_the_whole_catalogue(
    api, products_url, faceted_catalogue
):
    payload = api.get(products_url, {"category": "gaming-laptops"}).json()
    facets = payload["facets"]

    assert set(result_slugs(payload)) == {"asus-gaming", "lenovo-legion"}
    assert facets["brands"] == [
        {"slug": "asus", "name": "Asus", "count": 1},
        {"slug": "lenovo", "name": "Lenovo", "count": 1},
    ]
    assert facets["price"] == {"min": "100000.00", "max": "120000.00"}
    assert facets["in_stock"] == {"true": 2, "false": 0}


def test_brand_facet_is_blind_to_the_brand_filter_but_honours_the_others(
    api, products_url, faceted_catalogue
):
    payload = api.get(
        products_url, {"category": "gaming-laptops", "brand": "asus"}
    ).json()

    assert result_slugs(payload) == ["asus-gaming"]
    # Lenovo is still offered, so the customer can widen the brand filter;
    # HP is not, because the category filter still applies.
    assert payload["facets"]["brands"] == [
        {"slug": "asus", "name": "Asus", "count": 1},
        {"slug": "lenovo", "name": "Lenovo", "count": 1},
    ]


def test_category_facet_is_blind_to_the_category_filter_but_honours_the_others(
    api, products_url, faceted_catalogue
):
    payload = api.get(
        products_url, {"category": "gaming-laptops", "brand": "asus"}
    ).json()

    # Category dropped, brand kept: both Asus products, in the categories they
    # actually sit in.
    assert payload["facets"]["categories"] == [
        {"slug": "gaming-laptops", "name": "Gaming Laptops", "count": 1},
        {"slug": "ultrabooks", "name": "Ultrabooks", "count": 1},
    ]


def test_price_facet_spans_the_band_the_slider_may_cover(
    api, products_url, faceted_catalogue
):
    payload = api.get(products_url, {"min_price": "110000"}).json()

    assert result_slugs(payload) == ["lenovo-legion"]
    # Blind to its own filter, so the slider can be dragged back down.
    assert payload["facets"]["price"] == {"min": "25000.00", "max": "120000.00"}


def test_price_facet_still_respects_the_other_filters(
    api, products_url, faceted_catalogue
):
    payload = api.get(products_url, {"brand": "asus", "min_price": "90000"}).json()

    assert payload["facets"]["price"] == {"min": "80000.00", "max": "100000.00"}


def test_price_facet_ignores_a_product_whose_variants_are_all_retired(
    api, products_url, faceted_catalogue
):
    """
    The price facet is built on storefront_products(), not
    listable_products() -- it drops the EXISTS(active variant) the other
    facets need, because joining to an active variant re-establishes it and
    the doubled semijoin costs a duplicate-weedout temporary table
    (see catalogue._price_facet).

    This is the case where the two product sets genuinely differ: a product
    that is active but has nothing sellable left. It is admitted to the id
    set now and must still contribute nothing, or the slider would stretch
    to a price no one can pay.
    """
    laptops = make_category("Retired", "retired-shelf")
    make_product(
        laptops,
        name="Discontinued",
        slug="discontinued",
        variants=[
            {"sku": "DEAD-CHEAP", "price": "1.00", "stock": 0, "is_active": False},
            {"sku": "DEAD-DEAR", "price": "999999.00", "stock": 0, "is_active": False},
        ],
    )

    payload = api.get(products_url).json()

    assert "discontinued" not in result_slugs(payload)
    assert payload["facets"]["price"] == {"min": "25000.00", "max": "120000.00"}


def test_stock_facet_is_blind_to_the_stock_filter(api, products_url, faceted_catalogue):
    payload = api.get(products_url, {"in_stock": "true"}).json()

    assert set(result_slugs(payload)) == {
        "asus-gaming",
        "lenovo-legion",
        "hp-monitor",
    }
    assert payload["facets"]["in_stock"] == {"true": 3, "false": 1}


def test_rating_facet_reports_every_threshold_as_stars_and_up(
    api, products_url, faceted_catalogue
):
    payload = api.get(products_url).json()

    assert payload["facets"]["ratings"] == [
        {"value": 5, "count": 1},
        {"value": 4, "count": 2},
        {"value": 3, "count": 3},
        {"value": 2, "count": 3},
        {"value": 1, "count": 3},
    ]


def test_rating_facet_is_blind_to_the_rating_filter(
    api, products_url, faceted_catalogue
):
    payload = api.get(products_url, {"min_rating": "4"}).json()

    assert set(result_slugs(payload)) == {"asus-gaming", "hp-monitor"}
    assert payload["facets"]["ratings"] == [
        {"value": 5, "count": 1},
        {"value": 4, "count": 2},
        {"value": 3, "count": 3},
        {"value": 2, "count": 3},
        {"value": 1, "count": 3},
    ]


def test_brand_facet_skips_products_with_no_brand(
    api, products_url, faceted_catalogue
):
    make_product(
        faceted_catalogue["monitors"],
        brand=None,
        name="Unbranded Cable",
        slug="unbranded-cable",
        price="450.00",
    )

    payload = api.get(products_url).json()

    assert "unbranded-cable" in result_slugs(payload)
    assert [row["slug"] for row in payload["facets"]["brands"]] == [
        "asus",
        "hp",
        "lenovo",
    ]


def test_facets_count_the_whole_result_set_not_just_the_current_page(
    api, products_url
):
    category = make_category("Cables", "cables")
    brand = make_brand("Generic", "generic")
    for index in range(30):
        make_product(
            category,
            brand=brand,
            name="Cable {0}".format(index),
            slug="cable-{0}".format(index),
            price="500.00",
        )

    payload = api.get(products_url).json()

    assert len(payload["results"]) == 24  # one page
    assert payload["facets"]["brands"] == [
        {"slug": "generic", "name": "Generic", "count": 30}
    ]


def test_facets_are_present_on_every_page(api, products_url, faceted_catalogue):
    payload = api.get(products_url, {"page_size": "2", "page": "2"}).json()

    assert set(payload["facets"]) == {
        "brands",
        "categories",
        "price",
        "in_stock",
        "ratings",
    }


def test_a_multi_variant_product_is_counted_once_per_facet(api, products_url):
    # If any filter joined the variant table instead of using EXISTS, this
    # product would be counted three times and every facet would lie.
    category = make_category("Laptops", "laptops")
    brand = make_brand("Asus", "asus")
    make_product(
        category,
        brand=brand,
        name="Three Variants",
        slug="three-variants",
        variants=[
            {"sku": "TV-A", "price": "1000.00", "stock": 1},
            {"sku": "TV-B", "price": "2000.00", "stock": 2},
            {"sku": "TV-C", "price": "3000.00", "stock": 3},
        ],
    )

    payload = api.get(
        products_url, {"min_price": "500", "max_price": "5000", "in_stock": "true"}
    ).json()

    assert payload["count"] == 1
    assert len(payload["results"]) == 1
    assert payload["facets"]["brands"] == [
        {"slug": "asus", "name": "Asus", "count": 1}
    ]
    assert payload["facets"]["categories"] == [
        {"slug": "laptops", "name": "Laptops", "count": 1}
    ]
    assert payload["facets"]["in_stock"] == {"true": 1, "false": 0}
    assert payload["facets"]["ratings"][4] == {"value": 1, "count": 0}


def test_a_multi_variant_product_is_counted_once_under_search(api, products_url):
    category = make_category("Laptops", "laptops")
    brand = make_brand("Asus", "asus")
    make_product(
        category,
        brand=brand,
        name="Asus Multi Variant",
        slug="asus-multi-variant",
        variants=[
            {"sku": "MULTI-ASUS-A", "price": "1000.00", "stock": 1},
            {"sku": "MULTI-ASUS-B", "price": "2000.00", "stock": 2},
        ],
    )

    # "Asus" hits the product name, the brand name and both SKUs at once.
    payload = api.get(products_url, {"q": "Asus"}).json()

    assert payload["count"] == 1
    assert payload["facets"]["brands"] == [
        {"slug": "asus", "name": "Asus", "count": 1}
    ]
