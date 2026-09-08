"""
Admin payload shapes (PRD 7.3).

Nothing here computes anything. Every figure is read off a dict built by
apps/dashboard/services/ or off an Order row, and money is a
`DecimalField`, which DRF's COERCE_DECIMAL_TO_STRING renders as a decimal
string. A float would be one arithmetic step away from reporting revenue of
284059.99999999994.

The order serializers subclass the storefront's rather than restating them.
An order detail is a snapshot, and there must be exactly one description of
how that snapshot is rendered -- the admin additions here are the customer
identity and the transitions the state machine would currently accept, both
of which a shopper has no business seeing.
"""
from rest_framework import serializers

from apps.orders.models import Actor, Order, OrderStatus
from apps.orders.serializers import OrderDetailSerializer, OrderItemSerializer

from .models import StoreSettings

MONEY = {"max_digits": 16, "decimal_places": 2, "read_only": True}
CURRENCY = "BDT"


# ---------------------------------------------------------------------------
# Dashboard (US-A1)
# ---------------------------------------------------------------------------
class MetricWindowSerializer(serializers.Serializer):
    revenue = serializers.DecimalField(**MONEY)
    orders = serializers.IntegerField(read_only=True)
    average_order_value = serializers.DecimalField(**MONEY)


class TrendPointSerializer(serializers.Serializer):
    date = serializers.DateField(read_only=True)
    revenue = serializers.DecimalField(**MONEY)
    orders = serializers.IntegerField(read_only=True)


class AwaitingActionSerializer(serializers.Serializer):
    total = serializers.IntegerField(read_only=True)
    pending = serializers.IntegerField(read_only=True)
    confirmed = serializers.IntegerField(read_only=True)
    packed = serializers.IntegerField(read_only=True)


class DashboardSerializer(serializers.Serializer):
    """
    GET /admin/dashboard/.

    `revenue_statuses` is published deliberately: the number is only
    interpretable next to the definition of what it counts, and an admin
    asking "why is that lower than my sales report" deserves the answer in the
    payload rather than in a code comment.
    """

    generated_at = serializers.DateTimeField(read_only=True)
    currency = serializers.CharField(read_only=True)
    revenue_statuses = serializers.ListField(
        child=serializers.CharField(), read_only=True
    )
    today = MetricWindowSerializer(read_only=True)
    last_7_days = MetricWindowSerializer(read_only=True)
    last_30_days = MetricWindowSerializer(read_only=True)
    trend_days = serializers.IntegerField(read_only=True)
    trend = TrendPointSerializer(many=True, read_only=True)
    orders_awaiting_action = AwaitingActionSerializer(read_only=True)
    low_stock_count = serializers.IntegerField(read_only=True)


# ---------------------------------------------------------------------------
# Orders (US-A3, US-T1)
# ---------------------------------------------------------------------------
class AdminOrderCustomerMixin:
    """Who placed it -- the one thing an admin list needs that a shopper's does not."""

    def get_customer(self, obj):
        return {
            "id": obj.user_id,
            "name": obj.user.full_name if obj.user_id else obj.ship_recipient_name,
            "email": obj.email,
            "phone": obj.phone,
            # A guest checkout has no account behind it (FR-CHK-5), and the
            # support agent on the phone needs to know that before asking the
            # caller to "log in and check".
            "is_guest": obj.user_id is None,
        }


class AdminOrderListSerializer(AdminOrderCustomerMixin, serializers.ModelSerializer):
    """A row in GET /admin/orders/."""

    customer = serializers.SerializerMethodField()
    items = OrderItemSerializer(many=True, read_only=True)
    item_count = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    grand_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    currency = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()
    has_shipment = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "reference",
            "status",
            "status_label",
            "payment_method",
            "placed_at",
            "updated_at",
            "grand_total",
            "currency",
            "item_count",
            "customer",
            "allowed_transitions",
            "has_shipment",
            "items",
        ]

    def get_item_count(self, obj):
        return sum(item.quantity for item in obj.items.all())

    def get_currency(self, obj):
        return CURRENCY

    def get_allowed_transitions(self, obj):
        # Straight off the state machine, so the admin UI offers exactly the
        # buttons the server would accept. It is a convenience, never the
        # control: POSTing an unlisted status is still refused with 422.
        return obj.allowed_transitions(actor=Actor.ADMIN)

    def get_has_shipment(self, obj):
        return getattr(obj, "shipment", None) is not None


class AdminStatusLogSerializer(serializers.Serializer):
    """
    US-A3: every status change is logged "with actor and timestamp", so the
    admin timeline names the actor. The customer's timeline deliberately does
    not -- it shows the role, not which member of staff.
    """

    from_status = serializers.CharField(read_only=True)
    to_status = serializers.CharField(read_only=True)
    actor_role = serializers.CharField(read_only=True)
    actor_email = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()
    note = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def get_actor_email(self, obj):
        return obj.actor.email if obj.actor_id else None

    def get_actor_name(self, obj):
        return obj.actor.full_name if obj.actor_id else None


class AdminOrderDetailSerializer(AdminOrderCustomerMixin, OrderDetailSerializer):
    """GET /admin/orders/{reference}/ -- the shopper's detail plus the admin's extras."""

    customer = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()
    timeline = AdminStatusLogSerializer(source="status_logs", many=True, read_only=True)

    class Meta(OrderDetailSerializer.Meta):
        fields = OrderDetailSerializer.Meta.fields + [
            "customer",
            "allowed_transitions",
            "updated_at",
        ]

    def get_allowed_transitions(self, obj):
        return obj.allowed_transitions(actor=Actor.ADMIN)


class OrderStatusUpdateSerializer(serializers.Serializer):
    """
    POST /admin/orders/{reference}/status/.

    `status` is validated against the enum here so an unknown *string* is a
    400 field error; whether a known status is a *legal* next step is the
    state machine's call, and it answers 422.
    """

    status = serializers.ChoiceField(choices=OrderStatus.choices)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


class ShipmentInputSerializer(serializers.Serializer):
    """POST /admin/orders/{reference}/shipment/ (FR-ORD-7)."""

    courier_name = serializers.CharField(max_length=120)
    tracking_number = serializers.CharField(max_length=120)


class ShipmentSerializer(serializers.Serializer):
    courier_name = serializers.CharField(read_only=True)
    tracking_number = serializers.CharField(read_only=True)
    shipped_at = serializers.DateTimeField(read_only=True)
    delivered_at = serializers.DateTimeField(read_only=True)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
class AdminCustomerSerializer(serializers.Serializer):
    """A row in GET /admin/customers/, annotated by the customers service."""

    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    date_joined = serializers.DateTimeField(read_only=True)
    order_count = serializers.IntegerField(read_only=True)
    paid_order_count = serializers.IntegerField(read_only=True)
    lifetime_value = serializers.DecimalField(**MONEY)
    last_order_at = serializers.DateTimeField(read_only=True)
    currency = serializers.SerializerMethodField()

    def get_currency(self, obj):
        return CURRENCY


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class StoreSettingsSerializer(serializers.ModelSerializer):
    """
    GET / PATCH /admin/settings/.

    Deliberately has no `id`: there is one store, and exposing a primary key
    invites a client to think there could be a second.
    """

    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    cod_max_order_value = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True, allow_null=True
    )

    class Meta:
        model = StoreSettings
        fields = [
            "store_name",
            "support_email",
            "support_phone",
            "tax_rate",
            "tax_inclusive_pricing",
            "cod_enabled",
            "cod_max_order_value",
            "low_stock_digest_recipients",
            "updated_at",
        ]
        read_only_fields = fields


class StoreSettingsUpdateSerializer(serializers.Serializer):
    """
    The writable half. Every field is optional -- PATCH is a partial update --
    and the *values* are validated in the service, so a management command
    setting the VAT rate is held to the same rules as this endpoint.
    """

    store_name = serializers.CharField(max_length=120, required=False)
    support_email = serializers.EmailField(required=False, allow_blank=True)
    support_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    tax_inclusive_pricing = serializers.BooleanField(required=False)
    cod_enabled = serializers.BooleanField(required=False)
    cod_max_order_value = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    low_stock_digest_recipients = serializers.ListField(
        child=serializers.CharField(), required=False
    )
