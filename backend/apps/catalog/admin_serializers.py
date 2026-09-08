"""
Serializers for the admin catalogue surface (PRD 7.3, US-A2/US-A4).

Split from serializers.py on purpose. That module is the *frozen* storefront
contract in docs/api-contract-catalogue.md; this one shows an admin things a
shopper must never see -- inactive rows, raw stock, thresholds, SKUs of
withdrawn variants -- and the two shapes have no reason to move together.

Every write serializer here is a plain `Serializer`, not a `ModelSerializer`.
That is deliberate: a ModelSerializer would quietly attach a UniqueValidator to
`sku` and a unique-slug validator to `slug`, and those rules would then be
enforced in two places with two different error codes depending on which
surface you came in through. Uniqueness, nesting depth, "keep one variant" and
"stock is not writable" all belong to services/administration.py, so these
classes do parsing and per-field type validation and nothing else.
"""
from rest_framework import serializers

from .models import (
    Brand,
    Category,
    Product,
    ProductImage,
    ProductSpec,
    ProductVariant,
)
from .serializers import media_url
from .services.administration import MANUAL_ADJUSTMENT_REASONS

MONEY = {"max_digits": 12, "decimal_places": 2}


def _active_variants(product):
    """Prefetched, so this costs no query -- see administration.admin_products."""
    return [row for row in product.variants.all() if row.is_active]


# ---------------------------------------------------------------------------
# Taxonomy -- read
# ---------------------------------------------------------------------------
class AdminCategorySerializer(serializers.ModelSerializer):
    parent_id = serializers.IntegerField(read_only=True, allow_null=True)
    parent_name = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    product_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "parent_id",
            "parent_name",
            "image",
            "sort_order",
            "is_active",
            "product_count",
        ]

    def get_parent_name(self, obj):
        return obj.parent.name if obj.parent_id else None

    def get_image(self, obj):
        return media_url(obj.image)


class AdminBrandSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()
    product_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Brand
        fields = ["id", "name", "slug", "logo", "is_active", "product_count"]

    def get_logo(self, obj):
        return media_url(obj.logo)


# ---------------------------------------------------------------------------
# Taxonomy -- write
# ---------------------------------------------------------------------------
class AdminCategoryWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=140, required=False, allow_blank=True)
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    sort_order = serializers.IntegerField(required=False, min_value=0)
    is_active = serializers.BooleanField(required=False)
    image = serializers.ImageField(required=False, allow_null=True)


class AdminCategoryPatchSerializer(AdminCategoryWriteSerializer):
    name = serializers.CharField(max_length=120, required=False)


class AdminBrandWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=140, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    logo = serializers.ImageField(required=False, allow_null=True)


class AdminBrandPatchSerializer(AdminBrandWriteSerializer):
    name = serializers.CharField(max_length=120, required=False)


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------
class AdminVariantSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_slug = serializers.CharField(source="product.slug", read_only=True)
    product_is_active = serializers.BooleanField(
        source="product.is_active", read_only=True
    )
    price = serializers.DecimalField(read_only=True, **MONEY)
    compare_at_price = serializers.DecimalField(
        read_only=True, allow_null=True, **MONEY
    )
    discount_percent = serializers.IntegerField(read_only=True)
    in_stock = serializers.BooleanField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "product_id",
            "product_name",
            "product_slug",
            "product_is_active",
            "sku",
            "option_label",
            "price",
            "compare_at_price",
            "discount_percent",
            # Reported, never accepted: see AdminVariantUpdateSerializer.
            "stock",
            "low_stock_threshold",
            "in_stock",
            "is_low_stock",
            "weight_grams",
            "is_active",
        ]
        read_only_fields = fields


class VariantInputSerializer(serializers.Serializer):
    """
    One variant as the product form sends it (US-A2: independent price, SKU and
    stock per variant).

    `stock` is an *opening* quantity only. It is written through the inventory
    ledger by services.administration.create_variant, never assigned to the
    column, so a variant that starts at 12 has a +12 InventoryLog row behind it.
    """

    sku = serializers.CharField(max_length=64)
    option_label = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    # No `min_value` here, deliberately. A negative price has to be refused by
    # services.administration._assert_price_sane so the error names `price`:
    # inside a nested `variants` list the envelope in config/exceptions.py can
    # only report the outermost key, and "variants: ensure this value is
    # greater than or equal to 0" does not tell the form which input to mark.
    price = serializers.DecimalField(**MONEY)
    compare_at_price = serializers.DecimalField(
        required=False, allow_null=True, **MONEY
    )
    stock = serializers.IntegerField(required=False, min_value=0)
    low_stock_threshold = serializers.IntegerField(required=False, min_value=0)
    weight_grams = serializers.IntegerField(required=False, min_value=0)
    is_active = serializers.BooleanField(required=False)


class AdminVariantCreateSerializer(VariantInputSerializer):
    product_id = serializers.IntegerField()


class AdminVariantUpdateSerializer(serializers.Serializer):
    """
    PATCH /admin/variants/{id}/.

    `stock` is declared here **so that it reaches the service and is refused
    there**, rather than being dropped by an unknown-field filter. A dropped
    key answers 200 and moves nothing, which is the worst of the three possible
    behaviours: the admin reads success and stops checking. The service raises
    STOCK_NOT_WRITABLE and points at /admin/inventory/adjust/.
    """

    sku = serializers.CharField(max_length=64, required=False)
    option_label = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    price = serializers.DecimalField(required=False, **MONEY)
    compare_at_price = serializers.DecimalField(
        required=False, allow_null=True, **MONEY
    )
    stock = serializers.IntegerField(required=False)
    low_stock_threshold = serializers.IntegerField(required=False, min_value=0)
    weight_grams = serializers.IntegerField(required=False, min_value=0)
    is_active = serializers.BooleanField(required=False)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
class AdminProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    variant_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = ProductImage
        fields = ["id", "url", "alt_text", "variant_id", "sort_order", "is_primary"]
        read_only_fields = fields

    def get_url(self, obj):
        return media_url(obj.image)


class ProductImageUploadSerializer(serializers.Serializer):
    """
    Multipart upload. `ImageField` opens the file with Pillow, so a text file
    renamed to .jpg is refused here as a field error and never reaches storage;
    the size cap is catalogue policy and lives in the service.
    """

    image = serializers.ImageField()
    alt_text = serializers.CharField(max_length=255, required=False, allow_blank=True)
    variant_id = serializers.IntegerField(required=False, allow_null=True)
    is_primary = serializers.BooleanField(required=False, default=False)
    sort_order = serializers.IntegerField(required=False, min_value=0)


class ProductImageReorderSerializer(serializers.Serializer):
    """
    Manual ordering. `order` is the complete list of this product's image ids in
    the sequence they should render; `primary_id` optionally moves the primary
    flag in the same call. Omitting `primary_id` leaves the primary exactly
    where it was -- reordering does not reassign it.
    """

    order = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    primary_id = serializers.IntegerField(required=False, allow_null=True)


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------
class AdminSpecSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSpec
        fields = ["key", "value", "sort_order"]


class SpecInputSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=120)
    value = serializers.CharField(max_length=500)
    sort_order = serializers.IntegerField(required=False, min_value=0)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
class AdminProductListSerializer(serializers.ModelSerializer):
    """
    A row of the admin catalogue table.

    Everything derived here reads prefetched variants and annotated counts, so
    the page costs the same number of queries whether it holds one product or
    a hundred.
    """

    category = serializers.SerializerMethodField()
    brand = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    price_min = serializers.SerializerMethodField()
    price_max = serializers.SerializerMethodField()
    total_stock = serializers.SerializerMethodField()
    has_low_stock = serializers.SerializerMethodField()
    variant_count = serializers.IntegerField(read_only=True, default=0)
    active_variant_count = serializers.IntegerField(read_only=True, default=0)
    image_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "slug",
            "category",
            "brand",
            "primary_image",
            "price_min",
            "price_max",
            "total_stock",
            "has_low_stock",
            "variant_count",
            "active_variant_count",
            "image_count",
            "is_active",
            "rating_avg",
            "rating_count",
            "created_at",
            "updated_at",
        ]

    def get_category(self, obj):
        return {"id": obj.category_id, "name": obj.category.name, "slug": obj.category.slug}

    def get_brand(self, obj):
        if obj.brand_id is None:
            return None
        return {"id": obj.brand_id, "name": obj.brand.name, "slug": obj.brand.slug}

    def get_primary_image(self, obj):
        images = list(obj.images.all())
        if not images:
            return None
        image = next((row for row in images if row.is_primary), images[0])
        return {"id": image.pk, "url": media_url(image.image), "alt_text": image.alt_text}

    def get_price_min(self, obj):
        rows = _active_variants(obj)
        return str(min(row.price for row in rows)) if rows else None

    def get_price_max(self, obj):
        rows = _active_variants(obj)
        return str(max(row.price for row in rows)) if rows else None

    def get_total_stock(self, obj):
        return sum(row.stock for row in _active_variants(obj))

    def get_has_low_stock(self, obj):
        return any(row.stock <= row.low_stock_threshold for row in _active_variants(obj))


class AdminProductDetailSerializer(AdminProductListSerializer):
    variants = AdminVariantSerializer(many=True, read_only=True)
    images = AdminProductImageSerializer(many=True, read_only=True)
    specs = AdminSpecSerializer(many=True, read_only=True)

    class Meta(AdminProductListSerializer.Meta):
        fields = AdminProductListSerializer.Meta.fields + [
            "description",
            "warranty_months",
            "variants",
            "images",
            "specs",
        ]


class AdminProductCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=280, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    category_id = serializers.IntegerField()
    brand_id = serializers.IntegerField(required=False, allow_null=True)
    warranty_months = serializers.IntegerField(required=False, min_value=0)
    is_active = serializers.BooleanField(required=False)
    specs = SpecInputSerializer(many=True, required=False)
    # Required at the serializer level too, so the common mistake gets a plain
    # field error; the service still refuses an empty list, which is the case a
    # non-HTTP caller can reach.
    variants = VariantInputSerializer(many=True)


class AdminProductUpdateSerializer(serializers.Serializer):
    """
    PATCH /admin/products/{id}/ -- the product's own fields and its spec table.

    Variants are absent on purpose. They have their own CRUD endpoint because
    each one owns a price, an SKU and a stock ledger; folding them into a
    product PATCH would mean a partial product save could silently delete a
    variant that an order line still points at.
    """

    name = serializers.CharField(max_length=255, required=False)
    slug = serializers.SlugField(max_length=280, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    category_id = serializers.IntegerField(required=False)
    brand_id = serializers.IntegerField(required=False, allow_null=True)
    warranty_months = serializers.IntegerField(required=False, min_value=0)
    is_active = serializers.BooleanField(required=False)
    specs = SpecInputSerializer(many=True, required=False)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
class InventoryRowSerializer(AdminVariantSerializer):
    """A variant seen as a stock line rather than as a price line."""

    category_name = serializers.CharField(
        source="product.category.name", read_only=True
    )
    brand_name = serializers.SerializerMethodField()

    class Meta(AdminVariantSerializer.Meta):
        fields = AdminVariantSerializer.Meta.fields + ["category_name", "brand_name"]
        read_only_fields = fields

    def get_brand_name(self, obj):
        return obj.product.brand.name if obj.product.brand_id else None


class InventoryAdjustSerializer(serializers.Serializer):
    """
    POST /admin/inventory/adjust/.

    `reason` is required with no default -- FR-INV-8 calls it mandatory, and a
    default would turn every hurried adjustment into the same unhelpful word.
    The choice list excludes the order-driven reasons; only the order state
    machine writes those.
    """

    variant_id = serializers.IntegerField()
    delta = serializers.IntegerField()
    reason = serializers.ChoiceField(
        choices=[choice.value for choice in MANUAL_ADJUSTMENT_REASONS]
    )
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


class InventoryLogSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    delta = serializers.IntegerField(read_only=True)
    reason = serializers.CharField(read_only=True)
    note = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    actor_email = serializers.SerializerMethodField()
    order_reference = serializers.SerializerMethodField()

    def get_actor_email(self, obj):
        return obj.actor.email if obj.actor_id else None

    def get_order_reference(self, obj):
        return obj.order.reference if obj.order_id else None

