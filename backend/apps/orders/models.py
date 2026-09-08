"""
Order entities (PRD §6.3) and the status state machine (PRD §15.1).

Two rules dominate this module:

1. Order data is snapshotted, not referenced. OrderItem copies the product
   name, variant label, SKU and unit price; the shipping address is copied onto
   the order rather than FK'd to the address book; the tax rate applied is
   copied too. Later catalogue, address or tax-rate edits must never rewrite
   historical orders.
2. Status changes go through TRANSITIONS. Anything not listed there is rejected
   with 422 and is not logged as a state change.
"""
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.fields import MoneyField
from apps.common.models import TimeStampedModel


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    PACKED = "packed", "Packed"
    SHIPPED = "shipped", "Shipped"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"


class PaymentMethod(models.TextChoices):
    COD = "cod", "Cash on Delivery"
    ONLINE = "online", "Online (SSLCommerz)"


TERMINAL_STATUSES = frozenset(
    {OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
)


class Actor(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    ADMIN = "admin", "Admin or staff"
    SYSTEM = "system", "System"


# The complete, authoritative transition table (PRD §15.1). Each entry maps a
# legal (from, to) pair to the actors permitted to perform it and whether the
# transition moves stock. Any pair absent from this map is illegal.
TRANSITIONS = {
    (OrderStatus.PENDING, OrderStatus.CONFIRMED): {
        "actors": {Actor.CUSTOMER, Actor.ADMIN, Actor.SYSTEM},
        "stock": "decrement",
    },
    (OrderStatus.PENDING, OrderStatus.CANCELLED): {
        # Stock was never decremented on a pending order, so nothing to restore.
        "actors": {Actor.CUSTOMER, Actor.ADMIN},
        "stock": None,
    },
    (OrderStatus.CONFIRMED, OrderStatus.PACKED): {
        "actors": {Actor.ADMIN},
        "stock": None,
    },
    (OrderStatus.CONFIRMED, OrderStatus.CANCELLED): {
        "actors": {Actor.CUSTOMER, Actor.ADMIN},
        "stock": "restore",
    },
    (OrderStatus.PACKED, OrderStatus.SHIPPED): {
        "actors": {Actor.ADMIN},
        "stock": None,
        "requires_shipment": True,
    },
    (OrderStatus.PACKED, OrderStatus.CANCELLED): {
        "actors": {Actor.ADMIN},
        "stock": "restore",
    },
    (OrderStatus.SHIPPED, OrderStatus.DELIVERED): {
        "actors": {Actor.ADMIN},
        "stock": None,
    },
    (OrderStatus.SHIPPED, OrderStatus.CANCELLED): {
        # Failed delivery or COD refusal.
        "actors": {Actor.ADMIN},
        "stock": "restore",
    },
    (OrderStatus.DELIVERED, OrderStatus.REFUNDED): {
        # Manual record only -- no gateway call in v1.
        "actors": {Actor.ADMIN},
        "stock": None,
    },
}

# Customers may cancel only while the order has not shipped.
CUSTOMER_CANCELLABLE = frozenset({OrderStatus.PENDING, OrderStatus.CONFIRMED})


class Order(models.Model):
    reference = models.CharField(max_length=24, unique=True, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
        help_text="Null for guest checkout.",
    )
    email = models.EmailField()
    phone = models.CharField(max_length=20)

    # --- Shipping address, copied verbatim at placement. Never a FK. ---
    ship_recipient_name = models.CharField(max_length=150)
    ship_phone = models.CharField(max_length=20)
    ship_division = models.CharField(max_length=64)
    ship_district = models.CharField(max_length=64)
    ship_upazila = models.CharField(max_length=64, blank=True)
    ship_area = models.CharField(max_length=128, blank=True)
    ship_street = models.CharField(max_length=255)
    ship_postcode = models.CharField(max_length=12, blank=True)

    zone = models.ForeignKey(
        "shipping.ShippingZone",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    coupon = models.ForeignKey(
        "promotions.Coupon",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )

    # --- Money. Every figure is computed server-side (PRD §5.4). ---
    subtotal = MoneyField(default=0, validators=[MinValueValidator(0)])
    discount_total = MoneyField(default=0, validators=[MinValueValidator(0)])
    shipping_total = MoneyField(default=0, validators=[MinValueValidator(0)])
    tax_total = MoneyField(default=0, validators=[MinValueValidator(0)])
    tax_rate_applied = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Snapshotted percentage. A later rate change must not alter this order.",
    )
    grand_total = MoneyField(default=0, validators=[MinValueValidator(0)])

    payment_method = models.CharField(max_length=16, choices=PaymentMethod.choices)
    status = models.CharField(
        max_length=16, choices=OrderStatus.choices, default=OrderStatus.PENDING
    )
    note = models.TextField(blank=True)

    idempotency_key = models.CharField(
        max_length=64,
        unique=True,
        help_text="Client-generated. Stops a double-submit becoming two orders.",
    )
    placed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_order"
        ordering = ["-placed_at"]
        indexes = [
            models.Index(fields=["user", "-placed_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["status", "-placed_at"]),
        ]

    def __str__(self):
        return self.reference

    @property
    def is_terminal(self):
        return self.status in TERMINAL_STATUSES

    @property
    def can_customer_cancel(self):
        return self.status in CUSTOMER_CANCELLABLE

    @property
    def total_weight_grams(self):
        return sum(
            (item.variant.weight_grams if item.variant else 0) * item.quantity
            for item in self.items.all()
        )

    def allowed_transitions(self, actor=Actor.ADMIN):
        return [
            to_status
            for (frm, to_status), rule in TRANSITIONS.items()
            if frm == self.status and actor in rule["actors"]
        ]


class OrderItem(models.Model):
    """
    A full snapshot of what was bought. The variant FK exists only for
    analytics -- the order still reads correctly if the variant is later
    deleted, which is why it is ON DELETE SET NULL.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=255)
    variant_label = models.CharField(max_length=120, blank=True)
    sku = models.CharField(max_length=64)
    unit_price = MoneyField(validators=[MinValueValidator(0)])
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    line_total = MoneyField(validators=[MinValueValidator(0)])

    class Meta:
        db_table = "orders_order_item"
        ordering = ["id"]
        indexes = [models.Index(fields=["order"])]

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"


class OrderStatusLog(models.Model):
    """Append-only audit trail. Never updated, never deleted."""

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="status_logs"
    )
    from_status = models.CharField(
        max_length=16, choices=OrderStatus.choices, blank=True
    )
    to_status = models.CharField(max_length=16, choices=OrderStatus.choices)
    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_status_logs",
    )
    actor_role = models.CharField(
        max_length=16, choices=Actor.choices, default=Actor.SYSTEM
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "orders_order_status_log"
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["order", "created_at"])]

    def __str__(self):
        return f"{self.order_id}: {self.from_status} -> {self.to_status}"


class Shipment(TimeStampedModel):
    """One shipment per order in v1 -- no split shipments, no courier API."""

    order = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name="shipment"
    )
    courier_name = models.CharField(max_length=120)
    tracking_number = models.CharField(max_length=120)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orders_shipment"

    def __str__(self):
        return f"{self.courier_name} {self.tracking_number}"
