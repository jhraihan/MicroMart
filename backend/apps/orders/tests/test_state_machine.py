"""
The transition table is the single source of truth for order status changes
(PRD §15.1), so it is worth asserting directly -- these run without a database.
"""
from apps.orders.models import (
    TRANSITIONS,
    Actor,
    OrderStatus,
    TERMINAL_STATUSES,
)

# Transcribed from PRD §15.1 by hand. If a transition is added to the model
# without a deliberate spec change, this list stops matching.
EXPECTED = {
    (OrderStatus.PENDING, OrderStatus.CONFIRMED),
    (OrderStatus.PENDING, OrderStatus.CANCELLED),
    (OrderStatus.CONFIRMED, OrderStatus.PACKED),
    (OrderStatus.CONFIRMED, OrderStatus.CANCELLED),
    (OrderStatus.PACKED, OrderStatus.SHIPPED),
    (OrderStatus.PACKED, OrderStatus.CANCELLED),
    (OrderStatus.SHIPPED, OrderStatus.DELIVERED),
    (OrderStatus.SHIPPED, OrderStatus.CANCELLED),
    (OrderStatus.DELIVERED, OrderStatus.REFUNDED),
}


def test_transition_table_matches_the_prd_exactly():
    assert set(TRANSITIONS) == EXPECTED


def test_no_transition_leaves_a_terminal_status_except_delivered_to_refunded():
    leaving_terminal = {
        (frm, to) for (frm, to) in TRANSITIONS if frm in TERMINAL_STATUSES
    }
    assert leaving_terminal == {(OrderStatus.DELIVERED, OrderStatus.REFUNDED)}


def test_only_admin_may_pack_ship_deliver_or_refund():
    admin_only = [
        (OrderStatus.CONFIRMED, OrderStatus.PACKED),
        (OrderStatus.PACKED, OrderStatus.SHIPPED),
        (OrderStatus.SHIPPED, OrderStatus.DELIVERED),
        (OrderStatus.DELIVERED, OrderStatus.REFUNDED),
    ]
    for key in admin_only:
        assert TRANSITIONS[key]["actors"] == {Actor.ADMIN}, key


def test_customer_can_only_cancel_before_shipping():
    customer_transitions = {
        (frm, to)
        for (frm, to), rule in TRANSITIONS.items()
        if Actor.CUSTOMER in rule["actors"]
    }
    assert customer_transitions == {
        (OrderStatus.PENDING, OrderStatus.CONFIRMED),
        (OrderStatus.PENDING, OrderStatus.CANCELLED),
        (OrderStatus.CONFIRMED, OrderStatus.CANCELLED),
    }


def test_stock_restores_only_where_it_was_previously_decremented():
    # Stock is decremented on confirmation, so every cancellation from
    # confirmed onward must restore it -- and cancelling a pending order,
    # which never decremented, must not.
    assert TRANSITIONS[(OrderStatus.PENDING, OrderStatus.CANCELLED)]["stock"] is None
    assert TRANSITIONS[(OrderStatus.PENDING, OrderStatus.CONFIRMED)]["stock"] == "decrement"
    for frm in (OrderStatus.CONFIRMED, OrderStatus.PACKED, OrderStatus.SHIPPED):
        assert TRANSITIONS[(frm, OrderStatus.CANCELLED)]["stock"] == "restore", frm


def test_shipping_requires_a_shipment_record():
    rule = TRANSITIONS[(OrderStatus.PACKED, OrderStatus.SHIPPED)]
    assert rule.get("requires_shipment") is True
