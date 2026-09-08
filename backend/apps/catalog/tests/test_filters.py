"""
Filter combination (FR-SRC-4) and query-parameter validation.

The rule under test: values inside one dimension OR together, and dimensions
AND with each other. Two brands widen the shelf; adding a price range then
narrows it.
"""
import pytest

from .factories import make_brand, make_category, make_product, result_slugs

pytestmark = pytest.mark.django_db


@pytest.fixture
def multi_brand_catalogue():
    laptops = make_category("Laptops", "laptops")
    asus = make_brand("Asus", "asus")
    lenovo = make_brand("Lenovo", "lenovo")
    hp = make_brand("HP", "hp")

    make_product(
        laptops, brand=asus, name="Asus Budget", slug="asus-budget", price="80000.00"
    )
    make_product(
        laptops, brand=asus, name="Asus Flagship", slug="asus-flagship", price="200000.00"
    )
    make_product(
        laptops, brand=lenovo, name="Lenovo Mid", slug="lenovo-mid", price="120000.00"
    )
    make_product(laptops, brand=hp, name="HP Mid", slug="hp-mid", price="125000.00")
    # Neither variant falls inside 100k-150k, so a range filter must reject it
    # even though the product's overall span covers the whole window.
    make_product(
        laptops,
        brand=lenovo,
        name="Lenovo Spread",
        slug="lenovo-spread",
        variants=[
            {"sku": "SPREAD-LOW", "price": "50000.00", "stock": 4},
            {"sku": "SPREAD-HIGH", "price": "300000.00", "stock": 4},
        ],
    )
    return laptops


def test_two_brands_or_together(api, products_url, multi_brand_catalogue):
    payload = api.get(products_url, {"brand": ["asus", "lenovo"]}).json()

    assert set(result_slugs(payload)) == {
        "asus-budget",
        "asus-flagship",
        "lenovo-mid",
        "lenovo-spread",
    }


def test_brands_or_together_then_and_with_the_price_range(
    api, products_url, multi_brand_catalogue
):
    payload = api.get(
        products_url,
        {"brand": ["asus", "lenovo"], "min_price": "100000", "max_price": "150000"},
    ).json()

    # HP is inside the price band but outside the brand set; the Asus rows are
    # the right brand but outside the band; Lenovo Spread has no variant in it.
    assert result_slugs(payload) == ["lenovo-mid"]
    assert payload["count"] == 1


def test_price_range_alone_ignores_brand(api, products_url, multi_brand_catalogue):
    payload = api.get(
        products_url, {"min_price": "100000", "max_price": "150000"}
    ).json()

    assert set(result_slugs(payload)) == {"lenovo-mid", "hp-mid"}


def test_price_bounds_are_inclusive(api, products_url, multi_brand_catalogue):
    payload = api.get(
        products_url, {"min_price": "120000.00", "max_price": "120000.00"}
    ).json()

    assert result_slugs(payload) == ["lenovo-mid"]


def test_min_price_alone_is_an_open_upper_bound(
    api, products_url, multi_brand_catalogue
):
    payload = api.get(products_url, {"min_price": "125000"}).json()

    assert set(result_slugs(payload)) == {"asus-flagship", "hp-mid", "lenovo-spread"}


def test_in_stock_filter_keeps_only_products_with_sellable_stock(api, products_url):
    category = make_category("Monitors", "monitors")
    make_product(category, name="In Stock", slug="in-stock-monitor", stock=4)
    make_product(category, name="Sold Out", slug="sold-out-monitor", stock=0)

    payload = api.get(products_url, {"in_stock": "true"}).json()

    assert result_slugs(payload) == ["in-stock-monitor"]


def test_in_stock_false_does_not_filter_anything_out(api, products_url):
    category = make_category("Monitors", "monitors")
    make_product(category, name="In Stock", slug="in-stock-monitor", stock=4)
    make_product(category, name="Sold Out", slug="sold-out-monitor", stock=0)

    payload = api.get(products_url, {"in_stock": "false"}).json()

    assert set(result_slugs(payload)) == {"in-stock-monitor", "sold-out-monitor"}


def test_min_rating_compares_against_the_denormalised_average(api, products_url):
    category = make_category("Keyboards", "keyboards")
    make_product(category, name="Great", slug="great-kb", rating_avg="4.50", rating_count=8)
    make_product(category, name="Fine", slug="fine-kb", rating_avg="4.00", rating_count=3)
    make_product(category, name="Poor", slug="poor-kb", rating_avg="2.10", rating_count=9)

    payload = api.get(products_url, {"min_rating": "4"}).json()

    assert set(result_slugs(payload)) == {"great-kb", "fine-kb"}


def test_empty_parameter_values_are_treated_as_absent(
    api, products_url, multi_brand_catalogue
):
    # A UI clearing a field must not be an error.
    response = api.get(
        products_url,
        {"q": "", "brand": "", "category": "", "min_price": "", "sort": "", "in_stock": ""},
    )

    assert response.status_code == 200
    assert response.json()["count"] == 5


@pytest.mark.parametrize(
    "params,code,field",
    [
        ({"sort": "cheapest"}, "INVALID_SORT", "sort"),
        ({"min_price": "abc"}, "INVALID_FILTER", "min_price"),
        ({"min_price": "-5"}, "INVALID_FILTER", "min_price"),
        ({"in_stock": "maybe"}, "INVALID_FILTER", "in_stock"),
        ({"min_rating": "9"}, "INVALID_FILTER", "min_rating"),
        ({"brand": "Not A Slug!"}, "INVALID_FILTER", "brand"),
        ({"min_price": "500", "max_price": "100"}, "INVALID_PRICE_RANGE", "min_price"),
    ],
)
def test_malformed_parameters_return_422_with_a_stable_code(
    api, products_url, multi_brand_catalogue, params, code, field
):
    # A filter that silently does nothing returns a wrong result set that
    # looks right, which is far harder to notice than a 422.
    response = api.get(products_url, params)

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def test_keyword_and_filters_combine(api, products_url, multi_brand_catalogue):
    payload = api.get(
        products_url, {"q": "Lenovo", "min_price": "100000", "max_price": "150000"}
    ).json()

    assert result_slugs(payload) == ["lenovo-mid"]


def test_comma_separated_values_are_read_as_repeated_values(
    api, products_url, multi_brand_catalogue
):
    repeated = api.get(products_url, {"brand": ["asus", "hp"]}).json()
    csv = api.get(products_url, {"brand": "asus,hp"}).json()

    assert result_slugs(csv) == result_slugs(repeated)
    assert set(result_slugs(csv)) == {"asus-budget", "asus-flagship", "hp-mid"}


def test_slug_filters_are_case_insensitive(api, products_url, multi_brand_catalogue):
    payload = api.get(products_url, {"brand": "ASUS"}).json()

    assert set(result_slugs(payload)) == {"asus-budget", "asus-flagship"}
