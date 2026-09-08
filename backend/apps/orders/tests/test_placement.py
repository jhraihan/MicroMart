"""
Order placement, snapshotting, idempotency and cancellation
(apps/orders/services/placement.py -- PRD 5.4, 5.6, 5.11, 15.1).

This is the code that takes money, so the assertions here are deliberately
about *state*, not about return values: what ended up in orders_order, in
orders_order_item, in orders_order_status_log and in catalog_inventory_log
after the call. A placement that returned a plausible object while leaving the
ledger wrong would still be a broken shop.

Two conventions carried from the rest of the suite:

* Every test builds the rows it asserts on. Nothing reads seed data.
* Failures are asserted on `DomainError.code`, never on the message. Codes are
  the stable contract (PRD 7.1); messages are not.

Stock is opened with an INITIAL ledger row rather than written straight onto
the variant, so `sum(InventoryLog.delta) == ProductVariant.stock` holds from
the first line of every test -- that reconciliation is the integrity check the
whole inventory design exists to support, and a fixture that broke it would
make it untestable.

Concurrency and oversell under real row locks are deliberately *not* here:
select_for_update does not engage inside pytest's wrapping transaction, so
those need `transaction=True` and live in their own module.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Address, Role, User
from apps.cart.services import cart as cart_services
from apps.catalog.models import InventoryLog, InventoryReason
from apps.catalog.services import inventory as inventory_services
from apps.catalog.tests.factories import make_category, make_product, make_variant
from apps.dashboard.models import StoreSettings
from apps.orders.models import (
    Actor,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusLog,
    PaymentMethod,
    Shipment,
)
from apps.orders.services import placement
from apps.promotions.models import Coupon, CouponRedemption, DiscountType, ScopeType
from apps.shipping.models import ShippingZone
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


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

# Deliberately different in every field from SHIPPING_ADDRESS, so a test that
# checks out against `address_id` can prove the address book was read rather
# than the form silently winning.
BOOK_ADDRESS = {
    "recipient_name": "Nusrat Jahan",
    "phone": "01812345678",
    "division": "Dhaka",
    "district": "Gazipur",
    "upazila": "Tongi",
    "area": "Cherag Ali",
    "street": "Flat 3B, House 9, Cherag Ali",
    "postcode": "1710",
}


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------
def open_stock(variant, quantity, *, actor=None):
    """
    Seed a variant's stock *through the ledger*, the way the importer does.

    Writing ProductVariant.stock directly would leave sum(delta) disagreeing
    with stock before a test had done anything, and the reconciliation
    assertions below would then be meaningless.
    """
    inventory_services.record_movement(
        variant=variant,
        delta=quantity,
        reason=InventoryReason.INITIAL,
        actor=actor,
        note="Opening stock",
    )
    variant.refresh_from_db()
    return variant


def buy(variant, quantity=1):
    """The `items` payload for one line."""
    return [{"variant_id": variant.pk, "quantity": quantity}]


def place(*, items=None, **kwargs):
    """
    place_order with the boring arguments filled in.

    Every default is overridable, because most tests here are about exactly
    one of them being different.
    """
    kwargs.setdefault("idempotency_key", uuid4().hex)
    kwargs.setdefault("payment_method", PaymentMethod.COD)
    kwargs.setdefault("email", "guest@example.com")
    # A saved address supersedes the typed one, so the typed one is left out
    # entirely -- the service must read the book, not fall back to the form.
    default_address = None if kwargs.get("address_id") else dict(SHIPPING_ADDRESS)
    kwargs.setdefault("shipping_address", default_address)
    return placement.place_order(items=items, **kwargs)


def logs_for(order, reason=None):
    queryset = InventoryLog.objects.filter(order=order)
    if reason is not None:
        queryset = queryset.filter(reason=reason)
    return list(queryset.order_by("id"))


def status_pairs(order):
    """The append-only timeline as (from, to) pairs, oldest first."""
    return [
        (log.from_status, log.to_status)
        for log in OrderStatusLog.objects.filter(order=order).order_by("created_at", "id")
    ]


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
        per_kg_rate=Decimal("20.00"),
        base_weight_grams=1000,
        free_shipping_threshold=None,
        cod_allowed=True,
        districts=["Dhaka", "Gazipur"],
    )


@pytest.fixture
def category(db):
    return make_category("Laptops", "laptops")


@pytest.fixture
def product(category):
    return make_product(
        category, name="Asus TUF Gaming F15 FX507", slug="asus-tuf-f15", variants=[]
    )


@pytest.fixture
def variant(product):
    """Ten units on the shelf at BDT 1000.00, weightless so shipping is flat."""
    row = make_variant(
        product,
        sku="TUF-F15-16-512",
        option_label="16GB / 512GB",
        price="1000.00",
        stock=0,
        weight_grams=0,
    )
    return open_stock(row, 10)


@pytest.fixture
def other_variant(category):
    other = make_product(
        category, name="Logitech MX Master 3S", slug="logitech-mx-master", variants=[]
    )
    row = make_variant(
        other, sku="MX-MASTER-3S", option_label="Graphite", price="200.00", stock=0
    )
    return open_stock(row, 5)


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="shopper@example.com",
        password="Str0ngPass!2026",
        full_name="Rafiq Hasan",
        is_email_verified=True,
    )


@pytest.fixture
def other_customer(db):
    return User.objects.create_user(
        email="someone.else@example.com", password="Str0ngPass!2026"
    )


@pytest.fixture
def staff(db):
    return User.objects.create_user(
        email="ops@example.com", password="Str0ngPass!2026", role=Role.ADMIN
    )


@pytest.fixture
def coupon(db):
    now = timezone.now()
    return Coupon.objects.create(
        code="welcome10",
        discount_type=DiscountType.PERCENT,
        value=Decimal("10.00"),
        min_order_value=Decimal("0.00"),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=30),
        usage_limit=None,
        per_user_limit=1,
        scope_type=ScopeType.ALL,
    )


@pytest.fixture
def api():
    return APIClient()


# ---------------------------------------------------------------------------
# Cash on Delivery: the happy path
# ---------------------------------------------------------------------------
def test_placing_a_cash_on_delivery_order_creates_it_confirmed_with_server_computed_totals(
    store, zone, variant
):
    order, created = place(items=buy(variant, 2))

    assert created is True
    assert order.pk is not None
    assert order.reference.startswith("ORD-{0}-".format(timezone.now().year))
    assert order.payment_method == PaymentMethod.COD
    # COD is agreed at placement, so the order is confirmed on the spot.
    assert order.status == OrderStatus.CONFIRMED
    assert order.zone_id == zone.pk
    assert order.subtotal == Decimal("2000.00")
    assert order.discount_total == Decimal("0.00")
    assert order.shipping_total == Decimal("60.00")
    assert order.tax_total == Decimal("0.00")
    assert order.grand_total == Decimal("2060.00")


def test_placing_an_order_creates_one_order_item_per_basket_line(store, zone, variant, other_variant):
    order, _ = place(
        items=[
            {"variant_id": variant.pk, "quantity": 2},
            {"variant_id": other_variant.pk, "quantity": 1},
        ]
    )

    items = list(order.items.order_by("id"))
    assert len(items) == 2
    assert {item.sku for item in items} == {"TUF-F15-16-512", "MX-MASTER-3S"}
    assert sum(item.quantity for item in items) == 3


def test_a_cash_on_delivery_placement_decrements_stock_exactly_once(store, zone, variant):
    place(items=buy(variant, 3))

    variant.refresh_from_db()
    assert variant.stock == 7


def test_a_cash_on_delivery_placement_writes_one_inventory_log_row_matching_the_decrement(
    store, zone, variant
):
    order, _ = place(items=buy(variant, 3))

    movements = logs_for(order)
    assert len(movements) == 1
    movement = movements[0]
    assert movement.delta == -3
    assert movement.reason == InventoryReason.ORDER_CONFIRMED
    assert movement.variant_id == variant.pk
    assert order.reference in movement.note


def test_order_placement_opens_the_timeline_with_a_blank_from_status_then_logs_the_confirmation(
    store, zone, variant
):
    order, _ = place(items=buy(variant))

    assert status_pairs(order) == [
        ("", OrderStatus.PENDING),
        (OrderStatus.PENDING, OrderStatus.CONFIRMED),
    ]
    opening = OrderStatusLog.objects.filter(order=order).earliest("created_at", "id")
    assert opening.actor_role == Actor.CUSTOMER
    assert opening.note == "Order placed"


def test_an_online_payment_order_is_left_pending_with_stock_untouched_until_the_gateway_confirms(
    store, zone, variant
):
    order, _ = place(items=buy(variant, 4), payment_method=PaymentMethod.ONLINE)

    variant.refresh_from_db()
    assert order.status == OrderStatus.PENDING
    assert variant.stock == 10
    assert logs_for(order) == []
    assert status_pairs(order) == [("", OrderStatus.PENDING)]


def test_placing_an_order_from_the_signed_in_customers_server_cart_empties_that_cart(
    store, zone, variant, customer
):
    cart = cart_services.get_cart(customer)
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    assert cart.items.count() == 1

    order, _ = place(items=None, user=customer)

    cart.refresh_from_db()
    assert cart.items.count() == 0
    assert order.items.count() == 1
    assert order.items.first().quantity == 2


# ---------------------------------------------------------------------------
# Snapshotting (FR-ORD-2, FR-SHP-7) -- the core domain invariant
# ---------------------------------------------------------------------------
def test_order_items_copy_the_product_name_variant_label_sku_and_unit_price_at_purchase_time(
    store, zone, variant, product
):
    order, _ = place(items=buy(variant, 2))

    item = order.items.get()
    assert item.product_name == product.name
    assert item.variant_label == "16GB / 512GB"
    assert item.sku == "TUF-F15-16-512"
    assert item.unit_price == Decimal("1000.00")
    assert item.quantity == 2
    assert item.line_total == Decimal("2000.00")


def test_the_order_snapshots_the_tax_rate_that_was_live_when_it_was_placed(store, zone, variant):
    store.tax_rate = Decimal("15.00")
    store.save()

    order, _ = place(items=buy(variant, 2))

    assert order.tax_rate_applied == Decimal("15.00")
    assert order.tax_total == Decimal("300.00")  # 15% of the 2000.00 merchandise
    assert order.grand_total == Decimal("2360.00")


def test_the_shipping_address_is_copied_onto_the_order_and_never_referenced_by_foreign_key(
    store, zone, variant, customer
):
    saved = Address.objects.create(user=customer, **BOOK_ADDRESS)

    order, _ = place(items=buy(variant), user=customer, address_id=saved.pk, save_address=True)

    # There is no FK from Order to the address book at all -- the columns are
    # plain snapshot fields.
    assert [
        field.name
        for field in Order._meta.get_fields()
        if getattr(field, "related_model", None) is Address
    ] == []
    for key, value in BOOK_ADDRESS.items():
        assert getattr(order, "ship_{0}".format(key)) == value, key
    # address_id means the address is already in the book, so save_address is
    # ignored rather than writing a duplicate row.
    assert Address.objects.filter(user=customer).count() == 1


def test_a_shipping_address_phone_is_normalised_to_its_canonical_bangladesh_form(
    store, zone, variant
):
    address = dict(SHIPPING_ADDRESS, phone="+880 1712-345678")

    order, _ = place(items=buy(variant), shipping_address=address)

    assert order.ship_phone == "01712345678"


def _order_state(order):
    """Every stored column on the order and its items, read back from the database."""
    fresh = Order.objects.get(pk=order.pk)
    columns = {
        field.attname: getattr(fresh, field.attname)
        for field in Order._meta.concrete_fields
    }
    items = [
        {
            field.attname: getattr(item, field.attname)
            for field in OrderItem._meta.concrete_fields
        }
        for item in fresh.items.order_by("id")
    ]
    return columns, items


def test_later_catalogue_address_book_tax_and_shipping_edits_leave_a_historical_order_unchanged(
    store, zone, variant, product, customer, coupon
):
    """
    The single most important test in this module.

    An order is a record of a sale that already happened. Renaming a product,
    repricing a variant, correcting the customer's saved address, changing the
    VAT rate or reworking a shipping zone are all edits to *today's* shop, and
    none of them may reach backwards into an order that has already been paid
    for and shipped.
    """
    saved = Address.objects.create(user=customer, **BOOK_ADDRESS)
    store.tax_rate = Decimal("15.00")
    store.save()

    order, _ = place(
        items=buy(variant, 2), user=customer, address_id=saved.pk, coupon_code="WELCOME10"
    )
    before = _order_state(order)

    # --- Now change everything the order was built from. ---
    product.name = "Asus TUF Gaming F15 (2027 refresh)"
    product.slug = "asus-tuf-f15-2027"
    product.save()

    variant.option_label = "32GB / 2TB"
    variant.sku = "TUF-F15-32-2048"
    variant.price = Decimal("4999.00")
    variant.save()

    saved.recipient_name = "Someone Else Entirely"
    saved.phone = "01911111111"
    saved.district = "Chattogram"
    saved.street = "A completely different street"
    saved.postcode = "4000"
    saved.save()

    store.tax_rate = Decimal("5.00")
    store.tax_inclusive_pricing = True
    store.save()

    zone.name = "Dhaka Metro"
    zone.flat_rate = Decimal("500.00")
    zone.save()

    coupon.value = Decimal("90.00")
    coupon.is_active = False
    coupon.save()

    # --- Nothing about the stored order moved. ---
    assert _order_state(order) == before

    fresh = Order.objects.get(pk=order.pk)
    item = fresh.items.get()
    assert item.product_name == "Asus TUF Gaming F15 FX507"
    assert item.variant_label == "16GB / 512GB"
    assert item.sku == "TUF-F15-16-512"
    assert item.unit_price == Decimal("1000.00")
    assert fresh.ship_recipient_name == "Nusrat Jahan"
    assert fresh.ship_district == "Gazipur"
    assert fresh.tax_rate_applied == Decimal("15.00")
    assert fresh.shipping_total == Decimal("60.00")

    # ...and every one of those now differs from the live row it was copied
    # from, so none of the assertions above can be passing by coincidence.
    for snapshot, live, label in (
        (item.product_name, product.name, "product name"),
        (item.variant_label, variant.option_label, "variant label"),
        (item.sku, variant.sku, "sku"),
        (item.unit_price, variant.price, "unit price"),
        (fresh.ship_recipient_name, saved.recipient_name, "recipient name"),
        (fresh.ship_district, saved.district, "district"),
        (fresh.tax_rate_applied, store.tax_rate, "tax rate"),
        (fresh.shipping_total, zone.flat_rate, "shipping total"),
    ):
        assert snapshot != live, label


# ---------------------------------------------------------------------------
# Idempotency (FR-CHK-7)
# ---------------------------------------------------------------------------
def test_replaying_an_idempotency_key_returns_the_original_order_and_creates_no_second_one(
    store, zone, variant, customer
):
    key = uuid4().hex

    first, first_created = place(items=buy(variant, 2), user=customer, idempotency_key=key)
    second, second_created = place(items=buy(variant, 2), user=customer, idempotency_key=key)

    assert first_created is True
    assert second_created is False
    assert second.pk == first.pk
    assert second.reference == first.reference
    assert Order.objects.count() == 1


def test_replaying_an_idempotency_key_does_not_decrement_stock_or_charge_a_second_time(
    store, zone, variant, customer
):
    key = uuid4().hex

    first, _ = place(items=buy(variant, 3), user=customer, idempotency_key=key)
    second, _ = place(items=buy(variant, 3), user=customer, idempotency_key=key)

    variant.refresh_from_db()
    assert variant.stock == 7
    assert InventoryLog.objects.filter(reason=InventoryReason.ORDER_CONFIRMED).count() == 1
    assert second.grand_total == first.grand_total
    assert OrderItem.objects.count() == 1


def test_a_guest_replaying_the_same_key_with_the_same_email_receives_the_original_order(
    store, zone, variant
):
    key = uuid4().hex

    first, first_created = place(
        items=buy(variant), idempotency_key=key, email="guest@example.com"
    )
    second, second_created = place(
        items=buy(variant), idempotency_key=key, email="GUEST@example.com"
    )

    assert first_created is True
    assert second_created is False
    assert second.pk == first.pk
    assert first.user_id is None
    assert Order.objects.count() == 1


def test_a_different_idempotency_key_creates_a_distinct_second_order(store, zone, variant, customer):
    first, _ = place(items=buy(variant), user=customer, idempotency_key=uuid4().hex)
    second, created = place(items=buy(variant), user=customer, idempotency_key=uuid4().hex)

    assert created is True
    assert second.pk != first.pk
    assert second.reference != first.reference
    assert Order.objects.count() == 2

    variant.refresh_from_db()
    assert variant.stock == 8


def test_a_guest_key_replayed_by_a_signed_in_customer_is_refused_as_a_key_conflict(
    store, zone, variant, customer
):
    key = uuid4().hex
    place(items=buy(variant), idempotency_key=key, email="guest@example.com")

    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant), user=customer, idempotency_key=key)

    assert excinfo.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert excinfo.value.status_code == 409
    assert Order.objects.count() == 1


def test_a_guest_key_replayed_under_a_different_email_is_refused_as_a_key_conflict(
    store, zone, variant
):
    key = uuid4().hex
    place(items=buy(variant), idempotency_key=key, email="first@example.com")

    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant), idempotency_key=key, email="second@example.com")

    assert excinfo.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert Order.objects.count() == 1


def test_one_customers_idempotency_key_never_hands_back_another_customers_order(
    store, zone, variant, customer, other_customer
):
    key = uuid4().hex
    place(items=buy(variant), user=customer, idempotency_key=key)

    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant), user=other_customer, idempotency_key=key)

    assert excinfo.value.code == "IDEMPOTENCY_KEY_CONFLICT"


def test_placing_an_order_without_an_idempotency_key_is_refused(store, zone, variant):
    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant), idempotency_key="   ")

    assert excinfo.value.code == "IDEMPOTENCY_KEY_REQUIRED"
    assert excinfo.value.status_code == 400
    assert Order.objects.count() == 0


# ---------------------------------------------------------------------------
# Guest checkout (FR-CHK-5)
# ---------------------------------------------------------------------------
def test_a_guest_can_place_an_order_with_only_a_contact_email_and_phone(store, zone, variant):
    order, created = place(
        items=buy(variant, 2), email="Walk.In@Example.COM", phone="+8801812345678"
    )

    assert created is True
    assert order.user_id is None
    assert order.email == "walk.in@example.com"
    assert order.phone == "01812345678"
    assert order.status == OrderStatus.CONFIRMED


def test_a_guest_order_falls_back_to_the_shipping_address_phone_when_no_contact_phone_is_given(
    store, zone, variant
):
    order, _ = place(items=buy(variant), phone="")

    assert order.phone == SHIPPING_ADDRESS["phone"]


def test_a_signed_in_customers_account_email_overrides_whatever_the_checkout_form_supplied(
    store, zone, variant, customer
):
    order, _ = place(items=buy(variant), user=customer, email="typo@example.com")

    assert order.user_id == customer.pk
    assert order.email == customer.email


def test_an_order_with_no_email_at_all_is_refused_because_the_receipt_has_nowhere_to_go(
    store, zone, variant
):
    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant), email="")

    assert excinfo.value.code == "EMAIL_REQUIRED"
    assert excinfo.value.status_code == 400
    assert Order.objects.count() == 0


def test_an_incomplete_shipping_address_names_the_missing_field(store, zone, variant):
    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant), shipping_address=dict(SHIPPING_ADDRESS, street=""))

    assert excinfo.value.code == "ADDRESS_INCOMPLETE"
    assert excinfo.value.field == "shipping_address.street"
    assert Order.objects.count() == 0


def test_opting_to_save_the_shipping_address_writes_it_to_the_customers_address_book(
    store, zone, variant, customer
):
    order, _ = place(items=buy(variant), user=customer, save_address=True)

    saved = Address.objects.get(user=customer)
    assert saved.recipient_name == order.ship_recipient_name
    assert saved.street == order.ship_street
    assert saved.is_default is True


def test_a_guest_cannot_check_out_against_a_saved_address(store, zone, variant, customer):
    saved = Address.objects.create(user=customer, **BOOK_ADDRESS)

    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant), address_id=saved.pk)

    assert excinfo.value.code == "NOT_FOUND"
    assert excinfo.value.status_code == 404


def test_checking_out_against_another_customers_saved_address_is_not_found_rather_than_forbidden(
    store, zone, variant, customer, other_customer
):
    saved = Address.objects.create(user=other_customer, **BOOK_ADDRESS)

    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant), user=customer, address_id=saved.pk)

    assert excinfo.value.code == "NOT_FOUND"
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# Reference numbers (FR-ORD-1)
# ---------------------------------------------------------------------------
def test_repeated_placements_are_handed_distinct_sequential_references(store, zone, variant):
    references = [place(items=buy(variant))[0].reference for _ in range(5)]
    year = timezone.now().year

    assert len(set(references)) == 5
    assert references == sorted(references)
    assert references[0] == "ORD-{0}-000001".format(year)
    assert references[-1] == "ORD-{0}-000005".format(year)


def test_reserving_a_reference_never_returns_one_that_is_already_in_use(store, zone, variant):
    for _ in range(3):
        place(items=buy(variant))

    reserved = placement._reserve_reference()

    assert not Order.objects.filter(reference=reserved).exists()
    assert reserved == "ORD-{0}-000004".format(timezone.now().year)


def test_deleting_an_order_never_causes_a_reference_to_be_handed_out_twice(store, zone, variant):
    references = [place(items=buy(variant))[0].reference for _ in range(3)]
    # Deleting the *middle* row is what a count-based sequence gets wrong: the
    # count drops to two and the next order collides with the third reference.
    Order.objects.filter(reference=references[1]).delete()

    assert placement.next_reference() == "ORD-{0}-000004".format(timezone.now().year)


def test_the_reference_sequence_is_scoped_to_the_year_it_is_issued_in(store, zone, variant):
    place(items=buy(variant))
    next_year = timezone.make_aware(datetime(timezone.now().year + 1, 1, 3, 9, 0))

    assert placement.next_reference(next_year) == "ORD-{0}-000001".format(next_year.year)


# ---------------------------------------------------------------------------
# Stock refusals (FR-INV-4)
# ---------------------------------------------------------------------------
def test_ordering_more_units_than_are_in_stock_is_refused(store, zone, variant):
    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant, 11))

    assert excinfo.value.code == "INSUFFICIENT_STOCK"
    assert excinfo.value.field == "items"
    assert excinfo.value.status_code == 422


def test_a_refused_placement_leaves_the_order_table_stock_and_the_ledger_untouched(
    store, zone, variant
):
    before_logs = InventoryLog.objects.count()

    with pytest.raises(DomainError):
        place(items=buy(variant, 11))

    variant.refresh_from_db()
    assert variant.stock == 10
    assert InventoryLog.objects.count() == before_logs
    assert Order.objects.count() == 0
    assert OrderItem.objects.count() == 0


def test_two_lines_naming_the_same_variant_are_summed_before_stock_is_checked(
    store, zone, variant
):
    with pytest.raises(DomainError) as excinfo:
        place(
            items=[
                {"variant_id": variant.pk, "quantity": 6},
                {"variant_id": variant.pk, "quantity": 6},
            ]
        )

    assert excinfo.value.code == "INSUFFICIENT_STOCK"

    variant.refresh_from_db()
    assert variant.stock == 10


def test_an_order_naming_a_deactivated_variant_is_refused_as_not_found(store, zone, variant):
    variant.is_active = False
    variant.save(update_fields=["is_active"])

    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant))

    assert excinfo.value.code == "VARIANT_NOT_FOUND"
    assert excinfo.value.status_code == 404


def test_an_order_shipping_to_a_district_no_zone_claims_is_refused(store, zone, variant):
    with pytest.raises(DomainError) as excinfo:
        place(
            items=buy(variant),
            shipping_address=dict(SHIPPING_ADDRESS, district="Bandarban"),
        )

    assert excinfo.value.code == "SHIPPING_ZONE_UNAVAILABLE"
    assert Order.objects.count() == 0


def test_cash_on_delivery_above_the_store_ceiling_is_refused_at_placement(store, zone, variant):
    store.cod_max_order_value = Decimal("500.00")
    store.save()

    with pytest.raises(DomainError) as excinfo:
        place(items=buy(variant, 2))

    assert excinfo.value.code == "COD_LIMIT_EXCEEDED"
    assert excinfo.value.field == "payment_method"
    assert Order.objects.count() == 0


# ---------------------------------------------------------------------------
# Coupons (FR-CPN-5, FR-CPN-8)
# ---------------------------------------------------------------------------
def test_placing_an_order_with_a_coupon_records_the_redemption_that_was_applied(
    store, zone, variant, customer, coupon
):
    order, _ = place(items=buy(variant, 2), user=customer, coupon_code="welcome10")

    redemption = CouponRedemption.objects.get(order=order)
    assert redemption.coupon_id == coupon.pk
    assert redemption.user_id == customer.pk
    assert redemption.discount_amount == Decimal("200.00")
    assert order.coupon_id == coupon.pk
    assert order.discount_total == Decimal("200.00")
    assert order.grand_total == Decimal("1860.00")  # 2000 - 200 + 60 shipping


def test_cancelling_before_shipment_releases_the_coupon_so_it_can_be_used_again(
    store, zone, variant, customer, coupon
):
    first, _ = place(items=buy(variant), user=customer, coupon_code="WELCOME10")
    assert CouponRedemption.objects.filter(order=first).exists()

    placement.cancel_order(first, actor=customer, reason="Changed my mind")

    assert CouponRedemption.objects.filter(order=first).count() == 0
    # per_user_limit is 1, so a second order proves the redemption was released.
    second, _ = place(items=buy(variant), user=customer, coupon_code="WELCOME10")
    assert second.discount_total == Decimal("100.00")


def test_cancelling_a_pending_order_releases_its_coupon_redemption_too(
    store, zone, variant, customer, coupon
):
    order, _ = place(
        items=buy(variant),
        user=customer,
        coupon_code="WELCOME10",
        payment_method=PaymentMethod.ONLINE,
    )
    assert order.status == OrderStatus.PENDING

    placement.cancel_order(order, actor=customer)

    assert CouponRedemption.objects.filter(order=order).count() == 0


def test_a_coupon_consumed_on_a_shipped_order_is_not_released_when_delivery_later_fails(
    store, zone, variant, customer, coupon, staff
):
    order, _ = place(items=buy(variant, 2), user=customer, coupon_code="WELCOME10")

    order = placement.transition_order(
        order=order, to_status=OrderStatus.PACKED, actor=staff, actor_role=Actor.ADMIN
    )
    Shipment.objects.create(order=order, courier_name="Pathao", tracking_number="PT-1")
    order = placement.transition_order(
        order=order, to_status=OrderStatus.SHIPPED, actor=staff, actor_role=Actor.ADMIN
    )
    placement.transition_order(
        order=order,
        to_status=OrderStatus.CANCELLED,
        actor=staff,
        actor_role=Actor.ADMIN,
        note="Customer refused the parcel",
    )

    # The merchandise left the building, so the promotion stays consumed --
    # but the stock does come back.
    assert CouponRedemption.objects.filter(order=order).count() == 1
    variant.refresh_from_db()
    assert variant.stock == 10


# ---------------------------------------------------------------------------
# Cancellation and stock restoration (FR-ORD-4, FR-INV-3)
# ---------------------------------------------------------------------------
def test_cancelling_a_confirmed_order_restores_stock_and_writes_a_matching_ledger_row(
    store, zone, variant, customer
):
    order, _ = place(items=buy(variant, 3), user=customer)
    variant.refresh_from_db()
    assert variant.stock == 7

    cancelled = placement.cancel_order(order, actor=customer, reason="Ordered the wrong variant")

    variant.refresh_from_db()
    assert cancelled.status == OrderStatus.CANCELLED
    assert variant.stock == 10

    restores = logs_for(order, InventoryReason.ORDER_CANCELLED)
    assert len(restores) == 1
    assert restores[0].delta == 3
    assert restores[0].variant_id == variant.pk


def test_cancelling_a_pending_order_restores_nothing_because_stock_was_never_taken(
    store, zone, variant, customer
):
    order, _ = place(items=buy(variant, 3), user=customer, payment_method=PaymentMethod.ONLINE)
    assert order.status == OrderStatus.PENDING

    placement.cancel_order(order, actor=customer)

    variant.refresh_from_db()
    assert variant.stock == 10
    assert logs_for(order) == []


def test_cancellation_is_written_to_the_append_only_status_log_with_its_actor_and_reason(
    store, zone, variant, customer
):
    order, _ = place(items=buy(variant), user=customer)

    placement.cancel_order(order, actor=customer, reason="Ordered the wrong variant")

    log = OrderStatusLog.objects.filter(order=order).latest("created_at", "id")
    assert (log.from_status, log.to_status) == (OrderStatus.CONFIRMED, OrderStatus.CANCELLED)
    assert log.actor_id == customer.pk
    assert log.actor_role == Actor.CUSTOMER
    assert log.note == "Ordered the wrong variant"


def test_a_customer_may_not_cancel_an_order_that_has_already_shipped(
    store, zone, variant, customer, staff
):
    order, _ = place(items=buy(variant), user=customer)
    order = placement.transition_order(
        order=order, to_status=OrderStatus.PACKED, actor=staff, actor_role=Actor.ADMIN
    )
    Shipment.objects.create(order=order, courier_name="Pathao", tracking_number="PT-2")
    order = placement.transition_order(
        order=order, to_status=OrderStatus.SHIPPED, actor=staff, actor_role=Actor.ADMIN
    )
    logged_before = OrderStatusLog.objects.filter(order=order).count()

    with pytest.raises(DomainError) as excinfo:
        placement.cancel_order(order, actor=customer)

    # Shipped -> cancelled is legal, but not for a customer: that is a
    # permissions answer, not a state answer.
    assert excinfo.value.code == "TRANSITION_NOT_PERMITTED"
    assert excinfo.value.status_code == 403
    order.refresh_from_db()
    assert order.status == OrderStatus.SHIPPED
    assert OrderStatusLog.objects.filter(order=order).count() == logged_before


def test_an_illegal_transition_is_rejected_and_is_never_written_to_the_status_log(
    store, zone, variant, customer, staff
):
    order, _ = place(items=buy(variant), user=customer)
    logged_before = OrderStatusLog.objects.filter(order=order).count()

    with pytest.raises(DomainError) as excinfo:
        placement.transition_order(
            order=order, to_status=OrderStatus.DELIVERED, actor=staff, actor_role=Actor.ADMIN
        )

    assert excinfo.value.code == "ILLEGAL_STATUS_TRANSITION"
    assert excinfo.value.status_code == 422
    order.refresh_from_db()
    assert order.status == OrderStatus.CONFIRMED
    assert OrderStatusLog.objects.filter(order=order).count() == logged_before


def test_marking_an_order_shipped_without_a_shipment_record_is_refused(
    store, zone, variant, customer, staff
):
    order, _ = place(items=buy(variant), user=customer)
    order = placement.transition_order(
        order=order, to_status=OrderStatus.PACKED, actor=staff, actor_role=Actor.ADMIN
    )

    with pytest.raises(DomainError) as excinfo:
        placement.transition_order(
            order=order, to_status=OrderStatus.SHIPPED, actor=staff, actor_role=Actor.ADMIN
        )

    assert excinfo.value.code == "SHIPMENT_REQUIRED"


# ---------------------------------------------------------------------------
# confirm_order (FR-INV-2)
# ---------------------------------------------------------------------------
def test_confirming_a_pending_online_order_moves_it_to_confirmed_and_decrements_stock_once(
    store, zone, variant
):
    order, _ = place(items=buy(variant, 4), payment_method=PaymentMethod.ONLINE)

    confirmed = placement.confirm_order(order)

    variant.refresh_from_db()
    assert confirmed.status == OrderStatus.CONFIRMED
    assert variant.stock == 6
    movements = logs_for(order, InventoryReason.ORDER_CONFIRMED)
    assert len(movements) == 1
    assert movements[0].delta == -4
    assert status_pairs(order) == [
        ("", OrderStatus.PENDING),
        (OrderStatus.PENDING, OrderStatus.CONFIRMED),
    ]


def test_confirming_an_order_a_second_time_is_refused_and_cannot_decrement_stock_twice(
    store, zone, variant
):
    order, _ = place(items=buy(variant, 4), payment_method=PaymentMethod.ONLINE)
    placement.confirm_order(order)
    variant.refresh_from_db()
    assert variant.stock == 6

    with pytest.raises(DomainError) as excinfo:
        placement.confirm_order(order)

    assert excinfo.value.code == "ILLEGAL_STATUS_TRANSITION"
    variant.refresh_from_db()
    assert variant.stock == 6
    assert InventoryLog.objects.filter(
        order=order, reason=InventoryReason.ORDER_CONFIRMED
    ).count() == 1


def test_a_cash_on_delivery_order_is_already_confirmed_so_confirming_it_again_is_refused(
    store, zone, variant
):
    order, _ = place(items=buy(variant, 2))

    with pytest.raises(DomainError) as excinfo:
        placement.confirm_order(order)

    assert excinfo.value.code == "ILLEGAL_STATUS_TRANSITION"
    variant.refresh_from_db()
    assert variant.stock == 8


# ---------------------------------------------------------------------------
# The ledger invariant: sum(delta) reconciles to stock
# ---------------------------------------------------------------------------
def test_the_inventory_ledger_reconciles_to_current_stock_after_placements_and_cancellations(
    store, zone, variant, other_variant, customer
):
    # 10 laptops and 5 mice on the shelf, both opened through the ledger.
    first, _ = place(
        items=[
            {"variant_id": variant.pk, "quantity": 3},
            {"variant_id": other_variant.pk, "quantity": 1},
        ],
        user=customer,
    )
    place(items=buy(variant, 2), user=customer)
    placement.cancel_order(first, actor=customer, reason="Changed my mind")
    third, _ = place(items=buy(variant, 4), user=customer, payment_method=PaymentMethod.ONLINE)
    placement.confirm_order(third)

    variant.refresh_from_db()
    other_variant.refresh_from_db()

    # 10 - 3 - 2 + 3 - 4 = 4, and 5 - 1 + 1 = 5.
    assert variant.stock == 4
    assert other_variant.stock == 5
    assert inventory_services.logged_stock(variant) == variant.stock
    assert inventory_services.logged_stock(other_variant) == other_variant.stock


def test_every_stock_movement_the_order_lifecycle_makes_is_attributed_to_its_order(
    store, zone, variant, customer
):
    order, _ = place(items=buy(variant, 3), user=customer)
    placement.cancel_order(order, actor=customer)

    movements = logs_for(order)
    assert [movement.delta for movement in movements] == [-3, 3]
    assert [movement.reason for movement in movements] == [
        InventoryReason.ORDER_CONFIRMED,
        InventoryReason.ORDER_CANCELLED,
    ]
    assert sum(movement.delta for movement in movements) == 0
    assert inventory_services.logged_stock(variant) == 10


# ---------------------------------------------------------------------------
# The HTTP surface: object-level authorisation and idempotency end to end
# ---------------------------------------------------------------------------
def test_a_customer_can_read_their_own_order_by_reference(store, zone, variant, customer, api):
    order, _ = place(items=buy(variant), user=customer)
    api.force_authenticate(customer)

    response = api.get(reverse("orders:order-detail", kwargs={"reference": order.reference}))

    assert response.status_code == 200
    assert response.data["reference"] == order.reference
    assert response.data["grand_total"] == "1060.00"


def test_another_customers_order_reference_returns_404_rather_than_403(
    store, zone, variant, customer, other_customer, api
):
    order, _ = place(items=buy(variant), user=customer)
    api.force_authenticate(other_customer)

    response = api.get(reverse("orders:order-detail", kwargs={"reference": order.reference}))

    # 403 would confirm the reference is real and leak the ID space.
    assert response.status_code == 404
    assert response.data["error"]["code"] == "NOT_FOUND"


def test_another_customer_cannot_cancel_an_order_they_do_not_own(
    store, zone, variant, customer, other_customer, api
):
    order, _ = place(items=buy(variant, 3), user=customer)
    api.force_authenticate(other_customer)

    response = api.post(
        reverse("orders:order-cancel", kwargs={"reference": order.reference}),
        {"reason": "Not mine"},
        format="json",
    )

    assert response.status_code == 404
    assert response.data["error"]["code"] == "NOT_FOUND"
    order.refresh_from_db()
    assert order.status == OrderStatus.CONFIRMED
    variant.refresh_from_db()
    assert variant.stock == 7


def test_a_guest_order_is_not_readable_through_the_authenticated_order_endpoint(
    store, zone, variant, customer, api
):
    order, _ = place(items=buy(variant), email="walkin@example.com")
    api.force_authenticate(customer)

    response = api.get(reverse("orders:order-detail", kwargs={"reference": order.reference}))

    assert response.status_code == 404


def test_placing_the_same_order_twice_over_http_returns_201_then_200_with_one_order(
    store, zone, variant, api
):
    payload = {
        "idempotency_key": uuid4().hex,
        "payment_method": PaymentMethod.COD.value,
        "email": "walkin@example.com",
        "items": [{"variant_id": variant.pk, "quantity": 2}],
        "shipping_address": dict(SHIPPING_ADDRESS),
    }
    url = reverse("orders:order-list")

    first = api.post(url, payload, format="json")
    second = api.post(url, payload, format="json")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["reference"] == first.data["reference"]
    assert Order.objects.count() == 1

    variant.refresh_from_db()
    assert variant.stock == 8
    assert inventory_services.logged_stock(variant) == 8


def test_an_out_of_stock_line_is_reported_over_http_with_its_stable_code(
    store, zone, variant, api
):
    response = api.post(
        reverse("orders:order-list"),
        {
            "idempotency_key": uuid4().hex,
            "payment_method": PaymentMethod.COD.value,
            "email": "walkin@example.com",
            "items": [{"variant_id": variant.pk, "quantity": 11}],
            "shipping_address": dict(SHIPPING_ADDRESS),
        },
        format="json",
    )

    assert response.status_code == 422
    assert response.data["error"]["code"] == "INSUFFICIENT_STOCK"
    assert response.data["error"]["field"] == "items"
    assert Order.objects.count() == 0


def test_money_crosses_the_http_boundary_as_decimal_strings_never_as_floats(
    store, zone, variant, customer, api
):
    order, _ = place(items=buy(variant, 2), user=customer)
    api.force_authenticate(customer)

    response = api.get(reverse("orders:order-detail", kwargs={"reference": order.reference}))

    for key in ("subtotal", "discount_total", "shipping_total", "tax_total", "grand_total"):
        assert isinstance(response.data[key], str), key
    assert response.data["subtotal"] == "2000.00"
    assert response.data["shipping_total"] == "60.00"
    assert response.data["grand_total"] == "2060.00"
