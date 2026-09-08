"""
Review and wishlist payload shapes (PRD 7.2, 7.3).

These translate only. Who may review, what counts toward a rating and whether
a saved product is buyable are all decided in services/; a serializer that
recomputed any of them would be a second opinion, and the two would drift.

Two shapes are derived rather than stored on purpose:

* **Verified Purchase** is `order_id is not None` (FR-REV-6). Eligibility
  already guarantees the purchase, so the badge is a consequence of the
  proving order, never a field a request can set.
* A wishlist line's product is rendered by the catalogue's own
  ProductListSerializer, so the current price, discount badge and stock
  status on the wishlist are literally the product card's (FR-WSH-2).

An author is shown by display name, never by email address.
"""
from rest_framework import serializers

from apps.catalog.serializers import ProductListSerializer

from .models import Review, WishlistItem
from .services import reviews as review_services
from .services import wishlist as wishlist_services


def display_name(user):
    """
    A name safe to print next to a review.

    Falls back to a masked mailbox rather than the address itself: a review
    list is public, and an email address on it is a harvestable one.
    """
    if user is None:
        return "Customer"
    name = (user.full_name or "").strip()
    if name:
        return name
    local = (user.email or "").split("@")[0]
    return (local[:2] + "***") if local else "Customer"


# ---------------------------------------------------------------------------
# Reviews -- storefront
# ---------------------------------------------------------------------------
class ReviewSerializer(serializers.ModelSerializer):
    """
    One review as the storefront reads it.

    `status` and `is_editable` are here for the author's own copy, which comes
    back from POST and PATCH: without them the UI cannot say "awaiting
    moderation" or know whether to still offer an edit form. Both are harmless
    on the public list, where every row is approved by construction.
    """

    product_id = serializers.IntegerField(read_only=True)
    author_name = serializers.SerializerMethodField()
    is_verified_purchase = serializers.SerializerMethodField()
    is_editable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "product_id",
            "rating",
            "title",
            "body",
            "status",
            "author_name",
            "is_verified_purchase",
            "is_editable",
            "created_at",
            "updated_at",
        ]
        # Only the plain model fields need naming here; every declared field
        # above is already read_only. Nothing writes through this serializer --
        # input has its own shapes below.
        read_only_fields = ["rating", "title", "body", "status"]

    def get_author_name(self, obj):
        return display_name(obj.user)

    def get_is_verified_purchase(self, obj):
        # FR-REV-6: derived from the order that proved eligibility.
        return obj.order_id is not None


class ReviewInputSerializer(serializers.Serializer):
    """
    POST /products/{slug}/reviews/ -- rating required, text optional
    (FR-REV-1).

    The bounds are restated here so a bad rating is a 400 with a field name
    rather than reaching the service; the service checks them again anyway,
    because it is also called from tests and management code.
    """

    rating = serializers.IntegerField(
        min_value=review_services.RATING_MIN, max_value=review_services.RATING_MAX
    )
    title = serializers.CharField(
        max_length=review_services.MAX_TITLE_LENGTH,
        required=False,
        allow_blank=True,
        default="",
    )
    body = serializers.CharField(
        max_length=review_services.MAX_BODY_LENGTH,
        required=False,
        allow_blank=True,
        default="",
    )


class ReviewUpdateSerializer(serializers.Serializer):
    """
    PATCH /reviews/{id}/ -- a partial edit, so every field is optional.

    Absent means "leave alone"; the service distinguishes that from an empty
    string, which genuinely clears the field.
    """

    rating = serializers.IntegerField(
        min_value=review_services.RATING_MIN,
        max_value=review_services.RATING_MAX,
        required=False,
    )
    title = serializers.CharField(
        max_length=review_services.MAX_TITLE_LENGTH, required=False, allow_blank=True
    )
    body = serializers.CharField(
        max_length=review_services.MAX_BODY_LENGTH, required=False, allow_blank=True
    )


# ---------------------------------------------------------------------------
# Reviews -- admin
# ---------------------------------------------------------------------------
class AdminReviewSerializer(ReviewSerializer):
    """
    The moderation queue row (PRD 7.3).

    Carries what a moderator needs to judge the review -- which product, who
    wrote it, whether they really bought it, and who last acted on it. The
    customer's email is shown here and only here: this endpoint is gated to
    the admin role.
    """

    product = serializers.SerializerMethodField()
    author_email = serializers.EmailField(source="user.email", read_only=True)
    moderated_by_email = serializers.SerializerMethodField()
    order_reference = serializers.SerializerMethodField()

    class Meta(ReviewSerializer.Meta):
        fields = ReviewSerializer.Meta.fields + [
            "product",
            "author_email",
            "order_reference",
            "moderated_at",
            "moderated_by_email",
        ]
        read_only_fields = ReviewSerializer.Meta.read_only_fields + ["moderated_at"]

    def get_product(self, obj):
        return {"id": obj.product_id, "name": obj.product.name, "slug": obj.product.slug}

    def get_moderated_by_email(self, obj):
        return obj.moderated_by.email if obj.moderated_by_id else None

    def get_order_reference(self, obj):
        return obj.order.reference if obj.order_id else None


class ModerationSerializer(serializers.Serializer):
    """POST /admin/reviews/{id}/moderate/ -- approve or reject (FR-REV-4)."""

    decision = serializers.ChoiceField(
        choices=[review_services.DECISION_APPROVE, review_services.DECISION_REJECT]
    )


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
class WishlistItemSerializer(serializers.ModelSerializer):
    """
    One saved product (FR-WSH-2, FR-WSH-3).

    `issue` is the catalogue's vocabulary -- out_of_stock / unavailable /
    None -- so the label a wishlist prints is the same word a cart line
    prints. An out-of-stock line is present and flagged, never dropped.

    `in_stock` means **buyable right now**, which is `issue is None` and not
    "some stock exists". A withdrawn product can still have units on a shelf,
    and a wishlist that called that in stock would offer a move-to-cart button
    the cart would then refuse. A cart line answers the same question the same
    way, from the same three strings.
    """

    # None is a meaningful `issue`, so the memo needs a sentinel rather than a
    # None check -- otherwise every buyable row is recomputed twice per render.
    _UNSET = object()

    product = ProductListSerializer(read_only=True)
    default_variant_id = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    issue = serializers.SerializerMethodField()
    added_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = WishlistItem
        fields = [
            "id",
            "product",
            "default_variant_id",
            "in_stock",
            "issue",
            "added_at",
        ]

    def get_default_variant_id(self, obj):
        return getattr(obj.product, "default_variant_id", None)

    def get_in_stock(self, obj):
        return self._issue(obj) is None

    def get_issue(self, obj):
        return self._issue(obj)

    def _issue(self, obj):
        value = getattr(obj, "_wishlist_issue", self._UNSET)
        if value is self._UNSET:
            value = wishlist_services.issue_for(obj.product)
            obj._wishlist_issue = value
        return value


class WishlistAddSerializer(serializers.Serializer):
    """POST /wishlist/ -- one product id. A repeat is a no-op, not an error."""

    product_id = serializers.IntegerField(min_value=1)
