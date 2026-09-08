"""
Shipping zones and rates (PRD §5.12, §6.3).

Rates are configuration, not code: the actual inside/outside-Dhaka numbers and
the free-shipping threshold are still an open owner decision (PRD §14 Q3), so
nothing here hard-codes a figure.
"""
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.fields import MoneyField
from apps.common.models import TimeStampedModel


class ShippingZone(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    flat_rate = MoneyField(default=0, validators=[MinValueValidator(0)])
    per_kg_rate = MoneyField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Charged on weight above base_weight_grams.",
    )
    base_weight_grams = models.PositiveIntegerField(
        default=1000, help_text="Weight included in the flat rate."
    )
    free_shipping_threshold = MoneyField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Order subtotal at or above which shipping is free. Null disables it.",
    )
    cod_allowed = models.BooleanField(default=True)
    districts = models.JSONField(
        default=list, help_text="District names that map an address to this zone."
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "shipping_zone"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    def matches_district(self, district):
        if not district:
            return False
        target = district.strip().casefold()
        return any(str(d).strip().casefold() == target for d in self.districts or [])
