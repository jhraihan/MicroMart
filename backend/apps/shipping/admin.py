from django.contrib import admin

from .models import ShippingZone


@admin.register(ShippingZone)
class ShippingZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "flat_rate", "per_kg_rate", "free_shipping_threshold", "cod_allowed", "is_active")
    list_filter = ("is_active", "cod_allowed")
