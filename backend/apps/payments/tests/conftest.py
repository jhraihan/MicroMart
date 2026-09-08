"""
Fixtures for the payments suite (PRD 5.5, FR-PAY-1..8).

Two things about this file are load-bearing.

**No test in this package opens a socket.** `gateway` replaces the two client
functions in `apps.payments.services.sslcommerz` with a stub that records what
it was asked and answers what the test told it to. A suite that reached the
real sandbox would be slow, flaky, and -- worse -- would prove nothing about
the cases that matter here, because a real gateway will not send you a
notification claiming an amount it did not collect. Forging that notification
is the entire point.

**Stock is opened through the inventory ledger**, never written onto the
variant row, so `sum(InventoryLog.delta) == ProductVariant.stock` holds from
each variant's first second. That turns every stock assertion downstream into
an equality rather than a difference, and it is the reconciliation check the
whole inventory design exists to support.

Written in the style of apps/orders/tests/conftest.py: every test builds the
rows it asserts on, nothing reads seed data, and every price and quantity a
test depends on is stated by the test.
"""
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import transaction
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import InventoryLog, InventoryReason, ProductVariant
from apps.catalog.services import inventory as inventory_services
from apps.catalog.tests.factories import make_category, make_product, make_variant
from apps.dashboard.models import StoreSettings
from apps.orders.models import Order, PaymentMethod
from apps.orders.services import placement as placement_services
from apps.payments.services import sslcommerz
from apps.shipping.models import ShippingZone

SHIPPING_ADDRESS = {
    "recipient_name": "Rafiq Hasan",
    "phone": "01712345678",
    "division": "Dhaka",
    "district": "Dhaka",
    "upazila": "Dhanmondi",
    "area": "Road 7",
    "street": "House 42, Road 7, Dhanmondi",
    "postcode": "1205",
}


# ---------------------------------------------------------------------------
# Clients, people, store
# ---------------------------------------------------------------------------
@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="shopper@example.com", password="Str0ngPass!2026"
    )


@pytest.fixture
def other_customer(db):
    return User.objects.create_user(
        email="someone.else@example.com", password="Str0ngPass!2026"
    )


@pytest.fixture
def store_settings(db):
    """No VAT, COD on with no ceiling -- a deliberately boring baseline.

    Money is not the subject of this suite; *which* money is. Zero VAT keeps
    the grand total equal to a figure the test wrote down, so an amount
    assertion names one cause when it fails.
    """
    settings = StoreSettings.load()
    settings.tax_rate = Decimal("0.00")
    settings.tax_inclusive_pricing = False
    settings.cod_enabled = True
    settings.cod_max_order_value = None
    settings.save()
    return settings


@pytest.fixture
def dhaka_zone(db):
    return ShippingZone.objects.create(
        name="Inside Dhaka",
        flat_rate=Decimal("0.00"),
        per_kg_rate=Decimal("0.00"),
        base_weight_grams=1000,
        free_shipping_threshold=None,
        cod_allowed=True,
        districts=["Dhaka"],
        sort_order=0,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@pytest.fixture
def category(db):
    return make_category("Laptops")


@pytest.fixture
def ledger_stocked(db, category):
    """A purchasable variant whose whole stock arrived through InventoryLog."""

    def _make(*, quantity=10, price="1000.00", name="Test Laptop"):
        product = make_product(category, name=name, variants=[])
        variant = make_variant(product, price=price, stock=0)
        with transaction.atomic():
            inventory_services.adjust_stock(
                variant=variant,
                delta=quantity,
                reason=InventoryReason.INITIAL,
                note="Opening stock",
            )
        variant.refresh_from_db()
        assert variant.stock == quantity
        return variant

    return _make


@pytest.fixture
def variant(store_settings, dhaka_zone, ledger_stocked):
    """Ten units at 1,000 taka. Free delivery, no VAT -- so an order of one
    line of two units totals exactly 2,000.00 and nothing else."""
    return ledger_stocked(quantity=10, price="1000.00", name="Payable Laptop")


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@pytest.fixture
def place(store_settings, dhaka_zone):
    """Place a real order through the real placement service.

    Building an Order row by hand would skip the totals engine, and the amount
    the gateway is checked against is precisely the figure that engine
    computes. This suite must assert against the real one.
    """

    def _place(
        *,
        variant,
        quantity=2,
        payment_method=PaymentMethod.ONLINE,
        user=None,
        email="shopper@example.com",
    ):
        order, _created = placement_services.place_order(
            idempotency_key=str(uuid4()),
            payment_method=payment_method,
            shipping_address=dict(SHIPPING_ADDRESS),
            user=user,
            email=email,
            items=[{"variant_id": variant.pk, "quantity": quantity}],
        )
        return order

    return _place


@pytest.fixture
def online_order(place, variant):
    """A pending, unpaid, online-payment order for 2,000.00 BDT."""
    order = place(variant=variant, quantity=2)
    assert order.grand_total == Decimal("2000.00")
    return order


# ---------------------------------------------------------------------------
# The gateway stub
# ---------------------------------------------------------------------------
class StubGateway:
    """
    Stands in for SSLCommerz at the module's only network seam.

    It records every call so a test can assert on what was *sent* -- that the
    validation call happened at all is half of FR-PAY-4 -- and answers with
    whatever the test staged. `will_validate` builds a response in the gateway's
    real shape so that a test forging an amount changes one field and leaves the
    rest honest.
    """

    def __init__(self):
        self.session_calls = []
        self.validation_calls = []
        self.session_error = None
        self.validation_error = None
        self.session_response = {
            "status": "SUCCESS",
            "sessionkey": "SESSION-KEY-0001",
            "GatewayPageURL": "https://sandbox.sslcommerz.com/EasyCheckOut/testcde0001",
            "storeBanner": "https://sandbox.sslcommerz.com/logo.png",
        }
        self.validation_response = {}

    # --- the two functions payments.py calls -------------------------------
    def create_session(self, payload):
        self.session_calls.append(dict(payload))
        if self.session_error is not None:
            raise self.session_error
        return dict(self.session_response)

    def validate_transaction(self, val_id):
        self.validation_calls.append(str(val_id))
        if self.validation_error is not None:
            raise self.validation_error
        return dict(self.validation_response)

    # --- staging helpers ---------------------------------------------------
    def will_validate(
        self,
        *,
        order=None,
        tran_id=None,
        status="VALID",
        amount=None,
        currency="BDT",
        val_id="VAL-0001",
        bank_tran_id="BANK-0001",
    ):
        """Stage the answer the validation API will give. Returns it too."""
        reference = tran_id if tran_id is not None else (order.reference if order else "")
        if amount is None:
            amount = str(order.grand_total) if order is not None else "0.00"
        self.validation_response = {
            "status": status,
            "tran_date": "2026-08-22 12:00:00",
            "tran_id": reference,
            "val_id": val_id,
            "amount": str(amount),
            "store_amount": str(amount),
            "currency": currency,
            "bank_tran_id": bank_tran_id,
            "card_type": "VISA-Dutch Bangla",
            "card_issuer": "Dutch Bangla Bank",
            "risk_level": "0",
            "risk_title": "Safe",
        }
        return dict(self.validation_response)

    def notification(self, **overrides):
        """
        A form-encoded IPN body, in the gateway's real shape.

        Defaults are copied from the staged validation response so that a test
        which forges one field is forging *only* that field -- the difference
        between the body and the truth is the thing under test.
        """
        staged = self.validation_response
        body = {
            "val_id": staged.get("val_id", "VAL-0001"),
            "tran_id": staged.get("tran_id", ""),
            "status": staged.get("status", "VALID"),
            "amount": staged.get("amount", "0.00"),
            "currency": staged.get("currency", "BDT"),
            "bank_tran_id": staged.get("bank_tran_id", "BANK-0001"),
            "card_type": "VISA-Dutch Bangla",
            "store_id": "micromart_test",
            "verify_sign": "0123456789abcdef0123456789abcdef",
        }
        body.update(overrides)
        return body


@pytest.fixture
def gateway(monkeypatch, settings):
    """
    Replace the SSLCommerz client and hand back the stub.

    The credentials are fake and are set only so the client's own
    GATEWAY_NOT_CONFIGURED guard does not fire in the one test that reaches it.
    """
    settings.SSLCOMMERZ_STORE_ID = "micromart_test"
    settings.SSLCOMMERZ_STORE_PASSWORD = "micromart_test@ssl"
    settings.SSLCOMMERZ_SANDBOX = True

    stub = StubGateway()
    monkeypatch.setattr(sslcommerz, "create_session", stub.create_session)
    monkeypatch.setattr(sslcommerz, "validate_transaction", stub.validate_transaction)
    return stub


# ---------------------------------------------------------------------------
# State snapshots -- "nothing moved" assertions
# ---------------------------------------------------------------------------
@pytest.fixture
def inventory_state(db):
    """
    A snapshot of every stock number and every ledger row.

    Proving that a callback moved no stock is cheapest as an equality between
    two of these: a byte-identical pair is a much stronger claim than checking
    one variant a test happened to think of.
    """

    def _snapshot():
        return {
            "stock": dict(ProductVariant.objects.values_list("pk", "stock")),
            "logs": list(
                InventoryLog.objects.order_by("pk").values_list(
                    "pk", "variant_id", "delta", "reason"
                )
            ),
        }

    return _snapshot


@pytest.fixture
def order_state(db):
    """Every order's status and every payment's status, for the same purpose."""

    def _snapshot():
        from apps.payments.models import Payment

        return {
            "orders": dict(Order.objects.values_list("reference", "status")),
            "payments": list(
                Payment.objects.order_by("pk").values_list(
                    "pk", "order_id", "status", "amount", "gateway_txn_id"
                )
            ),
        }

    return _snapshot


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
@pytest.fixture
def initiate_url():
    return reverse("payments:initiate")


@pytest.fixture
def ipn_url():
    return reverse("payments:ipn")


@pytest.fixture
def callback_url():
    def _url(result):
        return reverse("payments:callback", kwargs={"result": result})

    return _url
