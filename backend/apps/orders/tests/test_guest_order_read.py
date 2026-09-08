"""
The guest order read -- GET /orders/{reference}/?email= (PRD 7.2, FR-CHK-5,
docs/api-contract-cart-checkout-orders.md).

Why it exists: a guest who checks out and is sent to the payment gateway comes
back on a *full navigation from another origin*. No session, no access token,
and the SPA's query cache gone with the page. Without this read they cannot
see the order they have just paid for.

Because the endpoint is unauthenticated, most of this file is about what it
must refuse. Four claims:

1. **The reference alone is not a capability.** References are short and
   sequential and printed on every receipt; the email is what makes the pair a
   secret. No email means no read.
2. **Every miss is the same 404 with the same body.** A wrong email, an
   unknown reference and an order belonging to an account are indistinguishable
   from outside, so the endpoint cannot be used to discover which references
   exist (PRD 10.2 -- 404, never 403).
3. **The email is matched whole.** Case-insensitively, because nobody retypes
   an address the same way twice, but no prefix, no suffix and no wildcard.
4. **A registered customer's order is never readable this way**, even by
   someone who knows the address. That would be an authentication bypass on a
   real account.

Assertions are on HTTP status and on stable error codes, never on wording.
"""
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.models import User
from apps.catalog.models import InventoryReason
from apps.catalog.services import inventory as inventory_services
from apps.catalog.tests.factories import make_category, make_product, make_variant
from apps.dashboard.models import StoreSettings
from apps.orders.models import Order, OrderStatus, PaymentMethod
from apps.orders.services import history as history_services
from apps.orders.services import placement
from apps.shipping.models import ShippingZone
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPass!2026"
GUEST_EMAIL = "walkin@example.com"

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
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _relax_order_lookup_throttle(monkeypatch):
    """
    The guest read is rate limited per IP, which is a real control with its own
    test at the bottom of this file. Every *other* test here would otherwise
    start failing on the twenty-first request in a run for a reason that has
    nothing to do with what it is asserting.

    Patched on the throttle class rather than through the `settings` fixture
    because DRF binds `SimpleRateThrottle.THROTTLE_RATES` to the settings dict
    once, at import time.
    """
    cache.clear()
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "order_lookup", None)
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def store(db):
    settings = StoreSettings.load()
    settings.tax_rate = Decimal("0.00")
    settings.tax_inclusive_pricing = False
    settings.cod_enabled = True
    settings.cod_max_order_value = None
    settings.save()
    return settings


@pytest.fixture
def zone(db):
    return ShippingZone.objects.create(
        name="Inside Dhaka",
        flat_rate=Decimal("60.00"),
        per_kg_rate=Decimal("0.00"),
        base_weight_grams=1000,
        free_shipping_threshold=None,
        cod_allowed=True,
        districts=["Dhaka"],
    )


@pytest.fixture
def variant(db):
    """Ten units at BDT 1000.00, opened through the ledger."""
    category = make_category("Laptops", "laptops")
    product = make_product(
        category, name="Asus TUF Gaming F15", slug="asus-tuf", variants=[]
    )
    row = make_variant(
        product,
        sku="TUF-F15-16-512",
        option_label="16GB / 512GB",
        price="1000.00",
        stock=0,
        weight_grams=0,
    )
    inventory_services.record_movement(
        variant=row,
        delta=10,
        reason=InventoryReason.INITIAL,
        actor=None,
        note="Opening stock",
    )
    row.refresh_from_db()
    return row


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="shopper@example.com",
        password=PASSWORD,
        full_name="Rafiq Hasan",
        is_email_verified=True,
    )


@pytest.fixture
def other_customer(db):
    return User.objects.create_user(email="someone.else@example.com", password=PASSWORD)


def place(*, user=None, email=GUEST_EMAIL, variant=None, quantity=1):
    order, _ = placement.place_order(
        user=user,
        idempotency_key=uuid4().hex,
        payment_method=PaymentMethod.COD,
        shipping_address=dict(SHIPPING_ADDRESS),
        email=email,
        items=[{"variant_id": variant.pk, "quantity": quantity}],
    )
    return order


@pytest.fixture
def guest_order(store, zone, variant):
    return place(variant=variant)


@pytest.fixture
def order_url():
    return lambda reference: reverse(
        "orders:order-detail", kwargs={"reference": reference}
    )


# ---------------------------------------------------------------------------
# The read itself
# ---------------------------------------------------------------------------
def test_a_guest_reads_their_order_with_the_reference_and_the_email_that_placed_it(
    api, guest_order, order_url
):
    response = api.get(order_url(guest_order.reference), {"email": GUEST_EMAIL})

    assert response.status_code == 200
    assert response.json()["reference"] == guest_order.reference


def test_the_guest_read_returns_the_whole_order_the_confirmation_screen_renders(
    api, guest_order, order_url
):
    """
    The gateway return lands on the confirmation page, so this read has to
    carry everything that page shows -- otherwise the guest is told their
    payment worked by a screen with no order on it.
    """
    body = api.get(order_url(guest_order.reference), {"email": GUEST_EMAIL}).json()

    assert body["status"] == OrderStatus.CONFIRMED
    assert body["email"] == GUEST_EMAIL
    assert body["payment_method"] == PaymentMethod.COD
    assert [line["sku"] for line in body["items"]] == ["TUF-F15-16-512"]
    assert body["shipping_address"]["district"] == "Dhaka"
    assert [log["to_status"] for log in body["timeline"]] == ["pending", "confirmed"]
    # Money is decimal strings here exactly as on the signed-in read.
    assert body["subtotal"] == "1000.00"
    assert body["shipping_total"] == "60.00"
    assert body["grand_total"] == "1060.00"


def test_the_email_is_matched_whatever_case_the_guest_types_it_in(
    api, guest_order, order_url
):
    for typed in ("walkin@example.com", "WALKIN@EXAMPLE.COM", "Walkin@Example.Com"):
        response = api.get(order_url(guest_order.reference), {"email": typed})
        assert response.status_code == 200, typed


def test_surrounding_whitespace_in_the_email_is_forgiven(api, guest_order, order_url):
    response = api.get(order_url(guest_order.reference), {"email": "  walkin@example.com "})

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------
def test_the_reference_on_its_own_does_not_open_the_order(api, guest_order, order_url):
    """
    The capability is the pair. A reference is printed on the receipt, quoted
    over the phone and sequential enough to guess at -- on its own it must
    open nothing.
    """
    response = api.get(order_url(guest_order.reference))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_an_empty_email_parameter_is_the_same_as_none_at_all(
    api, guest_order, order_url
):
    response = api.get(order_url(guest_order.reference), {"email": "   "})

    assert response.status_code == 401


@pytest.mark.parametrize(
    "wrong_email",
    [
        "someone.else@example.com",
        "walkin@example.co",
        "walkin@example.comm",
        "alkin@example.com",
        "walkin",
        "walkin@",
        "@example.com",
    ],
)
def test_a_wrong_email_is_a_404_and_never_a_hint(
    api, guest_order, order_url, wrong_email
):
    response = api.get(order_url(guest_order.reference), {"email": wrong_email})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("pattern", ["%", "%@example.com", "walkin@example_com", "_alkin@example.com", "%%"])
def test_a_wildcard_cannot_stand_in_for_the_email(
    api, guest_order, order_url, pattern
):
    """
    `iexact` compiles to a LIKE on MySQL, so the escaping Django does for `%`
    and `_` is load-bearing here rather than incidental: without it the whole
    guest order table would be readable with one request.
    """
    response = api.get(order_url(guest_order.reference), {"email": pattern})

    assert response.status_code == 404


def test_a_wrong_email_and_an_unknown_reference_are_indistinguishable(
    api, guest_order, order_url
):
    """
    If a real reference with a wrong email answered differently from an
    invented one, the endpoint would be an oracle for which references exist.
    """
    real_reference_wrong_email = api.get(
        order_url(guest_order.reference), {"email": "nobody@example.com"}
    )
    no_such_reference = api.get(
        order_url("ORD-2026-999999"), {"email": "nobody@example.com"}
    )

    assert real_reference_wrong_email.status_code == no_such_reference.status_code == 404
    assert real_reference_wrong_email.json() == no_such_reference.json()


# ---------------------------------------------------------------------------
# The account boundary
# ---------------------------------------------------------------------------
def test_a_registered_customers_order_is_not_readable_by_quoting_their_email(
    api, store, zone, variant, customer, order_url
):
    """
    The whole point of the `user__isnull=True` scope. An account's email is
    its identifier, not its password: if quoting it opened the account's
    orders, the guest read would be an authentication bypass.
    """
    order = place(user=customer, variant=variant)

    response = api.get(order_url(order.reference), {"email": customer.email})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_registered_customer_reads_their_own_order_the_way_they_always_did(
    api, store, zone, variant, customer, order_url
):
    order = place(user=customer, variant=variant)
    api.force_authenticate(customer)

    response = api.get(order_url(order.reference))

    assert response.status_code == 200
    assert response.json()["reference"] == order.reference


def test_being_signed_in_never_widens_what_an_account_may_read(
    api, guest_order, other_customer, order_url
):
    """
    A signed-in caller is scoped to their own orders and the `?email=` is
    ignored -- otherwise any account holder could read every guest order by
    supplying the address, which is exactly the hole the pair is meant to
    close.
    """
    api.force_authenticate(other_customer)

    response = api.get(order_url(guest_order.reference), {"email": GUEST_EMAIL})

    assert response.status_code == 404


def test_the_guest_read_does_not_open_the_cancel_endpoint(
    api, guest_order, order_url
):
    """Reading is not writing. Cancellation stays behind authentication."""
    response = api.post(
        reverse("orders:order-cancel", kwargs={"reference": guest_order.reference}),
        {"reason": "Changed my mind", "email": GUEST_EMAIL},
        format="json",
    )

    assert response.status_code == 401
    guest_order.refresh_from_db()
    assert guest_order.status == OrderStatus.CONFIRMED


def test_the_order_list_is_still_closed_to_guests(api):
    response = api.get(reverse("orders:order-list"), {"email": GUEST_EMAIL})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# The service, where the rule actually lives
# ---------------------------------------------------------------------------
def test_the_guest_reader_is_a_service_function_so_both_surfaces_share_one_reader(
    guest_order
):
    order = history_services.get_guest_order(guest_order.reference, GUEST_EMAIL)

    assert order.pk == guest_order.pk
    # The same prefetches the signed-in read uses, so the two cannot drift into
    # rendering different order screens.
    assert [item.sku for item in order.items.all()] == ["TUF-F15-16-512"]
    assert history_services.timeline(order)


def test_the_guest_reader_refuses_an_order_that_belongs_to_an_account(
    store, zone, variant, customer
):
    order = place(user=customer, variant=variant)

    with pytest.raises(DomainError) as excinfo:
        history_services.get_guest_order(order.reference, customer.email)

    assert excinfo.value.code == "NOT_FOUND"
    assert excinfo.value.status_code == 404


@pytest.mark.parametrize("missing", ["", "   ", None])
def test_the_guest_reader_refuses_a_missing_email_before_it_reaches_the_database(
    guest_order, missing
):
    with pytest.raises(DomainError) as excinfo:
        history_services.get_guest_order(guest_order.reference, missing)

    assert excinfo.value.status_code == 404


@pytest.mark.parametrize("missing", ["", "   ", None])
def test_the_guest_reader_refuses_a_missing_reference(guest_order, missing):
    with pytest.raises(DomainError) as excinfo:
        history_services.get_guest_order(missing, GUEST_EMAIL)

    assert excinfo.value.status_code == 404


def test_the_guest_queryset_never_contains_an_order_with_an_account_behind_it(
    store, zone, variant, customer
):
    place(user=customer, variant=variant)
    guest = place(variant=variant)

    assert [order.pk for order in history_services.guest_orders()] == [guest.pk]


# ---------------------------------------------------------------------------
# Enumeration budget (PRD 10.4)
# ---------------------------------------------------------------------------
def test_repeated_guest_lookups_from_one_client_are_rate_limited(
    api, guest_order, order_url, monkeypatch
):
    """
    Re-arms the throttle the autouse fixture above switches off, so the control
    is proved rather than assumed. The reference space is small enough to walk;
    this is what makes walking it expensive.
    """
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "order_lookup", "20/min")
    url = order_url(guest_order.reference)

    for _ in range(20):
        assert api.get(url, {"email": "nobody@example.com"}).status_code == 404

    assert api.get(url, {"email": "nobody@example.com"}).status_code == 429


def test_a_signed_in_customer_is_not_spending_the_guest_lookup_budget(
    api, store, zone, variant, customer, order_url, monkeypatch
):
    """
    The budget is for the anonymous reader. A customer refreshing their own
    order history must not be throttled out of it by a stranger's guesses --
    or by their own reloads.
    """
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "order_lookup", "20/min")
    order = place(user=customer, variant=variant)
    api.force_authenticate(customer)
    url = order_url(order.reference)

    statuses = {api.get(url).status_code for _ in range(25)}

    assert statuses == {200}
