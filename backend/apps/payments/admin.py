from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "method", "amount", "currency", "status", "created_at", "confirmed_at")
    list_filter = ("status", "method")
    search_fields = ("order__reference", "gateway_txn_id")
    # The gateway response is evidence for reconciliation and disputes; it is
    # read here, never edited.
    readonly_fields = ("raw_response", "gateway_txn_id", "session_key", "created_at", "confirmed_at")

    def has_delete_permission(self, request, obj=None):
        return False
