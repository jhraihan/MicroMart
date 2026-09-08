"""
Catalogue serializers -- the frozen shapes in docs/api-contract-catalogue.md.

These only translate. Which products exist, what the discount is derived from
and how facets are counted all live in services/catalogue.py; a serializer that
started deciding those things would let the storefront and admin surfaces
drift apart.

Money is DECIMAL(12,2) throughout and DRF is configured with
COERCE_DECIMAL_TO_STRING, so every price leaves as a decimal string.

Media URLs are emitted MEDIA_URL-relative ("/media/...") exactly as the
contract shows them, rather than DRF's default absolute form.
"""
from rest_framework import serializers

from .models import Brand, Category, Product, ProductImage, ProductSpec, ProductVariant
from .services import catalogue

MONEY_KWARGS = {"max_digits": 12, "decimal_places": 2, "read_only": True}


def media_url(file_field):
    """Relative URL for an image field, or None when nothing is attached."""
    if not file_field:
        return None
    try:
        return file_field.url
    except ValueError:  # pragma: no cover -- storage without a resolvable URL
        return None


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
class BrandSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()

    class Meta:
        model = Brand
        fields = ["id", "name", "slug", "logo"]

    def get_logo(self, obj):
        return media_url(obj.logo)


class BrandRefSerializer(serializers.ModelSerializer):
    """The trimmed brand embedded in a product."""

    class Meta:
        model = Brand
        fields = ["id", "name", "slug"]


class CategoryRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class CategorySerializer(serializers.ModelSerializer):
    """
    One node of the category tree. Nesting is one level deep (FR-CAT-1), so a
    child short-circuits to an empty `children` list -- recursing would fire a
    query per child for a branch that can never exist.
    """

    image = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "image", "product_count", "children"]

    def get_image(self, obj):
        return media_url(obj.image)

    def get_product_count(self, obj):
        return self.context.get("product_counts", {}).get(obj.pk, 0)

    def get_children(self, obj):
        if obj.parent_id is not None:
            return []
        return CategorySerializer(
            obj.children.all(), many=True, context=self.context
        ).data


# ---------------------------------------------------------------------------
# Product parts
# ---------------------------------------------------------------------------
class ProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    variant_id = serializers.IntegerField(read_only=True, allow_null=True)
    credit = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = [
            "id", "url", "alt_text", "variant_id", "sort_order", "is_primary",
            "credit",
        ]

    def get_url(self, obj):
        return media_url(obj.image)

    def get_credit(self, obj):
        """
        Author, licence and source for an externally-licensed image.

        Null for the store's own artwork. This is not decoration: CC BY and
        CC BY-SA make displaying the author and licence a *condition* of
        using the image at all, so the client needs it to render a compliant
        page.
        """
        if not obj.source_url:
            return None
        return {
            "attribution": obj.attribution,
            "license": obj.license_name,
            "source_url": obj.source_url,
            # Set by `fetch_media` when the photo shows the right kind of
            # product rather than this exact model.
            "is_representative": obj.alt_text.startswith("Representative image"),
        }


class ProductSpecSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSpec
        fields = ["key", "value", "group"]


class SpecGroupSerializer(serializers.Serializer):
    """
    Specs banded under their group heading.

    Served *alongside* the flat `specs` array rather than replacing it: the
    flat list is in the frozen contract and other clients read it, and
    regrouping it correctly needs the group order, which a flat array loses.
    """

    group = serializers.CharField()
    rows = serializers.ListField(child=serializers.DictField())


class ProductVariantSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(**MONEY_KWARGS)
    compare_at_price = serializers.SerializerMethodField()
    discount_percent = serializers.IntegerField(read_only=True)
    in_stock = serializers.BooleanField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "sku",
            "option_label",
            "price",
            "compare_at_price",
            "discount_percent",
            # An integer, so the quantity selector can cap itself. Reading it
            # reserves nothing -- stock moves only on order confirmation.
            "stock",
            "in_stock",
            "is_low_stock",
            "weight_grams",
            "images",
        ]

    def get_compare_at_price(self, obj):
        # FR-CAT-8: a compare-at that does not exceed the price is not a
        # discount, and must not render as a struck-through original.
        if obj.discount_percent == 0:
            return None
        return str(obj.compare_at_price)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
class ProductListSerializer(serializers.ModelSerializer):
    """
    A product card. Every aggregate here (price_min, price_max, total_stock,
    variant_count, cheapest_compare_at) arrives as a database annotation from
    services.catalogue.annotate_product_aggregates -- nothing walks variants in
    Python, which is what keeps the list inside its p95 budget (PRD 9.1).
    """

    brand = BrandRefSerializer(read_only=True)
    category = CategoryRefSerializer(read_only=True)
    primary_image = serializers.SerializerMethodField()
    price_min = serializers.DecimalField(**MONEY_KWARGS)
    price_max = serializers.DecimalField(**MONEY_KWARGS)
    compare_at_price = serializers.SerializerMethodField()
    discount_percent = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    total_stock = serializers.IntegerField(read_only=True)
    variant_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "slug",
            "brand",
            "category",
            "primary_image",
            "price_min",
            "price_max",
            "compare_at_price",
            "discount_percent",
            "in_stock",
            "total_stock",
            "rating_avg",
            "rating_count",
            "variant_count",
        ]

    def get_primary_image(self, obj):
        images = list(obj.images.all())
        if not images:
            return None
        image = next((item for item in images if item.is_primary), images[0])
        return {"url": media_url(image.image), "alt_text": image.alt_text}

    def get_compare_at_price(self, obj):
        # FR-CAT-8: the badge belongs to the cheapest active variant, which is
        # the same variant price_min reports.
        if catalogue.discount_percent(obj.price_min, obj.cheapest_compare_at) == 0:
            return None
        return str(obj.cheapest_compare_at)

    def get_discount_percent(self, obj):
        return catalogue.discount_percent(obj.price_min, obj.cheapest_compare_at)

    def get_in_stock(self, obj):
        return (obj.total_stock or 0) > 0


class ProductDetailSerializer(ProductListSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    specs = ProductSpecSerializer(many=True, read_only=True)
    spec_groups = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, read_only=True)
    component = serializers.SerializerMethodField()

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + [
            "description",
            "model_number",
            "highlights",
            "warranty_months",
            "images",
            "specs",
            "spec_groups",
            "variants",
            "component",
        ]

    def get_spec_groups(self, obj):
        """
        Group the prefetched specs in order, without a second query.

        `specs` arrives ordered by (group_order, sort_order, id), so first
        appearance is already the intended group order and a plain dict
        preserves it.
        """
        groups = {}
        for spec in obj.specs.all():
            groups.setdefault(spec.group or "Specifications", []).append(
                {"key": spec.key, "value": spec.value}
            )
        return [{"group": name, "rows": rows} for name, rows in groups.items()]

    def get_component(self, obj):
        """
        The PC-builder slot this product occupies, or null.

        Only the slot and its label: the full profile is the builder's
        business, and the detail page needs no more than "this can go in a
        build, as a motherboard".
        """
        profile = getattr(obj, "component", None)
        if profile is None:
            return None
        return {"slot": profile.slot, "label": profile.get_slot_display()}
