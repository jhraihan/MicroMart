"""
The admin order pipeline (PRD 4.3 US-A3 and US-T1, 7.3, 15.1).

"Order list is filterable by status, payment method, and date range,
searchable by order ID, customer name, or phone; status changes are restricted
to legal transitions (15.1) and each is logged with actor and timestamp."

The transition tests assert on *codes* and *rows*, never on wording: the
message a refusal carries is free to improve, the `ILLEGAL_STATUS_TRANSITION`
code and the absence of an OrderStatusLog row are the contract.
"""
import pytest
from django.utils import timezone
from rest_framework import status

from apps.catalog.models import InventoryLog
from apps.orders.models import (
    Actor,
    Order,
    OrderStatus,
    OrderStatusLog,
    PaymentMethod,
    Shipment,
)

pytestmark = pytest.mark.django_db


def references(response):
    return [row["reference"] for row in response.data["results"]]


def as_date(moment):
    return timezone.localtime(moment).date().isoformat()


# ---------------------------------------------------------------------------
# Listing, filtering (US-A3)
# ---------------------------------------------------------------------------
def test_the_admin_list_shows_every_customers_orders_not_just_the_callers(
    admin_client, orders_url, make_order, customer, days_ago
):
    """
    The mirror image of the storefront rule. `customer_orders` scopes to one
    user before matching anything; `admin_orders` deliberately does not, and
    that difference is stated once in the service rather than in each view.
    """
    mine = make_order(user=None, placed_at=days_ago(1))
    theirs = make_order(user=customer, placed_at=days_ago(2))

    response = admin_client.get(orders_url)

    assert response.status_code == status.HTTP_200_OK
    assert set(references(response)) == {mine.reference, theirs.reference}


def test_orders_are_listed_newest_first(admin_client, orders_url, make_order, days_ago):
    old = make_order(placed_at=days_ago(9))
    new = make_order(placed_at=days_ago(1))

    assert references(admin_client.get(orders_url)) == [new.reference, old.reference]


def test_the_list_is_filterable_by_status(admin_client, orders_url, make_order, days_ago):
    packed = make_order(status=OrderStatus.PACKED, placed_at=days_ago(1))
    make_order(status=OrderStatus.DELIVERED, placed_at=days_ago(1))

    response = admin_client.get(orders_url, {"status": "packed"})

    assert references(response) == [packed.reference]


def test_several_statuses_can_be_selected_at_once(
    admin_client, orders_url, make_order, days_ago
):
    """
    A fulfilment queue is "confirmed or packed", not one status at a time.
    Repeating the parameter and comma-separating it both work, because a React
    multi-select produces the first and a hand-typed URL the second.
    """
    confirmed = make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(1))
    packed = make_order(status=OrderStatus.PACKED, placed_at=days_ago(2))
    make_order(status=OrderStatus.CANCELLED, placed_at=days_ago(3))

    repeated = admin_client.get(orders_url, {"status": ["confirmed", "packed"]})
    comma = admin_client.get(orders_url, {"status": "confirmed,packed"})

    assert set(references(repeated)) == {confirmed.reference, packed.reference}
    assert set(references(comma)) == set(references(repeated))


def test_the_list_is_filterable_by_payment_method(
    admin_client, orders_url, make_order, days_ago
):
    cod = make_order(payment_method=PaymentMethod.COD, placed_at=days_ago(1))
    make_order(payment_method=PaymentMethod.ONLINE, placed_at=days_ago(1))

    response = admin_client.get(orders_url, {"payment_method": "cod"})

    assert references(response) == [cod.reference]


def test_the_list_is_filterable_by_a_date_range_that_includes_both_named_days(
    admin_client, orders_url, make_order, days_ago
):
    """
    A support agent asked for "the 3rd to the 5th" means those days included.
    An exclusive upper bound silently drops the last day of every range
    anybody types.
    """
    before = make_order(placed_at=days_ago(10))
    inside = make_order(placed_at=days_ago(5))
    edge = make_order(placed_at=days_ago(3, hour=23))
    after = make_order(placed_at=days_ago(1))

    response = admin_client.get(
        orders_url,
        {"placed_from": as_date(days_ago(5)), "placed_to": as_date(days_ago(3))},
    )

    found = set(references(response))
    assert found == {inside.reference, edge.reference}
    assert before.reference not in found and after.reference not in found


@pytest.mark.parametrize(
    "params,field",
    [
        ({"status": "shippped"}, "status"),
        ({"payment_method": "bkash"}, "payment_method"),
        ({"placed_from": "22-08-2026"}, "placed_from"),
        ({"placed_to": "not-a-date"}, "placed_to"),
    ],
)
def test_a_malformed_filter_is_refused_rather_than_silently_ignored(
    admin_client, orders_url, params, field
):
    """
    Ignoring a typo'd filter answers a question nobody asked, and the agent
    reads the unfiltered list as if it were the filtered one.
    """
    response = admin_client.get(orders_url, params)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.data["error"]["code"] == "INVALID_FILTER"
    assert response.data["error"]["field"] == field


# ---------------------------------------------------------------------------
# Search (US-A3, US-T1)
# ---------------------------------------------------------------------------
def test_search_finds_an_order_by_a_partial_reference(
    admin_client, orders_url, make_order, days_ago
):
    order = make_order(placed_at=days_ago(1))
    make_order(placed_at=days_ago(1))

    response = admin_client.get(orders_url, {"q": order.reference[-6:]})

    assert references(response) == [order.reference]


def test_search_finds_an_order_by_phone_number(
    admin_client, orders_url, make_order, days_ago
):
    order = make_order(phone="01812345678", placed_at=days_ago(1))
    make_order(phone="01912345678", placed_at=days_ago(1))

    response = admin_client.get(orders_url, {"q": "01812345678"})

    assert references(response) == [order.reference]


def test_search_recognises_a_phone_number_typed_in_international_form(
    admin_client, orders_url, make_order, days_ago
):
    """
    US-T1 is a support agent with a caller on the line. The caller reads out
    "+880 1812 345678"; the database holds "01812345678". One subscriber, and
    the agent should not have to know which form was stored.
    """
    order = make_order(phone="01812345678", placed_at=days_ago(1))

    response = admin_client.get(orders_url, {"q": "+880 1812-345678"})

    assert references(response) == [order.reference]


def test_search_finds_an_order_by_email(admin_client, orders_url, make_order, days_ago):
    order = make_order(email="nadia@example.com", placed_at=days_ago(1))
    make_order(email="someone@example.com", placed_at=days_ago(1))

    response = admin_client.get(orders_url, {"q": "nadia@example.com"})

    assert references(response) == [order.reference]


def test_search_finds_an_order_by_the_recipient_name_on_the_shipping_address(
    admin_client, orders_url, make_order, days_ago
):
    order = make_order(recipient_name="Shirin Akter", placed_at=days_ago(1))
    make_order(recipient_name="Kamal Uddin", placed_at=days_ago(1))

    response = admin_client.get(orders_url, {"q": "shirin"})

    assert references(response) == [order.reference]


def test_search_finds_an_order_by_the_account_holders_name(
    admin_client, orders_url, make_order, customer, days_ago
):
    """
    The name on the account and the name on the parcel are often different --
    a gift, or a colleague receiving it at the office.
    """
    order = make_order(
        user=customer, recipient_name="Office Reception", placed_at=days_ago(1)
    )
    make_order(recipient_name="Kamal Uddin", placed_at=days_ago(1))

    response = admin_client.get(orders_url, {"q": "Rafiq"})

    assert references(response) == [order.reference]


def test_a_search_that_matches_nothing_is_an_empty_list_not_an_error(
    admin_client, orders_url, make_order, days_ago
):
    make_order(placed_at=days_ago(1))

    response = admin_client.get(orders_url, {"q": "ORD-1999-000001"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["results"] == []


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
def test_order_detail_carries_the_snapshot_the_timeline_and_the_legal_next_steps(
    admin_client, order_detail_url, make_order, days_ago
):
    order = make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(1))
    OrderStatusLog.objects.create(
        order=order,
        from_status=OrderStatus.PENDING,
        to_status=OrderStatus.CONFIRMED,
        actor_role=Actor.SYSTEM,
        note="Cash on Delivery order placed",
    )

    response = admin_client.get(order_detail_url(order.reference))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["reference"] == order.reference
    assert response.data["items"][0]["sku"] == order.items.get().sku
    assert [entry["to_status"] for entry in response.data["timeline"]] == ["confirmed"]
    assert set(response.data["allowed_transitions"]) == {"packed", "cancelled"}


def test_the_admin_timeline_names_the_actor_because_us_a3_requires_it(
    admin_client, order_status_url, order_detail_url, make_order, admin, days_ago
):
    order = make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(1))
    admin_client.post(order_status_url(order.reference), {"status": "packed"}, format="json")

    response = admin_client.get(order_detail_url(order.reference))

    entry = response.data["timeline"][-1]
    assert entry["to_status"] == "packed"
    assert entry["actor_email"] == admin.email
    assert entry["actor_role"] == Actor.ADMIN
    assert entry["created_at"] is not None


def test_a_reference_that_does_not_exist_is_a_404(admin_client, order_detail_url):
    response = admin_client.get(order_detail_url("ORD-1999-000001"))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["error"]["code"] == "NOT_FOUND"


def test_a_guest_order_is_marked_as_one_so_support_does_not_send_the_caller_to_login(
    admin_client, orders_url, make_order, customer, days_ago
):
    make_order(user=None, placed_at=days_ago(1))
    make_order(user=customer, placed_at=days_ago(2))

    rows = {row["reference"]: row for row in admin_client.get(orders_url).data["results"]}
    guests = [row["customer"]["is_guest"] for row in rows.values()]

    assert sorted(guests) == [False, True]


# ---------------------------------------------------------------------------
# Status transitions (US-A3, PRD 15.1)
# ---------------------------------------------------------------------------
def test_a_legal_transition_is_applied_and_logged_with_actor_and_timestamp(
    admin_client, order_status_url, make_order, admin, days_ago
):
    order = make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(1))

    response = admin_client.post(
        order_status_url(order.reference), {"status": "packed"}, format="json"
    )

    order.refresh_from_db()
    log = OrderStatusLog.objects.filter(order=order).latest("created_at")
    assert response.status_code == status.HTTP_200_OK
    assert order.status == OrderStatus.PACKED
    assert (log.from_status, log.to_status) == (OrderStatus.CONFIRMED, OrderStatus.PACKED)
    assert log.actor_id == admin.pk
    assert log.actor_role == Actor.ADMIN
    assert log.created_at is not None


def test_an_admins_note_is_kept_on_the_log_row(
    admin_client, order_status_url, make_order, days_ago
):
    order = make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(1))

    admin_client.post(
        order_status_url(order.reference),
        {"status": "cancelled", "note": "Customer called to cancel"},
        format="json",
    )

    log = OrderStatusLog.objects.filter(order=order).latest("created_at")
    assert log.note == "Customer called to cancel"


@pytest.mark.parametrize(
    "start,target",
    [
        (OrderStatus.PENDING, OrderStatus.PACKED),
        (OrderStatus.PENDING, OrderStatus.DELIVERED),
        (OrderStatus.CONFIRMED, OrderStatus.SHIPPED),
        (OrderStatus.CONFIRMED, OrderStatus.REFUNDED),
        (OrderStatus.PACKED, OrderStatus.DELIVERED),
        (OrderStatus.DELIVERED, OrderStatus.SHIPPED),
        (OrderStatus.CANCELLED, OrderStatus.CONFIRMED),
        (OrderStatus.REFUNDED, OrderStatus.DELIVERED),
    ],
)
def test_an_illegal_transition_is_refused_with_422(
    admin_client, order_status_url, make_order, days_ago, start, target
):
    """
    PRD 15.1: "Any transition not listed is rejected with 422." The
    `confirmed -> refunded` row is deliberate -- the 15.1 diagram draws that
    arrow and the transition table does not, and the table states it is
    authoritative. See docs/HANDOFF.md 4; if the owner rules the other way,
    change the transition table, not this test.
    """
    order = make_order(status=start, placed_at=days_ago(1))

    response = admin_client.post(
        order_status_url(order.reference), {"status": target}, format="json"
    )

    order.refresh_from_db()
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.data["error"]["code"] == "ILLEGAL_STATUS_TRANSITION"
    assert order.status == start


def test_an_illegal_transition_is_not_written_to_the_audit_trail(
    admin_client, order_status_url, make_order, days_ago
):
    """
    An illegal transition is not an event that happened. Logging the attempt
    would put a state change in an append-only log of state changes that never
    occurred, and the log is the timeline the customer is shown.
    """
    order = make_order(status=OrderStatus.PENDING, placed_at=days_ago(1))
    before = OrderStatusLog.objects.filter(order=order).count()

    admin_client.post(
        order_status_url(order.reference), {"status": "delivered"}, format="json"
    )

    assert OrderStatusLog.objects.filter(order=order).count() == before


def test_an_unknown_status_string_is_a_field_error_not_a_state_machine_answer(
    admin_client, order_status_url, make_order, days_ago
):
    order = make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(1))

    response = admin_client.post(
        order_status_url(order.reference), {"status": "gift-wrapped"}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["field"] == "status"


def test_confirming_an_order_moves_stock_through_the_inventory_ledger(
    admin_client, order_status_url, make_variant, make_order, days_ago, admin
):
    """
    The admin surface must not have its own stock path. Confirming here runs
    the same `transition_order` a COD placement runs, so the InventoryLog row
    is written and the variant's logged deltas still reconcile.
    """
    variant = make_variant(stock=10)
    order = make_order(
        status=OrderStatus.PENDING, items=[(variant, 3)], placed_at=days_ago(0)
    )

    admin_client.post(
        order_status_url(order.reference), {"status": "confirmed"}, format="json"
    )

    variant.refresh_from_db()
    log = InventoryLog.objects.filter(variant=variant, order=order).latest("id")
    assert variant.stock == 7
    assert log.delta == -3
    assert log.actor_id == admin.pk


def test_cancelling_a_confirmed_order_puts_the_stock_back(
    admin_client, order_status_url, make_variant, make_order, days_ago
):
    variant = make_variant(stock=10)
    order = make_order(
        status=OrderStatus.PENDING, items=[(variant, 4)], placed_at=days_ago(0)
    )

    admin_client.post(
        order_status_url(order.reference), {"status": "confirmed"}, format="json"
    )
    admin_client.post(
        order_status_url(order.reference), {"status": "cancelled"}, format="json"
    )

    variant.refresh_from_db()
    deltas = list(
        InventoryLog.objects.filter(variant=variant, order=order).values_list(
            "delta", flat=True
        )
    )
    assert variant.stock == 10
    assert sorted(deltas) == [-4, 4]


def test_staff_may_advance_an_order_and_the_log_names_them(
    staff_client, order_status_url, make_order, staff_member, days_ago
):
    """US-A8 and US-T2: updating delivery status is the staff role's whole job."""
    order = make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(1))

    response = staff_client.post(
        order_status_url(order.reference), {"status": "packed"}, format="json"
    )

    log = OrderStatusLog.objects.filter(order=order).latest("created_at")
    assert response.status_code == status.HTTP_200_OK
    assert log.actor_id == staff_member.pk
    assert log.actor_role == Actor.ADMIN


# ---------------------------------------------------------------------------
# Shipments (FR-ORD-7, PRD 15.1 packed -> shipped)
# ---------------------------------------------------------------------------
def test_marking_a_packed_order_shipped_without_a_shipment_is_refused(
    admin_client, order_status_url, make_order, days_ago
):
    """
    PRD 15.1: "packed -> shipped. Admin only. Requires courier + tracking
    number." Enforced by TRANSITIONS itself, so the storefront, the admin API
    and any future management command are all held to it.
    """
    order = make_order(status=OrderStatus.PACKED, placed_at=days_ago(1))

    response = admin_client.post(
        order_status_url(order.reference), {"status": "shipped"}, format="json"
    )

    order.refresh_from_db()
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.data["error"]["code"] == "SHIPMENT_REQUIRED"
    assert order.status == OrderStatus.PACKED


def test_attaching_a_courier_and_tracking_number_unlocks_the_shipped_transition(
    admin_client, order_shipment_url, order_status_url, make_order, days_ago
):
    order = make_order(status=OrderStatus.PACKED, placed_at=days_ago(1))

    attached = admin_client.post(
        order_shipment_url(order.reference),
        {"courier_name": "Pathao", "tracking_number": "PT-100234"},
        format="json",
    )
    shipped = admin_client.post(
        order_status_url(order.reference), {"status": "shipped"}, format="json"
    )

    order.refresh_from_db()
    shipment = Shipment.objects.get(order=order)
    assert attached.status_code == status.HTTP_200_OK
    assert attached.data["shipment"]["tracking_number"] == "PT-100234"
    assert shipped.status_code == status.HTTP_200_OK
    assert order.status == OrderStatus.SHIPPED
    assert shipment.courier_name == "Pathao"


def test_the_dispatch_time_is_recorded_on_the_transition_that_dispatched_it(
    admin_client, order_shipment_url, order_status_url, make_order, days_ago
):
    order = make_order(status=OrderStatus.PACKED, placed_at=days_ago(1))
    admin_client.post(
        order_shipment_url(order.reference),
        {"courier_name": "Pathao", "tracking_number": "PT-100234"},
        format="json",
    )
    assert Shipment.objects.get(order=order).shipped_at is None

    admin_client.post(order_status_url(order.reference), {"status": "shipped"}, format="json")
    admin_client.post(order_status_url(order.reference), {"status": "delivered"}, format="json")

    shipment = Shipment.objects.get(order=order)
    assert shipment.shipped_at is not None
    assert shipment.delivered_at is not None


def test_correcting_a_tracking_number_does_not_rewrite_when_the_parcel_shipped(
    admin_client, order_shipment_url, order_status_url, make_order, days_ago
):
    order = make_order(status=OrderStatus.PACKED, placed_at=days_ago(1))
    admin_client.post(
        order_shipment_url(order.reference),
        {"courier_name": "Pathao", "tracking_number": "WRONG-1"},
        format="json",
    )
    admin_client.post(order_status_url(order.reference), {"status": "shipped"}, format="json")
    shipped_at = Shipment.objects.get(order=order).shipped_at

    admin_client.post(
        order_shipment_url(order.reference),
        {"courier_name": "Sundarban", "tracking_number": "SB-9001"},
        format="json",
    )

    shipment = Shipment.objects.get(order=order)
    assert shipment.tracking_number == "SB-9001"
    assert shipment.courier_name == "Sundarban"
    assert shipment.shipped_at == shipped_at


def test_a_second_shipment_post_updates_the_one_record_rather_than_adding_another(
    admin_client, order_shipment_url, make_order, days_ago
):
    order = make_order(status=OrderStatus.PACKED, placed_at=days_ago(1))

    for tracking in ("PT-1", "PT-2"):
        admin_client.post(
            order_shipment_url(order.reference),
            {"courier_name": "Pathao", "tracking_number": tracking},
            format="json",
        )

    assert Shipment.objects.filter(order=order).count() == 1


@pytest.mark.parametrize(
    "body,field",
    [
        ({"courier_name": "", "tracking_number": "PT-1"}, "courier_name"),
        ({"courier_name": "Pathao", "tracking_number": ""}, "tracking_number"),
        ({"tracking_number": "PT-1"}, "courier_name"),
    ],
)
def test_a_shipment_needs_both_a_courier_and_a_tracking_number(
    admin_client, order_shipment_url, make_order, days_ago, body, field
):
    """
    A tracking number nobody can track is worse than none: it tells the
    customer the parcel is findable when it is not.
    """
    order = make_order(status=OrderStatus.PACKED, placed_at=days_ago(1))

    response = admin_client.post(order_shipment_url(order.reference), body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["field"] == field
    assert not Shipment.objects.filter(order=order).exists()


@pytest.mark.parametrize("state", [OrderStatus.PENDING, OrderStatus.CANCELLED, OrderStatus.REFUNDED])
def test_a_courier_cannot_be_attached_to_an_order_that_is_going_nowhere(
    admin_client, order_shipment_url, make_order, days_ago, state
):
    order = make_order(status=state, placed_at=days_ago(1))

    response = admin_client.post(
        order_shipment_url(order.reference),
        {"courier_name": "Pathao", "tracking_number": "PT-1"},
        format="json",
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.data["error"]["code"] == "SHIPMENT_NOT_ALLOWED"
    assert not Shipment.objects.filter(order=order).exists()


def test_the_admin_surface_never_writes_order_status_outside_the_service(
    admin_client, order_status_url, make_order, days_ago
):
    """
    Every status the order has ever held is reachable by replaying its log.
    A view that assigned `order.status` directly would break that, and this is
    the cheap check that it has not.
    """
    order = make_order(status=OrderStatus.PENDING, placed_at=days_ago(1))
    for target in ("confirmed", "packed"):
        admin_client.post(order_status_url(order.reference), {"status": target}, format="json")

    order.refresh_from_db()
    replayed = list(
        OrderStatusLog.objects.filter(order=order)
        .order_by("created_at", "id")
        .values_list("to_status", flat=True)
    )
    assert replayed[-1] == order.status
    assert Order.objects.get(pk=order.pk).status == OrderStatus.PACKED
