"""
POST /api/v1/payments/initiate/ -- opening an SSLCommerz session
(apps/payments/services/payments.py, FR-PAY-2).

What initiate must get right is narrower than it looks. It moves no money and
confirms nothing, so the assertions here are about three things:

1. **The amount sent to the gateway is the server's own figure**, read off the
   order the totals engine priced. If a client could influence it, the amount
   check at validation time would be checking a number the attacker chose
   against a number the attacker chose.
2. **An order that must not be paid for is refused**, with a code stable enough
   for the checkout page to branch on.
3. **Nothing moves.** Stock is untouched -- it moves on confirmation and
   nowhere else (FR-INV-2) -- and the order stays pending.

Failures are asserted on `DomainError.code` and HTTP status, never on message
wording: codes are the contract (PRD 7.1), messages are not.
"""
from decimal import Decimal

import pytest

from apps.orders.models import OrderStatus, PaymentMethod
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import payments as payment_services
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------
def test_initiating_a_payment_records_an_initiated_payment_and_returns_the_gateway_url(
    gateway, online_order
):
    session = payment_services.initiate_payment(order_reference=online_order.reference)

    assert session.redirect_url == gateway.session_response["GatewayPageURL"]

    payment = Payment.objects.get(order=online_order)
    assert payment.status == PaymentStatus.INITIATED, (
        "a session is an invitation to pay, not a payment -- only a validated "
        "IPN may write PAID"
    )
    assert payment.method == "sslcommerz"
    assert payment.session_key == "SESSION-KEY-0001"
    assert payment.amount == Decimal("2000.00")
    assert payment.currency == "BDT"
    assert payment.gateway_txn_id == "", "no transaction exists yet to have an id"
    assert payment.confirmed_at is None


def test_the_amount_sent_to_the_gateway_is_the_orders_own_server_computed_total(
    gateway, online_order
):
    payment_services.initiate_payment(order_reference=online_order.reference)

    sent = gateway.session_calls[0]
    assert sent["total_amount"] == "2000.00", (
        "the gateway must be asked for the total the server computed at "
        "placement -- any other figure makes the validation-time amount check "
        "meaningless"
    )
    assert sent["currency"] == "BDT"
    assert sent["tran_id"] == online_order.reference


def test_the_session_request_points_all_four_callbacks_back_at_this_api(
    gateway, online_order
):
    payment_services.initiate_payment(
        order_reference=online_order.reference, base_url="https://shop.example.com/"
    )

    sent = gateway.session_calls[0]
    assert sent["success_url"] == "https://shop.example.com/api/v1/payments/callback/success/"
    assert sent["fail_url"] == "https://shop.example.com/api/v1/payments/callback/fail/"
    assert sent["cancel_url"] == "https://shop.example.com/api/v1/payments/callback/cancel/"
    assert sent["ipn_url"] == "https://shop.example.com/api/v1/payments/ipn/", (
        "the IPN URL is the only one of the four that decides anything, so it "
        "must reach this application's own server-to-server endpoint"
    )


def test_the_endpoint_returns_the_redirect_url_and_leaves_the_order_pending(
    api, gateway, online_order, initiate_url
):
    response = api.post(
        initiate_url, {"order_reference": online_order.reference}, format="json"
    )

    assert response.status_code == 200
    assert response.data["redirect_url"] == gateway.session_response["GatewayPageURL"]
    assert response.data["order_reference"] == online_order.reference
    assert response.data["amount"] == "2000.00", "money crosses the wire as a string"
    assert response.data["currency"] == "BDT"
    assert response.data["payment_status"] == PaymentStatus.INITIATED

    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.PENDING


def test_opening_a_session_moves_no_stock_whatsoever(
    gateway, online_order, variant, inventory_state
):
    before = inventory_state()

    payment_services.initiate_payment(order_reference=online_order.reference)

    assert inventory_state() == before, (
        "stock moves on confirmation and nowhere else (FR-INV-2); sending a "
        "customer to the gateway is not a sale"
    )


def test_a_second_attempt_after_a_failure_reuses_the_one_payment_row_for_the_order(
    gateway, online_order
):
    payment_services.initiate_payment(order_reference=online_order.reference)
    Payment.objects.filter(order=online_order).update(status=PaymentStatus.FAILED)

    gateway.session_response = dict(
        gateway.session_response, sessionkey="SESSION-KEY-0002"
    )
    payment_services.initiate_payment(order_reference=online_order.reference)

    payments = Payment.objects.filter(order=online_order)
    assert payments.count() == 1, "Payment is one-to-one with Order"
    assert payments.first().session_key == "SESSION-KEY-0002"
    assert payments.first().status == PaymentStatus.INITIATED, (
        "a retry after a failed attempt must be payable again (FR-PAY-7)"
    )


# ---------------------------------------------------------------------------
# Orders that must not be paid for
# ---------------------------------------------------------------------------
def test_an_order_that_is_already_paid_cannot_open_another_session(
    gateway, online_order
):
    payment_services.initiate_payment(order_reference=online_order.reference)
    Payment.objects.filter(order=online_order).update(status=PaymentStatus.PAID)

    with pytest.raises(DomainError) as exc:
        payment_services.initiate_payment(order_reference=online_order.reference)

    assert exc.value.code == "ORDER_ALREADY_PAID"
    assert len(gateway.session_calls) == 1, "the gateway must not be called at all"


def test_a_cancelled_order_cannot_open_a_session(gateway, online_order):
    from apps.orders.services import placement as placement_services

    placement_services.cancel_order(online_order, actor=None, reason="Changed my mind")

    with pytest.raises(DomainError) as exc:
        payment_services.initiate_payment(order_reference=online_order.reference)

    assert exc.value.code == "ORDER_NOT_PAYABLE"
    assert gateway.session_calls == []


def test_a_cash_on_delivery_order_cannot_open_an_online_session(
    gateway, place, variant
):
    order = place(variant=variant, quantity=1, payment_method=PaymentMethod.COD)

    with pytest.raises(DomainError) as exc:
        payment_services.initiate_payment(order_reference=order.reference)

    assert exc.value.code == "PAYMENT_METHOD_NOT_ONLINE"


def test_an_unknown_reference_is_not_found(gateway, db):
    with pytest.raises(DomainError) as exc:
        payment_services.initiate_payment(order_reference="ORD-2026-999999")

    assert exc.value.code == "NOT_FOUND"
    assert exc.value.status_code == 404


def test_another_customers_order_is_404_and_never_403(
    api, gateway, place, variant, customer, other_customer, initiate_url
):
    order = place(variant=variant, quantity=1, user=customer)

    api.force_authenticate(other_customer)
    response = api.post(
        initiate_url, {"order_reference": order.reference}, format="json"
    )

    assert response.status_code == 404, (
        "a 403 confirms the order exists and leaks the reference space (PRD 10.2)"
    )
    assert response.data["error"]["code"] == "NOT_FOUND"
    assert gateway.session_calls == []


def test_an_anonymous_request_cannot_pay_for_a_registered_customers_order(
    api, gateway, place, variant, customer, initiate_url
):
    order = place(variant=variant, quantity=1, user=customer)

    response = api.post(
        initiate_url, {"order_reference": order.reference}, format="json"
    )

    assert response.status_code == 404
    assert gateway.session_calls == []


def test_a_guest_can_pay_for_a_guest_order_because_the_reference_is_the_capability(
    api, gateway, online_order, initiate_url
):
    # online_order is a guest order: the reference is the only thing the guest
    # was ever issued, and it is the same capability the confirmation page uses.
    response = api.post(
        initiate_url, {"order_reference": online_order.reference}, format="json"
    )

    assert response.status_code == 200
    assert Payment.objects.filter(order=online_order).exists()


# ---------------------------------------------------------------------------
# Gateway failures
# ---------------------------------------------------------------------------
def test_a_store_with_no_credentials_refuses_cleanly_without_writing_a_payment(
    settings, online_order
):
    settings.SSLCOMMERZ_STORE_ID = ""
    settings.SSLCOMMERZ_STORE_PASSWORD = ""

    with pytest.raises(DomainError) as exc:
        payment_services.initiate_payment(order_reference=online_order.reference)

    assert exc.value.code == "GATEWAY_NOT_CONFIGURED"
    assert exc.value.status_code == 503, (
        "an unconfigured store is a deployment problem, not the shopper's"
    )
    assert not Payment.objects.filter(order=online_order).exists()


def test_a_gateway_that_refuses_the_session_writes_no_payment_row(
    gateway, online_order
):
    gateway.session_error = DomainError(
        "Store is inactive", code="GATEWAY_SESSION_FAILED", status_code=502
    )

    with pytest.raises(DomainError) as exc:
        payment_services.initiate_payment(order_reference=online_order.reference)

    assert exc.value.code == "GATEWAY_SESSION_FAILED"
    assert not Payment.objects.filter(order=online_order).exists()
    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.PENDING
