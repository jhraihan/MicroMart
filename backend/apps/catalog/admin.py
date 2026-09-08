"""
Django Admin registrations.

This is the operational safety net from PRD §12.2, enabled from week 1 so
fulfilment is never blocked if the React dashboard slips. The React dashboard
remains the product; this is the fallback.
"""
from django.contrib import admin

from .models import (
    Brand,
    Category,
    InventoryLog,
    Product,
    ProductImage,
    ProductSpec,
    ProductVariant,
)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ("sku", "option_label", "price", "compare_at_price", "stock",
              "low_stock_threshold", "weight_grams", "is_active")


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ("image", "variant", "alt_text", "sort_order", "is_primary")


class ProductSpecInline(admin.TabularInline):
    model = ProductSpec
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "sort_order", "is_active")
    list_filter = ("is_active", "parent")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "brand", "is_active", "rating_avg", "rating_count")
    list_filter = ("is_active", "category", "brand")
    search_fields = ("name", "slug", "variants__sku")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("rating_avg", "rating_count")
    inlines = [ProductVariantInline, ProductImageInline, ProductSpecInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("category", "brand")


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("sku", "product", "option_label", "price", "stock", "is_active")
    list_filter = ("is_active",)
    search_fields = ("sku", "product__name")
    # Stock is edited through the inventory service so every movement is
    # logged. Editing it here would bypass InventoryLog.
    readonly_fields = ("stock",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product")


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "variant", "delta", "reason", "actor", "order")
    list_filter = ("reason",)
    search_fields = ("variant__sku", "note")
    date_hierarchy = "created_at"

    # Append-only: readable, never editable or deletable.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
