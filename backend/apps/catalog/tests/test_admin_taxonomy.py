"""
Admin categories and brands (PRD 7.3 /admin/categories/, /admin/brands/,
FR-CAT-1).

FR-CAT-1 fixes the taxonomy at exactly two levels, and that is not a styling
preference. `services/inventory.is_sellable` walks `variant -> product ->
category -> category.parent` and stops there, so a third level would hold
products that a deactivated root could never withdraw -- visible, buyable, and
unreachable from the navigation that was supposed to hide them. Three separate
ways to create one, three refusals.

Both DELETEs deactivate, but for asymmetric reasons the tests state, because
the asymmetry is a deliberate decision recorded in docs/HANDOFF.md: an inactive
*category* hides the products inside it; an inactive *brand* only leaves the
brand facet.
"""
import pytest

from apps.catalog.models import Brand, Category
from apps.catalog.tests import factories

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
def test_creating_a_root_category(admin_api, admin_categories_url):
    response = admin_api.post(
        admin_categories_url, {"name": "Monitors", "sort_order": 3}, format="json"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "monitors"
    assert body["parent_id"] is None
    assert body["sort_order"] == 3


def test_creating_a_child_of_a_root_category(
    admin_api, admin_categories_url, category
):
    response = admin_api.post(
        admin_categories_url,
        {"name": "Gaming Laptops", "parent_id": category.pk},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["parent_id"] == category.pk
    assert response.json()["parent_name"] == "Laptops"


def test_a_grandchild_category_is_refused(
    admin_api, admin_categories_url, child_category
):
    """FR-CAT-1: one level of nesting, and the parent already has a parent."""
    response = admin_api.post(
        admin_categories_url,
        {"name": "Ultrabooks", "parent_id": child_category.pk},
        format="json",
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "CATEGORY_NESTING_TOO_DEEP"
    assert error["field"] == "parent_id"
    assert not Category.objects.filter(name="Ultrabooks").exists()


def test_a_root_with_children_cannot_be_reparented_into_a_child(
    admin_api, admin_category_url, category, child_category
):
    """The same depth rule reached from the other end -- moving the root under
    another root would push its existing children to level three."""
    other_root = factories.make_category("Components", "components")

    response = admin_api.patch(
        admin_category_url(category.pk), {"parent_id": other_root.pk}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CATEGORY_HAS_CHILDREN"
    category.refresh_from_db()
    assert category.parent_id is None


def test_a_category_cannot_be_its_own_parent(
    admin_api, admin_category_url, category
):
    response = admin_api.patch(
        admin_category_url(category.pk), {"parent_id": category.pk}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CATEGORY_SELF_PARENT"


def test_an_unknown_parent_is_reported_against_the_parent_field(
    admin_api, admin_categories_url
):
    response = admin_api.post(
        admin_categories_url, {"name": "Orphan", "parent_id": 999_999}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "parent_id"


def test_a_child_can_be_promoted_back_to_a_root(
    admin_api, admin_category_url, child_category
):
    response = admin_api.patch(
        admin_category_url(child_category.pk), {"parent_id": None}, format="json"
    )

    assert response.status_code == 200
    child_category.refresh_from_db()
    assert child_category.parent_id is None


def test_the_admin_category_list_includes_inactive_ones_and_their_product_counts(
    admin_api, admin_categories_url, category, product
):
    factories.make_category("Retired", "retired", is_active=False)

    rows = {row["slug"]: row for row in admin_api.get(admin_categories_url).json()}

    assert rows["laptops"]["product_count"] == 1
    assert rows["retired"]["is_active"] is False


def test_deleting_a_category_deactivates_it_and_hides_what_is_inside(
    admin_api, api, admin_category_url, products_url, category, product
):
    """
    A category is a place in the navigation, so withdrawing it withdraws its
    contents. Deactivating rather than deleting is also the only safe answer:
    Product.category is PROTECT.
    """
    response = admin_api.delete(admin_category_url(category.pk))

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert Category.objects.filter(pk=category.pk).exists()
    assert api.get(products_url).json()["count"] == 0


def test_a_category_delete_never_touches_a_placed_order(
    admin_api, admin_category_url, category, variant
):
    order = factories.place_order([(variant, 1)])
    snapshot = order.items.get().product_name

    admin_api.delete(admin_category_url(category.pk))

    assert order.items.get().product_name == snapshot


def test_a_duplicate_category_slug_is_a_per_field_error(
    admin_api, admin_categories_url, category
):
    response = admin_api.post(
        admin_categories_url, {"name": "Other", "slug": category.slug}, format="json"
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "SLUG_TAKEN"
    assert error["field"] == "slug"


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------
def test_creating_a_brand(admin_api, admin_brands_url):
    response = admin_api.post(admin_brands_url, {"name": "Logitech"}, format="json")

    assert response.status_code == 201
    assert response.json()["slug"] == "logitech"


def test_renaming_a_brand(admin_api, admin_brand_url, brand):
    response = admin_api.patch(
        admin_brand_url(brand.pk), {"name": "ASUS"}, format="json"
    )

    assert response.status_code == 200
    brand.refresh_from_db()
    assert brand.name == "ASUS"
    assert brand.slug == "asus", "the slug is a URL, not a display name"


def test_deleting_a_brand_deactivates_it_but_leaves_its_products_on_sale(
    admin_api, api, admin_brand_url, products_url, brand, product
):
    """
    The deliberate asymmetry with categories (docs/HANDOFF.md 3): a brand is a
    label on sellable stock. Withdrawing it removes it from the brand facet;
    the products keep selling.
    """
    response = admin_api.delete(admin_brand_url(brand.pk))

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert Brand.objects.filter(pk=brand.pk).exists()
    assert api.get(products_url).json()["count"] == 1


def test_a_deactivated_brand_leaves_the_public_brand_list(
    admin_api, api, admin_brand_url, brands_url, brand, product
):
    admin_api.delete(admin_brand_url(brand.pk))

    assert api.get(brands_url).json() == []


def test_the_admin_brand_list_shows_inactive_brands_with_product_counts(
    admin_api, admin_brands_url, brand, product
):
    factories.make_brand("Retired", "retired-brand", is_active=False)

    rows = {row["slug"]: row for row in admin_api.get(admin_brands_url).json()}

    assert rows["asus"]["product_count"] == 1
    assert rows["retired-brand"]["is_active"] is False


def test_a_duplicate_brand_slug_is_a_per_field_error(
    admin_api, admin_brands_url, brand
):
    response = admin_api.post(
        admin_brands_url, {"name": "Other", "slug": brand.slug}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "slug"


def test_an_unknown_brand_is_a_404(admin_api, admin_brand_url):
    assert admin_api.get(admin_brand_url(999_999)).status_code == 404
