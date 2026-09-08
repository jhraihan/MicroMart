"""
Fixtures for the admin order pipeline and dashboard metrics
(PRD 7.3, US-A1, US-A3, US-A8, US-T1).

Written in the style of apps/orders/tests/conftest.py: every row a test
asserts on is built by that test, and the two things these tests turn on --
order *status* and *when* an order was placed -- are always stated by the
caller.

`make_order` writes `placed_at` with a queryset UPDATE rather than passing it
to `create()`, because the column is `auto_now_add`. That is the only honest
way to build a week of trading history without sleeping through it.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.catalog.tests.factories import make_category, make_product
from apps.dashboard.models import StoreSettings
from apps.orders.models import Order, OrderItem, OrderStatus, PaymentMethod

PASSWORD = "Str0ngPass!2026"


# ---------------------------------------------------------------------------
# Clients and people
# ---------------------------------------------------------------------------
@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def admin(db):
    return User.objects.create_user(
        email="owner@example.com",
        password=PASSWORD,
        full_name="Owner",
        role=Role.ADMIN,
    )


@pytest.fixture
def staff_member(db):
    """
    Staff, not admin (PRD 4.3 US-A8). Their whole authority is: view orders,
    update order status. Every other admin endpoint must refuse them, which is
    only worth anything if someone asserts it -- see test_role_matrix.py.
    """
    return User.objects.create_user(
        email="helper@example.com",
        password=PASSWORD,
        full_name="Helper",
        role=Role.STAFF,
    )


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="shopper@example.com",
        password=PASSWORD,
        full_name="Rafiq Hasan",
        phone="01712345678",
    )


@pytest.fixture
def as_user(api):
    """Re-point the shared client at whoever the test needs next."""

    def _as(user):
        api.force_authenticate(user=user)
        return api

    return _as


@pytest.fixture
def admin_client(api, admin):
    api.force_authenticate(user=admin)
    return api


@pytest.fixture
def staff_client(api, staff_member):
    api.force_authenticate(user=staff_member)
    return api


# ---------------------------------------------------------------------------
# Catalogue and orders
# ---------------------------------------------------------------------------
@pytest.fixture
def category(db):
    return make_category("Laptops")


@pytest.fixture
def make_variant(category):
    """A purchasable variant at the stock the test names."""
    counter = {"n": 0}

    def _make(*, price="1000.00", stock=50, low_stock_threshold=5, name=None):
        counter["n"] += 1
        product = make_product(
            category,
            name=name or "Product {0:02d}".format(counter["n"]),
            price=price,
            stock=stock,
        )
        variant = product.variants.get()
        if variant.low_stock_threshold != low_stock_threshold:
            variant.low_stock_threshold = low_stock_threshold
            variant.save(update_fields=["low_stock_threshold"])
        return variant

    return _make


@pytest.fixture
def make_order(db, make_variant):
    """
    An order in whatever state and at whatever moment the test needs.

    Built with the ORM rather than through `place_order`, deliberately: these
    tests are about reading and advancing orders that already exist, and
    placement would insist on a shipping zone, a live catalogue and a clock
    that only moves forwards. Orders whose *transitions* are under test start
    at `pending` and are moved by the service, so the stock ledger stays
    honest wherever it is asserted on.
    """
    sequence = {"n": 0}

    def _make(
        *,
        status=OrderStatus.CONFIRMED,
        payment_method=PaymentMethod.COD,
        grand_total="1000.00",
        subtotal=None,
        placed_at=None,
        user=None,
        email="buyer@example.com",
        phone="01712345678",
        recipient_name="Buyer Rahman",
        district="Dhaka",
        items=None,
        quantity=1,
    ):
        sequence["n"] += 1
        reference = "ORD-2026-{0:06d}".format(sequence["n"])
        order = Order.objects.create(
            reference=reference,
            user=user,
            email=email,
            phone=phone,
            ship_recipient_name=recipient_name,
            ship_phone=phone,
            ship_division="Dhaka",
            ship_district=district,
            ship_street="1 Test Road",
            subtotal=Decimal(subtotal if subtotal is not None else grand_total),
            grand_total=Decimal(grand_total),
            payment_method=payment_method,
            status=status,
            idempotency_key="idem-{0}".format(reference),
        )

        lines = items if items is not None else [(make_variant(), quantity)]
        for variant, qty in lines:
            OrderItem.objects.create(
                order=order,
                variant=variant,
                product_name=variant.product.name,
                variant_label=variant.label,
                sku=variant.sku,
                unit_price=variant.price,
                quantity=qty,
                line_total=variant.price * qty,
            )

        if placed_at is not None:
            # placed_at is auto_now_add, so it can only be set after the fact.
            Order.objects.filter(pk=order.pk).update(placed_at=placed_at)
            order.refresh_from_db()
        return order

    return _make


@pytest.fixture
def days_ago():
    """A moment N whole local days back, at midday, so no test sits on a boundary."""

    def _at(days, *, hour=12):
        local_now = timezone.localtime(timezone.now())
        target = local_now.replace(
            hour=hour, minute=0, second=0, microsecond=0
        ) - timedelta(days=days)
        return target

    return _at


@pytest.fixture
def store_settings(db):
    """The singleton, reset to a boring baseline so a failure names one cause."""
    settings = StoreSettings.load()
    settings.store_name = "MicroMart"
    settings.tax_rate = Decimal("0.00")
    settings.tax_inclusive_pricing = False
    settings.cod_enabled = True
    settings.cod_max_order_value = None
    settings.low_stock_digest_recipients = []
    settings.save()
    return settings


# ---------------------------------------------------------------------------
# Routes (apps/dashboard/urls.py)
# ---------------------------------------------------------------------------
@pytest.fixture
def dashboard_url():
    return reverse("dashboard:dashboard")


@pytest.fixture
def orders_url():
    return reverse("dashboard:order-list")


@pytest.fixture
def order_detail_url():
    return lambda reference: reverse(
        "dashboard:order-detail", kwargs={"reference": reference}
    )


@pytest.fixture
def order_status_url():
    return lambda reference: reverse(
        "dashboard:order-status", kwargs={"reference": reference}
    )


@pytest.fixture
def order_shipment_url():
    return lambda reference: reverse(
        "dashboard:order-shipment", kwargs={"reference": reference}
    )


@pytest.fixture
def customers_url():
    return reverse("dashboard:customer-list")


@pytest.fixture
def settings_url():
    return reverse("dashboard:store-settings")
