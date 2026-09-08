"""
Cart payload shapes (docs/api-contract-cart-checkout-orders.md).

These translate only. Availability, clamping and the subtotal are decided in
services/cart.py; a serializer that recomputed any of them would be a second
opinion about money, and the two would drift.

Money leaves as decimal strings (COERCE_DECIMAL_TO_STRING), image URLs are
MEDIA_URL-relative, exactly as the catalogue contract already established.
"""
from rest_framework import serializers

from apps.catalog.serializers import media_url

MONEY_KWARGS = {"max_digits": 12, "decimal_places": 2, "read_only": True}


def variant_image(variant):
    """
    The variant's own image, or the product's primary, or its first.

    Falls back deliberately: a cart line with no thumbnail reads as a broken
    page, and most variants carry no image of their own.
    """
    images = list(variant.images.all())
    if not images:
        images = list(variant.product.images.all())
    if not images:
        return None
    image = next((item for item in images if item.is_primary), images[0])
    return {"url": media_url(image.image), "alt_text": image.alt_text}


class CartLineSerializer(serializers.Serializer):
    """
    One row. `quantity` is what the customer asked for; `effective_quantity`
    is what can be bought right now, and it is what `line_total` prices.

    **Flat, not nested, and that is load-bearing.** This is the same line
    vocabulary as a quote line (apps/orders/serializers.py QuoteLineSerializer)
    and as an order item, so the cart page, the checkout review list and the
    order screens read one shape instead of three. It was nested under a
    `variant` object until 2026-08-22, which silently broke the signed-in cart:
    the storefront reads the flat keys, so every line rendered with no name, no
    image and no link, and -- because `variant_id` was among the missing keys
    -- the quote request built from those lines was rejected 400, taking the
    totals down with it. See docs/api-contract-cart-checkout-orders.md.
    """

    id = serializers.IntegerField(source="item.id", read_only=True)
    variant_id = serializers.IntegerField(source="variant.id", read_only=True)
    product_id = serializers.IntegerField(source="variant.product_id", read_only=True)
    product_name = serializers.CharField(source="variant.product.name", read_only=True)
    product_slug = serializers.CharField(source="variant.product.slug", read_only=True)
    variant_label = serializers.CharField(source="variant.label", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    image = serializers.SerializerMethodField()
    unit_price = serializers.DecimalField(**MONEY_KWARGS)
    compare_at_price = serializers.DecimalField(
        source="variant.compare_at_price", allow_null=True, **MONEY_KWARGS
    )
    quantity = serializers.IntegerField(read_only=True)
    effective_quantity = serializers.IntegerField(read_only=True)
    line_total = serializers.DecimalField(**MONEY_KWARGS)
    stock = serializers.IntegerField(source="available_stock", read_only=True)
    in_stock = serializers.SerializerMethodField()
    is_available = serializers.BooleanField(read_only=True)
    issue = serializers.CharField(read_only=True, allow_null=True)

    def get_image(self, obj):
        # A URL string, not an object: every consumer feeds it straight to an
        # <img src>, and the quote line already answers in that shape.
        image = variant_image(obj.variant)
        return image["url"] if image else None

    def get_in_stock(self, obj):
        return obj.available_stock > 0


class CartSerializer(serializers.Serializer):
    """
    GET /cart/ and the body every mutating cart endpoint returns.

    Always the whole cart, never the changed line alone: the mini-cart count,
    the subtotal and every clamp notice have to stay in step, and a client that
    patched one line locally would drift from the server on the first
    out-of-stock edit.
    """

    id = serializers.IntegerField(source="cart.id", read_only=True)
    items = CartLineSerializer(source="lines", many=True, read_only=True)
    item_count = serializers.IntegerField(read_only=True)
    subtotal = serializers.DecimalField(**MONEY_KWARGS)
    notices = serializers.ListField(read_only=True)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
class CartItemInputSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, default=1)


class CartItemAddSerializer(CartItemInputSerializer):
    pass


class CartItemUpdateSerializer(serializers.Serializer):
    """Quantity only. Removal is DELETE -- a PATCH to zero is not a delete."""

    quantity = serializers.IntegerField(min_value=1)


class CartMergeSerializer(serializers.Serializer):
    """The guest cart arriving from localStorage at login (FR-CRT-2)."""

    items = CartItemInputSerializer(many=True, allow_empty=True)
