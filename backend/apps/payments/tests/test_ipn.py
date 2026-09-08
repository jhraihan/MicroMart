"""
POST /api/v1/payments/ipn/ -- the only endpoint that may mark an order paid
(apps/payments/services/payments.py, FR-PAY-4..7).

PRD 5.5 states the rule this file exists to prove, and marks it Critical:

    "An order must never be marked paid on the strength of a browser redirect
    alone. A redirect URL is user-controllable; treating it as proof of payment
    is a direct route to free merchandise."

The IPN body is user-controllable for exactly the same reason -- the endpoint
is reachable by anyone who can make an HTTP request -- so the tests below are
written as attacks wherever an attack is possible. A notification claiming
`status=VALID` and `amount=2000.00` proves nothing; only the server's own
outbound validation call does.

Assertions are on *state*, not on return values: what ended up in orders_order,
in payments_payment, in catalog_inventory_log and in orders_order_status_log
after the call. A handler that returned a plausible object while leaving the
ledger wrong would still be a shop giving away laptops.
"""
from decimal import Decimal

import pytest

from apps.catalog.models import InventoryLog, InventoryReason
from apps.orders.models import Actor, OrderStatus, OrderStatusLog, PaymentMethod
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import payments as payment_services
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


def _initiated(order, gateway, user=None):
    """Put the order where a real one is when an IPN arrives: session opened."""
    payment_services.initiate_payment(order_reference=order.reference, user=user)
    return Payment.objects.get(order=order)


def _confirmations(order):
    return OrderStatusLog.objects.filter(
        order=order, to_status=OrderStatus.CONFIRMED
    )


def _movements(variant):
    return InventoryLog.objects.filter(
        variant=variant, reason=InventoryReason.ORDER_CONFIRMED
    )


# ---------------------------------------------------------------------------
# The one path that confirms
# ---------------------------------------------------------------------------
def test_a_validated_amount_matching_notification_confirms_the_order_and_decrements_stock_once(
    gateway, online_order, variant
):
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order)

    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is True
    assert result.reason == payment_services.REASON_CONFIRMED

    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.CONFIRMED

    variant.refresh_from_db()
    assert variant.stock == 8, "ten units, two bought"
    assert _movements(variant).count() == 1
    assert _movements(variant).first().delta == -2
    assert _confirmations(online_order).count() == 1


def test_confirmation_is_written_by_the_order_state_machine_as_a_system_actor(
    gateway, online_order
):
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order)

    payment_services.handle_ipn(gateway.notification())

    log = _confirmations(online_order).get()
    assert log.from_status == OrderStatus.PENDING
    assert log.actor_role == Actor.SYSTEM, (
        "nobody pressed a button -- the gateway's validated notification did "
        "this, and the audit trail must say so (FR-ORD-5)"
    )
    assert log.actor is None


def test_a_confirmed_payment_records_everything_reconciliation_needs(
    gateway, online_order
):
    _initiated(online_order, gateway)
    validation = gateway.will_validate(order=online_order, bank_tran_id="BANK-XYZ-9")

    payment_services.handle_ipn(gateway.notification())

    payment = Payment.objects.get(order=online_order)
    assert payment.status == PaymentStatus.PAID
    assert payment.gateway_txn_id == "BANK-XYZ-9"
    assert payment.amount == Decimal("2000.00")
    assert payment.currency == "BDT"
    assert payment.confirmed_at is not None
    # FR-PAY-6: the raw gateway response is kept, and the two halves are kept
    # apart -- what we verified, and what we were merely told.
    assert payment.raw_response["validation"]["status"] == validation["status"]
    assert payment.raw_response["validation"]["bank_tran_id"] == "BANK-XYZ-9"
    assert "notification" in payment.raw_response


def test_the_endpoint_answers_200_so_the_gateway_stops_retrying(
    api, gateway, online_order, ipn_url
):
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order)

    response = api.post(ipn_url, gateway.notification())

    assert response.status_code == 200
    assert response.data["status"] == "confirmed"
    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.CONFIRMED


def test_the_ipn_endpoint_needs_no_authentication_and_no_csrf_token(
    gateway, online_order, ipn_url
):
    """
    SSLCommerz carries neither a session cookie nor a JWT nor a CSRF token, so
    a gated endpoint would simply never fire. Safety here comes from
    distrusting the request, not from gating it.
    """
    from django.test import Client

    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order)

    csrf_checking = Client(enforce_csrf_checks=True)
    response = csrf_checking.post(ipn_url, gateway.notification())

    assert response.status_code == 200
    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.CONFIRMED


# ---------------------------------------------------------------------------
# FR-PAY-5: idempotency. The replay test.
# ---------------------------------------------------------------------------
def test_the_same_notification_delivered_twice_confirms_once_and_decrements_once(
    gateway, online_order, variant
):
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order)
    notification = gateway.notification()

    first = payment_services.handle_ipn(notification)
    second = payment_services.handle_ipn(notification)

    assert first.confirmed is True
    assert second.confirmed is False, (
        "a replayed IPN is acknowledged and ignored, never double-applied "
        "(FR-PAY-5)"
    )
    assert second.reason == payment_services.REASON_ALREADY_CONFIRMED

    variant.refresh_from_db()
    assert variant.stock == 8, "two units left the shelf once, not twice"
    assert _movements(variant).count() == 1
    assert _confirmations(online_order).count() == 1

    payment = Payment.objects.get(order=online_order)
    assert payment.status == PaymentStatus.PAID
    assert payment.amount == Decimal("2000.00")


def test_a_replay_that_arrives_as_validated_rather_than_valid_is_still_ignored(
    gateway, online_order, variant
):
    # The gateway answers VALID the first time a transaction is validated and
    # VALIDATED every time after, which is precisely what a replay produces.
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, status="VALID")
    payment_services.handle_ipn(gateway.notification())

    gateway.will_validate(order=online_order, status="VALIDATED")
    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is False
    assert result.reason == payment_services.REASON_ALREADY_CONFIRMED
    variant.refresh_from_db()
    assert variant.stock == 8
    assert _movements(variant).count() == 1


def test_a_first_notification_that_arrives_as_validated_still_confirms(
    gateway, online_order, variant
):
    """VALIDATED is a success status in its own right, not only a replay marker."""
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, status="VALIDATED")

    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is True
    variant.refresh_from_db()
    assert variant.stock == 8


# ---------------------------------------------------------------------------
# The free-merchandise attack, in its several shapes
# ---------------------------------------------------------------------------
def test_a_validated_payment_for_less_than_the_order_total_does_not_confirm(
    gateway, online_order, variant
):
    """
    The attack this whole module exists to stop.

    The transaction is genuine and the gateway validates it -- the customer
    really did pay. They paid 10 taka for a 2,000 taka order. Confirming here
    is a laptop given away for the price of a cup of tea.
    """
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, amount="10.00")

    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is False
    assert result.reason == payment_services.REASON_AMOUNT_MISMATCH

    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.PENDING, "the order must stay unpaid"
    variant.refresh_from_db()
    assert variant.stock == 10, "no stock may leave the shelf"
    assert _movements(variant).count() == 0
    assert _confirmations(online_order).count() == 0

    payment = Payment.objects.get(order=online_order)
    assert payment.status == PaymentStatus.FAILED
    assert payment.confirmed_at is None
    assert payment.raw_response["validation"]["amount"] == "10.00", (
        "the mismatch is recorded, not silently dropped -- a refund is manual "
        "in v1 (FR-PAY-8) and a manual refund needs evidence"
    )


def test_a_validated_payment_for_more_than_the_order_total_does_not_confirm_either(
    gateway, online_order, variant
):
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, amount="2000.01")

    result = payment_services.handle_ipn(gateway.notification())

    assert result.reason == payment_services.REASON_AMOUNT_MISMATCH
    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.PENDING
    variant.refresh_from_db()
    assert variant.stock == 10


def test_an_amount_that_is_not_a_number_at_all_does_not_confirm(
    gateway, online_order, variant
):
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, amount="two thousand")

    result = payment_services.handle_ipn(gateway.notification())

    assert result.reason == payment_services.REASON_AMOUNT_MISMATCH
    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.PENDING
    variant.refresh_from_db()
    assert variant.stock == 10


def test_a_payment_validated_in_the_wrong_currency_does_not_confirm(
    gateway, online_order, variant
):
    """2,000 US dollars and 2,000 taka are not the same payment."""
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, currency="USD")

    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is False
    assert result.reason == payment_services.REASON_CURRENCY_MISMATCH

    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.PENDING
    variant.refresh_from_db()
    assert variant.stock == 10
    assert Payment.objects.get(order=online_order).status == PaymentStatus.FAILED


def test_a_notification_claiming_success_that_the_validation_api_contradicts_does_not_confirm(
    gateway, online_order, variant
):
    """
    The POST body is not trusted. This is the proof.

    The body says VALID for the full 2,000. The validation API -- our own
    outbound call, authenticated with our store password -- says FAILED. The
    order stays pending, because the body is evidence and the validation
    response is the finding.
    """
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, status="FAILED")

    forged = gateway.notification(status="VALID", amount="2000.00")
    result = payment_services.handle_ipn(forged)

    assert result.confirmed is False
    assert result.reason == payment_services.REASON_VALIDATION_FAILED

    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.PENDING
    variant.refresh_from_db()
    assert variant.stock == 10
    assert _movements(variant).count() == 0

    payment = Payment.objects.get(order=online_order)
    assert payment.status == PaymentStatus.FAILED
    assert payment.raw_response["notification"]["status"] == "VALID", (
        "the forged claim is kept as evidence"
    )
    assert payment.raw_response["validation"]["status"] == "FAILED", (
        "and so is what actually happened"
    )


def test_a_notification_claiming_an_amount_the_validation_api_contradicts_does_not_confirm(
    gateway, online_order, variant
):
    """The body's `amount` is never read. Only the validated one counts."""
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, amount="10.00")

    forged = gateway.notification(amount="2000.00", status="VALID")
    result = payment_services.handle_ipn(forged)

    assert result.reason == payment_services.REASON_AMOUNT_MISMATCH
    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.PENDING
    variant.refresh_from_db()
    assert variant.stock == 10


def test_the_order_is_taken_from_the_validation_response_not_from_the_notification(
    gateway, place, variant, online_order
):
    """
    A forged `tran_id` cannot aim a real payment at a different order.

    The attacker pays 2,000 taka for their own cheap order, then re-posts the
    notification with the expensive order's reference in the body. The
    validation response still names the transaction they actually paid for, and
    that is the only reference the handler reads.
    """
    expensive = online_order  # 2,000.00
    cheap = place(variant=variant, quantity=1)  # 1,000.00
    _initiated(cheap, gateway)
    _initiated(expensive, gateway)

    gateway.will_validate(order=cheap, amount="1000.00")
    forged = gateway.notification(tran_id=expensive.reference)

    result = payment_services.handle_ipn(forged)

    assert result.confirmed is True
    assert result.order.reference == cheap.reference, (
        "the handler must follow the validated tran_id, not the one it was told"
    )
    expensive.refresh_from_db()
    assert expensive.status == OrderStatus.PENDING, (
        "the order the attacker aimed at is untouched"
    )
    cheap.refresh_from_db()
    assert cheap.status == OrderStatus.CONFIRMED


# ---------------------------------------------------------------------------
# Notifications that are not about a payable order
# ---------------------------------------------------------------------------
def test_a_notification_without_a_val_id_is_refused_before_anything_is_read(
    gateway, online_order
):
    with pytest.raises(DomainError) as exc:
        payment_services.handle_ipn({"tran_id": online_order.reference, "status": "VALID"})

    assert exc.value.code == "MISSING_VAL_ID"
    assert exc.value.status_code == 400
    assert gateway.validation_calls == []


def test_the_val_id_from_the_notification_is_the_one_sent_to_the_validation_api(
    gateway, online_order
):
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, val_id="VAL-FROM-GATEWAY")

    payment_services.handle_ipn(gateway.notification(val_id="VAL-FROM-GATEWAY"))

    assert gateway.validation_calls == ["VAL-FROM-GATEWAY"], (
        "the val_id is the one thing read from the notification, and it is read "
        "as a lookup key rather than as an assertion (FR-PAY-4)"
    )


def test_a_validated_transaction_for_an_unknown_order_is_not_found(gateway, db):
    gateway.will_validate(tran_id="ORD-2026-999999")

    with pytest.raises(DomainError) as exc:
        payment_services.handle_ipn(gateway.notification())

    assert exc.value.code == "NOT_FOUND"
    assert exc.value.status_code == 404


def test_a_notification_naming_a_cash_on_delivery_order_confirms_nothing(
    gateway, place, variant
):
    order = place(variant=variant, quantity=1, payment_method=PaymentMethod.COD)
    variant.refresh_from_db()
    stock_after_cod = variant.stock

    gateway.will_validate(order=order)
    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is False
    assert result.reason == payment_services.REASON_NOT_AN_ONLINE_ORDER
    variant.refresh_from_db()
    assert variant.stock == stock_after_cod, "the courier collects; no second decrement"
    assert not Payment.objects.filter(order=order).exists(), (
        "a COD order must not sprout a payment row because somebody posted at "
        "the IPN endpoint"
    )


def test_a_notification_for_a_cancelled_order_confirms_nothing(
    gateway, online_order, variant
):
    from apps.orders.services import placement as placement_services

    _initiated(online_order, gateway)
    placement_services.cancel_order(online_order, actor=None, reason="Changed my mind")

    gateway.will_validate(order=online_order)
    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is False
    assert result.reason == payment_services.REASON_ORDER_NOT_PAYABLE
    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.CANCELLED
    variant.refresh_from_db()
    assert variant.stock == 10


# ---------------------------------------------------------------------------
# FR-PAY-7: what a failed payment leaves behind
# ---------------------------------------------------------------------------
def test_a_failed_payment_leaves_the_order_pending_the_stock_untouched_and_the_cart_intact(
    gateway, customer, place, variant, ledger_stocked, inventory_state
):
    from apps.cart.services import cart as cart_services

    other = ledger_stocked(quantity=4, price="500.00", name="Still In The Cart")
    cart = cart_services.get_cart(customer)
    cart_services.add_item(cart=cart, variant_id=other.pk, quantity=3)

    order = place(variant=variant, quantity=2, user=customer)
    _initiated(order, gateway, user=customer)

    before_inventory = inventory_state()
    before_cart = list(
        cart.items.order_by("pk").values_list("variant_id", "quantity")
    )

    gateway.will_validate(order=order, status="FAILED")
    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is False
    order.refresh_from_db()
    assert order.status == OrderStatus.PENDING
    assert inventory_state() == before_inventory
    assert (
        list(cart.items.order_by("pk").values_list("variant_id", "quantity"))
        == before_cart
    ), "an abandoned payment must not disturb what the shopper is still holding"


def test_an_order_whose_payment_failed_can_be_paid_for_again(
    gateway, online_order, variant
):
    _initiated(online_order, gateway)
    gateway.will_validate(order=online_order, status="FAILED")
    payment_services.handle_ipn(gateway.notification())

    # The customer tries again, this time successfully.
    payment_services.initiate_payment(order_reference=online_order.reference)
    gateway.will_validate(order=online_order, status="VALID", bank_tran_id="BANK-RETRY")
    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is True
    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.CONFIRMED
    variant.refresh_from_db()
    assert variant.stock == 8
    assert _movements(variant).count() == 1


def test_a_notification_for_an_order_with_no_session_row_still_records_the_payment(
    gateway, online_order, variant
):
    """
    The initiate write can be lost -- a crash, a rolled-back deploy. The money
    still arrived, so the evidence is recorded rather than dropped.
    """
    assert not Payment.objects.filter(order=online_order).exists()
    gateway.will_validate(order=online_order)

    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is True
    payment = Payment.objects.get(order=online_order)
    assert payment.status == PaymentStatus.PAID
    assert payment.amount == Decimal("2000.00")


# ---------------------------------------------------------------------------
# Paid, but not confirmable
# ---------------------------------------------------------------------------
def test_a_payment_that_arrives_after_the_stock_ran_out_is_recorded_and_the_order_left_pending(
    gateway, online_order, variant
):
    """
    The customer paid while they were on the gateway's page and the last units
    went to somebody else. Losing the payment record here would be far worse
    than an order stuck pending: refunds are manual in v1 (FR-PAY-8), and a
    manual refund needs evidence that money arrived.
    """
    from apps.catalog.services import inventory as inventory_services
    from django.db import transaction

    _initiated(online_order, gateway)
    with transaction.atomic():
        inventory_services.adjust_stock(
            variant=variant,
            delta=-10,
            reason=InventoryReason.MANUAL_ADJUSTMENT,
            note="Sold out elsewhere",
        )

    gateway.will_validate(order=online_order)
    result = payment_services.handle_ipn(gateway.notification())

    assert result.confirmed is False
    assert result.reason == payment_services.REASON_CONFIRMATION_FAILED

    payment = Payment.objects.get(order=online_order)
    assert payment.status == PaymentStatus.PAID, "the money did arrive"
    assert payment.confirmed_at is not None

    online_order.refresh_from_db()
    assert online_order.status == OrderStatus.PENDING, "and a human must sort it out"
    variant.refresh_from_db()
    assert variant.stock == 0
    assert _confirmations(online_order).count() == 0
