"""
Fixtures for the money suite -- the totals engine (`apps/orders/services/totals.py`)
and the checkout quote (`apps/orders/services/checkout.py`).

Every price, weight, rate, threshold and ceiling asserted on downstream is
stated by the test that depends on it. Nothing here reads seed data: PRD §5.4
and §5.12 give exact figures, and a suite priced from whatever happens to be in
the dev database would be asserting on a moving target.

The catalogue factories are reused rather than re-written, so a product built
here is visible to exactly the same `purchasable_variants()` predicate the
storefront uses.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.tests.factories import make_category, make_product, make_variant
from apps.dashboard.models import StoreSettings
from apps.promotions.models import Coupon, DiscountType, ScopeType
from apps.shipping.models import ShippingZone


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def quote_url():
    return reverse("orders:checkout-quote")


@pytest.fixture
def assert_money():
    """
    A money figure is a two-decimal-place `Decimal` and nothing else.

    The type check is the point: a float that happened to compare equal to the
    expected value would still be a bug, because it is one arithmetic step away
    from charging a customer 284059.99999999994.
    """

    def _assert(value, expected, label="value"):
        assert type(value) is Decimal, "{0} is {1}, not Decimal".format(
            label, type(value).__name__
        )
        assert value == Decimal(expected), "{0} was {1}, expected {2}".format(
            label, value, expected
        )
        assert value.as_tuple().exponent == -2, "{0} was not quantised to 2dp: {1}".format(
            label, value
        )

    return _assert


@pytest.fixture
def store_settings(db):
    """
    The store singleton, reset to a deliberately boring baseline: no VAT, Cash
    on Delivery on with no ceiling. Each test switches on only the rule it is
    about, so a failure names one cause.
    """
    settings = StoreSettings.load()
    settings.tax_rate = Decimal("0.00")
    settings.tax_inclusive_pricing = False
    settings.cod_enabled = True
    settings.cod_max_order_value = None
    settings.save()
    return settings


@pytest.fixture
def category(db):
    return make_category("Laptops")


@pytest.fixture
def make_sellable_variant(db, category):
    """
    A purchasable variant at the price, stock and weight the test names.

    Price and weight are the values under test, so they are always stated by the
    caller and never filled in by a fixture library.
    """

    def _make(
        *,
        price="1000.00",
        stock=10,
        weight_grams=0,
        name="Test Product",
        option_label="",
        in_category=None,
    ):
        product = make_product(in_category or category, name=name, variants=[])
        return make_variant(
            product,
            price=price,
            stock=stock,
            weight_grams=weight_grams,
            option_label=option_label,
        )

    return _make


@pytest.fixture
def make_zone(db):
    def _make(
        *,
        name="Inside Dhaka",
        flat_rate="60.00",
        per_kg_rate="0.00",
        base_weight_grams=1000,
        free_shipping_threshold=None,
        cod_allowed=True,
        districts=("Dhaka",),
        sort_order=0,
        is_active=True,
    ):
        return ShippingZone.objects.create(
            name=name,
            flat_rate=Decimal(flat_rate),
            per_kg_rate=Decimal(per_kg_rate),
            base_weight_grams=base_weight_grams,
            free_shipping_threshold=(
                None
                if free_shipping_threshold is None
                else Decimal(free_shipping_threshold)
            ),
            cod_allowed=cod_allowed,
            districts=list(districts),
            sort_order=sort_order,
            is_active=is_active,
        )

    return _make


@pytest.fixture
def dhaka_zone(make_zone):
    """The plain flat-rate zone most of these tests price against."""
    return make_zone()


@pytest.fixture
def make_coupon(db):
    def _make(
        code="SAVE10",
        *,
        discount_type=DiscountType.PERCENT,
        value="10.00",
        max_discount=None,
        min_order_value="0.00",
        scope_type=ScopeType.ALL,
        scope_ids=None,
        usage_limit=None,
        per_user_limit=1,
        is_active=True,
        valid_from=None,
        valid_until=None,
    ):
        now = timezone.now()
        return Coupon.objects.create(
            code=code,
            discount_type=discount_type,
            value=Decimal(value),
            max_discount=None if max_discount is None else Decimal(max_discount),
            min_order_value=Decimal(min_order_value),
            valid_from=valid_from or (now - timedelta(days=1)),
            valid_until=valid_until or (now + timedelta(days=30)),
            usage_limit=usage_limit,
            per_user_limit=per_user_limit,
            scope_type=scope_type,
            scope_ids=list(scope_ids or []),
            is_active=is_active,
        )

    return _make


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="shopper@example.com",
        password="Str0ngPass!2026",
        is_email_verified=True,
    )
