"""
Wire shapes for the PC builder.

The component list reuses the catalogue's card vocabulary (`price`,
`compare_at_price`, `in_stock`) so a builder row and a product card can never
disagree about the same variant.
"""
from rest_framework import serializers

from apps.catalog.models import ComponentSlot


class ComponentOptionSerializer(serializers.Serializer):
    """One choosable part, flattened from ComponentProfile + its cheapest variant."""

    product_id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.SlugField()
    brand = serializers.CharField(allow_null=True)
    category = serializers.CharField(allow_null=True)
    image = serializers.CharField(allow_null=True)
    variant_id = serializers.IntegerField()
    sku = serializers.CharField()
    variant_label = serializers.CharField(allow_blank=True)
    price = serializers.DecimalField(max_digits=12, decimal_places=2)
    compare_at_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    stock = serializers.IntegerField()
    in_stock = serializers.BooleanField()
    rating_avg = serializers.DecimalField(max_digits=3, decimal_places=2)
    rating_count = serializers.IntegerField()
    # The handful of build attributes worth showing on the row itself, so a
    # shopper can tell two boards apart without opening both.
    attributes = serializers.DictField(child=serializers.CharField(), allow_null=True)


class BuildItemInputSerializer(serializers.Serializer):
    slot = serializers.ChoiceField(choices=ComponentSlot.choices)
    variant_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=4, default=1)


class BuildValidateInputSerializer(serializers.Serializer):
    items = BuildItemInputSerializer(many=True)


class BuildSaveInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    items = BuildItemInputSerializer(many=True)
