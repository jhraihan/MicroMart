"""
The wishlist (PRD 5.9, FR-WSH-1..4).

Four claims, each one a thing a naive implementation gets wrong:

1. **It requires a login** and is scoped to one customer -- another shopper's
   saved product is invisible, and removing it is a 404 rather than a 403
   (PRD 10.2).
2. **Adding twice is idempotent.** A second click is a no-op that reports the
   existing row, not a 422 and not a duplicate.
3. **Price and stock are read fresh** (FR-WSH-2). Nothing is copied onto the
   wishlist row, so a later price change is visible on the next read.
4. **Out-of-stock items are labelled, not hidden** (FR-WSH-3) -- and so is a
   product that was withdrawn from sale entirely.
"""
import pytest
from django.urls import reverse

from apps.catalog.models import ProductVariant
from apps.catalog.services import inventory as inventory_services
from apps.reviews.models import WishlistItem

pytestmark = pytest.mark.django_db


ANONYMOUS_CALLS = [
    ("get", "reviews:wishlist", {}, None),
    ("post", "reviews:wishlist", {}, {"product_id": 1}),
    ("delete", "reviews:wishlist-item", {"product_id": 1}, None),
]


def rows(response):
    return response.json()["results"]


@pytest.mark.parametrize("method,route,kwargs,payload", ANONYMOUS_CALLS)
def test_an_anonymous_caller_is_refused_on_every_wishlist_route(
    api, method, route, kwargs, payload
):
    url = reverse(route, kwargs=kwargs)

    call = getattr(api, method)
    response = call(url) if payload is None else call(url, payload, format="json")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Add, re-add, remove
# ---------------------------------------------------------------------------
def test_a_customer_can_save_a_product(shopper, customer, product, wishlist_url):
    response = shopper.post(
        wishlist_url, {"product_id": product.pk}, format="json"
    )

    assert response.status_code == 201
    assert response.json()["product"]["slug"] == product.slug
    assert WishlistItem.objects.filter(user=customer, product=product).count() == 1


def test_saving_the_same_product_twice_is_a_no_op_not_an_error(
    shopper, customer, product, wishlist_url
):
    """
    FR-WSH-1: a wishlist is a set.

    The second call answers 200 rather than 201 so a client can tell "already
    saved" from "just saved" -- but neither is an error, and neither writes a
    second row.
    """
    first = shopper.post(wishlist_url, {"product_id": product.pk}, format="json")
    second = shopper.post(wishlist_url, {"product_id": product.pk}, format="json")

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"]
    assert WishlistItem.objects.filter(user=customer, product=product).count() == 1


def test_saving_a_product_that_is_not_on_sale_is_a_404(
    shopper, product, wishlist_url
):
    product.is_active = False
    product.save(update_fields=["is_active"])

    response = shopper.post(wishlist_url, {"product_id": product.pk}, format="json")

    assert response.status_code == 404
    assert WishlistItem.objects.count() == 0


def test_a_customer_can_remove_a_saved_product(
    shopper, customer, product, wishlist_url, wishlist_item_url
):
    shopper.post(wishlist_url, {"product_id": product.pk}, format="json")

    response = shopper.delete(wishlist_item_url(product.pk))

    assert response.status_code == 204
    assert WishlistItem.objects.filter(user=customer).count() == 0
    assert rows(shopper.get(wishlist_url)) == []


def test_removing_something_that_was_never_saved_is_a_404(
    shopper, product, wishlist_item_url
):
    response = shopper.delete(wishlist_item_url(product.pk))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# What the list says (FR-WSH-2, FR-WSH-3)
# ---------------------------------------------------------------------------
def test_the_list_shows_the_current_price_and_stock_status(
    shopper, product, variant, wishlist_url
):
    shopper.post(wishlist_url, {"product_id": product.pk}, format="json")

    row = rows(shopper.get(wishlist_url))[0]

    assert row["product"]["price_min"] == "1000.00", "money is a decimal string"
    assert row["in_stock"] is True
    assert row["issue"] is None
    assert row["default_variant_id"] == variant.pk, "move-to-cart needs a variant"


def test_the_price_shown_is_todays_price_not_the_price_when_it_was_saved(
    shopper, product, variant, wishlist_url
):
    """FR-WSH-2: nothing about the product is snapshotted onto the wishlist row."""
    shopper.post(wishlist_url, {"product_id": product.pk}, format="json")
    ProductVariant.objects.filter(pk=variant.pk).update(price="899.00")

    row = rows(shopper.get(wishlist_url))[0]

    assert row["product"]["price_min"] == "899.00"


def test_an_out_of_stock_item_stays_on_the_list_and_is_labelled(
    shopper, build_product, wishlist_url
):
    """
    FR-WSH-3, stated as plainly as the requirement does: **labelled, not
    hidden.** Dropping the row is the failure mode this test exists to catch.
    """
    sold_out = build_product(
        name="Sold Out Laptop", slug="sold-out-laptop", price="500.00", stock=0
    )
    shopper.post(wishlist_url, {"product_id": sold_out.pk}, format="json")

    row = rows(shopper.get(wishlist_url))[0]

    assert row["product"]["slug"] == sold_out.slug
    assert row["in_stock"] is False
    assert row["issue"] == inventory_services.ISSUE_OUT_OF_STOCK
    assert row["product"]["price_min"] == "500.00", "the price is still readable"


def test_a_product_withdrawn_after_it_was_saved_is_labelled_unavailable(
    shopper, product, wishlist_url
):
    shopper.post(wishlist_url, {"product_id": product.pk}, format="json")
    product.is_active = False
    product.save(update_fields=["is_active"])

    row = rows(shopper.get(wishlist_url))[0]

    assert row["issue"] == inventory_services.ISSUE_UNAVAILABLE
    assert row["in_stock"] is False


def test_a_product_whose_category_was_deactivated_is_labelled_unavailable(
    shopper, product, category, wishlist_url
):
    """
    Withdrawing a category withdraws everything under it -- the same rule the
    storefront and the cart use, not a second opinion about visibility.
    """
    shopper.post(wishlist_url, {"product_id": product.pk}, format="json")
    category.is_active = False
    category.save(update_fields=["is_active"])

    row = rows(shopper.get(wishlist_url))[0]

    assert row["issue"] == inventory_services.ISSUE_UNAVAILABLE


def test_the_list_is_newest_first(
    shopper, product, other_product, wishlist_url
):
    shopper.post(wishlist_url, {"product_id": product.pk}, format="json")
    shopper.post(wishlist_url, {"product_id": other_product.pk}, format="json")

    slugs = [row["product"]["slug"] for row in rows(shopper.get(wishlist_url))]

    assert slugs == [other_product.slug, product.slug]


# ---------------------------------------------------------------------------
# One customer's wishlist is invisible to another (PRD 10.2)
# ---------------------------------------------------------------------------
def test_another_customers_wishlist_is_invisible(
    as_user, customer, other_customer, product, wishlist_url
):
    as_user(other_customer).post(
        wishlist_url, {"product_id": product.pk}, format="json"
    )

    response = as_user(customer).get(wishlist_url)

    assert rows(response) == []
    assert response.json()["count"] == 0


def test_removing_a_product_saved_by_someone_else_is_a_404_and_leaves_it_alone(
    as_user, customer, other_customer, product, wishlist_url, wishlist_item_url
):
    """
    A 403 here would answer "does that customer have this product saved" for
    any pair -- so a row that exists but is not yours must be indistinguishable
    from one that does not exist at all.
    """
    as_user(other_customer).post(
        wishlist_url, {"product_id": product.pk}, format="json"
    )

    response = as_user(customer).delete(wishlist_item_url(product.pk))

    assert response.status_code == 404
    assert WishlistItem.objects.filter(user=other_customer, product=product).exists()


def test_two_customers_can_save_the_same_product(
    as_user, customer, other_customer, product, wishlist_url
):
    """The uniqueness constraint is per (user, product), not per product."""
    mine = as_user(customer).post(
        wishlist_url, {"product_id": product.pk}, format="json"
    )
    theirs = as_user(other_customer).post(
        wishlist_url, {"product_id": product.pk}, format="json"
    )

    assert (mine.status_code, theirs.status_code) == (201, 201)
    assert WishlistItem.objects.filter(product=product).count() == 2
