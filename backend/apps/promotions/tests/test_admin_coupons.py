"""
The admin coupon surface (PRD 7.3 CRUD /admin/coupons/, US-A5, US-A8).

Four claims carry this module:

1. **Admin only.** PRD 7.3 lists coupons under the Admin role and US-A8/US-T2
   say staff may view orders and update order status *only* -- so a staff user
   is refused every one of these five calls with 403, and the whole matrix is
   asserted rather than the happy path alone. Hiding the screen in React is
   not the control.
2. **The admin cannot create a coupon checkout would consider malformed.**
   Every definition rule is enforced in apps/promotions/services/coupons.py,
   beside `validate_coupon`, and each rejection carries its own stable code
   (PRD 7.1). Assertions here are on codes and HTTP status, never on wording.
3. **A code is one code.** Normalised to upper case on write, so `save10` and
   `SAVE10` cannot both exist, and the storefront's `find_coupon` still
   resolves whatever case the shopper types.
4. **Editing a coupon never reaches an order already placed.** The discount is
   snapshotted onto Order and onto CouponRedemption at placement; the coupon
   row is not the record of what was charged.

The orders in this file are placed through `apps.orders.services.placement`
rather than built with `Order.objects.create`, because a hand-built order
would prove nothing about what placement actually snapshots.
"""
import itertools
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.catalog.models import InventoryReason
from apps.catalog.services import inventory as inventory_services
from apps.catalog.tests.factories import make_category, make_product, make_variant
from apps.dashboard.models import StoreSettings
from apps.orders.models import Order, PaymentMethod
from apps.orders.services import placement
from apps.promotions.models import Coupon, CouponRedemption, DiscountType, ScopeType
from apps.promotions.services import coupons as coupon_services
from apps.shipping.models import ShippingZone
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPass!2026"
_seq = itertools.count(1)

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
# People, clients, routes
# ---------------------------------------------------------------------------
@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def admin(db):
    return User.objects.create_user(
        email="owner@example.com", password=PASSWORD, role=Role.ADMIN
    )


@pytest.fixture
def staff_member(db):
    """
    Staff, not admin. US-A8 is the whole reason this fixture exists: a staff
    user must be refused every coupon call, and that is only meaningful if
    someone asserts it.
    """
    return User.objects.create_user(
        email="helper@example.com", password=PASSWORD, role=Role.STAFF
    )


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="shopper@example.com",
        password=PASSWORD,
        full_name="Rafiq Hasan",
        is_email_verified=True,
    )


@pytest.fixture
def as_admin(api, admin):
    api.force_authenticate(admin)
    return api


@pytest.fixture
def as_user(api):
    def _as(user):
        api.force_authenticate(user)
        return api

    return _as


@pytest.fixture
def list_url():
    return reverse("promotions_admin:coupon-list")


@pytest.fixture
def detail_url():
    return lambda pk: reverse("promotions_admin:coupon-detail", kwargs={"pk": pk})


# ---------------------------------------------------------------------------
# Payloads and catalogue
# ---------------------------------------------------------------------------
def payload(**overrides):
    """A legal create body. Every value a test depends on, it states itself."""
    now = timezone.now()
    body = {
        "code": "SAVE10",
        "discount_type": DiscountType.PERCENT.value,
        "value": "10.00",
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=30)).isoformat(),
    }
    body.update(overrides)
    return body


@pytest.fixture
def category(db):
    return make_category("Laptops", "laptops")


@pytest.fixture
def product(category):
    return make_product(category, name="Asus TUF Gaming F15", slug="asus-tuf", variants=[])


@pytest.fixture
def variant(product):
    """Ten units at BDT 1000.00, opened through the ledger like the importer."""
    row = make_variant(
        product, sku="TUF-F15", price="1000.00", stock=0, weight_grams=0
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


def place_with(coupon_code, *, variant, user=None, quantity=1):
    """A real order through the real placement service."""
    order, _ = placement.place_order(
        user=user,
        idempotency_key=uuid4().hex,
        payment_method=PaymentMethod.COD,
        shipping_address=dict(SHIPPING_ADDRESS),
        email="walkin@example.com",
        items=[{"variant_id": variant.pk, "quantity": quantity}],
        coupon_code=coupon_code,
    )
    return order


# ---------------------------------------------------------------------------
# Role matrix (US-A8, US-T2, PRD 7.3)
# ---------------------------------------------------------------------------
def _calls(api, list_url, detail_url, coupon):
    """Every method of the coupon surface, as (label, callable)."""
    return [
        ("list", lambda: api.get(list_url)),
        ("create", lambda: api.post(list_url, payload(code="NEWCODE"), format="json")),
        ("retrieve", lambda: api.get(detail_url(coupon.pk))),
        (
            "update",
            lambda: api.patch(
                detail_url(coupon.pk), {"value": "5.00"}, format="json"
            ),
        ),
        ("delete", lambda: api.delete(detail_url(coupon.pk))),
    ]


@pytest.fixture
def existing_coupon(db):
    return Coupon.objects.create(
        code="WELCOME10",
        discount_type=DiscountType.PERCENT,
        value=Decimal("10.00"),
        min_order_value=Decimal("0.00"),
        valid_from=timezone.now() - timedelta(days=1),
        valid_until=timezone.now() + timedelta(days=30),
        per_user_limit=1,
        scope_type=ScopeType.ALL,
        scope_ids=[],
    )


def test_an_anonymous_caller_is_refused_every_coupon_endpoint(
    api, list_url, detail_url, existing_coupon
):
    for label, call in _calls(api, list_url, detail_url, existing_coupon):
        assert call().status_code == 401, label


def test_a_signed_in_customer_is_refused_every_coupon_endpoint_with_403(
    as_user, customer, list_url, detail_url, existing_coupon
):
    client = as_user(customer)
    for label, call in _calls(client, list_url, detail_url, existing_coupon):
        assert call().status_code == 403, label


def test_a_staff_user_is_refused_every_coupon_endpoint_with_403(
    as_user, staff_member, list_url, detail_url, existing_coupon
):
    """
    US-A8: staff may view orders and update order status only. US-T2 says the
    refusal is server-side. Staff is the role most likely to be handed a
    dashboard login, so this is the test that stops a price control leaking to
    the counter.
    """
    client = as_user(staff_member)
    for label, call in _calls(client, list_url, detail_url, existing_coupon):
        assert call().status_code == 403, label

    existing_coupon.refresh_from_db()
    assert existing_coupon.value == Decimal("10.00")
    assert existing_coupon.is_active is True
    assert Coupon.objects.count() == 1


def test_an_admin_reaches_every_coupon_endpoint(
    as_admin, list_url, detail_url, existing_coupon
):
    statuses = {
        label: call().status_code
        for label, call in _calls(as_admin, list_url, detail_url, existing_coupon)
    }

    assert statuses == {
        "list": 200,
        "create": 201,
        "retrieve": 200,
        "update": 200,
        "delete": 200,
    }


# ---------------------------------------------------------------------------
# Create -- the US-A5 form, field by field
# ---------------------------------------------------------------------------
def test_an_admin_creates_a_percentage_coupon_with_every_field_us_a5_names(
    as_admin, list_url, category
):
    now = timezone.now()
    response = as_admin.post(
        list_url,
        payload(
            code="EID2026",
            discount_type=DiscountType.PERCENT.value,
            value="15.00",
            max_discount="2000.00",
            min_order_value="5000.00",
            valid_from=(now + timedelta(days=1)).isoformat(),
            valid_until=(now + timedelta(days=10)).isoformat(),
            usage_limit=100,
            per_user_limit=2,
            scope_type=ScopeType.CATEGORY.value,
            scope_ids=[category.pk],
        ),
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "EID2026"
    assert body["discount_type"] == DiscountType.PERCENT
    assert body["value"] == "15.00"
    assert body["max_discount"] == "2000.00"
    assert body["min_order_value"] == "5000.00"
    assert body["usage_limit"] == 100
    assert body["per_user_limit"] == 2
    assert body["scope_type"] == ScopeType.CATEGORY
    assert body["scope_ids"] == [category.pk]
    # Not started yet, so the register says so rather than calling it active.
    assert body["status"] == "scheduled"
    assert body["redemption_count"] == 0
    assert body["remaining_uses"] == 100


def test_a_fixed_amount_coupon_is_creatable_because_us_a5_asks_for_both_kinds(
    as_admin, list_url
):
    response = as_admin.post(
        list_url,
        payload(code="FLAT500", discount_type=DiscountType.FIXED.value, value="500.00"),
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["discount_type"] == DiscountType.FIXED
    assert response.json()["value"] == "500.00"


def test_money_crosses_the_coupon_api_as_decimal_strings_never_as_floats(
    as_admin, list_url
):
    body = as_admin.post(
        list_url, payload(min_order_value="1500.50", max_discount="250.25"), format="json"
    ).json()

    for key in ("value", "max_discount", "min_order_value", "redeemed_value"):
        assert isinstance(body[key], str), key
    assert body["min_order_value"] == "1500.50"


# ---------------------------------------------------------------------------
# Validation -- reused from the storefront validator's own module
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides,code,field",
    [
        ({"value": "150.00"}, "COUPON_PERCENT_INVALID", "value"),
        ({"value": "0.00"}, "COUPON_VALUE_INVALID", "value"),
        ({"value": "-10.00"}, "COUPON_VALUE_INVALID", "value"),
        ({"min_order_value": "-1.00"}, "COUPON_MIN_ORDER_INVALID", "min_order_value"),
        ({"usage_limit": 0}, "COUPON_USAGE_LIMIT_INVALID", "usage_limit"),
        ({"per_user_limit": 0}, "COUPON_PER_USER_LIMIT_INVALID", "per_user_limit"),
        ({"code": "AB"}, "COUPON_CODE_INVALID", "code"),
        ({"code": "SAVE 10"}, "COUPON_CODE_INVALID", "code"),
        ({"code": "SAVE%10"}, "COUPON_CODE_INVALID", "code"),
        (
            {"scope_type": ScopeType.CATEGORY.value, "scope_ids": []},
            "COUPON_SCOPE_REQUIRED",
            "scope_ids",
        ),
        (
            {"scope_type": ScopeType.PRODUCT.value, "scope_ids": [98765]},
            "COUPON_SCOPE_UNKNOWN",
            "scope_ids",
        ),
        (
            {"discount_type": DiscountType.FIXED.value, "value": "500.00", "max_discount": "100.00"},
            "COUPON_MAX_DISCOUNT_NOT_APPLICABLE",
            "max_discount",
        ),
    ],
)
def test_a_malformed_coupon_definition_is_refused_with_its_own_stable_code(
    as_admin, list_url, overrides, code, field
):
    """
    Each of these would otherwise reach a shopper: a >100% discount, a coupon
    that can never validate, a per-user cap of 0 that `validate_coupon` reads
    as *unlimited*, or a scope pointing at a category that does not exist.
    """
    response = as_admin.post(list_url, payload(**overrides), format="json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["field"] == field
    assert Coupon.objects.count() == 0


def test_a_validity_window_that_ends_before_it_starts_is_refused(as_admin, list_url):
    now = timezone.now()
    response = as_admin.post(
        list_url,
        payload(
            valid_from=(now + timedelta(days=10)).isoformat(),
            valid_until=(now + timedelta(days=1)).isoformat(),
        ),
        format="json",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COUPON_WINDOW_INVALID"
    assert Coupon.objects.count() == 0


def test_a_zero_length_window_is_refused_because_a_coupon_needs_a_life(
    as_admin, list_url
):
    instant = (timezone.now() + timedelta(days=1)).isoformat()
    response = as_admin.post(
        list_url, payload(valid_from=instant, valid_until=instant), format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COUPON_WINDOW_INVALID"


def test_a_percentage_of_exactly_one_hundred_is_allowed_because_it_is_a_real_promotion(
    as_admin, list_url
):
    response = as_admin.post(list_url, payload(code="FREEBIE", value="100.00"), format="json")

    assert response.status_code == 201


def test_the_admin_api_and_the_checkout_validator_agree_on_what_a_coupon_does(
    as_admin, list_url, product
):
    """
    The point of putting the definition rules in the same module as
    `validate_coupon`: a coupon the admin was allowed to create must price a
    basket, not blow up in checkout.
    """
    as_admin.post(
        list_url,
        payload(code="MIX20", discount_type=DiscountType.PERCENT.value, value="20.00"),
        format="json",
    )

    class Line:
        variant = product.variants.first()
        line_total = Decimal("1000.00")

    coupon = coupon_services.find_coupon("mix20")
    discount = coupon_services.validate_coupon(
        coupon=coupon, lines=[Line()], subtotal=Decimal("1000.00")
    )

    assert discount == Decimal("200.00")


# ---------------------------------------------------------------------------
# Code normalisation and uniqueness
# ---------------------------------------------------------------------------
def test_a_code_is_stored_upper_cased_whatever_case_the_admin_typed(
    as_admin, list_url
):
    response = as_admin.post(list_url, payload(code="  save10  "), format="json")

    assert response.status_code == 201
    assert response.json()["code"] == "SAVE10"
    assert Coupon.objects.get().code == "SAVE10"


def test_the_same_code_in_another_case_cannot_be_created_twice(as_admin, list_url):
    assert as_admin.post(list_url, payload(code="save10"), format="json").status_code == 201

    response = as_admin.post(list_url, payload(code="SAVE10"), format="json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COUPON_CODE_TAKEN"
    assert response.json()["error"]["field"] == "code"
    assert Coupon.objects.count() == 1


def test_the_storefront_lookup_still_matches_a_coupon_the_admin_created(
    as_admin, list_url
):
    """
    Normalising on write is only half the rule -- `find_coupon` normalises the
    shopper's input through the same `canonical_code`, so every case matches.
    """
    as_admin.post(list_url, payload(code="save10"), format="json")

    for typed in ("save10", "SAVE10", "  SaVe10  "):
        assert coupon_services.find_coupon(typed).code == "SAVE10"


def test_renaming_a_coupon_onto_another_coupons_code_is_refused(
    as_admin, list_url, detail_url
):
    first = as_admin.post(list_url, payload(code="SAVE10"), format="json").json()
    as_admin.post(list_url, payload(code="SAVE20"), format="json")

    response = as_admin.patch(
        detail_url(first["id"]), {"code": "save20"}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COUPON_CODE_TAKEN"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
def test_an_edit_changes_only_the_fields_it_names(as_admin, list_url, detail_url):
    created = as_admin.post(
        list_url, payload(code="SAVE10", min_order_value="1000.00"), format="json"
    ).json()

    updated = as_admin.patch(
        detail_url(created["id"]), {"value": "25.00"}, format="json"
    ).json()

    assert updated["value"] == "25.00"
    assert updated["min_order_value"] == "1000.00"
    assert updated["code"] == "SAVE10"


def test_a_partial_edit_is_judged_as_the_whole_coupon_it_would_produce(
    as_admin, list_url, detail_url
):
    """
    Switching a percentage coupon to a fixed one while a cap is still set
    would leave a cap that silently does nothing -- so the edit is judged on
    the coupon it *results in*, not on the one key it sent.
    """
    created = as_admin.post(
        list_url, payload(value="10.00", max_discount="500.00"), format="json"
    ).json()

    response = as_admin.patch(
        detail_url(created["id"]),
        {"discount_type": DiscountType.FIXED.value},
        format="json",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COUPON_MAX_DISCOUNT_NOT_APPLICABLE"


def test_switching_a_coupon_back_to_catalogue_wide_clears_its_stale_scope(
    as_admin, list_url, detail_url, category
):
    created = as_admin.post(
        list_url,
        payload(scope_type=ScopeType.CATEGORY.value, scope_ids=[category.pk]),
        format="json",
    ).json()

    updated = as_admin.patch(
        detail_url(created["id"]), {"scope_type": ScopeType.ALL.value}, format="json"
    ).json()

    assert updated["scope_type"] == ScopeType.ALL
    assert updated["scope_ids"] == []


def test_an_empty_edit_is_a_400_rather_than_a_silent_no_op(
    as_admin, detail_url, existing_coupon
):
    response = as_admin.patch(detail_url(existing_coupon.pk), {}, format="json")

    assert response.status_code == 400


def test_editing_a_coupon_that_does_not_exist_is_a_404(as_admin, detail_url):
    response = as_admin.patch(detail_url(9999), {"value": "5.00"}, format="json")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# The rule that protects placed orders
# ---------------------------------------------------------------------------
def test_a_placed_order_keeps_the_discount_it_was_given_when_the_coupon_is_later_edited(
    as_admin, list_url, detail_url, store, zone, variant
):
    """
    The coupon row is not the record of what was charged. `Order.discount_total`
    and `CouponRedemption.discount_amount` are snapshots taken at placement,
    and a later edit -- here 10% becoming 90% -- must not reach back through
    them (PRD 6.3, FR-ORD-2).
    """
    created = as_admin.post(list_url, payload(code="SAVE10", value="10.00"), format="json").json()
    order = place_with("SAVE10", variant=variant)

    assert order.discount_total == Decimal("100.00")
    assert order.grand_total == Decimal("960.00")  # 1000 - 100 + 60 shipping

    response = as_admin.patch(detail_url(created["id"]), {"value": "90.00"}, format="json")
    assert response.status_code == 200

    order.refresh_from_db()
    assert order.discount_total == Decimal("100.00")
    assert order.subtotal == Decimal("1000.00")
    assert order.grand_total == Decimal("960.00")
    assert CouponRedemption.objects.get(order=order).discount_amount == Decimal("100.00")


def test_the_customers_own_order_screen_still_shows_the_discount_that_was_charged(
    as_admin, list_url, detail_url, store, zone, variant, customer, api
):
    created = as_admin.post(list_url, payload(code="SAVE10", value="10.00"), format="json").json()
    order = place_with("SAVE10", variant=variant, user=customer)
    as_admin.patch(detail_url(created["id"]), {"value": "90.00"}, format="json")

    api.force_authenticate(customer)
    body = api.get(
        reverse("orders:order-detail", kwargs={"reference": order.reference})
    ).json()

    assert body["discount_total"] == "100.00"
    assert body["grand_total"] == "960.00"


def test_the_code_of_a_redeemed_coupon_cannot_be_changed(
    as_admin, list_url, detail_url, store, zone, variant
):
    """
    Order.coupon is a reference, not a snapshot, so renaming a used coupon
    would rewrite which code every historical order reports having used.
    """
    created = as_admin.post(list_url, payload(code="SAVE10"), format="json").json()
    order = place_with("SAVE10", variant=variant)

    response = as_admin.patch(detail_url(created["id"]), {"code": "SAVE99"}, format="json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COUPON_CODE_IMMUTABLE"
    assert response.json()["error"]["field"] == "code"
    order.refresh_from_db()
    assert order.coupon.code == "SAVE10"


def test_an_unused_coupons_code_can_still_be_corrected(as_admin, list_url, detail_url):
    created = as_admin.post(list_url, payload(code="SVAE10"), format="json").json()

    updated = as_admin.patch(detail_url(created["id"]), {"code": "save10"}, format="json")

    assert updated.status_code == 200
    assert updated.json()["code"] == "SAVE10"


# ---------------------------------------------------------------------------
# Redemption count (US-A5: "a redemption count is visible per coupon")
# ---------------------------------------------------------------------------
def test_a_coupon_row_carries_the_redemption_count_counted_from_the_redemption_rows(
    as_admin, list_url, detail_url, store, zone, variant
):
    created = as_admin.post(
        list_url, payload(code="SAVE10", usage_limit=5, per_user_limit=5), format="json"
    ).json()
    assert created["redemption_count"] == 0

    place_with("SAVE10", variant=variant)
    place_with("SAVE10", variant=variant)

    detail = as_admin.get(detail_url(created["id"])).json()
    assert detail["redemption_count"] == 2
    assert detail["redeemed_value"] == "200.00"
    assert detail["remaining_uses"] == 3

    row = as_admin.get(list_url).json()["results"][0]
    assert row["redemption_count"] == 2


def test_the_redemption_count_follows_the_redemption_rows_rather_than_a_counter(
    as_admin, list_url, detail_url, store, zone, variant
):
    """
    A cancelled order releases its redemption (FR-CPN-8). A stored counter
    would have to be decremented by whoever remembered to; a COUNT(*) cannot
    forget, and it is the same rows `validate_coupon` enforces the caps from.
    """
    created = as_admin.post(
        list_url, payload(code="SAVE10", usage_limit=5), format="json"
    ).json()
    order = place_with("SAVE10", variant=variant)
    assert as_admin.get(detail_url(created["id"])).json()["redemption_count"] == 1

    placement.cancel_order(order, actor=None, reason="Changed my mind")

    body = as_admin.get(detail_url(created["id"])).json()
    assert body["redemption_count"] == 0
    assert body["redeemed_value"] == "0.00"
    assert body["remaining_uses"] == 5


def test_an_unlimited_coupon_reports_no_remaining_uses_rather_than_zero(
    as_admin, list_url
):
    body = as_admin.post(list_url, payload(usage_limit=None), format="json").json()

    assert body["usage_limit"] is None
    assert body["remaining_uses"] is None, "null is unlimited; 0 would mean exhausted"


# ---------------------------------------------------------------------------
# Delete -- retire, never destroy
# ---------------------------------------------------------------------------
def test_deleting_a_coupon_retires_it_and_keeps_the_history_of_what_it_discounted(
    as_admin, list_url, detail_url, store, zone, variant
):
    created = as_admin.post(list_url, payload(code="SAVE10"), format="json").json()
    order = place_with("SAVE10", variant=variant)

    response = as_admin.delete(detail_url(created["id"]))

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["status"] == "inactive"
    assert response.json()["redemption_count"] == 1
    # The promotion really ran: the order still points at it and the
    # redemption row is still there to prove it.
    assert Coupon.objects.filter(pk=created["id"]).exists()
    order.refresh_from_db()
    assert order.coupon_id == created["id"]
    assert order.discount_total == Decimal("100.00")
    assert CouponRedemption.objects.filter(order=order).count() == 1


def test_a_retired_coupon_is_refused_at_checkout_by_the_validator(
    as_admin, list_url, detail_url, product
):
    created = as_admin.post(list_url, payload(code="SAVE10"), format="json").json()
    as_admin.delete(detail_url(created["id"]))

    class Line:
        variant = product.variants.first()
        line_total = Decimal("1000.00")

    with pytest.raises(DomainError) as excinfo:
        coupon_services.validate_coupon(
            coupon=coupon_services.find_coupon("SAVE10"),
            lines=[Line()],
            subtotal=Decimal("1000.00"),
        )

    assert excinfo.value.code == "COUPON_INACTIVE"


def test_deleting_an_already_retired_coupon_is_a_no_op_rather_than_an_error(
    as_admin, list_url, detail_url
):
    created = as_admin.post(list_url, payload(is_active=False), format="json").json()

    response = as_admin.delete(detail_url(created["id"]))

    assert response.status_code == 200
    assert response.json()["is_active"] is False


# ---------------------------------------------------------------------------
# The register: filtering and listing
# ---------------------------------------------------------------------------
@pytest.fixture
def register(as_admin, list_url):
    """One coupon in each of the four lifecycle states."""
    now = timezone.now()
    as_admin.post(list_url, payload(code="LIVE"), format="json")
    as_admin.post(
        list_url,
        payload(
            code="SOON",
            valid_from=(now + timedelta(days=2)).isoformat(),
            valid_until=(now + timedelta(days=9)).isoformat(),
        ),
        format="json",
    )
    Coupon.objects.create(
        code="LASTYEAR",
        discount_type=DiscountType.PERCENT,
        value=Decimal("10.00"),
        valid_from=now - timedelta(days=400),
        valid_until=now - timedelta(days=300),
        per_user_limit=1,
    )
    as_admin.post(list_url, payload(code="SWITCHEDOFF", is_active=False), format="json")
    return None


@pytest.mark.parametrize(
    "status,expected",
    [
        ("active", ["LIVE"]),
        ("scheduled", ["SOON"]),
        ("expired", ["LASTYEAR"]),
        ("inactive", ["SWITCHEDOFF"]),
    ],
)
def test_the_register_can_be_filtered_to_one_lifecycle_state(
    as_admin, list_url, register, status, expected
):
    body = as_admin.get(list_url, {"status": status}).json()

    assert sorted(row["code"] for row in body["results"]) == expected


def test_the_lifecycle_states_partition_the_register_exactly(
    as_admin, list_url, register
):
    """
    Every coupon is in one state and only one, so `?status=` and the `status`
    on a row can never disagree about where a coupon belongs.
    """
    everything = as_admin.get(list_url).json()
    seen = []
    for status in ("active", "scheduled", "expired", "inactive"):
        seen += [row["code"] for row in as_admin.get(list_url, {"status": status}).json()["results"]]

    assert sorted(seen) == sorted(row["code"] for row in everything["results"])
    assert len(seen) == len(set(seen))


def test_the_register_can_be_searched_by_code_in_any_case(
    as_admin, list_url, register
):
    body = as_admin.get(list_url, {"search": "last"}).json()

    assert [row["code"] for row in body["results"]] == ["LASTYEAR"]


def test_a_search_term_cannot_smuggle_a_wildcard_into_the_lookup(
    as_admin, list_url, register
):
    body = as_admin.get(list_url, {"search": "%"}).json()

    assert body["results"] == []


def test_a_nonsense_status_filter_is_a_422_rather_than_being_ignored(
    as_admin, list_url
):
    response = as_admin.get(list_url, {"status": "runningish"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FILTER"
    assert response.json()["error"]["field"] == "status"


def test_the_register_is_newest_first_and_paginated(as_admin, list_url):
    for index in range(3):
        as_admin.post(list_url, payload(code="CODE{0}".format(index)), format="json")

    body = as_admin.get(list_url, {"page_size": 2}).json()

    assert body["count"] == 3
    assert [row["code"] for row in body["results"]] == ["CODE2", "CODE1"]


# ---------------------------------------------------------------------------
# The service layer on its own, where no serializer is involved
# ---------------------------------------------------------------------------
def test_the_service_refuses_a_malformed_definition_even_with_no_view_in_sight(db):
    """
    The rules live in the service because a management command, a data
    migration or a test can call it with no serializer anywhere near.
    """
    now = timezone.now()
    with pytest.raises(DomainError) as excinfo:
        coupon_services.create_coupon(
            code="BAD",
            discount_type=DiscountType.PERCENT,
            value=Decimal("200.00"),
            valid_from=now,
            valid_until=now + timedelta(days=1),
        )

    assert excinfo.value.code == "COUPON_PERCENT_INVALID"
    assert Coupon.objects.count() == 0


def test_the_service_refuses_a_field_it_does_not_own(db):
    now = timezone.now()
    with pytest.raises(DomainError) as excinfo:
        coupon_services.create_coupon(
            code="SAVE10",
            discount_type=DiscountType.PERCENT,
            value=Decimal("10.00"),
            valid_from=now,
            valid_until=now + timedelta(days=1),
            redemption_count=99,
        )

    assert excinfo.value.code == "COUPON_FIELD_UNKNOWN"


def test_a_create_missing_a_field_a_coupon_cannot_exist_without_is_refused(db):
    with pytest.raises(DomainError) as excinfo:
        coupon_services.create_coupon(code="SAVE10")

    assert excinfo.value.code == "COUPON_FIELD_REQUIRED"
