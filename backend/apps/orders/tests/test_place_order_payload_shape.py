"""
The *shape* of a POST /orders/ body, as the storefront actually sends it.

This module exists because of a bug the rest of the suite could not see. Every
other API test here builds its payload by naming only the keys it needs, so
`address_id` and `coupon_code` were simply absent whenever they did not apply.
The real client does the opposite: `toOrderPayload` in
frontend/src/features/checkout/schemas.js always sends the full body and sets
the inapplicable keys to `null` -- which is exactly what the frozen contract's
canonical request shows (docs/api-contract-cart-checkout-orders.md).

To DRF those are different things. `required=False` permits omission; it does
not permit `null`. So `PlaceOrderSerializer` answered 400 "This field may not
be null." to every order the storefront tried to place -- guest and signed-in
alike -- while 1200-odd backend tests stayed green, because not one of them
sent the payload the browser sends.

These tests send the contract's body verbatim, nulls included. They fail if
`allow_null` is dropped from any of the three fields again.
"""
from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse

from apps.accounts.models import Address
from apps.orders.models import Order, OrderStatus


@pytest.fixture
def orders_url():
    return reverse("orders:order-list")


def contract_body(variant, **overrides):
    """
    The POST /orders/ body from the contract, nulls and all.

    Kept as one function so a test cannot accidentally "fix" the payload by
    omitting the very keys whose nullability is the thing under test.
    """
    body = {
        "idempotency_key": str(uuid4()),
        "items": [{"variant_id": variant.pk, "quantity": 1}],
        "email": "shopper@example.com",
        "phone": "01712345678",
        "shipping_address": {
            "recipient_name": "Rafiq Hasan",
            "phone": "01712345678",
            "division": "Dhaka",
            "district": "Dhaka",
            "upazila": "Dhanmondi",
            "area": "Road 7",
            "street": "House 42, Road 7, Dhanmondi",
            "postcode": "1205",
        },
        "address_id": None,
        "save_address": False,
        "coupon_code": None,
        "payment_method": "cod",
        "note": "",
    }
    body.update(overrides)
    return body


@pytest.mark.django_db
def test_a_guest_places_the_contracts_own_request_body_verbatim(
    api, orders_url, store_settings, dhaka_zone, make_sellable_variant
):
    """
    The exact JSON in docs/api-contract-cart-checkout-orders.md must be
    accepted. `address_id: null` is how a guest says "I have no address book",
    and rejecting it broke guest checkout (FR-CHK-5) completely.
    """
    variant = make_sellable_variant(price="1200.00", stock=5)

    response = api.post(
        orders_url, contract_body(variant), format="json"
    )

    assert response.status_code == 201, response.json()
    order = Order.objects.get(reference=response.json()["reference"])
    assert order.status == OrderStatus.CONFIRMED, "COD confirms on placement"
    assert order.grand_total == Decimal("1260.00"), "1200 + 60 flat rate"
    assert order.ship_district == "Dhaka"


@pytest.mark.django_db
def test_a_signed_in_shopper_sends_a_null_shipping_address_with_a_saved_one(
    api, orders_url, store_settings, dhaka_zone, make_sellable_variant, customer
):
    """
    The mirror case. Picking a saved address sends `address_id` and sets
    `shipping_address` to null -- and that null is what the client sends, so
    the serializer has to take it.
    """
    variant = make_sellable_variant(price="1200.00", stock=5)
    address = Address.objects.create(
        user=customer,
        recipient_name="Rafiq Hasan",
        phone="01712345678",
        division="Dhaka",
        district="Dhaka",
        upazila="Dhanmondi",
        area="Road 7",
        street="House 42, Road 7, Dhanmondi",
        postcode="1205",
        is_default=True,
    )
    api.force_authenticate(customer)

    response = api.post(
        orders_url,
        contract_body(variant, shipping_address=None, address_id=address.pk),
        format="json",
    )

    assert response.status_code == 201, response.json()
    order = Order.objects.get(reference=response.json()["reference"])
    # Snapshotted onto the order, never FK'd to the address book (FR-ORD-2).
    assert order.ship_street == address.street
    assert order.user_id == customer.pk


@pytest.mark.django_db
def test_a_null_coupon_code_means_no_coupon_rather_than_a_bad_request(
    api, orders_url, store_settings, dhaka_zone, make_sellable_variant
):
    """
    Every order placed without a coupon carries `coupon_code: null`, so this
    one null alone was enough to break the entire checkout.
    """
    variant = make_sellable_variant(price="1200.00", stock=5)

    response = api.post(
        orders_url, contract_body(variant, coupon_code=None), format="json"
    )

    assert response.status_code == 201, response.json()
    order = Order.objects.get(reference=response.json()["reference"])
    assert order.discount_total == Decimal("0.00")
    assert order.coupon_id is None


@pytest.mark.django_db
def test_a_body_naming_no_address_at_all_is_still_refused(
    api, orders_url, store_settings, dhaka_zone, make_sellable_variant
):
    """
    Nullable is not optional-in-effect. With both address fields null there is
    nowhere to deliver, and `validate()` still has to say so -- otherwise the
    allow_null fix would have traded a false 400 for a much worse 500.
    """
    variant = make_sellable_variant(price="1200.00", stock=5)

    response = api.post(
        orders_url,
        contract_body(variant, shipping_address=None, address_id=None),
        format="json",
    )

    assert response.status_code == 400, response.json()
    assert response.json()["error"]["field"] == "shipping_address"
    assert not Order.objects.exists()
