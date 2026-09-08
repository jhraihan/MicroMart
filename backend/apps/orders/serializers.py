"""
Checkout and order payload shapes (docs/api-contract-cart-orders.md).

Two things are worth stating because they are easy to get wrong:

1. **Nothing here computes money.** Every figure is read off a `Totals` object
   or an Order row. The one arithmetic rule a serializer may apply is
   formatting, and DRF's COERCE_DECIMAL_TO_STRING does that.
2. **Order output is read from the snapshot, never from the catalogue.**
   `product_name`, `variant_label`, `sku` and `unit_price` come off OrderItem.
   The variant FK is exposed only as `product_slug`, and only so the UI can
   link back -- it is nullable and the line still reads correctly without it.
"""
from rest_framework import serializers

from apps.cart.serializers import variant_image
from apps.common.phone import is_valid_phone
from apps.shipping.serializers import ShippingZoneSerializer

from .models import Order, OrderItem, OrderStatusLog, PaymentMethod

MONEY_KWARGS = {"max_digits": 12, "decimal_places": 2, "read_only": True}
CURRENCY = "BDT"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
class BasketItemInputSerializer(serializers.Serializer):
    """What the client may say about a line: which variant, how many. No price."""

    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, default=1)


class ShippingAddressInputSerializer(serializers.Serializer):
    """Bangladesh address shape (FR-CHK-2). Copied onto the order verbatim."""

    recipient_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    division = serializers.CharField(max_length=64)
    district = serializers.CharField(max_length=64)
    upazila = serializers.CharField(max_length=64, required=False, allow_blank=True)
    area = serializers.CharField(max_length=128, required=False, allow_blank=True)
    street = serializers.CharField(max_length=255)
    postcode = serializers.CharField(max_length=12, required=False, allow_blank=True)

    def validate_phone(self, value):
        # FR-CHK-3. Normalisation happens in the service; this is the per-field
        # message the form needs.
        if not is_valid_phone(value):
            raise serializers.ValidationError(
                "Enter a valid Bangladesh mobile number, e.g. 01712345678."
            )
        return value


class CheckoutQuoteSerializer(serializers.Serializer):
    """
    POST /checkout/quote/. `items` is required for guests and optional for a
    signed-in customer, who is quoted on their server cart when it is omitted.
    """

    items = BasketItemInputSerializer(many=True, required=False)
    district = serializers.CharField(max_length=64, required=False, allow_blank=True)
    coupon_code = serializers.CharField(max_length=32, required=False, allow_blank=True)


class PlaceOrderSerializer(serializers.Serializer):
    """
    POST /orders/. The idempotency key is mandatory (FR-CHK-7).

    **The three nullable fields are nullable on purpose, and it is load-bearing.**
    A checkout body always carries all three keys and sets the ones that do not
    apply to `null` -- that is exactly what the frozen contract's canonical
    request shows (docs/api-contract-cart-checkout-orders.md, POST /orders/),
    and it is what `toOrderPayload` in features/checkout/schemas.js sends:
    a guest, or anyone typing a fresh address, sends `address_id: null`; a
    signed-in shopper picking a saved address sends `shipping_address: null`;
    and everybody without a coupon sends `coupon_code: null`.

    Without `allow_null` those three were `required=False` but not nullable, so
    DRF answered every single one of them with 400 "This field may not be
    null." -- which meant no order could be placed from the storefront at all,
    by anyone, ever. It went unnoticed because the API tests build their
    payloads by *omitting* the keys they do not need, and omission and null are
    different things to DRF. Do not drop `allow_null` again without changing
    the contract and the client with it.

    `validate()` below still refuses a body that names no address either way,
    so "nullable" never means "optional in effect".
    """

    idempotency_key = serializers.CharField(max_length=64)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    shipping_address = ShippingAddressInputSerializer(required=False, allow_null=True)
    address_id = serializers.IntegerField(required=False, min_value=1, allow_null=True)
    save_address = serializers.BooleanField(required=False, default=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    items = BasketItemInputSerializer(many=True, required=False)
    coupon_code = serializers.CharField(
        max_length=32, required=False, allow_blank=True, allow_null=True
    )
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("address_id") and not attrs.get("shipping_address"):
            raise serializers.ValidationError(
                {"shipping_address": "A shipping address is required."}
            )
        return attrs


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


# ---------------------------------------------------------------------------
# Quote output
# ---------------------------------------------------------------------------
class QuoteLineSerializer(serializers.Serializer):
    """
    A priced line, exactly as it would be snapshotted onto an order, plus the
    availability the cart and checkout render it with.

    Flat, not nested: this is the same line shape the cart page and the
    checkout review list read, and one shape means one renderer.
    """

    variant_id = serializers.IntegerField(source="variant.id", read_only=True)
    product_id = serializers.IntegerField(source="variant.product_id", read_only=True)
    product_name = serializers.CharField(read_only=True)
    product_slug = serializers.CharField(source="variant.product.slug", read_only=True)
    variant_label = serializers.CharField(read_only=True)
    sku = serializers.CharField(read_only=True)
    image = serializers.SerializerMethodField()
    unit_price = serializers.DecimalField(**MONEY_KWARGS)
    quantity = serializers.IntegerField(read_only=True)
    line_total = serializers.DecimalField(**MONEY_KWARGS)
    available_stock = serializers.IntegerField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)
    issue = serializers.CharField(read_only=True, allow_null=True)

    def get_image(self, obj):
        # A URL string, not an object: every consumer feeds it straight to an
        # <img src>.
        image = variant_image(obj.variant)
        return image["url"] if image else None


class QuoteSerializer(serializers.Serializer):
    """
    The server's answer to "what does this cost?" -- the only totals the
    checkout page may display (FR-CRT-4).

    Shaped by docs/api-contract-cart-checkout-orders.md. Two things in here
    are load-bearing rather than cosmetic:

    * Before a district is known, `zone`, `shipping_total`, `tax_total` and
      `grand_total` are **null**, not "0.00". A zero grand total renders as a
      free order; null renders as "calculated at checkout".
    * `can_place_order` is the server's verdict, so the client blocks on a
      flag instead of re-deriving the rule and disagreeing with placement.

    The serialiser computes none of this -- it reads a `Quote` built by
    apps/orders/services/checkout.py.
    """

    currency = serializers.SerializerMethodField()
    lines = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    discount_total = serializers.SerializerMethodField()
    shipping_total = serializers.SerializerMethodField()
    tax_rate_applied = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    prices_include_tax = serializers.SerializerMethodField()
    grand_total = serializers.SerializerMethodField()
    total_weight_grams = serializers.SerializerMethodField()
    zone = serializers.SerializerMethodField()
    free_shipping_applied = serializers.SerializerMethodField()
    coupon = serializers.SerializerMethodField()
    coupon_error = serializers.SerializerMethodField()
    payment_methods = serializers.SerializerMethodField()
    notices = serializers.SerializerMethodField()
    can_place_order = serializers.BooleanField(read_only=True)

    # `obj` is a checkout.Quote; its Totals carries every figure.
    @staticmethod
    def _totals(obj):
        return obj.totals

    def get_currency(self, obj):
        return CURRENCY

    def get_lines(self, obj):
        return QuoteLineSerializer(obj.totals.lines, many=True).data

    def get_item_count(self, obj):
        return obj.totals.item_count

    def get_subtotal(self, obj):
        return str(obj.totals.subtotal)

    def get_discount_total(self, obj):
        return str(obj.totals.discount_total)

    def get_total_weight_grams(self, obj):
        return obj.totals.total_weight_grams

    def get_prices_include_tax(self, obj):
        return bool(obj.totals.tax_inclusive)

    def get_free_shipping_applied(self, obj):
        return bool(obj.totals.free_shipping_applied)

    # --- Figures that only exist once delivery is known --------------------
    def get_shipping_total(self, obj):
        return str(obj.totals.shipping_total) if obj.totals.shipping_known else None

    def get_tax_total(self, obj):
        return str(obj.totals.tax_total) if obj.totals.shipping_known else None

    def get_tax_rate_applied(self, obj):
        return str(obj.totals.tax_rate) if obj.totals.shipping_known else None

    def get_grand_total(self, obj):
        return str(obj.totals.grand_total) if obj.totals.shipping_known else None

    def get_zone(self, obj):
        zone = obj.totals.zone
        return ShippingZoneSerializer(zone).data if zone else None

    # --- Coupon ------------------------------------------------------------
    def get_coupon(self, obj):
        coupon = obj.totals.coupon
        if coupon is None:
            return None
        return {
            "code": coupon.code,
            "discount_type": coupon.discount_type,
            "discount_total": str(obj.totals.discount_total),
        }

    def get_coupon_error(self, obj):
        return obj.coupon_error

    # --- Server verdicts ---------------------------------------------------
    def get_payment_methods(self, obj):
        return [
            {
                "code": option["method"],
                "label": option["label"],
                "available": option["available"],
                "unavailable_code": option["unavailable_code"],
                "unavailable_reason": option["unavailable_reason"],
            }
            for option in obj.payment_options
        ]

    def get_notices(self, obj):
        return list(obj.notices)


# ---------------------------------------------------------------------------
# Order output
# ---------------------------------------------------------------------------
class OrderItemSerializer(serializers.ModelSerializer):
    unit_price = serializers.DecimalField(**MONEY_KWARGS)
    line_total = serializers.DecimalField(**MONEY_KWARGS)
    product_slug = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product_name",
            "variant_label",
            "sku",
            "unit_price",
            "quantity",
            "line_total",
            "variant_id",
            "product_slug",
        ]

    def get_product_slug(self, obj):
        # Null once the variant is gone from the catalogue. The snapshot above
        # still describes what was bought.
        return obj.variant.product.slug if obj.variant_id else None


class OrderStatusLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatusLog
        fields = ["from_status", "to_status", "actor_role", "note", "created_at"]


class OrderListSerializer(serializers.ModelSerializer):
    """The order-history row."""

    items = OrderItemSerializer(many=True, read_only=True)
    item_count = serializers.SerializerMethodField()
    grand_total = serializers.DecimalField(**MONEY_KWARGS)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    can_cancel = serializers.BooleanField(source="can_customer_cancel", read_only=True)
    currency = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "reference",
            "status",
            "status_label",
            "payment_method",
            "placed_at",
            "grand_total",
            "currency",
            "item_count",
            "can_cancel",
            "items",
        ]

    def get_item_count(self, obj):
        return sum(item.quantity for item in obj.items.all())

    def get_currency(self, obj):
        return CURRENCY


class OrderDetailSerializer(OrderListSerializer):
    """Order detail plus the status timeline (FR-ORD-5)."""

    shipping_address = serializers.SerializerMethodField()
    timeline = OrderStatusLogSerializer(source="status_logs", many=True, read_only=True)
    shipment = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    coupon_code = serializers.SerializerMethodField()
    shipping_zone = serializers.SerializerMethodField()
    subtotal = serializers.DecimalField(**MONEY_KWARGS)
    discount_total = serializers.DecimalField(**MONEY_KWARGS)
    shipping_total = serializers.DecimalField(**MONEY_KWARGS)
    tax_total = serializers.DecimalField(**MONEY_KWARGS)
    tax_rate_applied = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True
    )

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + [
            "email",
            "phone",
            "note",
            "shipping_address",
            "shipping_zone",
            "coupon_code",
            "subtotal",
            "discount_total",
            "shipping_total",
            "tax_rate_applied",
            "tax_total",
            "payment_status",
            "shipment",
            "timeline",
        ]

    def get_shipping_address(self, obj):
        return {
            "recipient_name": obj.ship_recipient_name,
            "phone": obj.ship_phone,
            "division": obj.ship_division,
            "district": obj.ship_district,
            "upazila": obj.ship_upazila,
            "area": obj.ship_area,
            "street": obj.ship_street,
            "postcode": obj.ship_postcode,
        }

    def get_shipping_zone(self, obj):
        return obj.zone.name if obj.zone_id else None

    def get_coupon_code(self, obj):
        return obj.coupon.code if obj.coupon_id else None

    def get_shipment(self, obj):
        shipment = getattr(obj, "shipment", None)
        if shipment is None:
            return None
        return {
            "courier_name": shipment.courier_name,
            "tracking_number": shipment.tracking_number,
            "shipped_at": shipment.shipped_at,
            "delivered_at": shipment.delivered_at,
        }

    def get_payment_status(self, obj):
        # Null until apps/payments writes a Payment row (week 4). A COD order
        # never has one -- the courier collects.
        payment = getattr(obj, "payment", None)
        return payment.status if payment is not None else None
