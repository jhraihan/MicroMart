"""
Wishlist (PRD 5.9, FR-WSH-1..4).

Three rules shape this module:

1. **A wishlist belongs to one signed-in customer** (FR-WSH-1). Every queryset
   here is filtered by user before anything else, so another customer's saved
   item does not exist for this request and a miss is a 404 (PRD 10.2). There
   is no guest wishlist: FR-WSH-4's "prompt login, then complete the add" is a
   client-side replay of POST /wishlist/ after authentication, not a server
   concept.
2. **Adding twice is idempotent** (FR-WSH-1). A wishlist is a set, so a second
   click on an already-saved product is a no-op that reports the existing row,
   not an error and never a duplicate. The model's UniqueConstraint is what
   makes that true under a race, not just under a check.
3. **Nothing is hidden, everything is labelled** (FR-WSH-3). An out-of-stock
   or withdrawn product stays on the list carrying an `issue`, because a
   customer who cannot see what happened to a saved item cannot decide what to
   do about it. The issue vocabulary is the catalogue's own
   (inventory_services.ISSUE_*), so a wishlist line, a cart line and a quote
   line describe the same condition with the same word.

Price and stock are read fresh on every list (FR-WSH-2) -- nothing about a
product is copied onto the wishlist row, so a price change is visible the next
time the page is opened.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import IntegerField, OuterRef, Prefetch, Subquery

from apps.catalog.models import Product, ProductImage, ProductVariant
from apps.catalog.services import catalogue
from apps.catalog.services import inventory as inventory_services
from config.exceptions import DomainError

from ..models import WishlistItem


def _product_queryset():
    """
    Wishlisted products, annotated exactly as a product card is.

    Reuses catalogue.annotate_product_aggregates so price_min, total_stock and
    the discount badge are computed by the same expressions the storefront
    list uses -- one definition of "the current price", not two.

    Deliberately *not* restricted to listable_products(): a product that went
    inactive after being saved must still resolve, so the line can say so
    (FR-WSH-3). Visibility is reported per line by `issue`, never by dropping
    the row.
    """
    cheapest = ProductVariant.objects.filter(
        product=OuterRef("pk"), is_active=True
    ).order_by("price", "id")
    return (
        catalogue.annotate_product_aggregates(
            Product.objects.select_related("brand", "category", "category__parent")
        )
        .annotate(
            # What "move to cart" adds (FR-WSH-2). The cheapest active variant,
            # which is the same one price_min reports, so the button and the
            # price on the card agree.
            default_variant_id=Subquery(
                cheapest.values("id")[:1], output_field=IntegerField()
            )
        )
        .prefetch_related(
            Prefetch(
                "images", queryset=ProductImage.objects.order_by("sort_order", "id")
            )
        )
    )


def wishlist_items(user):
    """This customer's saved products, most recently added first."""
    return (
        WishlistItem.objects.filter(user=user)
        .prefetch_related(Prefetch("product", queryset=_product_queryset()))
        .order_by("-created_at", "-id")
    )


def issue_for(product):
    """
    Why this saved product cannot be bought right now, or None.

    Answered from the annotations the list already carries, so labelling a
    wishlist costs no extra query. `variant_count` and `total_stock` come from
    catalogue.annotate_product_aggregates and count active variants only.
    """
    category = product.category
    parent_ok = category.parent_id is None or category.parent.is_active
    sellable = bool(
        product.is_active
        and category.is_active
        and parent_ok
        and (getattr(product, "variant_count", 0) or 0) > 0
    )
    if not sellable:
        return inventory_services.ISSUE_UNAVAILABLE
    if (getattr(product, "total_stock", 0) or 0) <= 0:
        return inventory_services.ISSUE_OUT_OF_STOCK
    return None


def add_to_wishlist(*, user, product_id):
    """
    Save a product, or report the row already saved (FR-WSH-1).

    Returns `(item, created)`. `created` is False on a repeat click, which is
    what lets the API answer 200 for a no-op and 201 for a genuine add without
    either being an error.

    The product must be one the storefront actually shows -- an id a customer
    could never have seen resolves to a 404 rather than saving a hidden row.
    """
    product = catalogue.storefront_products().filter(pk=product_id).first()
    if product is None:
        raise DomainError("Not found.", code="NOT_FOUND", status_code=404)

    try:
        with transaction.atomic():
            item, created = WishlistItem.objects.get_or_create(
                user=user, product=product
            )
    except IntegrityError:
        # Two clicks landed at once; the UniqueConstraint arbitrated and this
        # one lost. The customer's intent is satisfied either way.
        item = WishlistItem.objects.get(user=user, product=product)
        created = False
    return item, created


def remove_from_wishlist(*, user, product_id):
    """
    DELETE /wishlist/{product_id}/ -- scoped to this customer's own row.

    Removing something that is not on *this* customer's list is a 404, whether
    it was never saved or belongs to someone else. The two cases must be
    indistinguishable, or the endpoint answers "does user X have product Y
    saved" for any X.
    """
    deleted, _ = WishlistItem.objects.filter(
        user=user, product_id=product_id
    ).delete()
    if not deleted:
        raise DomainError("Not found.", code="NOT_FOUND", status_code=404)
    return True


def is_wishlisted(user, product):
    """Does this customer already have this product saved? Drives the heart icon."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return WishlistItem.objects.filter(user=user, product=product).exists()
