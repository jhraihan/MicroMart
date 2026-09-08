"""
Category browsing (FR-CAT-1, FR-SRC-4).

Categories nest exactly one level, so a parent slug has to pull in its
children's products -- otherwise "Laptops" is an empty shelf while every
laptop sits under "Gaming Laptops".
"""
import pytest

from .factories import make_brand, make_category, make_product, result_slugs

pytestmark = pytest.mark.django_db


@pytest.fixture
def nested_catalogue():
    laptops = make_category("Laptops", "laptops", sort_order=0)
    gaming = make_category("Gaming Laptops", "gaming-laptops", parent=laptops)
    ultrabooks = make_category("Ultrabooks", "ultrabooks", parent=laptops)
    phones = make_category("Phones", "phones", sort_order=1)
    asus = make_brand("Asus", "asus")

    tuf = make_product(
        gaming, brand=asus, name="Asus TUF F15", slug="asus-tuf-f15", price="142000.00"
    )
    zen = make_product(
        ultrabooks,
        brand=asus,
        name="Asus Zenbook 14",
        slug="asus-zenbook-14",
        price="118000.00",
    )
    # Sits directly on the parent, which is legal even with children present.
    dock = make_product(
        laptops,
        brand=asus,
        name="Asus Docking Station",
        slug="asus-dock",
        price="9000.00",
    )
    phone = make_product(
        phones,
        brand=asus,
        name="Asus Zenfone 10",
        slug="asus-zenfone-10",
        price="88000.00",
    )
    return {
        "laptops": laptops,
        "gaming": gaming,
        "ultrabooks": ultrabooks,
        "phones": phones,
        "products": {"tuf": tuf, "zen": zen, "dock": dock, "phone": phone},
    }


def test_parent_category_listing_includes_child_category_products(
    api, products_url, nested_catalogue
):
    payload = api.get(products_url, {"category": "laptops"}).json()

    assert set(result_slugs(payload)) == {
        "asus-tuf-f15",
        "asus-zenbook-14",
        "asus-dock",
    }
    assert payload["count"] == 3
    assert "asus-zenfone-10" not in result_slugs(payload)


def test_child_category_listing_is_limited_to_that_child(
    api, products_url, nested_catalogue
):
    payload = api.get(products_url, {"category": "gaming-laptops"}).json()

    assert result_slugs(payload) == ["asus-tuf-f15"]


def test_multiple_category_slugs_or_together(api, products_url, nested_catalogue):
    payload = api.get(products_url, {"category": ["gaming-laptops", "phones"]}).json()

    assert set(result_slugs(payload)) == {"asus-tuf-f15", "asus-zenfone-10"}


def test_category_tree_nests_one_level_and_rolls_counts_up(
    api, categories_url, nested_catalogue
):
    tree = api.get(categories_url).json()

    laptops = next(node for node in tree if node["slug"] == "laptops")
    child_slugs = [child["slug"] for child in laptops["children"]]

    # Parent count is its own products plus every child's (FR-CAT-1).
    assert laptops["product_count"] == 3
    assert set(child_slugs) == {"gaming-laptops", "ultrabooks"}
    for child in laptops["children"]:
        assert child["children"] == []
        assert child["product_count"] == 1


def test_category_tree_omits_inactive_categories(api, categories_url, nested_catalogue):
    make_category("Secret Bundles", "secret-bundles", is_active=False)
    hidden_child = make_category(
        "Retired Ultrabooks",
        "retired-ultrabooks",
        parent=nested_catalogue["laptops"],
        is_active=False,
    )

    tree = api.get(categories_url).json()
    roots = [node["slug"] for node in tree]
    laptops = next(node for node in tree if node["slug"] == "laptops")

    assert "secret-bundles" not in roots
    assert hidden_child.slug not in [child["slug"] for child in laptops["children"]]


def test_category_counts_match_what_the_list_endpoint_returns(
    api, categories_url, products_url, nested_catalogue
):
    tree = api.get(categories_url).json()

    for node in tree:
        for category in [node] + node["children"]:
            listed = api.get(products_url, {"category": category["slug"]}).json()
            assert category["product_count"] == listed["count"], category["slug"]


def test_unknown_category_slug_returns_an_empty_page_not_an_error(
    api, products_url, nested_catalogue
):
    response = api.get(products_url, {"category": "not-a-category"})

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_category_node_carries_the_contract_shape(api, categories_url, nested_catalogue):
    node = api.get(categories_url).json()[0]

    assert set(node) == {"id", "name", "slug", "image", "product_count", "children"}
    assert node["image"] is None
    assert isinstance(node["product_count"], int)
