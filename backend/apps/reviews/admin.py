from django.contrib import admin

from .models import Review, WishlistItem


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "rating", "status", "created_at", "moderated_at")
    list_filter = ("status", "rating")
    search_fields = ("product__name", "user__email", "title", "body")
    # Moderation goes through the review service so rating_avg / rating_count
    # are recomputed. Flipping `status` here would leave them stale.
    readonly_fields = ("status", "moderated_at", "moderated_by")


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "created_at")
    search_fields = ("user__email", "product__name")
