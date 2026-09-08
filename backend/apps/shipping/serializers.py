"""
Shipping zone shapes (PRD 7.2 GET /shipping/zones/).

Rates are published so checkout can show delivery cost before an address is
complete. Nothing secret lives on a zone -- these are the numbers printed on
the shipping policy page.
"""
from rest_framework import serializers

from .models import ShippingZone

MONEY_KWARGS = {"max_digits": 12, "decimal_places": 2, "read_only": True}


class ShippingZoneSerializer(serializers.ModelSerializer):
    flat_rate = serializers.DecimalField(**MONEY_KWARGS)
    per_kg_rate = serializers.DecimalField(**MONEY_KWARGS)
    free_shipping_threshold = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True, allow_null=True
    )

    class Meta:
        model = ShippingZone
        fields = [
            "id",
            "name",
            "flat_rate",
            "per_kg_rate",
            "base_weight_grams",
            "free_shipping_threshold",
            "cod_allowed",
            "districts",
        ]
