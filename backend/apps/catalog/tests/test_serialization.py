"""
Wire format: money as decimal strings (PRD 6.5) and the FR-CAT-8 discount rule.

`response.json()` is deliberate -- these assertions run against parsed JSON, so
a number on the wire arrives here as int/float and fails the isinstance check.
Reading `response.data` instead would let a float through unnoticed.
"""
import json

import pytest

from .factories import (
    make_brand,
    make_category,
    make_image,
    make_product,
    make_spec,
    make_variant,
)

pytestmark = pytest.mark.django_db

MONEY_FIELDS = ("price_min", "price_max", "compare_at_price")


@pytest.fixture
def discounted_product():
    category = make_category("Gaming Laptops", "gaming-laptops")
    brand = make_brand("Asus", "asus")
    product = make_product(
        category,
        brand=brand,
        name="Asus TUF Gaming F15",
        slug="asus-tuf-gaming-f15",
        description="A gaming laptop.",
        warranty_months=24,
        rating_avg="4.25",
        rating_count=8,
        variants=[
            {
                "sku": "TUF-16-512",
                "option_label": "16GB / 512GB",
                "price": "142000.00",
                "compare_at_price": "155000.00",
                "stock": 12,
                "weight_grams": 2200,
            },
            {
                "sku": "TUF-32-1024",
                "option_label": "32GB / 1TB",
                "price": "178000.00",
                "compare_at_price": "190000.00",
                "stock": 10,
                "weight_grams": 2200,
            },
        ],
    )
    make_spec(product, "Processor", "Intel Core i7-12700H")
    return product


# ---------------------------------------------------------------------------
# Money is a string, everywhere
# ---------------------------------------------------------------------------
def test_list_money_fields_are_decimal_strings(api, products_url, discounted_product):
    row = api.get(products_url).json()["results"][0]

    for field in MONEY_FIELDS:
        assert isinstance(row[field], str), field
        assert not isinstance(row[field], float)
    assert row["price_min"] == "142000.00"
    assert row["price_max"] == "178000.00"
    assert isinstance(row["rating_avg"], str)
    assert row["rating_avg"] == "4.25"


def test_counts_and_flags_keep_their_native_json_types(
    api, products_url, discounted_product
):
    row = api.get(products_url).json()["results"][0]

    assert isinstance(row["total_stock"], int)
    assert isinstance(row["variant_count"], int)
    assert isinstance(row["rating_count"], int)
    assert isinstance(row["discount_percent"], int)
    assert row["in_stock"] is True
    assert row["total_stock"] == 22
    assert row["variant_count"] == 2


def test_detail_variant_money_is_a_string_and_stock_is_an_integer(
    api, detail_url, discounted_product
):
    variant = api.get(detail_url(discounted_product.slug)).json()["variants"][0]

    assert isinstance(variant["price"], str)
    assert variant["price"] == "142000.00"
    assert isinstance(variant["compare_at_price"], str)
    assert isinstance(variant["stock"], int)
    assert variant["stock"] == 12


def test_facet_price_bounds_are_decimal_strings(api, products_url, discounted_product):
    price = api.get(products_url).json()["facets"]["price"]

    assert price == {"min": "142000.00", "max": "178000.00"}


def test_no_money_value_is_emitted_as_a_json_number(
    api, products_url, detail_url, discounted_product
):
    # Belt and braces: a float would render unquoted in the raw body.
    for response in (
        api.get(products_url),
        api.get(detail_url(discounted_product.slug)),
    ):
        _assert_money_is_stringy(json.loads(response.content.decode()))


def _assert_money_is_stringy(node, key=None):
    money_keys = {
        "price",
        "price_min",
        "price_max",
        "compare_at_price",
        "rating_avg",
        "min",
        "max",
    }
    if isinstance(node, dict):
        for child_key, value in node.items():
            _assert_money_is_stringy(value, child_key)
    elif isinstance(node, list):
        for value in node:
            _assert_money_is_stringy(value, key)
    elif key in money_keys and node is not None:
        assert isinstance(node, str), "{0} = {1!r} is not a decimal string".format(
            key, node
        )


# ---------------------------------------------------------------------------
# FR-CAT-8 -- the discount badge
# ---------------------------------------------------------------------------
def test_discount_comes_from_the_cheapest_active_variant(
    api, products_url, discounted_product
):
    row = api.get(products_url).json()["results"][0]

    # round((155000 - 142000) / 155000 * 100) == 8
    assert row["compare_at_price"] == "155000.00"
    assert row["discount_percent"] == 8


def test_list_and_variant_discounts_cannot_disagree(
    api, products_url, detail_url, discounted_product
):
    row = api.get(products_url).json()["results"][0]
    cheapest = api.get(detail_url(discounted_product.slug)).json()["variants"][0]

    assert cheapest["price"] == row["price_min"]
    assert cheapest["discount_percent"] == row["discount_percent"]
    assert cheapest["compare_at_price"] == row["compare_at_price"]


@pytest.mark.parametrize(
    "compare_at",
    [None, "142000.00", "100000.00"],
    ids=["no-compare-at", "equal-to-price", "below-price"],
)
def test_discount_is_zero_and_compare_at_is_null_unless_it_exceeds_the_price(
    api, products_url, detail_url, compare_at
):
    category = make_category("Laptops", "laptops")
    product = make_product(
        category,
        name="Flat Priced",
        slug="flat-priced",
        sku="FLAT-1",
        price="142000.00",
        compare_at_price=compare_at,
    )

    row = api.get(products_url).json()["results"][0]
    variant = api.get(detail_url(product.slug)).json()["variants"][0]

    # A struck-through original that is not actually higher is a lie on the
    # card, so both levels null it out.
    assert row["discount_percent"] == 0
    assert row["compare_at_price"] is None
    assert variant["discount_percent"] == 0
    assert variant["compare_at_price"] is None


def test_out_of_stock_product_reports_zero_stock_not_a_missing_price(
    api, products_url
):
    category = make_category("Laptops", "laptops")
    make_product(category, name="Sold Out", slug="sold-out", sku="OUT-1", price="500.00", stock=0)

    row = api.get(products_url).json()["results"][0]

    assert row["in_stock"] is False
    assert row["total_stock"] == 0
    assert row["price_min"] == "500.00"


# ---------------------------------------------------------------------------
# Detail shape
# ---------------------------------------------------------------------------
def test_detail_adds_description_specs_images_and_variants_to_the_card_shape(
    api, detail_url, discounted_product
):
    payload = api.get(detail_url(discounted_product.slug)).json()

    assert set(payload) == {
        "id",
        "name",
        "slug",
        "brand",
        "category",
        "primary_image",
        "price_min",
        "price_max",
        "compare_at_price",
        "discount_percent",
        "in_stock",
        "total_stock",
        "rating_avg",
        "rating_count",
        "variant_count",
        "description",
        "model_number",
        "highlights",
        "warranty_months",
        "images",
        "specs",
        "spec_groups",
        "variants",
        "component",
    }
    assert payload["warranty_months"] == 24
    assert payload["specs"] == [
        {"key": "Processor", "value": "Intel Core i7-12700H", "group": ""}
    ]
    # spec_groups is the same rows banded by heading. An ungrouped spec lands
    # under a single default band rather than being dropped, so a product
    # written before groups existed still renders a table.
    assert payload["spec_groups"] == [
        {
            "group": "Specifications",
            "rows": [{"key": "Processor", "value": "Intel Core i7-12700H"}],
        }
    ]
    # Null for anything that is not a PC-builder part, which is most of the
    # catalogue.
    assert payload["component"] is None
    assert payload["brand"] == {
        "id": discounted_product.brand_id,
        "name": "Asus",
        "slug": "asus",
    }


def test_detail_variants_are_ordered_cheapest_first_and_omit_inactive_rows(
    api, detail_url, discounted_product
):
    make_variant(
        discounted_product,
        sku="TUF-RETIRED",
        price="99000.00",
        stock=1,
        is_active=False,
    )

    variants = api.get(detail_url(discounted_product.slug)).json()["variants"]

    assert [variant["sku"] for variant in variants] == ["TUF-16-512", "TUF-32-1024"]


def test_low_stock_flag_follows_the_variant_threshold(
    api, detail_url, discounted_product
):
    discounted_product.variants.filter(sku="TUF-16-512").update(
        stock=3, low_stock_threshold=5
    )

    variants = api.get(detail_url(discounted_product.slug)).json()["variants"]
    cheapest = next(row for row in variants if row["sku"] == "TUF-16-512")

    assert cheapest["is_low_stock"] is True
    assert cheapest["in_stock"] is True


def test_images_serialise_as_media_relative_urls(
    api, products_url, detail_url, discounted_product
):
    make_image(discounted_product, is_primary=False, sort_order=1, alt_text="side")
    primary = make_image(
        discounted_product, is_primary=True, sort_order=0, alt_text="front"
    )

    row = api.get(products_url).json()["results"][0]
    payload = api.get(detail_url(discounted_product.slug)).json()

    assert row["primary_image"]["alt_text"] == "front"
    assert row["primary_image"]["url"].startswith("/media/")
    assert [image["id"] for image in payload["images"]][0] == primary.id
    assert payload["images"][0]["is_primary"] is True
    assert payload["images"][0]["variant_id"] is None


def test_primary_image_is_null_when_a_product_has_none(
    api, products_url, discounted_product
):
    row = api.get(products_url).json()["results"][0]

    assert row["primary_image"] is None


# ---------------------------------------------------------------------------
# Taxonomy endpoints
# ---------------------------------------------------------------------------
def test_brand_list_shape_and_inactive_brands(api, brands_url):
    make_brand("Asus", "asus")
    make_brand("Retired", "retired", is_active=False)

    payload = api.get(brands_url).json()

    assert payload == [{"id": payload[0]["id"], "name": "Asus", "slug": "asus", "logo": None}]


def test_compare_at_is_null_when_only_a_pricier_variant_is_discounted(
    api, products_url
):
    # A naive MAX(compare_at_price) would advertise a discount the cheapest
    # variant does not have, and the card shows the cheapest price.
    category = make_category("Laptops", "laptops")
    make_product(
        category,
        name="Mixed Discounts",
        slug="mixed-discounts",
        variants=[
            {"sku": "MIX-CHEAP", "price": "100000.00", "stock": 3},
            {
                "sku": "MIX-DEAR",
                "price": "200000.00",
                "compare_at_price": "300000.00",
                "stock": 3,
            },
        ],
    )

    row = api.get(products_url).json()["results"][0]

    assert row["price_min"] == "100000.00"
    assert row["compare_at_price"] is None
    assert row["discount_percent"] == 0


def test_aggregates_ignore_inactive_variants(api, products_url, detail_url):
    category = make_category("Laptops", "laptops")
    product = make_product(
        category,
        name="Partly Retired",
        slug="partly-retired",
        variants=[
            {"sku": "PR-A", "price": "1000.00", "stock": 4},
            {"sku": "PR-B", "price": "2000.00", "stock": 6},
            {"sku": "PR-C", "price": "500.00", "stock": 99, "is_active": False},
        ],
    )

    row = api.get(products_url).json()["results"][0]

    assert row["variant_count"] == 2
    assert row["total_stock"] == 10
    assert row["price_min"] == "1000.00"
    assert len(api.get(detail_url(product.slug)).json()["variants"]) == 2


def test_a_product_without_a_brand_serialises_brand_as_null(api, products_url):
    category = make_category("Cables", "cables")
    make_product(category, brand=None, name="Unbranded", slug="unbranded", sku="UNB-1")

    row = api.get(products_url).json()["results"][0]

    assert row["brand"] is None
    assert row["category"]["slug"] == "cables"
