"""
Shipping zone resolution and rate arithmetic (PRD 5.12, FR-SHP-1..5).

The two rules the service calls load-bearing get the most attention here:

1. **An unmapped district is an error, not a free delivery.** Only 13
   districts are seeded, so an address in no zone is a live path, and the
   difference between "raise" and "charge zero" is the price of a laptop.
2. **Weight above the base weight is billed per *started* kilogram.** A
   courier rounds a part-kilogram up, so the boundary is tested exactly at
   the threshold, one gram under, and one gram over -- an off-by-one here is
   money, every order, silently.

Rates are configuration: every zone in this file states its own numbers, and
nothing reads the seeded data.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.shipping.models import ShippingZone
from apps.shipping.services import rates as shipping_services
from config.exceptions import DomainError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def make_zone(
    name="Inside Dhaka",
    *,
    flat_rate="60.00",
    per_kg_rate="20.00",
    base_weight_grams=1000,
    free_shipping_threshold=None,
    cod_allowed=True,
    districts=None,
    sort_order=0,
    is_active=True,
):
    return ShippingZone.objects.create(
        name=name,
        flat_rate=Decimal(flat_rate),
        per_kg_rate=Decimal(per_kg_rate),
        base_weight_grams=base_weight_grams,
        free_shipping_threshold=(
            None if free_shipping_threshold is None else Decimal(free_shipping_threshold)
        ),
        cod_allowed=cod_allowed,
        districts=["Dhaka", "Gazipur", "Narayanganj"] if districts is None else districts,
        sort_order=sort_order,
        is_active=is_active,
    )


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def zones_url():
    return reverse("shipping:zone-list")


# ---------------------------------------------------------------------------
# active_zones
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_active_zones_excludes_a_zone_that_has_been_switched_off():
    live = make_zone("Inside Dhaka", districts=["Dhaka"])
    make_zone("Retired zone", districts=["Khulna"], is_active=False)

    assert list(shipping_services.active_zones()) == [live]


@pytest.mark.django_db
def test_active_zones_come_back_in_display_order_not_insertion_order():
    # Display order is (sort_order, name); resolve_zone depends on it to break
    # ties deterministically, so it is asserted rather than assumed.
    third = make_zone("Chattogram", districts=["Chattogram"], sort_order=2)
    first = make_zone("Inside Dhaka", districts=["Dhaka"], sort_order=0)
    second = make_zone("Outside Dhaka", districts=["Sylhet"], sort_order=1)

    assert list(shipping_services.active_zones()) == [first, second, third]


# ---------------------------------------------------------------------------
# resolve_zone
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_resolve_zone_maps_a_known_district_to_the_zone_that_claims_it():
    inside = make_zone("Inside Dhaka", districts=["Dhaka", "Gazipur"], sort_order=0)
    outside = make_zone("Outside Dhaka", districts=["Sylhet"], sort_order=1)

    assert shipping_services.resolve_zone("Dhaka") == inside
    assert shipping_services.resolve_zone("Gazipur") == inside
    assert shipping_services.resolve_zone("Sylhet") == outside


@pytest.mark.django_db
def test_resolve_zone_refuses_a_district_no_zone_claims_rather_than_shipping_it_free():
    make_zone("Inside Dhaka", districts=["Dhaka"])

    with pytest.raises(DomainError) as excinfo:
        shipping_services.resolve_zone("Bandarban")
    assert excinfo.value.code == "SHIPPING_ZONE_UNAVAILABLE"
    assert excinfo.value.field == "district"


@pytest.mark.django_db
def test_resolve_zone_refuses_a_missing_district_with_its_own_code():
    make_zone("Inside Dhaka", districts=["Dhaka"])

    for missing in ("", "   ", None):
        with pytest.raises(DomainError) as excinfo:
            shipping_services.resolve_zone(missing)
        assert excinfo.value.code == "DISTRICT_REQUIRED"
        assert excinfo.value.field == "district"


@pytest.mark.django_db
def test_resolve_zone_matches_a_district_regardless_of_case_or_surrounding_whitespace():
    inside = make_zone("Inside Dhaka", districts=["Dhaka"])

    for spelling in ("dhaka", "DHAKA", "  Dhaka  ", "\tdHaKa\n"):
        assert shipping_services.resolve_zone(spelling) == inside


@pytest.mark.django_db
def test_resolve_zone_matches_a_configured_district_that_itself_carries_stray_whitespace():
    # Zone districts are hand-entered JSON in the admin, so the stored value is
    # normalised on comparison too, not only the customer's input.
    inside = make_zone("Inside Dhaka", districts=["  Dhaka  ", "gazipur"])

    assert shipping_services.resolve_zone("Dhaka") == inside
    assert shipping_services.resolve_zone("Gazipur") == inside


@pytest.mark.django_db
def test_an_inactive_zone_cannot_claim_a_district_even_though_it_still_lists_one():
    make_zone("Retired zone", districts=["Dhaka"], is_active=False)

    with pytest.raises(DomainError) as excinfo:
        shipping_services.resolve_zone("Dhaka")
    assert excinfo.value.code == "SHIPPING_ZONE_UNAVAILABLE"


@pytest.mark.django_db
def test_when_two_zones_claim_the_same_district_the_lower_sort_order_wins_deterministically():
    cheaper = make_zone("Inside Dhaka", districts=["Dhaka"], sort_order=0)
    make_zone("Nationwide", districts=["Dhaka"], sort_order=5)

    assert shipping_services.resolve_zone("Dhaka") == cheaper


@pytest.mark.django_db
def test_a_zone_with_no_districts_configured_claims_nothing():
    make_zone("Unconfigured", districts=[])

    with pytest.raises(DomainError) as excinfo:
        shipping_services.resolve_zone("Dhaka")
    assert excinfo.value.code == "SHIPPING_ZONE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# billable_extra_kg -- the rounding boundary, in grams
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_basket_exactly_on_the_base_weight_is_billed_no_extra_kilograms():
    zone = make_zone(base_weight_grams=1000)
    assert shipping_services.billable_extra_kg(zone, 1000) == 0


@pytest.mark.django_db
def test_a_basket_one_gram_under_the_base_weight_is_billed_no_extra_kilograms():
    zone = make_zone(base_weight_grams=1000)
    assert shipping_services.billable_extra_kg(zone, 999) == 0


@pytest.mark.django_db
def test_a_basket_one_gram_over_the_base_weight_is_billed_a_whole_extra_kilogram():
    # A started kilogram is a charged kilogram -- couriers do not prorate.
    zone = make_zone(base_weight_grams=1000)
    assert shipping_services.billable_extra_kg(zone, 1001) == 1


@pytest.mark.django_db
def test_a_basket_exactly_one_kilogram_over_the_base_weight_is_billed_one_kilogram_not_two():
    zone = make_zone(base_weight_grams=1000)
    assert shipping_services.billable_extra_kg(zone, 2000) == 1


@pytest.mark.django_db
def test_a_basket_one_gram_past_the_second_kilogram_boundary_is_billed_two_kilograms():
    zone = make_zone(base_weight_grams=1000)
    assert shipping_services.billable_extra_kg(zone, 2001) == 2


@pytest.mark.django_db
def test_a_weightless_or_unweighed_basket_is_billed_no_extra_kilograms():
    zone = make_zone(base_weight_grams=1000)
    assert shipping_services.billable_extra_kg(zone, 0) == 0
    assert shipping_services.billable_extra_kg(zone, None) == 0


@pytest.mark.django_db
def test_a_zone_with_no_included_base_weight_bills_every_started_kilogram():
    zone = make_zone(base_weight_grams=0)
    assert shipping_services.billable_extra_kg(zone, 1) == 1
    assert shipping_services.billable_extra_kg(zone, 1000) == 1
    assert shipping_services.billable_extra_kg(zone, 1001) == 2


# ---------------------------------------------------------------------------
# quote_shipping
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_basket_within_the_base_weight_is_charged_the_zones_flat_rate_and_nothing_more():
    zone = make_zone(flat_rate="60.00", per_kg_rate="20.00", base_weight_grams=1000)

    quote = shipping_services.quote_shipping(
        zone=zone, subtotal=Decimal("1000.00"), weight_grams=800
    )

    assert quote.amount == Decimal("60.00")
    assert quote.billable_extra_kg == 0
    assert quote.free_shipping_applied is False
    assert quote.zone == zone


@pytest.mark.django_db
def test_a_heavier_basket_adds_the_per_kilogram_rate_for_every_started_kilogram():
    zone = make_zone(flat_rate="60.00", per_kg_rate="20.00", base_weight_grams=1000)

    at_boundary = shipping_services.quote_shipping(
        zone=zone, subtotal=Decimal("1000.00"), weight_grams=1000
    )
    just_over = shipping_services.quote_shipping(
        zone=zone, subtotal=Decimal("1000.00"), weight_grams=1001
    )
    two_kilos_over = shipping_services.quote_shipping(
        zone=zone, subtotal=Decimal("1000.00"), weight_grams=3000
    )

    assert at_boundary.amount == Decimal("60.00")
    assert just_over.amount == Decimal("80.00")
    assert two_kilos_over.amount == Decimal("100.00")
    assert two_kilos_over.billable_extra_kg == 2


@pytest.mark.django_db
def test_a_zone_with_no_per_kilogram_rate_charges_the_flat_rate_however_heavy_the_basket():
    zone = make_zone(flat_rate="120.00", per_kg_rate="0.00", base_weight_grams=1000)

    quote = shipping_services.quote_shipping(
        zone=zone, subtotal=Decimal("1000.00"), weight_grams=25000
    )
    assert quote.amount == Decimal("120.00")
    assert quote.billable_extra_kg == 24


@pytest.mark.django_db
def test_a_basket_one_taka_under_the_free_shipping_threshold_is_still_charged():
    zone = make_zone(flat_rate="60.00", free_shipping_threshold="5000.00")

    quote = shipping_services.quote_shipping(zone=zone, subtotal=Decimal("4999.99"))

    assert quote.amount == Decimal("60.00")
    assert quote.free_shipping_applied is False


@pytest.mark.django_db
def test_a_basket_exactly_on_the_free_shipping_threshold_ships_free():
    # "At or above" -- the boundary is inclusive, as the field's help text says.
    zone = make_zone(flat_rate="60.00", free_shipping_threshold="5000.00")

    quote = shipping_services.quote_shipping(zone=zone, subtotal=Decimal("5000.00"))

    assert quote.amount == Decimal("0.00")
    assert quote.free_shipping_applied is True


@pytest.mark.django_db
def test_a_basket_over_the_free_shipping_threshold_ships_free():
    zone = make_zone(flat_rate="60.00", free_shipping_threshold="5000.00")

    quote = shipping_services.quote_shipping(zone=zone, subtotal=Decimal("5000.01"))

    assert quote.amount == Decimal("0.00")
    assert quote.free_shipping_applied is True


@pytest.mark.django_db
def test_free_shipping_waives_the_weight_surcharge_as_well_as_the_flat_rate():
    zone = make_zone(
        flat_rate="60.00",
        per_kg_rate="20.00",
        base_weight_grams=1000,
        free_shipping_threshold="5000.00",
    )

    quote = shipping_services.quote_shipping(
        zone=zone, subtotal=Decimal("9000.00"), weight_grams=8000
    )

    assert quote.amount == Decimal("0.00")
    assert quote.free_shipping_applied is True
    assert quote.billable_extra_kg == 0


@pytest.mark.django_db
def test_a_zone_with_no_free_shipping_threshold_never_ships_free_however_large_the_order():
    zone = make_zone(flat_rate="60.00", free_shipping_threshold=None)

    quote = shipping_services.quote_shipping(zone=zone, subtotal=Decimal("999999.00"))

    assert quote.amount == Decimal("60.00")
    assert quote.free_shipping_applied is False


@pytest.mark.django_db
def test_free_shipping_is_decided_on_the_subtotal_it_is_handed_so_a_discount_can_remove_it():
    # quote_shipping is given the subtotal *after* discount. A coupon that
    # drops an order under the threshold must lose the free shipping with it,
    # or the threshold is trivially gamed.
    zone = make_zone(flat_rate="60.00", free_shipping_threshold="5000.00")

    before_discount = shipping_services.quote_shipping(zone=zone, subtotal=Decimal("5200.00"))
    after_discount = shipping_services.quote_shipping(zone=zone, subtotal=Decimal("4680.00"))

    assert before_discount.free_shipping_applied is True
    assert after_discount.free_shipping_applied is False
    assert after_discount.amount == Decimal("60.00")


@pytest.mark.django_db
def test_the_totals_engine_loses_free_shipping_when_a_coupon_drops_the_order_under_the_threshold():
    # The same rule end to end, through the code checkout actually runs.
    from datetime import timedelta

    from django.utils import timezone

    from apps.catalog.tests.factories import make_category, make_product
    from apps.orders.services import totals as totals_services
    from apps.promotions.models import Coupon, DiscountType

    make_zone("Inside Dhaka", flat_rate="60.00", free_shipping_threshold="5000.00",
              districts=["Dhaka"])
    category = make_category("Laptops")
    product = make_product(category, price="5200.00", stock=5)
    now = timezone.now()
    Coupon.objects.create(
        code="TEN",
        discount_type=DiscountType.PERCENT,
        value=Decimal("10.00"),
        min_order_value=Decimal("0.00"),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
    )
    lines = [totals_services.build_line(product.variants.first(), 1)]

    without_coupon = totals_services.compute_totals(lines=lines, district="Dhaka")
    with_coupon = totals_services.compute_totals(
        lines=lines, district="Dhaka", coupon_code="TEN"
    )

    assert without_coupon.shipping_total == Decimal("0.00")
    assert without_coupon.free_shipping_applied is True
    # 5200 - 520 = 4680, under the 5000 threshold, so delivery is charged again.
    assert with_coupon.shipping_total == Decimal("60.00")
    assert with_coupon.free_shipping_applied is False


# ---------------------------------------------------------------------------
# assert_zone_allows_cod (FR-SHP-5)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_zone_that_permits_cash_on_delivery_passes_the_check_silently():
    zone = make_zone("Inside Dhaka", cod_allowed=True)
    assert shipping_services.assert_zone_allows_cod(zone) is None


@pytest.mark.django_db
def test_a_zone_that_refuses_cash_on_delivery_blocks_it_with_its_own_code_and_field():
    zone = make_zone("Remote hill districts", cod_allowed=False, districts=["Bandarban"])

    with pytest.raises(DomainError) as excinfo:
        shipping_services.assert_zone_allows_cod(zone)
    assert excinfo.value.code == "COD_NOT_ALLOWED_IN_ZONE"
    assert excinfo.value.field == "payment_method"


@pytest.mark.django_db
def test_an_unknown_zone_is_not_treated_as_a_cash_on_delivery_refusal():
    # No zone yet means the district has not been entered; refusing COD here
    # would print "COD unavailable" on a checkout page with an empty address.
    assert shipping_services.assert_zone_allows_cod(None) is None


# ---------------------------------------------------------------------------
# GET /api/v1/shipping/zones/
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_zones_endpoint_lists_active_zones_only(api, zones_url):
    make_zone("Inside Dhaka", districts=["Dhaka"], sort_order=0)
    make_zone("Retired zone", districts=["Khulna"], is_active=False, sort_order=1)

    response = api.get(zones_url)

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == ["Inside Dhaka"]


@pytest.mark.django_db
def test_the_zones_endpoint_is_public_and_returns_a_bare_list_not_a_paginated_envelope(
    api, zones_url
):
    make_zone("Inside Dhaka", districts=["Dhaka"])

    body = api.get(zones_url).json()

    assert isinstance(body, list)


@pytest.mark.django_db
def test_the_zones_endpoint_serialises_every_rate_as_a_decimal_string_never_a_float(
    api, zones_url
):
    make_zone(
        "Inside Dhaka",
        flat_rate="60.00",
        per_kg_rate="20.50",
        free_shipping_threshold="5000.00",
        districts=["Dhaka"],
    )

    row = api.get(zones_url).json()[0]

    for field in ("flat_rate", "per_kg_rate", "free_shipping_threshold"):
        assert isinstance(row[field], str), field
    assert row["flat_rate"] == "60.00"
    assert row["per_kg_rate"] == "20.50"
    assert row["free_shipping_threshold"] == "5000.00"


@pytest.mark.django_db
def test_a_zone_without_a_free_shipping_threshold_reports_null_rather_than_zero(
    api, zones_url
):
    # "0.00" would render as "free shipping over ৳0" -- every order free.
    make_zone("Inside Dhaka", free_shipping_threshold=None, districts=["Dhaka"])

    row = api.get(zones_url).json()[0]

    assert row["free_shipping_threshold"] is None


@pytest.mark.django_db
def test_the_zones_endpoint_publishes_the_fields_the_checkout_page_needs(api, zones_url):
    make_zone("Inside Dhaka", districts=["Dhaka", "Gazipur"], cod_allowed=False)

    row = api.get(zones_url).json()[0]

    assert set(row) == {
        "id",
        "name",
        "flat_rate",
        "per_kg_rate",
        "base_weight_grams",
        "free_shipping_threshold",
        "cod_allowed",
        "districts",
    }
    assert row["districts"] == ["Dhaka", "Gazipur"]
    assert row["cod_allowed"] is False


@pytest.mark.django_db
def test_the_zones_endpoint_returns_them_in_display_order(api, zones_url):
    make_zone("Outside Dhaka", districts=["Sylhet"], sort_order=1)
    make_zone("Inside Dhaka", districts=["Dhaka"], sort_order=0)

    assert [row["name"] for row in api.get(zones_url).json()] == [
        "Inside Dhaka",
        "Outside Dhaka",
    ]
