"""
Shipping zone resolution and rate arithmetic (PRD 5.12, FR-SHP-1..5).

Rates are configuration, never code. Nothing in this module knows what "Inside
Dhaka" costs -- it reads the zone row, so adding a third zone is a data change.

Two rules are load-bearing:

1. **An unmapped district is an error, not a free delivery.** Silently charging
   zero for a district no zone claims is how a store ends up shipping a laptop
   to Bandarban for nothing. resolve_zone raises instead.
2. **Weight above the zone's base weight is billed per started kilogram.** A
   courier charges for a part-kilogram as a whole one, so the excess is rounded
   up, not prorated.
"""
import math
from dataclasses import dataclass
from decimal import Decimal

from config.exceptions import DomainError

from ..models import ShippingZone

GRAMS_PER_KG = 1000


@dataclass(frozen=True)
class ShippingQuote:
    """What a zone charges for one basket. Money is Decimal throughout."""

    zone: ShippingZone
    amount: Decimal
    free_shipping_applied: bool
    billable_extra_kg: int


def active_zones():
    """Zones offered at checkout, in display order (sort_order, name)."""
    return ShippingZone.objects.filter(is_active=True)


def resolve_zone(district):
    """
    Map a shipping district to its zone (FR-SHP-4).

    Zones are scanned in display order, so if two zones ever claim the same
    district the lower sort_order wins deterministically rather than by
    whatever order the database felt like returning.
    """
    cleaned = (district or "").strip()
    if not cleaned:
        raise DomainError(
            "A shipping district is required to calculate delivery.",
            code="DISTRICT_REQUIRED",
            field="district",
        )

    for zone in active_zones():
        if zone.matches_district(cleaned):
            return zone

    raise DomainError(
        f"We do not deliver to {cleaned} yet. Please choose another district.",
        code="SHIPPING_ZONE_UNAVAILABLE",
        field="district",
    )


def billable_extra_kg(zone, weight_grams):
    """Kilograms above the zone's included base weight, rounded up."""
    excess = max(0, int(weight_grams or 0) - int(zone.base_weight_grams or 0))
    return math.ceil(excess / GRAMS_PER_KG) if excess else 0


def quote_shipping(*, zone, subtotal, weight_grams=0):
    """
    Charge for one basket: flat rate, plus per-kg over the base weight, unless
    the zone's free-shipping threshold is met (FR-SHP-2, FR-SHP-3).

    `subtotal` is the merchandise subtotal *after* any discount -- a coupon
    that drops an order below the free-shipping threshold must lose the free
    shipping with it, otherwise the threshold is trivially gamed.
    """
    threshold = zone.free_shipping_threshold
    if threshold is not None and Decimal(subtotal) >= Decimal(threshold):
        return ShippingQuote(
            zone=zone, amount=Decimal("0.00"), free_shipping_applied=True, billable_extra_kg=0
        )

    extra_kg = billable_extra_kg(zone, weight_grams)
    amount = Decimal(zone.flat_rate) + (Decimal(zone.per_kg_rate) * extra_kg)
    return ShippingQuote(
        zone=zone,
        amount=amount,
        free_shipping_applied=False,
        billable_extra_kg=extra_kg,
    )


def assert_zone_allows_cod(zone):
    """FR-SHP-5: a zone may refuse Cash on Delivery outright."""
    if zone is not None and not zone.cod_allowed:
        raise DomainError(
            f"Cash on Delivery is not available for {zone.name}.",
            code="COD_NOT_ALLOWED_IN_ZONE",
            field="payment_method",
        )
