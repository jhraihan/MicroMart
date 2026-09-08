"""
GET /api/v1/payments/callback/{result}/ -- the browser coming back from
SSLCommerz (FR-PAY-3).

This file exists to prove a negative, and the negative is the most important
sentence in PRD 5.5:

    "An order must never be marked paid on the strength of a browser redirect
    alone. A redirect URL is user-controllable; treating it as proof of payment
    is a direct route to free merchandise."

So the tests below do not check what the callback returns nearly as much as
they check what it does *not do*. All three results are hit, and after each one
the order status, the payment status, every variant's stock and every row of
the append-only inventory ledger are asserted byte-identical to a snapshot
taken before the request. A whole-table snapshot rather than a spot check on
one field: the failure this is guarding against is a future edit that "helpfully"
confirms the order here, and such an edit would not stop at the field a
narrower test happened to name.
"""
import pytest

from apps.orders.models import OrderStatus
from apps.payments.models import PaymentStatus
from apps.payments.services import payments as payment_services
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db

RESULTS = ("success", "fail", "cancel")


@pytest.fixture
def awaiting_payment(gateway, online_order):
    """An order with a session open and a customer somewhere on the gateway."""
    payment_services.initiate_payment(order_reference=online_order.reference)
    return online_order


@pytest.mark.parametrize("result", RESULTS)
def test_the_callback_changes_no_order_no_payment_and_no_stock(
    api, callback_url, awaiting_payment, inventory_state, order_state, result
):
    before_inventory = inventory_state()
    before_orders = order_state()

    response = api.get(
        callback_url(result), {"tran_id": awaiting_payment.reference}
    )

    assert response.status_code == 302  # redirected to the SPA return screen
    assert inventory_state() == before_inventory, (
        "a redirect anybody can type must never move stock"
    )
    assert order_state() == before_orders, (
        "and must never move an order or a payment forward"
    )

    awaiting_payment.refresh_from_db()
    assert awaiting_payment.status == OrderStatus.PENDING
    assert awaiting_payment.payment.status == PaymentStatus.INITIATED


@pytest.mark.parametrize("result", RESULTS)
def test_the_callback_posted_by_the_gateway_changes_nothing_either(
    api, callback_url, awaiting_payment, inventory_state, order_state, result
):
    """SSLCommerz posts its redirect rather than getting it. Same nothing."""
    before_inventory = inventory_state()
    before_orders = order_state()

    response = api.post(
        callback_url(result),
        {"tran_id": awaiting_payment.reference, "status": "VALID", "amount": "2000.00"},
    )

    assert response.status_code == 302  # redirected to the SPA return screen
    assert inventory_state() == before_inventory
    assert order_state() == before_orders


def test_a_success_callback_forged_by_hand_confirms_nothing(
    api, callback_url, awaiting_payment, inventory_state, order_state
):
    """
    The attack, spelled out: no gateway involved at all, just somebody opening
    the success URL with a reference they read off their own confirmation page.
    """
    before_inventory = inventory_state()
    before_orders = order_state()

    response = api.get(
        callback_url("success"),
        {
            "tran_id": awaiting_payment.reference,
            "status": "VALID",
            "amount": "2000.00",
            "val_id": "ANYTHING-AT-ALL",
        },
    )

    # The forged call gets a redirect and nothing else. Every field the
    # attacker supplied -- status, amount, val_id -- is ignored: none of it
    # reaches the redirect target, so there is no way to smuggle a verdict
    # through this endpoint.
    assert response.status_code == 302
    location = response["Location"]
    assert "VALID" not in location
    assert "2000.00" not in location
    assert "ANYTHING-AT-ALL" not in location

    # And the endpoint still refuses to claim it knows: null is "ask the
    # order", not "no".
    assert payment_services.callback(
        "success", reference=awaiting_payment.reference
    )["payment_confirmed"] is None

    assert inventory_state() == before_inventory
    assert order_state() == before_orders


def test_the_callback_never_calls_the_validation_api(
    api, callback_url, gateway, awaiting_payment
):
    validations_before = len(gateway.validation_calls)

    for result in RESULTS:
        api.get(callback_url(result), {"tran_id": awaiting_payment.reference})

    assert len(gateway.validation_calls) == validations_before, (
        "validation belongs to the IPN handler; doing it here would make a "
        "user-controllable URL into a confirmation path"
    )


def test_the_callback_reads_no_rows_at_all(
    api, callback_url, awaiting_payment, django_assert_num_queries
):
    """
    Not one query. Looking the order up would turn a public, forgeable URL into
    an oracle over the reference space -- "is ORD-2026-000148 confirmed?" -- and
    the storefront already has an authenticated way to read an order.
    """
    with django_assert_num_queries(0):
        response = api.get(
            callback_url("success"), {"tran_id": awaiting_payment.reference}
        )

    # A 302 is still zero rows read. The redirect target is a page, not a verdict.
    assert response.status_code == 302


@pytest.mark.parametrize("result", RESULTS)
def test_each_result_returns_its_own_message_and_a_link_back_to_the_storefront(
    api, callback_url, settings, awaiting_payment, result
):
    settings.FRONTEND_BASE_URL = "https://shop.example.com"

    response = api.get(callback_url(result), {"tran_id": awaiting_payment.reference})

    # The browser is sent to the SPA's return screen, which reads the order
    # back and shows its real status -- NOT to /order/{reference}, which would
    # present a confirmation page on the say-so of a forgeable redirect.
    assert response.status_code == 302
    assert response["Location"] == (
        "https://shop.example.com/payments/callback/{0}?tran_id={1}".format(
            result, awaiting_payment.reference
        )
    )

    payload = payment_services.callback(
        result,
        reference=awaiting_payment.reference,
        frontend_base_url="https://shop.example.com",
    )
    assert payload["result"] == result
    assert payload["reference"] == awaiting_payment.reference
    assert payload["message"]


def test_a_success_callback_never_tells_the_customer_the_payment_succeeded(
    api, callback_url, awaiting_payment
):
    """
    Wording is part of the contract here. The server does not know yet -- the
    IPN may not have arrived -- so the copy must not assert it did.
    """
    payload = payment_services.callback(
        "success", reference=awaiting_payment.reference
    )

    assert "confirming" in payload["message"].lower()
    assert payload["payment_confirmed"] is None


def test_an_unknown_result_is_not_found(api, callback_url, db):
    response = api.get(callback_url("confirmed"))

    assert response.status_code == 404
    assert response.data["error"]["code"] == "NOT_FOUND"


def test_a_reference_that_is_not_reference_shaped_is_dropped_rather_than_echoed(
    api, callback_url, settings, db
):
    """A redirect URL is built from this. It is not a place for user text."""
    settings.FRONTEND_BASE_URL = "https://shop.example.com"

    response = api.get(callback_url("fail"), {"tran_id": "../../evil?x=1"})

    # Nothing of the hostile value survives into the Location header.
    assert response.status_code == 302
    assert response["Location"] == "https://shop.example.com/payments/callback/fail"
    assert "evil" not in response["Location"]


def test_the_service_refuses_an_unknown_result_directly(db):
    with pytest.raises(DomainError) as exc:
        payment_services.callback("paid")

    assert exc.value.code == "NOT_FOUND"
    assert exc.value.status_code == 404
