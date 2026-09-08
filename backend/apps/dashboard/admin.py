from django.contrib import admin

from .models import StoreSettings


@admin.register(StoreSettings)
class StoreSettingsAdmin(admin.ModelAdmin):
    list_display = ("store_name", "tax_rate", "cod_enabled", "cod_max_order_value")

    def has_add_permission(self, request):
        # Singleton: exactly one store.
        return not StoreSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
