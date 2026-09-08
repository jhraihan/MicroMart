"""
Coupon validation, scoping and redemption (PRD 5.10, FR-CPN-1..8).

Three things this suite exists to pin down:

1. **Every rejection has its own stable code.** FR-CPN-7 makes the code, not
   the message, the client's contract, so every assertion here is on
   `DomainError.code` and never on wording.
2. **Discount is computed on the eligible lines only** (FR-CPN-3), and can
   never exceed the merchandise it discounts -- a coupon is a discount, not
   store credit.
3. **One coupon per order. No stacking.** Asserted at all three layers that
   could break it: the schema, the service, and the checkout API.

`lines` is duck-typed on purpose -- the cart, the quote and order placement
each pass their own line objects -- so most tests here use the minimal `Line`
below, which is exactly the contract the service documents. One test drives a
real `apps.orders.services.totals.BasketLine` through the same code so the
duck-typing cannot silently rot.
"""
import itertools
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.tests.factories import make_category, make_product
from apps.orders.models import Order, PaymentMethod
from apps.promotions.models import Coupon, CouponRedemption, DiscountType, ScopeType
from apps.promotions.services import coupons as coupon_services
from config.exceptions import DomainError

_seq = itertools.count(1)


def _next(prefix):
    return "{0}-{1}".format(prefix, next(_seq))


# ---------------------------------------------------------------------------
# Fixtures -- plain builders, following apps/catalog/tests/factories.py: the
# values under test (value, min spend, window, scope) are always stated by the
# test that depends on them, never filled in silently.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Line:
    """The whole duck-typed contract `coupons.py` documents: variant + total."""

    variant: object
    line_total: Decimal


def make_coupon(
    code="WELCOME10",
    *,
    discount_type=DiscountType.PERCENT,
    value="10.00",
    max_discount=None,
    min_order_value="0.00",
    valid_from=None,
    valid_until=None,
    usage_limit=None,
    per_user_limit=1,
    scope_type=ScopeType.ALL,
    scope_ids=None,
    is_active=True,
):
    now = timezone.now()
    return Coupon.objects.create(
        code=code,
        discount_type=discount_type,
        value=Decimal(value),
        max_discount=None if max_discount is None else Decimal(max_discount),
        min_order_value=Decimal(min_order_value),
        valid_from=valid_from if valid_from is not None else now - timedelta(days=1),
        valid_until=valid_until if valid_until is not None else now + timedelta(days=30),
        usage_limit=usage_limit,
        per_user_limit=per_user_limit,
        scope_type=scope_type,
        scope_ids=[] if scope_ids is None else scope_ids,
        is_active=is_active,
    )


def make_order(*, user=None, email="buyer@example.com"):
    """A minimal order row -- only the redemption's FK target matters here."""
    return Order.objects.create(
        reference=_next("ORD"),
        user=user,
        email=email,
        phone="01700000000",
        ship_recipient_name="Buyer",
        ship_phone="01700000000",
        ship_division="Dhaka",
        ship_district="Dhaka",
        ship_street="1 Test Road",
        payment_method=PaymentMethod.COD,
        idempotency_key=_next("idem"),
    )


def make_customer(email="shopper@example.com"):
    return User.objects.create_user(email=email, password="Str0ngPass!2026")


def line_for(product, amount="1000.00"):
    return Line(variant=product.variants.first(), line_total=Decimal(amount))


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def quote_url():
    return reverse("orders:checkout-quote")


# ---------------------------------------------------------------------------
# find_coupon
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_find_coupon_rejects_a_blank_code_before_it_ever_reaches_the_database():
    for blank in ("", "   ", None):
        with pytest.raises(DomainError) as excinfo:
            coupon_services.find_coupon(blank)
        assert excinfo.value.code == "COUPON_REQUIRED"
        assert excinfo.value.field == "coupon_code"


@pytest.mark.django_db
def test_find_coupon_raises_coupon_not_found_for_a_code_that_does_not_exist():
    with pytest.raises(DomainError) as excinfo:
        coupon_services.find_coupon("NOSUCHCODE")
    assert excinfo.value.code == "COUPON_NOT_FOUND"
    assert excinfo.value.field == "coupon_code"


@pytest.mark.django_db
def test_find_coupon_matches_case_insensitively_and_ignores_surrounding_whitespace():
    coupon = make_coupon("WELCOME10")
    assert coupon_services.find_coupon("  welcome10  ") == coupon
    assert coupon_services.find_coupon("WeLcOmE10") == coupon


@pytest.mark.django_db
def test_find_coupon_still_returns_an_inactive_coupon_because_only_validation_may_reject_it():
    # The split matters: find_coupon answers "does this code exist", and
    # validate_coupon answers "may it be used". Folding the second into the
    # first would collapse four distinct FR-CPN-7 codes into COUPON_NOT_FOUND.
    coupon = make_coupon("DEADCODE", is_active=False)
    assert coupon_services.find_coupon("DEADCODE") == coupon


@pytest.mark.django_db
def test_find_coupon_still_returns_an_expired_coupon_because_only_validation_may_reject_it():
    now = timezone.now()
    coupon = make_coupon(
        "LASTYEAR", valid_from=now - timedelta(days=400), valid_until=now - timedelta(days=1)
    )
    assert coupon_services.find_coupon("LASTYEAR") == coupon


@pytest.mark.django_db(transaction=True)
def test_find_coupon_with_for_update_takes_a_row_lock_and_therefore_needs_a_transaction():
    # transaction=True because select_for_update never engages inside pytest's
    # own wrapping transaction -- and because the assertion below is precisely
    # that Django refuses the lock when there is no real transaction open.
    make_coupon("LOCKME")
    try:
        with pytest.raises(Exception) as excinfo:
            coupon_services.find_coupon("LOCKME", for_update=True)
        assert "select_for_update" in str(excinfo.value).lower()

        with transaction.atomic():
            locked = coupon_services.find_coupon("LOCKME", for_update=True)
            assert locked.code == "LOCKME"
    finally:
        Coupon.objects.all().delete()


# ---------------------------------------------------------------------------
# validate_coupon -- one test per FR-CPN-7 rejection code
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_validate_coupon_rejects_a_coupon_that_has_been_switched_off():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(is_active=False)

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00")
        )
    assert excinfo.value.code == "COUPON_INACTIVE"
    assert excinfo.value.field == "coupon_code"


@pytest.mark.django_db
def test_validate_coupon_rejects_a_coupon_whose_start_date_has_not_arrived_yet():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    now = timezone.now()
    coupon = make_coupon(
        valid_from=now + timedelta(days=1), valid_until=now + timedelta(days=30)
    )

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00")
        )
    assert excinfo.value.code == "COUPON_NOT_YET_VALID"


@pytest.mark.django_db
def test_validate_coupon_rejects_a_coupon_whose_end_date_has_passed():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    now = timezone.now()
    coupon = make_coupon(
        valid_from=now - timedelta(days=30), valid_until=now - timedelta(seconds=1)
    )

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00")
        )
    assert excinfo.value.code == "COUPON_EXPIRED"


@pytest.mark.django_db
def test_validate_coupon_rejects_a_basket_below_the_minimum_spend():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(min_order_value="2000.00")

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon,
            lines=[line_for(product, "1999.99")],
            subtotal=Decimal("1999.99"),
        )
    assert excinfo.value.code == "COUPON_MIN_ORDER_NOT_MET"
    assert excinfo.value.field == "coupon_code"


@pytest.mark.django_db
def test_validate_coupon_accepts_a_basket_exactly_on_the_minimum_spend():
    # The boundary is inclusive: "minimum order of 2000" means 2000 qualifies.
    category = make_category("Laptops")
    product = make_product(category, price="2000.00")
    coupon = make_coupon(min_order_value="2000.00")

    discount = coupon_services.validate_coupon(
        coupon=coupon, lines=[line_for(product, "2000.00")], subtotal=Decimal("2000.00")
    )
    assert discount == Decimal("200.00")


@pytest.mark.django_db
def test_validate_coupon_rejects_a_coupon_that_has_hit_its_global_usage_limit():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(usage_limit=2, per_user_limit=99)

    for _ in range(2):
        CouponRedemption.objects.create(
            coupon=coupon, user=None, order=make_order(), discount_amount=Decimal("100.00")
        )

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00")
        )
    assert excinfo.value.code == "COUPON_USAGE_LIMIT_REACHED"


@pytest.mark.django_db
def test_validate_coupon_accepts_the_redemption_that_lands_exactly_on_the_usage_limit():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(usage_limit=2, per_user_limit=99)
    CouponRedemption.objects.create(
        coupon=coupon, user=None, order=make_order(), discount_amount=Decimal("100.00")
    )

    # One redemption used, limit two -- the second must still be allowed.
    discount = coupon_services.validate_coupon(
        coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00")
    )
    assert discount == Decimal("100.00")


@pytest.mark.django_db
def test_validate_coupon_rejects_a_customer_who_has_reached_their_per_user_limit():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(per_user_limit=1)
    customer = make_customer()
    CouponRedemption.objects.create(
        coupon=coupon,
        user=customer,
        order=make_order(user=customer),
        discount_amount=Decimal("100.00"),
    )

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon,
            lines=[line_for(product)],
            subtotal=Decimal("1000.00"),
            user=customer,
        )
    assert excinfo.value.code == "COUPON_USER_LIMIT_REACHED"


@pytest.mark.django_db
def test_one_customers_redemption_does_not_exhaust_the_per_user_limit_of_another():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(per_user_limit=1)
    first = make_customer("first@example.com")
    second = make_customer("second@example.com")
    CouponRedemption.objects.create(
        coupon=coupon,
        user=first,
        order=make_order(user=first),
        discount_amount=Decimal("100.00"),
    )

    discount = coupon_services.validate_coupon(
        coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00"), user=second
    )
    assert discount == Decimal("100.00")


@pytest.mark.django_db
def test_a_guest_is_not_subject_to_the_per_user_limit_because_they_have_no_identity():
    # Documented in the service: only the global usage_limit bounds guests.
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(per_user_limit=1)
    CouponRedemption.objects.create(
        coupon=coupon, user=None, order=make_order(), discount_amount=Decimal("100.00")
    )

    discount = coupon_services.validate_coupon(
        coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00"), user=None
    )
    assert discount == Decimal("100.00")


@pytest.mark.django_db
def test_validate_coupon_rejects_a_category_scoped_coupon_when_the_basket_has_no_eligible_line():
    laptops = make_category("Laptops")
    mice = make_category("Mice")
    mouse = make_product(mice, price="1500.00")
    coupon = make_coupon(scope_type=ScopeType.CATEGORY, scope_ids=[laptops.pk])

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon, lines=[line_for(mouse, "1500.00")], subtotal=Decimal("1500.00")
        )
    assert excinfo.value.code == "COUPON_NOT_APPLICABLE"
    assert excinfo.value.field == "coupon_code"


@pytest.mark.django_db
def test_validate_coupon_rejects_a_product_scoped_coupon_when_the_basket_has_no_eligible_line():
    category = make_category("Laptops")
    scoped = make_product(category, name="Discounted laptop", price="1000.00")
    other = make_product(category, name="Full price laptop", price="1000.00")
    coupon = make_coupon(scope_type=ScopeType.PRODUCT, scope_ids=[scoped.pk])

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon, lines=[line_for(other)], subtotal=Decimal("1000.00")
        )
    assert excinfo.value.code == "COUPON_NOT_APPLICABLE"


@pytest.mark.django_db
def test_validate_coupon_discounts_only_the_eligible_lines_of_a_mixed_basket():
    laptops = make_category("Laptops")
    mice = make_category("Mice")
    laptop = make_product(laptops, price="100000.00")
    mouse = make_product(mice, price="1500.00")
    coupon = make_coupon(scope_type=ScopeType.CATEGORY, scope_ids=[laptops.pk])

    discount = coupon_services.validate_coupon(
        coupon=coupon,
        lines=[line_for(laptop, "100000.00"), line_for(mouse, "1500.00")],
        subtotal=Decimal("101500.00"),
    )
    # 10% of the laptop only -- the mouse is not in scope (FR-CPN-3).
    assert discount == Decimal("10000.00")


@pytest.mark.django_db
def test_validate_coupon_accepts_a_real_basket_line_from_the_totals_engine():
    # The `lines` contract is duck-typed. This is the production shape, so it
    # must keep working through exactly the same code path.
    from apps.orders.services import totals as totals_services

    category = make_category("Laptops")
    product = make_product(category, price="1000.00", stock=5)
    line = totals_services.build_line(product.variants.first(), 2)
    coupon = make_coupon()

    discount = coupon_services.validate_coupon(
        coupon=coupon, lines=[line], subtotal=Decimal("2000.00")
    )
    assert discount == Decimal("200.00")


# ---------------------------------------------------------------------------
# Scope: line_is_eligible / eligible_subtotal / _scoped_category_ids
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_coupon_scoped_to_the_whole_catalogue_treats_every_line_as_eligible():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(scope_type=ScopeType.ALL)

    assert coupon_services.line_is_eligible(coupon, line_for(product)) is True
    # Even a line with no variant at all -- scope "all" never inspects one.
    assert (
        coupon_services.line_is_eligible(
            coupon, Line(variant=None, line_total=Decimal("50.00"))
        )
        is True
    )


@pytest.mark.django_db
def test_a_product_scoped_coupon_matches_only_the_listed_products():
    category = make_category("Laptops")
    scoped = make_product(category, name="Scoped", price="1000.00")
    other = make_product(category, name="Other", price="1000.00")
    coupon = make_coupon(scope_type=ScopeType.PRODUCT, scope_ids=[scoped.pk])

    assert coupon_services.line_is_eligible(coupon, line_for(scoped)) is True
    assert coupon_services.line_is_eligible(coupon, line_for(other)) is False


@pytest.mark.django_db
def test_a_category_scoped_coupon_matches_only_products_in_that_category():
    laptops = make_category("Laptops")
    mice = make_category("Mice")
    laptop = make_product(laptops, price="1000.00")
    mouse = make_product(mice, price="1000.00")
    coupon = make_coupon(scope_type=ScopeType.CATEGORY, scope_ids=[laptops.pk])

    assert coupon_services.line_is_eligible(coupon, line_for(laptop)) is True
    assert coupon_services.line_is_eligible(coupon, line_for(mouse)) is False


@pytest.mark.django_db
def test_a_category_scoped_coupon_also_matches_a_product_filed_under_a_child_category():
    # A coupon on "Laptops" must reach "Laptops > Gaming Laptops", because that
    # is how a category page behaves and a shopper reads the two the same way.
    laptops = make_category("Laptops")
    gaming = make_category("Gaming Laptops", parent=laptops)
    gaming_laptop = make_product(gaming, price="150000.00")
    coupon = make_coupon(scope_type=ScopeType.CATEGORY, scope_ids=[laptops.pk])

    assert coupon_services.line_is_eligible(coupon, line_for(gaming_laptop)) is True
    assert coupon_services._scoped_category_ids(coupon) == {laptops.pk, gaming.pk}


@pytest.mark.django_db
def test_a_category_scope_expands_one_level_only_so_a_grandchild_is_not_covered():
    # Categories are two levels deep by design (PRD 5.2), so one level of
    # expansion is the whole tree. Stated here so a deeper taxonomy cannot
    # quietly start under-discounting.
    root = make_category("Computers")
    child = make_category("Laptops", parent=root)
    grandchild = make_category("Gaming Laptops", parent=child)
    deep_product = make_product(grandchild, price="150000.00")
    coupon = make_coupon(scope_type=ScopeType.CATEGORY, scope_ids=[root.pk])

    assert coupon_services._scoped_category_ids(coupon) == {root.pk, child.pk}
    assert coupon_services.line_is_eligible(coupon, line_for(deep_product)) is False


@pytest.mark.django_db
def test_a_scoped_coupon_cannot_match_a_line_that_carries_no_variant():
    laptops = make_category("Laptops")
    orphan = Line(variant=None, line_total=Decimal("500.00"))

    for scope_type in (ScopeType.CATEGORY, ScopeType.PRODUCT):
        coupon = make_coupon(
            code=_next("SCOPE"), scope_type=scope_type, scope_ids=[laptops.pk]
        )
        assert coupon_services.line_is_eligible(coupon, orphan) is False


@pytest.mark.django_db
def test_an_empty_or_junk_scope_id_list_matches_nothing_rather_than_everything():
    laptops = make_category("Laptops")
    laptop = make_product(laptops, price="1000.00")

    empty = make_coupon(code="EMPTY", scope_type=ScopeType.CATEGORY, scope_ids=[])
    assert coupon_services._scoped_category_ids(empty) == set()
    assert coupon_services.line_is_eligible(empty, line_for(laptop)) is False

    junk = make_coupon(
        code="JUNK", scope_type=ScopeType.PRODUCT, scope_ids=["not-an-id", None]
    )
    assert coupon_services.line_is_eligible(junk, line_for(laptop)) is False


@pytest.mark.django_db
def test_eligible_subtotal_sums_only_the_eligible_lines_and_returns_two_decimal_places():
    laptops = make_category("Laptops")
    mice = make_category("Mice")
    laptop = make_product(laptops, price="1000.00")
    mouse = make_product(mice, price="1500.00")
    coupon = make_coupon(scope_type=ScopeType.CATEGORY, scope_ids=[laptops.pk])

    total = coupon_services.eligible_subtotal(
        coupon, [line_for(laptop, "1000.00"), line_for(mouse, "1500.00")]
    )
    assert total == Decimal("1000.00")
    assert total.as_tuple().exponent == -2


@pytest.mark.django_db
def test_eligible_subtotal_of_a_basket_with_nothing_in_scope_is_zero_not_the_subtotal():
    laptops = make_category("Laptops")
    mice = make_category("Mice")
    mouse = make_product(mice, price="1500.00")
    coupon = make_coupon(scope_type=ScopeType.CATEGORY, scope_ids=[laptops.pk])

    assert coupon_services.eligible_subtotal(coupon, [line_for(mouse, "1500.00")]) == (
        Decimal("0.00")
    )


# ---------------------------------------------------------------------------
# compute_discount
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_percentage_coupon_takes_that_percentage_of_the_eligible_subtotal():
    coupon = make_coupon(discount_type=DiscountType.PERCENT, value="15.00")
    assert coupon_services.compute_discount(coupon, Decimal("2000.00")) == Decimal("300.00")


@pytest.mark.django_db
def test_a_percentage_discount_is_capped_by_max_discount_when_one_is_set():
    coupon = make_coupon(
        discount_type=DiscountType.PERCENT, value="20.00", max_discount="1000.00"
    )
    # 20% of 100000 would be 20000; the cap is what the shop actually gives up.
    assert coupon_services.compute_discount(coupon, Decimal("100000.00")) == Decimal(
        "1000.00"
    )
    # Below the cap the percentage still governs.
    assert coupon_services.compute_discount(coupon, Decimal("1000.00")) == Decimal(
        "200.00"
    )


@pytest.mark.django_db
def test_a_fixed_coupon_takes_its_face_value_off_the_eligible_subtotal():
    coupon = make_coupon(discount_type=DiscountType.FIXED, value="500.00")
    assert coupon_services.compute_discount(coupon, Decimal("2000.00")) == Decimal("500.00")


@pytest.mark.django_db
def test_a_fixed_discount_larger_than_the_basket_is_capped_at_the_eligible_subtotal():
    # A discount is a discount, never store credit and never a negative total.
    coupon = make_coupon(discount_type=DiscountType.FIXED, value="500.00")
    assert coupon_services.compute_discount(coupon, Decimal("300.00")) == Decimal("300.00")


@pytest.mark.django_db
def test_a_percentage_over_one_hundred_is_still_capped_at_the_eligible_subtotal():
    coupon = make_coupon(discount_type=DiscountType.PERCENT, value="150.00")
    assert coupon_services.compute_discount(coupon, Decimal("1000.00")) == Decimal(
        "1000.00"
    )


@pytest.mark.django_db
def test_a_discount_against_an_empty_or_negative_eligible_subtotal_is_zero():
    coupon = make_coupon(discount_type=DiscountType.FIXED, value="500.00")
    assert coupon_services.compute_discount(coupon, Decimal("0.00")) == Decimal("0.00")
    assert coupon_services.compute_discount(coupon, Decimal("-10.00")) == Decimal("0.00")


@pytest.mark.django_db
def test_a_percentage_discount_is_rounded_to_two_decimal_places_like_every_other_money_value():
    coupon = make_coupon(discount_type=DiscountType.PERCENT, value="7.50")
    # 7.5% of 333.33 is 24.999750 -- half-up to 25.00, never a float.
    discount = coupon_services.compute_discount(coupon, Decimal("333.33"))
    assert discount == Decimal("25.00")
    assert discount.as_tuple().exponent == -2


# ---------------------------------------------------------------------------
# record_redemption / release_redemption (FR-CPN-5, FR-CPN-8)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_recording_a_redemption_writes_a_row_that_ties_the_coupon_to_the_order_and_customer():
    coupon = make_coupon()
    customer = make_customer()
    order = make_order(user=customer)

    redemption = coupon_services.record_redemption(
        coupon=coupon, user=customer, order=order, discount_amount=Decimal("100.005")
    )

    assert redemption.coupon_id == coupon.pk
    assert redemption.user_id == customer.pk
    assert redemption.order_id == order.pk
    assert redemption.discount_amount == Decimal("100.01")


@pytest.mark.django_db
def test_a_guest_redemption_is_recorded_against_the_order_with_no_user_attached():
    coupon = make_coupon()
    order = make_order()

    redemption = coupon_services.record_redemption(
        coupon=coupon, user=None, order=order, discount_amount=Decimal("100.00")
    )
    assert redemption.user_id is None


@pytest.mark.django_db
def test_releasing_a_redemption_returns_the_usage_allowance_so_the_customer_may_use_it_again():
    # FR-CPN-8: cancelling before shipment must not burn the customer's coupon.
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(per_user_limit=1)
    customer = make_customer()
    order = make_order(user=customer)

    coupon_services.record_redemption(
        coupon=coupon, user=customer, order=order, discount_amount=Decimal("100.00")
    )
    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon,
            lines=[line_for(product)],
            subtotal=Decimal("1000.00"),
            user=customer,
        )
    assert excinfo.value.code == "COUPON_USER_LIMIT_REACHED"

    assert coupon_services.release_redemption(order) is True

    # Same customer, same coupon, after the cancellation -- allowed again.
    assert coupon_services.validate_coupon(
        coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00"), user=customer
    ) == Decimal("100.00")


@pytest.mark.django_db
def test_releasing_a_redemption_also_returns_the_global_usage_allowance():
    category = make_category("Laptops")
    product = make_product(category, price="1000.00")
    coupon = make_coupon(usage_limit=1, per_user_limit=99)
    order = make_order()
    coupon_services.record_redemption(
        coupon=coupon, user=None, order=order, discount_amount=Decimal("100.00")
    )

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00")
        )
    assert excinfo.value.code == "COUPON_USAGE_LIMIT_REACHED"

    coupon_services.release_redemption(order)
    assert coupon.redemption_count == 0
    assert coupon_services.validate_coupon(
        coupon=coupon, lines=[line_for(product)], subtotal=Decimal("1000.00")
    ) == Decimal("100.00")


@pytest.mark.django_db
def test_releasing_an_order_that_never_used_a_coupon_reports_that_nothing_was_released():
    assert coupon_services.release_redemption(make_order()) is False


@pytest.mark.django_db
def test_releasing_a_redemption_leaves_the_coupon_itself_untouched():
    # The row is deleted, not the coupon -- Order.coupon still records which
    # code a cancelled order used, so promotion reporting keeps its history.
    coupon = make_coupon()
    order = make_order()
    coupon_services.record_redemption(
        coupon=coupon, user=None, order=order, discount_amount=Decimal("100.00")
    )

    coupon_services.release_redemption(order)

    assert Coupon.objects.filter(pk=coupon.pk).exists()
    assert Order.objects.filter(pk=order.pk).exists()


# ---------------------------------------------------------------------------
# INVARIANT: one coupon per order. No stacking (PRD 5.10, FR-CPN-6).
# Asserted at every layer that could break it.
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_an_order_holds_a_single_coupon_reference_so_two_cannot_be_attached():
    field = Order._meta.get_field("coupon")
    assert field.many_to_one is True
    assert field.many_to_many is False


@pytest.mark.django_db
def test_a_second_redemption_against_the_same_order_is_refused_by_the_database():
    # CouponRedemption.order is a OneToOne. That constraint is the last line of
    # defence: even a service bug cannot land two coupons on one order.
    first = make_coupon("TEN", value="10.00")
    second = make_coupon("TWENTY", value="20.00")
    order = make_order()

    coupon_services.record_redemption(
        coupon=first, user=None, order=order, discount_amount=Decimal("100.00")
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            coupon_services.record_redemption(
                coupon=second, user=None, order=order, discount_amount=Decimal("200.00")
            )

    assert CouponRedemption.objects.filter(order=order).count() == 1


@pytest.mark.django_db
def test_the_checkout_api_takes_exactly_one_coupon_code_and_refuses_a_list_of_them(
    api, quote_url
):
    category = make_category("Laptops")
    product = make_product(category, price="1000.00", stock=5)
    make_coupon("TEN", value="10.00")
    make_coupon("TWENTY", value="20.00")

    response = api.post(
        quote_url,
        {
            "items": [{"variant_id": product.variants.first().pk, "quantity": 1}],
            "coupon_code": ["TEN", "TWENTY"],
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "coupon_code"


@pytest.mark.django_db
def test_two_codes_smuggled_into_the_single_coupon_field_match_no_coupon_at_all(
    api, quote_url
):
    category = make_category("Laptops")
    product = make_product(category, price="1000.00", stock=5)
    make_coupon("TEN", value="10.00")
    make_coupon("TWENTY", value="20.00")

    response = api.post(
        quote_url,
        {
            "items": [{"variant_id": product.variants.first().pk, "quantity": 1}],
            "coupon_code": "TEN,TWENTY",
        },
        format="json",
    )

    # No stacking: "TEN,TWENTY" is looked up as one literal code and matches
    # nothing, so neither discount is applied. The quote reports the miss in
    # `coupon_error` rather than failing -- an invalid coupon never blanks a
    # quote (FR-CPN-7, docs/api-contract-cart-checkout-orders.md) -- but the
    # property under test is that no discount is granted.
    assert response.status_code == 200
    body = response.json()
    assert body["coupon"] is None
    assert body["coupon_error"]["code"] == "COUPON_NOT_FOUND"
    assert body["discount_total"] == "0.00"
    assert body["subtotal"] == "1000.00"


@pytest.mark.django_db
def test_a_quote_applies_the_one_supplied_coupon_and_reports_it_as_a_single_coupon(
    api, quote_url
):
    category = make_category("Laptops")
    product = make_product(category, price="1000.00", stock=5)
    make_coupon("TEN", value="10.00")

    response = api.post(
        quote_url,
        {
            "items": [{"variant_id": product.variants.first().pk, "quantity": 1}],
            "coupon_code": "ten",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["coupon"]["code"] == "TEN"
    # Money crosses the wire as a decimal string, never a float (PRD 6.5).
    assert body["discount_total"] == "100.00"
    assert body["subtotal"] == "1000.00"
