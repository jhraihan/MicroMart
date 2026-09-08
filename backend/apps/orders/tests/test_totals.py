"""
The totals engine -- `apps/orders/services/totals.py`.

This is the code that decides how much money is charged, so the assertions here
are exact Decimals rather than "close enough". Three rules are what the suite
exists to pin down:

1. **Money is Decimal, quantised to two places, everywhere.** A figure that is
   the right number but the wrong type is still a bug -- it is one arithmetic
   step away from charging 284059.99999999994.
2. **The breakdown composes.** `subtotal - discount + shipping + tax` is the
   grand total when prices exclude VAT, and `subtotal - discount + shipping`
   when they include it. A shopper adding up the lines on the confirmation page
   must reach the number on their receipt.
3. **The rate in force at computation is the rate reported.** Tax is
   snapshotted, so a VAT change tomorrow cannot rewrite an order placed today
   (FR-SHP-7).

The arithmetic tests deliberately run **without a database**: `BasketLine` is a
plain frozen dataclass, and pricing arithmetic that needed a MySQL connection to
be checked would be arithmetic entangled with something it has no business
knowing about. The integration tests below them take the database they need.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.tests.factories import make_category
from apps.dashboard.models import StoreSettings
from apps.orders.models import PaymentMethod
from apps.orders.services import placement as placement_services
from apps.orders.services import totals as totals_services
from apps.orders.services.totals import MAX_LINE_QUANTITY, BasketLine
from apps.promotions.models import DiscountType, ScopeType
from config.exceptions import DomainError

MONEY_FIELDS = (
    "subtotal",
    "discount_total",
    "shipping_total",
    "tax_total",
    "grand_total",
)


def line(unit_price, quantity, *, weight_grams=0, variant=None, name="Test Product"):
    """
    A priced line with no database behind it.

    `BasketLine` is what the cart, the quote and placement all hand to the
    arithmetic, so building one directly tests exactly what those three share.
    """
    return BasketLine(
        variant=variant,
        quantity=quantity,
        unit_price=Decimal(unit_price),
        product_name=name,
        variant_label="Default",
        sku="SKU-TEST",
        weight_grams=weight_grams,
    )


# ---------------------------------------------------------------------------
# Line and basket arithmetic -- no database
# ---------------------------------------------------------------------------
def test_a_line_total_is_the_unit_price_times_the_quantity_as_an_exact_decimal(
    assert_money,
):
    assert_money(line("1234.57", 3).line_total, "3703.71", "line_total")


def test_a_line_total_is_rounded_half_up_to_two_decimal_places(assert_money):
    # 0.005 x 3 = 0.015, which is a genuine half-way case: ROUND_HALF_UP takes
    # it to 0.02, and any float-backed implementation would not be trusted to.
    assert_money(line("0.005", 3).line_total, "0.02", "line_total")


def test_a_single_unit_line_still_reports_two_decimal_places(assert_money):
    assert_money(line("999", 1).line_total, "999.00", "line_total")


def test_subtotal_of_sums_the_line_totals_exactly(assert_money):
    lines = [line("1999.99", 3), line("0.01", 7), line("142000.00", 2)]

    assert_money(totals_services.subtotal_of(lines), "290000.04", "subtotal")


def test_subtotal_of_an_empty_basket_is_a_two_decimal_place_zero_not_an_integer(
    assert_money,
):
    assert_money(totals_services.subtotal_of([]), "0.00", "subtotal")


def test_subtotal_stays_exact_at_the_top_of_the_money_column(assert_money):
    # DECIMAL(12,2) reaches 9,999,999,999.99. Ninety-nine units of a
    # seven-figure line lands well inside it and well outside the range a
    # float would carry to the paisa.
    assert_money(
        totals_services.subtotal_of([line("9999999.99", MAX_LINE_QUANTITY)]),
        "989999999.01",
        "subtotal",
    )


def test_weight_of_multiplies_each_lines_weight_by_its_quantity(assert_money):
    lines = [line("100.00", 2, weight_grams=1200), line("100.00", 3, weight_grams=350)]

    weight = totals_services.weight_of(lines)

    assert weight == 3450
    assert isinstance(weight, int)


def test_weight_of_treats_a_line_with_no_weight_as_zero_grams():
    assert totals_services.weight_of([line("100.00", 4, weight_grams=None)]) == 0
    assert totals_services.weight_of([]) == 0


# ---------------------------------------------------------------------------
# Tax arithmetic -- no database
# ---------------------------------------------------------------------------
def test_exclusive_tax_is_charged_on_top_of_the_net_merchandise_total(assert_money):
    assert_money(
        totals_services._tax_on(Decimal("1000.00"), Decimal("15.00"), False),
        "150.00",
        "tax_total",
    )


def test_inclusive_tax_reports_the_vat_already_contained_in_the_net_total(assert_money):
    # 1150 gross at 15% contains 150 of VAT, not 172.50 -- the inclusive mode
    # extracts, it does not add.
    assert_money(
        totals_services._tax_on(Decimal("1150.00"), Decimal("15.00"), True),
        "150.00",
        "tax_total",
    )


def test_tax_is_zero_in_both_modes_when_the_store_has_no_rate_configured(assert_money):
    assert_money(
        totals_services._tax_on(Decimal("1000.00"), Decimal("0.00"), False), "0.00"
    )
    assert_money(
        totals_services._tax_on(Decimal("1000.00"), Decimal("0.00"), True), "0.00"
    )


def test_tax_is_zero_when_a_discount_has_taken_the_net_total_down_to_nothing(
    assert_money,
):
    assert_money(totals_services._tax_on(Decimal("0.00"), Decimal("15.00"), False), "0.00")
    assert_money(totals_services._tax_on(Decimal("0.00"), Decimal("15.00"), True), "0.00")


def test_exclusive_tax_is_rounded_half_up_to_two_decimal_places(assert_money):
    # 53.50 at 5% is exactly 2.675 -- the half-way case ROUND_HALF_UP takes up.
    assert_money(
        totals_services._tax_on(Decimal("53.50"), Decimal("5.00"), False), "2.68"
    )


def test_inclusive_tax_is_rounded_half_up_to_two_decimal_places(assert_money):
    # 100 gross at 7.5% contains 6.9767... of VAT.
    assert_money(
        totals_services._tax_on(Decimal("100.00"), Decimal("7.50"), True), "6.98"
    )


def test_an_inclusive_rate_never_reports_more_tax_than_the_total_containing_it(
    assert_money,
):
    extracted = totals_services._tax_on(Decimal("200.00"), Decimal("100.00"), True)

    assert_money(extracted, "100.00")
    assert extracted <= Decimal("200.00")


# ---------------------------------------------------------------------------
# build_line / build_lines -- catalogue-priced, so a database is needed
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_build_line_prices_from_the_variant_row_and_snapshots_its_name_label_and_sku(
    make_sellable_variant, assert_money
):
    variant = make_sellable_variant(
        price="142000.00", name="Asus TUF Gaming F15", option_label="16GB / 512GB"
    )

    built = totals_services.build_line(variant, 2)

    assert_money(built.unit_price, "142000.00", "unit_price")
    assert_money(built.line_total, "284000.00", "line_total")
    assert built.product_name == "Asus TUF Gaming F15"
    assert built.variant_label == "16GB / 512GB"
    assert built.sku == variant.sku
    assert built.variant == variant


@pytest.mark.django_db
def test_build_line_refuses_a_quantity_below_one(make_sellable_variant):
    variant = make_sellable_variant()

    with pytest.raises(DomainError) as excinfo:
        totals_services.build_line(variant, 0)

    assert excinfo.value.code == "INVALID_QUANTITY"
    assert excinfo.value.field == "quantity"


@pytest.mark.django_db
def test_build_line_refuses_a_quantity_above_the_single_line_ceiling(
    make_sellable_variant,
):
    variant = make_sellable_variant()

    with pytest.raises(DomainError) as excinfo:
        totals_services.build_line(variant, MAX_LINE_QUANTITY + 1)

    assert excinfo.value.code == "QUANTITY_TOO_LARGE"
    assert excinfo.value.field == "quantity"


@pytest.mark.django_db
def test_build_line_accepts_the_single_line_ceiling_itself(make_sellable_variant):
    variant = make_sellable_variant(price="10.00", stock=200)

    assert totals_services.build_line(variant, MAX_LINE_QUANTITY).quantity == 99


@pytest.mark.django_db
def test_build_lines_prices_every_variant_and_quantity_pair_it_is_given(
    make_sellable_variant, assert_money
):
    cheap = make_sellable_variant(price="500.00", name="Mouse")
    dear = make_sellable_variant(price="142000.00", name="Laptop")

    lines = totals_services.build_lines([(cheap, 3), (dear, 1)])

    assert [built.product_name for built in lines] == ["Mouse", "Laptop"]
    assert_money(totals_services.subtotal_of(lines), "143500.00", "subtotal")


# ---------------------------------------------------------------------------
# compute_totals -- the whole breakdown
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_compute_totals_refuses_an_empty_basket_rather_than_pricing_nothing(
    store_settings,
):
    with pytest.raises(DomainError) as excinfo:
        totals_services.compute_totals(lines=[])

    assert excinfo.value.code == "CART_EMPTY"
    assert excinfo.value.field == "items"
    assert excinfo.value.status_code == 422


@pytest.mark.django_db
def test_compute_totals_reports_the_item_count_as_the_sum_of_the_line_quantities(
    store_settings, make_sellable_variant
):
    first = make_sellable_variant(price="100.00")
    second = make_sellable_variant(price="200.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(first, 2), (second, 3)])
    )

    assert result.item_count == 5


# --- Shipping ---------------------------------------------------------------
@pytest.mark.django_db
def test_a_basket_with_no_district_reports_shipping_as_unknown_rather_than_free(
    store_settings, dhaka_zone, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="1000.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)])
    )

    assert result.shipping_known is False
    assert result.zone is None
    assert_money(result.shipping_total, "0.00", "shipping_total")
    assert_money(result.grand_total, "2000.00", "grand_total")


@pytest.mark.django_db
def test_an_empty_district_string_is_treated_as_a_district_not_yet_chosen(
    store_settings, dhaka_zone, make_sellable_variant
):
    variant = make_sellable_variant(price="1000.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 1)]), district=""
    )

    assert result.shipping_known is False


@pytest.mark.django_db
def test_a_whitespace_only_district_is_refused_rather_than_priced_as_unknown(
    store_settings, dhaka_zone, make_sellable_variant
):
    variant = make_sellable_variant(price="1000.00")

    with pytest.raises(DomainError) as excinfo:
        totals_services.compute_totals(
            lines=totals_services.build_lines([(variant, 1)]), district="   "
        )

    assert excinfo.value.code == "DISTRICT_REQUIRED"
    assert excinfo.value.field == "district"


@pytest.mark.django_db
def test_a_district_inside_a_zone_is_charged_that_zones_flat_rate(
    store_settings, dhaka_zone, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="1000.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]), district="Dhaka"
    )

    assert result.shipping_known is True
    assert result.zone == dhaka_zone
    assert_money(result.subtotal, "2000.00", "subtotal")
    assert_money(result.shipping_total, "60.00", "shipping_total")
    assert_money(result.grand_total, "2060.00", "grand_total")


@pytest.mark.django_db
def test_a_district_matches_its_zone_regardless_of_the_case_it_was_typed_in(
    store_settings, dhaka_zone, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="1000.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 1)]), district="  dhaka  "
    )

    assert result.zone == dhaka_zone
    assert_money(result.shipping_total, "60.00", "shipping_total")


@pytest.mark.django_db
def test_a_district_no_zone_claims_is_refused_rather_than_shipped_for_free(
    store_settings, dhaka_zone, make_sellable_variant
):
    variant = make_sellable_variant(price="1000.00")

    with pytest.raises(DomainError) as excinfo:
        totals_services.compute_totals(
            lines=totals_services.build_lines([(variant, 1)]), district="Bandarban"
        )

    assert excinfo.value.code == "SHIPPING_ZONE_UNAVAILABLE"
    assert excinfo.value.field == "district"


@pytest.mark.django_db
def test_weight_above_the_zones_base_weight_is_billed_per_started_kilogram(
    store_settings, make_zone, make_sellable_variant, assert_money
):
    make_zone(per_kg_rate="20.00", base_weight_grams=1000)
    variant = make_sellable_variant(price="500.00", weight_grams=1200)

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]), district="Dhaka"
    )

    # 2400g is 1400g over the base weight, and a courier bills a part kilogram
    # as a whole one: two extra kilograms at 20.
    assert result.total_weight_grams == 2400
    assert_money(result.shipping_total, "100.00", "shipping_total")
    assert_money(result.grand_total, "1100.00", "grand_total")


@pytest.mark.django_db
def test_weight_at_exactly_the_base_weight_adds_nothing_to_the_flat_rate(
    store_settings, make_zone, make_sellable_variant, assert_money
):
    make_zone(per_kg_rate="20.00", base_weight_grams=1000)
    variant = make_sellable_variant(price="500.00", weight_grams=1000)

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 1)]), district="Dhaka"
    )

    assert_money(result.shipping_total, "60.00", "shipping_total")


@pytest.mark.django_db
def test_a_single_gram_above_the_base_weight_is_billed_as_a_whole_kilogram(
    store_settings, make_zone, make_sellable_variant, assert_money
):
    make_zone(per_kg_rate="20.00", base_weight_grams=1000)
    variant = make_sellable_variant(price="500.00", weight_grams=1001)

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 1)]), district="Dhaka"
    )

    assert_money(result.shipping_total, "80.00", "shipping_total")


@pytest.mark.django_db
def test_a_net_total_at_the_free_shipping_threshold_removes_the_delivery_charge(
    store_settings, make_zone, make_sellable_variant, assert_money
):
    make_zone(free_shipping_threshold="5000.00")
    variant = make_sellable_variant(price="2500.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]), district="Dhaka"
    )

    assert result.free_shipping_applied is True
    assert result.shipping_known is True
    assert_money(result.shipping_total, "0.00", "shipping_total")
    assert_money(result.grand_total, "5000.00", "grand_total")


@pytest.mark.django_db
def test_a_coupon_that_drops_the_net_below_the_free_shipping_threshold_loses_it_too(
    store_settings, make_zone, make_sellable_variant, make_coupon, assert_money
):
    make_zone(free_shipping_threshold="5000.00")
    variant = make_sellable_variant(price="2500.00")
    make_coupon("SAVE10", discount_type=DiscountType.PERCENT, value="10.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]),
        district="Dhaka",
        coupon_code="SAVE10",
    )

    # Free shipping is earned on what is actually paid for, otherwise the
    # threshold is trivially gamed with a coupon.
    assert result.free_shipping_applied is False
    assert_money(result.discount_total, "500.00", "discount_total")
    assert_money(result.shipping_total, "60.00", "shipping_total")
    assert_money(result.grand_total, "4560.00", "grand_total")


# --- Tax --------------------------------------------------------------------
@pytest.mark.django_db
def test_the_breakdown_composes_into_the_grand_total_when_prices_exclude_tax(
    store_settings, dhaka_zone, make_sellable_variant, make_coupon, assert_money
):
    store_settings.tax_rate = Decimal("15.00")
    store_settings.tax_inclusive_pricing = False
    store_settings.save()
    variant = make_sellable_variant(price="1000.00")
    make_coupon("FLAT200", discount_type=DiscountType.FIXED, value="200.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]),
        district="Dhaka",
        coupon_code="FLAT200",
    )

    assert_money(result.subtotal, "2000.00", "subtotal")
    assert_money(result.discount_total, "200.00", "discount_total")
    assert_money(result.shipping_total, "60.00", "shipping_total")
    assert_money(result.tax_total, "270.00", "tax_total")
    assert_money(result.grand_total, "2130.00", "grand_total")
    assert (
        result.subtotal
        - result.discount_total
        + result.shipping_total
        + result.tax_total
        == result.grand_total
    )


@pytest.mark.django_db
def test_the_breakdown_composes_into_the_grand_total_when_prices_already_include_tax(
    store_settings, dhaka_zone, make_sellable_variant, assert_money
):
    store_settings.tax_rate = Decimal("15.00")
    store_settings.tax_inclusive_pricing = True
    store_settings.save()
    variant = make_sellable_variant(price="1150.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]), district="Dhaka"
    )

    assert result.tax_inclusive is True
    assert_money(result.subtotal, "2300.00", "subtotal")
    # The VAT is reported because the receipt must show it, but it is already
    # inside the price and must not be charged a second time.
    assert_money(result.tax_total, "300.00", "tax_total")
    assert_money(result.grand_total, "2360.00", "grand_total")
    assert (
        result.subtotal - result.discount_total + result.shipping_total
        == result.grand_total
    )


@pytest.mark.django_db
def test_tax_is_charged_on_merchandise_only_and_never_on_the_delivery_charge(
    store_settings, dhaka_zone, make_sellable_variant, assert_money
):
    store_settings.tax_rate = Decimal("15.00")
    store_settings.save()
    variant = make_sellable_variant(price="1000.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 1)]), district="Dhaka"
    )

    assert_money(result.tax_total, "150.00", "tax_total")
    assert result.tax_total != Decimal("159.00")  # what taxing shipping would give
    assert_money(result.grand_total, "1210.00", "grand_total")


@pytest.mark.django_db
def test_tax_is_charged_on_the_discounted_total_not_on_the_undiscounted_subtotal(
    store_settings, make_sellable_variant, make_coupon, assert_money
):
    store_settings.tax_rate = Decimal("15.00")
    store_settings.save()
    variant = make_sellable_variant(price="1000.00")
    make_coupon("HALF", discount_type=DiscountType.PERCENT, value="50.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]), coupon_code="HALF"
    )

    assert_money(result.discount_total, "1000.00", "discount_total")
    assert_money(result.tax_total, "150.00", "tax_total")
    assert_money(result.grand_total, "1150.00", "grand_total")


@pytest.mark.django_db
def test_the_tax_rate_in_force_at_computation_is_snapshotted_onto_the_result(
    store_settings, make_sellable_variant, assert_money
):
    store_settings.tax_rate = Decimal("15.00")
    store_settings.save()
    variant = make_sellable_variant(price="1000.00")
    lines = totals_services.build_lines([(variant, 2)])

    quoted_at_fifteen = totals_services.compute_totals(lines=lines)

    store_settings.tax_rate = Decimal("5.00")
    store_settings.save()
    quoted_at_five = totals_services.compute_totals(lines=lines)

    assert_money(quoted_at_fifteen.tax_rate, "15.00", "tax_rate")
    assert_money(quoted_at_fifteen.tax_total, "300.00", "tax_total")
    assert_money(quoted_at_five.tax_rate, "5.00", "tax_rate")
    assert_money(quoted_at_five.tax_total, "100.00", "tax_total")


@pytest.mark.django_db
def test_a_settings_snapshot_handed_to_the_engine_overrides_the_live_store_settings(
    store_settings, make_sellable_variant, assert_money
):
    # Placement prices against the settings it captured, so the engine has to
    # honour a snapshot rather than always re-reading the singleton.
    store_settings.tax_rate = Decimal("15.00")
    store_settings.save()
    variant = make_sellable_variant(price="1000.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]),
        settings=StoreSettings(tax_rate=Decimal("7.50"), tax_inclusive_pricing=False),
    )

    assert_money(result.tax_rate, "7.50", "tax_rate")
    assert_money(result.tax_total, "150.00", "tax_total")


@pytest.mark.django_db
def test_an_order_keeps_the_tax_rate_it_was_placed_under_after_the_store_changes_it(
    store_settings, dhaka_zone, make_sellable_variant
):
    store_settings.tax_rate = Decimal("15.00")
    store_settings.save()
    variant = make_sellable_variant(price="1000.00", stock=5)

    order, created = placement_services.place_order(
        idempotency_key="snapshot-the-vat-rate",
        payment_method=PaymentMethod.COD,
        shipping_address={
            "recipient_name": "Rafiq Hasan",
            "phone": "01712345678",
            "division": "Dhaka",
            "district": "Dhaka",
            "street": "House 42, Road 7, Dhanmondi",
        },
        email="buyer@example.com",
        items=[{"variant_id": variant.pk, "quantity": 1}],
    )

    assert created is True
    assert order.tax_rate_applied == Decimal("15.00")
    assert order.tax_total == Decimal("150.00")
    assert order.grand_total == Decimal("1210.00")

    store_settings.tax_rate = Decimal("5.00")
    store_settings.save()
    order.refresh_from_db()

    # A VAT change tomorrow must not rewrite what was charged today.
    assert order.tax_rate_applied == Decimal("15.00")
    assert order.tax_total == Decimal("150.00")
    assert order.grand_total == Decimal("1210.00")


# --- Coupons ----------------------------------------------------------------
@pytest.mark.django_db
def test_no_coupon_code_leaves_the_discount_at_zero_and_the_coupon_unset(
    store_settings, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="1000.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]), coupon_code=""
    )

    assert result.coupon is None
    assert_money(result.discount_total, "0.00", "discount_total")


@pytest.mark.django_db
def test_a_percentage_coupon_takes_its_share_of_the_eligible_subtotal(
    store_settings, make_sellable_variant, make_coupon, assert_money
):
    variant = make_sellable_variant(price="1000.00")
    coupon = make_coupon("SAVE10", discount_type=DiscountType.PERCENT, value="10.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]), coupon_code="save10"
    )

    assert result.coupon == coupon
    assert_money(result.discount_total, "200.00", "discount_total")
    assert_money(result.grand_total, "1800.00", "grand_total")


@pytest.mark.django_db
def test_a_percentage_coupon_discounts_merchandise_only_and_never_the_shipping(
    store_settings, dhaka_zone, make_sellable_variant, make_coupon, assert_money
):
    variant = make_sellable_variant(price="1000.00")
    make_coupon("SAVE10", discount_type=DiscountType.PERCENT, value="10.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]),
        district="Dhaka",
        coupon_code="SAVE10",
    )

    # 10% of 2000, not 10% of 2060.
    assert_money(result.discount_total, "200.00", "discount_total")
    assert_money(result.grand_total, "1860.00", "grand_total")


@pytest.mark.django_db
def test_a_percentage_coupons_max_discount_caps_what_it_can_take_off(
    store_settings, make_sellable_variant, make_coupon, assert_money
):
    variant = make_sellable_variant(price="1000.00")
    make_coupon(
        "BIG20", discount_type=DiscountType.PERCENT, value="20.00", max_discount="150.00"
    )

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]), coupon_code="BIG20"
    )

    assert_money(result.discount_total, "150.00", "discount_total")


@pytest.mark.django_db
def test_a_fixed_coupon_reaches_the_grand_total_at_its_face_value(
    store_settings, make_sellable_variant, make_coupon, assert_money
):
    variant = make_sellable_variant(price="1000.00")
    make_coupon("FLAT250", discount_type=DiscountType.FIXED, value="250.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 2)]), coupon_code="FLAT250"
    )

    assert_money(result.discount_total, "250.00", "discount_total")
    assert_money(result.grand_total, "1750.00", "grand_total")


@pytest.mark.django_db
def test_a_category_scoped_coupon_excludes_a_line_from_another_category(
    store_settings, category, make_sellable_variant, make_coupon, assert_money
):
    mice = make_category("Mice")
    laptop = make_sellable_variant(price="2000.00", name="Laptop")
    mouse = make_sellable_variant(price="1000.00", name="Mouse", in_category=mice)
    make_coupon(
        "LAPTOP10",
        discount_type=DiscountType.PERCENT,
        value="10.00",
        scope_type=ScopeType.CATEGORY,
        scope_ids=[category.pk],
    )

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(laptop, 1), (mouse, 1)]),
        coupon_code="LAPTOP10",
    )

    # 10% of the 2000 laptop, not of the 3000 basket.
    assert_money(result.subtotal, "3000.00", "subtotal")
    assert_money(result.discount_total, "200.00", "discount_total")
    assert_money(result.grand_total, "2800.00", "grand_total")


@pytest.mark.django_db
def test_a_category_scoped_coupon_also_covers_the_children_of_the_category_it_names(
    store_settings, make_sellable_variant, make_coupon, assert_money
):
    computers = make_category("Computers")
    gaming = make_category("Gaming Laptops", parent=computers)
    variant = make_sellable_variant(price="2000.00", in_category=gaming)
    make_coupon(
        "COMPUTERS10",
        discount_type=DiscountType.PERCENT,
        value="10.00",
        scope_type=ScopeType.CATEGORY,
        scope_ids=[computers.pk],
    )

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 1)]), coupon_code="COMPUTERS10"
    )

    assert_money(result.discount_total, "200.00", "discount_total")


@pytest.mark.django_db
def test_a_product_scoped_coupon_discounts_only_the_product_it_names(
    store_settings, make_sellable_variant, make_coupon, assert_money
):
    chosen = make_sellable_variant(price="2000.00", name="Chosen")
    other = make_sellable_variant(price="5000.00", name="Other")
    make_coupon(
        "ONEPRODUCT",
        discount_type=DiscountType.PERCENT,
        value="10.00",
        scope_type=ScopeType.PRODUCT,
        scope_ids=[chosen.product_id],
    )

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(chosen, 1), (other, 1)]),
        coupon_code="ONEPRODUCT",
    )

    assert_money(result.subtotal, "7000.00", "subtotal")
    assert_money(result.discount_total, "200.00", "discount_total")


@pytest.mark.django_db
def test_a_coupon_that_matches_nothing_in_the_basket_is_refused_not_applied_as_zero(
    store_settings, make_sellable_variant, make_coupon
):
    in_basket = make_sellable_variant(price="2000.00", name="In basket")
    elsewhere = make_sellable_variant(price="2000.00", name="Elsewhere")
    make_coupon(
        "ELSEWHERE",
        discount_type=DiscountType.PERCENT,
        value="10.00",
        scope_type=ScopeType.PRODUCT,
        scope_ids=[elsewhere.product_id],
    )

    with pytest.raises(DomainError) as excinfo:
        totals_services.compute_totals(
            lines=totals_services.build_lines([(in_basket, 1)]),
            coupon_code="ELSEWHERE",
        )

    assert excinfo.value.code == "COUPON_NOT_APPLICABLE"
    assert excinfo.value.field == "coupon_code"


@pytest.mark.django_db
def test_a_fixed_coupon_larger_than_the_eligible_lines_takes_no_more_than_they_cost(
    store_settings, make_sellable_variant, make_coupon, assert_money
):
    cheap = make_sellable_variant(price="300.00", name="Cheap")
    dear = make_sellable_variant(price="100000.00", name="Dear")
    make_coupon(
        "FLAT5000",
        discount_type=DiscountType.FIXED,
        value="5000.00",
        scope_type=ScopeType.PRODUCT,
        scope_ids=[cheap.product_id],
    )

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(cheap, 1), (dear, 1)]),
        coupon_code="FLAT5000",
    )

    # A 5000 coupon against a 300 eligible line takes 300 -- never 5000, and
    # certainly never spills onto the 100000 line it does not cover.
    assert_money(result.subtotal, "100300.00", "subtotal")
    assert_money(result.discount_total, "300.00", "discount_total")
    assert_money(result.grand_total, "100000.00", "grand_total")


@pytest.mark.django_db
def test_a_discount_can_never_drive_the_grand_total_below_zero(
    store_settings, make_sellable_variant, make_coupon, assert_money
):
    variant = make_sellable_variant(price="300.00")
    make_coupon("FLAT5000", discount_type=DiscountType.FIXED, value="5000.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 1)]), coupon_code="FLAT5000"
    )

    assert_money(result.discount_total, "300.00", "discount_total")
    assert_money(result.grand_total, "0.00", "grand_total")
    assert result.grand_total >= Decimal("0.00")


@pytest.mark.django_db
def test_a_basket_fully_discounted_still_pays_for_its_delivery(
    store_settings, dhaka_zone, make_sellable_variant, make_coupon, assert_money
):
    variant = make_sellable_variant(price="300.00")
    make_coupon("FLAT5000", discount_type=DiscountType.FIXED, value="5000.00")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 1)]),
        district="Dhaka",
        coupon_code="FLAT5000",
    )

    assert_money(result.grand_total, "60.00", "grand_total")


@pytest.mark.django_db
def test_an_unknown_coupon_code_is_refused_with_its_own_code(
    store_settings, make_sellable_variant
):
    variant = make_sellable_variant(price="1000.00")

    with pytest.raises(DomainError) as excinfo:
        totals_services.compute_totals(
            lines=totals_services.build_lines([(variant, 1)]), coupon_code="NOSUCHCODE"
        )

    assert excinfo.value.code == "COUPON_NOT_FOUND"


@pytest.mark.django_db
def test_an_expired_coupon_is_refused_on_every_recomputation(
    store_settings, make_sellable_variant, make_coupon
):
    now = timezone.now()
    variant = make_sellable_variant(price="1000.00")
    make_coupon(
        "LASTMONTH",
        valid_from=now - timedelta(days=30),
        valid_until=now - timedelta(days=1),
    )

    with pytest.raises(DomainError) as excinfo:
        totals_services.compute_totals(
            lines=totals_services.build_lines([(variant, 1)]), coupon_code="LASTMONTH"
        )

    assert excinfo.value.code == "COUPON_EXPIRED"


@pytest.mark.django_db
def test_a_coupon_below_its_minimum_order_value_is_refused(
    store_settings, make_sellable_variant, make_coupon
):
    variant = make_sellable_variant(price="1000.00")
    make_coupon("BIGSPEND", min_order_value="5000.00")

    with pytest.raises(DomainError) as excinfo:
        totals_services.compute_totals(
            lines=totals_services.build_lines([(variant, 2)]), coupon_code="BIGSPEND"
        )

    assert excinfo.value.code == "COUPON_MIN_ORDER_NOT_MET"


# --- Rounding and stability -------------------------------------------------
@pytest.mark.django_db
def test_every_money_figure_in_an_awkward_breakdown_is_quantised_to_two_places(
    store_settings, make_zone, make_sellable_variant, make_coupon, assert_money
):
    store_settings.tax_rate = Decimal("7.50")
    store_settings.save()
    make_zone(per_kg_rate="20.00", base_weight_grams=1000)
    variant = make_sellable_variant(price="333.33", stock=20, weight_grams=250)
    make_coupon("TWELVEHALF", discount_type=DiscountType.PERCENT, value="12.50")

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, 7)]),
        district="Dhaka",
        coupon_code="TWELVEHALF",
    )

    # 2333.31 subtotal, 291.66375 discount rounded to 291.66, 1750g weight
    # billing one extra kilogram, 153.12375 of VAT rounded to 153.12.
    assert_money(result.subtotal, "2333.31", "subtotal")
    assert_money(result.discount_total, "291.66", "discount_total")
    assert_money(result.shipping_total, "80.00", "shipping_total")
    assert_money(result.tax_total, "153.12", "tax_total")
    assert_money(result.grand_total, "2274.77", "grand_total")
    assert_money(result.tax_rate, "7.50", "tax_rate")
    for field in MONEY_FIELDS:
        value = getattr(result, field)
        assert type(value) is Decimal, field
        assert value.as_tuple().exponent == -2, "{0} was {1}".format(field, value)
    assert (
        result.subtotal
        - result.discount_total
        + result.shipping_total
        + result.tax_total
        == result.grand_total
    )


@pytest.mark.django_db
def test_every_line_total_in_a_breakdown_is_quantised_to_two_places(
    store_settings, make_sellable_variant, assert_money
):
    first = make_sellable_variant(price="333.33", stock=20)
    second = make_sellable_variant(price="0.01", stock=20)

    result = totals_services.compute_totals(
        lines=totals_services.build_lines([(first, 7), (second, 3)])
    )

    assert_money(result.lines[0].line_total, "2333.31", "line_total")
    assert_money(result.lines[1].line_total, "0.03", "line_total")
    for basket_line in result.lines:
        assert type(basket_line.line_total) is Decimal
        assert basket_line.line_total.as_tuple().exponent == -2


@pytest.mark.django_db
def test_recomputing_the_same_basket_returns_an_identical_breakdown(
    store_settings, make_zone, make_sellable_variant, make_coupon
):
    store_settings.tax_rate = Decimal("7.50")
    store_settings.save()
    make_zone(per_kg_rate="20.00", base_weight_grams=1000)
    variant = make_sellable_variant(price="333.33", stock=40, weight_grams=250)
    make_coupon("TWELVEHALF", discount_type=DiscountType.PERCENT, value="12.50")

    def price_it():
        return totals_services.compute_totals(
            lines=totals_services.build_lines([(variant, 7)]),
            district="Dhaka",
            coupon_code="TWELVEHALF",
        )

    first, second, third = price_it(), price_it(), price_it()

    for field in MONEY_FIELDS + ("tax_rate", "total_weight_grams"):
        assert getattr(first, field) == getattr(second, field) == getattr(third, field), field
