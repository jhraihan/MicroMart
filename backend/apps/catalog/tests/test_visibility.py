"""
FR-CAT-7: an inactive product is invisible to the storefront.

"Invisible" is asserted at every entrance, not just the detail route -- a
product hidden from the detail page but still listed in search results is
still leaked.
"""
import pytest

from .factories import (
    make_brand,
    make_category,
    make_product,
    make_variant,
    result_slugs,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalogue_with_a_hidden_product():
    category = make_category("Laptops", "laptops")
    brand = make_brand("Asus", "asus")
    visible = make_product(
        category,
        brand=brand,
        name="Asus Vivobook Go 15",
        slug="asus-vivobook-go-15",
        sku="VIVO-8-512",
        price="62000.00",
    )
    hidden = make_product(
        category,
        brand=brand,
        name="Asus Vivobook Pro 16 unreleased",
        slug="asus-vivobook-pro-16",
        sku="VIVO-16-1024",
        price="145000.00",
        is_active=False,
    )
    return category, visible, hidden


def test_inactive_product_detail_returns_404_with_the_error_envelope(
    api, detail_url, catalogue_with_a_hidden_product
):
    _, _, hidden = catalogue_with_a_hidden_product

    response = api.get(detail_url(hidden.slug))

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not found."}}


def test_unknown_slug_returns_the_same_404_as_an_inactive_product(
    api, detail_url, catalogue_with_a_hidden_product
):
    # The two must be indistinguishable, otherwise the 404 leaks which slugs
    # exist but are hidden.
    response = api.get(detail_url("no-such-product"))

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not found."}}


def test_inactive_product_is_absent_from_the_list(
    api, products_url, catalogue_with_a_hidden_product
):
    _, visible, hidden = catalogue_with_a_hidden_product

    payload = api.get(products_url).json()

    assert result_slugs(payload) == [visible.slug]
    assert payload["count"] == 1


def test_inactive_product_is_absent_from_search_results(
    api, products_url, catalogue_with_a_hidden_product
):
    _, _, hidden = catalogue_with_a_hidden_product

    payload = api.get(products_url, {"q": "Vivobook"}).json()

    assert hidden.slug not in result_slugs(payload)


def test_inactive_product_is_absent_from_related_products(
    api, related_url, catalogue_with_a_hidden_product
):
    _, visible, hidden = catalogue_with_a_hidden_product

    rows = api.get(related_url(visible.slug)).json()

    assert hidden.slug not in result_slugs(rows)


def test_inactive_product_is_absent_from_facets_and_category_counts(
    api, products_url, categories_url, catalogue_with_a_hidden_product
):
    payload = api.get(products_url).json()
    tree = api.get(categories_url).json()

    assert payload["facets"]["brands"] == [{"slug": "asus", "name": "Asus", "count": 1}]
    assert tree[0]["product_count"] == 1


def test_a_product_whose_variants_are_all_inactive_drops_out_of_listings(
    api, products_url, detail_url
):
    # It has no price and no stock, so it cannot honour the list contract --
    # but FR-CAT-7 gates the detail page on the product's own flag, so detail
    # still resolves.
    category = make_category("Monitors", "monitors")
    product = make_product(
        category, name="Discontinued Monitor", slug="discontinued-monitor", variants=[]
    )
    make_variant(product, sku="MON-DEAD", price="9000.00", stock=4, is_active=False)

    listing = api.get(products_url).json()
    detail = api.get(detail_url(product.slug))
    body = detail.json()

    assert result_slugs(listing) == []
    assert detail.status_code == 200
    assert body["variants"] == []
    # With no active variant there is no price to report. The detail contract
    # types these three as nullable for exactly this case rather than letting
    # the card invent a 0.00 that would render as a free product.
    assert body["price_min"] is None
    assert body["price_max"] is None
    assert body["compare_at_price"] is None
    assert body["discount_percent"] == 0
    assert body["in_stock"] is False
    assert body["total_stock"] == 0
    assert body["variant_count"] == 0


# ---------------------------------------------------------------------------
# An inactive category or brand (FR-CAT-1 / FR-CAT-7)
# ---------------------------------------------------------------------------
def test_products_in_an_inactive_category_are_absent_everywhere(
    api, products_url, detail_url
):
    # /categories/ already hid the category. Leaving its products on
    # /products/ let two endpoints in the same contract disagree about what
    # exists -- and left ?category=<dead slug> working as a filter.
    live = make_category("Laptops", "laptops")
    dead = make_category("Clearance", "clearance", is_active=False)
    make_product(live, name="Live Laptop", slug="live-laptop", sku="LIVE-1")
    hidden = make_product(dead, name="Clearance Laptop", slug="dead-laptop", sku="DEAD-1")

    payload = api.get(products_url).json()
    filtered = api.get(products_url, {"category": "clearance"}).json()

    assert result_slugs(payload) == ["live-laptop"]
    assert [row["slug"] for row in payload["facets"]["categories"]] == ["laptops"]
    assert filtered["count"] == 0
    assert api.get(detail_url(hidden.slug)).status_code == 404


def test_a_child_of_a_deactivated_parent_category_is_hidden_too(api, products_url):
    # Categories nest one level, so a child is only reachable while its
    # parent is: deactivating the parent must take the whole branch with it.
    parent = make_category("Retired", "retired", is_active=False)
    child = make_category("Retired Docks", "retired-docks", parent=parent)
    make_product(child, name="Old Dock", slug="old-dock", sku="OLD-1")

    payload = api.get(products_url).json()

    assert payload["count"] == 0


def test_an_inactive_brand_hides_its_facet_row_but_keeps_its_products(
    api, products_url, brands_url
):
    """
    Deliberate asymmetry with category, and the conservative reading.

    A brand is a label on sellable stock, not a place in the navigation.
    Unticking one checkbox on a brand record should not silently delist every
    product carrying it, so the products stay listed, searchable and buyable;
    only the discovery surfaces (/brands/ and facets.brands) drop it.
    """
    category = make_category("Laptops", "laptops")
    retired = make_brand("Retired", "retired", is_active=False)
    live = make_brand("Asus", "asus")
    make_product(
        category, brand=retired, name="Retired Laptop", slug="retired-laptop", sku="RET-1"
    )
    make_product(
        category, brand=live, name="Asus Laptop", slug="asus-laptop", sku="ASUS-1"
    )

    payload = api.get(products_url).json()

    assert set(result_slugs(payload)) == {"retired-laptop", "asus-laptop"}
    assert payload["facets"]["brands"] == [
        {"slug": "asus", "name": "Asus", "count": 1}
    ]
    assert [row["slug"] for row in api.get(brands_url).json()] == ["asus"]
