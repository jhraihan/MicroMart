from django.contrib import admin

from .models import Coupon, CouponRedemption


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "value", "min_order_value", "valid_from", "valid_until", "is_active", "redemption_count")
    list_filter = ("discount_type", "scope_type", "is_active")
    search_fields = ("code",)


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "coupon", "user", "order", "discount_amount")
    search_fields = ("coupon__code", "order__reference", "user__email")

    def has_add_permission(self, request):
        return False
