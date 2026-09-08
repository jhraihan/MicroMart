"""
Order admin -- the PRD §12.2 fallback for fulfilment.

Status is read-only here on purpose. Changing it must go through the order
service so the transition is validated against the state machine, the stock
movement happens, and an OrderStatusLog row is written. A dropdown that wrote
`status` directly would silently skip all three.
"""
from django.contrib import admin

from .models import Order, OrderItem, OrderStatusLog, Shipment


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = (
        "variant", "product_name", "variant_label", "sku",
        "unit_price", "quantity", "line_total",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class OrderStatusLogInline(admin.TabularInline):
    model = OrderStatusLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "actor", "actor_role", "note", "created_at")
    can_delete = False
    ordering = ("created_at",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "placed_at", "email", "status", "payment_method", "grand_total",
    )
    list_filter = ("status", "payment_method", "placed_at")
    search_fields = ("reference", "email", "phone", "ship_recipient_name")
    date_hierarchy = "placed_at"
    inlines = [OrderItemInline, OrderStatusLogInline]
    readonly_fields = (
        "reference", "status", "subtotal", "discount_total", "shipping_total",
        "tax_total", "tax_rate_applied", "grand_total", "idempotency_key",
        "placed_at", "updated_at",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "zone", "coupon")

    def has_delete_permission(self, request, obj=None):
        # Order history is never deleted -- cancel or refund it instead.
        return False


@admin.register(OrderStatusLog)
class OrderStatusLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "order", "from_status", "to_status", "actor", "actor_role")
    list_filter = ("to_status", "actor_role")
    search_fields = ("order__reference",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("order", "courier_name", "tracking_number", "shipped_at", "delivered_at")
    search_fields = ("order__reference", "tracking_number")
