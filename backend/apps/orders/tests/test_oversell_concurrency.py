"""
Zero oversell under genuine concurrency -- the week-4 exit criterion (PRD 12.1).

This is the only place in the suite where the oversell guard is actually
exercised, and every mechanical choice here is load-bearing:

* **@pytest.mark.django_db(transaction=True) is mandatory.** Inside pytest's
  default wrapping transaction the workers would share one connection and one
  open transaction, SELECT ... FOR UPDATE would contend with nothing, and the
  file would pass while proving nothing whatsoever.
* **Real threads on real connections.** Django hands each thread its own; each
  worker closes it on the way out, or CONN_MAX_AGE keeps them alive holding
  locks and the run hangs.
* **A threading.Barrier releases every worker at one instant.** Without it the
  threads start staggered and serialise on their own, and contention -- the
  entire subject of the file -- never happens.

Three hazards are covered, and all three were chosen because they are the ones
this codebase can actually get wrong:

1. **Oversell.** More buyers than units, all arriving together.
2. **Deadlock.** Two orders holding the same two variants in opposite order.
   inventory.lock_variants sorts ids before locking precisely to prevent this;
   MySQL breaks a lock cycle by killing a transaction with error 1213, which
   would reach a shopper as a 500 rather than a clean 422.
3. **Baskets that share no lock.** Orders for *different* products serialise on
   nothing, so anything else in placement that races -- reference allocation,
   most of all -- is exposed only here. This is the case that found a real bug:
   see test_concurrent_orders_for_different_products_all_succeed.

These are slow by construction (seconds, not milliseconds) and marked `slow`
for selection, not exclusion -- they run by default, because a concurrency
guarantee nobody checks is a concurrency guarantee nobody has.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

import pytest
from django.db import OperationalError, connection, transaction
from django.db.models import Sum
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.catalog.models import InventoryLog, InventoryReason
from apps.catalog.services import inventory as inventory_services
from apps.orders.models import Order, OrderItem, OrderStatus, PaymentMethod
from apps.orders.services import placement as placement_services
from config.exceptions import DomainError

# MySQL's own error numbers. 1213 is a genuine lock cycle; 1205 is a lock wait
# that ran out of patience. Both mean the locking strategy failed, and they are
# reported apart from an ordinary crash so a failure message says which.
MYSQL_DEADLOCK = 1213
MYSQL_LOCK_WAIT_TIMEOUT = 1205
LOCK_ERRNOS = (MYSQL_DEADLOCK, MYSQL_LOCK_WAIT_TIMEOUT)

# Five units, twenty buyers. Deliberately lopsided: fifteen must be turned
# away, so a guard that merely slows things down cannot pass by luck.
STOCK = 5
CONTENDERS = 20

# Two variants, sixteen orders, ample stock. Nothing is meant to run out here
# -- the only question is whether opposing basket orders deadlock.
DEADLOCK_STOCK = 50
DEADLOCK_CONTENDERS = 16

# Twenty-four shoppers buying twenty-four different products at once. They
# contend for no variant row, so only placement's own shared state is at stake.
DISJOINT_STOCK = 5
DISJOINT_CONTENDERS = 24

BARRIER_TIMEOUT = 30
WORKER_TIMEOUT = 180

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


class Attempt(NamedTuple):
    """One worker's verdict. `detail` carries a reference, a code or a trace."""

    index: int
    outcome: str  # placed | refused | deadlocked | crashed
    detail: str


# ---------------------------------------------------------------------------
# Fixtures
#
# Everything is committed before the threads start: a worker on its own
# connection cannot see rows this test has not committed. `store_settings` and
# the catalogue factories come from the sibling conftest, so a product built
# here answers to the same purchasable_variants() predicate as the storefront.
# ---------------------------------------------------------------------------
@pytest.fixture
def ledger_stocked(make_sellable_variant):
    """A variant whose entire stock arrived through the inventory ledger.

    Opening stock is written with a movement rather than set on the row, so
    `sum(InventoryLog.delta) == variant.stock` is true of this variant from its
    first second -- which is what lets the reconciliation assertions below be
    equalities instead of differences.
    """

    def _make(*, quantity, name="Test Product", price="1000.00"):
        variant = make_sellable_variant(price=price, stock=0, name=name)
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
def scarce_variant(store_settings, dhaka_zone, ledger_stocked):
    """Five units, and twenty people about to want them."""
    return ledger_stocked(quantity=STOCK, name="Scarce Laptop")


@pytest.fixture
def two_variants(store_settings, dhaka_zone, ledger_stocked):
    """Two variants in a known pk order, so "opposite order" means something."""
    lower = ledger_stocked(quantity=DEADLOCK_STOCK, name="Deadlock Laptop A")
    higher = ledger_stocked(quantity=DEADLOCK_STOCK, name="Deadlock Laptop B")
    assert lower.pk < higher.pk
    return lower, higher


@pytest.fixture
def disjoint_variants(store_settings, dhaka_zone, ledger_stocked):
    """One variant per shopper -- no two orders touch the same row."""
    return [
        ledger_stocked(quantity=DISJOINT_STOCK, name="Disjoint Laptop {0}".format(index))
        for index in range(DISJOINT_CONTENDERS)
    ]


# ---------------------------------------------------------------------------
# The concurrency harness
# ---------------------------------------------------------------------------
def _attempt_placement(*, index, items, barrier, key_prefix):
    """One worker: wait for the others, place one order, close the connection.

    Every exception is caught and classified rather than raised. A worker that
    raised would leave the barrier broken for everyone still waiting on it, and
    the run would fail on a timeout that says nothing about what went wrong.
    """
    try:
        barrier.wait(timeout=BARRIER_TIMEOUT)
        order, _created = placement_services.place_order(
            idempotency_key="{0}-{1}".format(key_prefix, index),
            payment_method=PaymentMethod.COD,
            shipping_address=SHIPPING_ADDRESS,
            email="racer{0}@example.com".format(index),
            items=items,
        )
        return Attempt(index, "placed", order.reference)
    except DomainError as exc:
        # The only acceptable way to lose: a business rule, cleanly reported.
        return Attempt(index, "refused", exc.code)
    except OperationalError as exc:
        errno = exc.args[0] if exc.args else None
        outcome = "deadlocked" if errno in LOCK_ERRNOS else "crashed"
        return Attempt(index, outcome, "OperationalError {0}: {1}".format(errno, exc))
    except Exception as exc:  # noqa: BLE001 -- classified here, asserted on below
        return Attempt(index, "crashed", "{0}: {1}".format(type(exc).__name__, exc))
    finally:
        # Django opens a fresh connection per thread and CONN_MAX_AGE keeps it
        # alive afterwards. Left open, they hold locks and exhaust the pool.
        connection.close()


def _place_concurrently(build_items, *, count, key_prefix):
    """Fire `count` placements at one instant and collect every verdict.

    `build_items` runs on this thread, so a worker's first database contact is
    the placement itself.
    """
    barrier = threading.Barrier(count)
    payloads = [build_items(index) for index in range(count)]

    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [
            pool.submit(
                _attempt_placement,
                index=index,
                items=payloads[index],
                barrier=barrier,
                key_prefix=key_prefix,
            )
            for index in range(count)
        ]
        return [future.result(timeout=WORKER_TIMEOUT) for future in futures]


def _by_outcome(results, outcome):
    return [result for result in results if result.outcome == outcome]


def _broken(results):
    """Workers that failed in a way no shopper should ever see."""
    return _by_outcome(results, "deadlocked") + _by_outcome(results, "crashed")


def _report(results):
    """Readable evidence for an assertion message -- one line per bad worker."""
    return "\n".join(
        "  worker {0}: {1} -- {2}".format(r.index, r.outcome, r.detail)
        for r in _broken(results)
    )


def _logged_total(**filters):
    return (
        InventoryLog.objects.filter(**filters).aggregate(total=Sum("delta"))["total"] or 0
    )


# ---------------------------------------------------------------------------
# The lock-ordering invariant, asserted directly
# ---------------------------------------------------------------------------
@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_lock_variants_locks_rows_in_primary_key_order_whatever_order_it_was_asked_for(
    two_variants,
):
    lower, higher = two_variants

    with transaction.atomic():
        with CaptureQueriesContext(connection) as captured:
            locked = inventory_services.lock_variants([higher.pk, lower.pk])

    assert list(locked) == [lower.pk, higher.pk], (
        "lock_variants must return rows in primary-key order however the caller "
        "asked for them -- that ordering is the whole deadlock defence."
    )

    sql = " ".join(query["sql"].lower() for query in captured.captured_queries)
    assert "for update" in sql, "the lock query is not a locking read at all"
    assert "order by" in sql, "the lock query has no deterministic row order"
    assert sql.index("order by") < sql.index("for update"), (
        "ORDER BY must be part of the locking SELECT, not a later statement."
    )


# ---------------------------------------------------------------------------
# Hazard 1 -- oversell
# ---------------------------------------------------------------------------
@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_twenty_simultaneous_orders_for_five_units_confirm_exactly_five_and_leave_stock_at_zero(
    scarce_variant,
):
    variant = scarce_variant

    results = _place_concurrently(
        lambda index: [{"variant_id": variant.pk, "quantity": 1}],
        count=CONTENDERS,
        key_prefix="oversell",
    )
    placed = _by_outcome(results, "placed")
    refused = _by_outcome(results, "refused")

    assert not _broken(results), (
        "a concurrent placement failed with something other than a DomainError:\n"
        + _report(results)
    )
    assert len(placed) == STOCK, "expected exactly {0} winners for {0} units, got {1}".format(
        STOCK, len(placed)
    )
    assert len(refused) == CONTENDERS - STOCK
    assert {result.detail for result in refused} == {"INSUFFICIENT_STOCK"}, (
        "losers must be told the stock ran out, not something incidental: {0}".format(
            sorted({result.detail for result in refused})
        )
    )

    variant.refresh_from_db()
    assert variant.stock == 0, "oversell or undersell: stock ended at {0}".format(
        variant.stock
    )
    assert variant.stock >= 0

    # The ledger invariant (PRD 6.4): deltas must reconcile to the row.
    assert inventory_services.logged_stock(variant) == variant.stock
    assert _logged_total(variant=variant, reason=InventoryReason.ORDER_CONFIRMED) == -STOCK
    assert (
        InventoryLog.objects.filter(
            variant=variant, reason=InventoryReason.ORDER_CONFIRMED
        ).count()
        == STOCK
    )


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_a_lost_race_leaves_no_order_behind_and_every_surviving_order_paid_for_its_stock(
    scarce_variant,
):
    variant = scarce_variant

    results = _place_concurrently(
        lambda index: [{"variant_id": variant.pk, "quantity": 1}],
        count=CONTENDERS,
        key_prefix="rollback",
    )
    assert not _broken(results), _report(results)
    placed = _by_outcome(results, "placed")

    orders = list(Order.objects.all())
    assert len(orders) == STOCK, (
        "a refused placement must roll back completely -- found {0} orders for "
        "{1} units of stock".format(len(orders), STOCK)
    )
    assert {order.reference for order in orders} == {result.detail for result in placed}
    assert len({order.reference for order in orders}) == STOCK, "duplicate reference issued"
    assert {order.status for order in orders} == {OrderStatus.CONFIRMED}

    # Every unit on an order was taken out of stock, and every unit taken out
    # of stock belongs to an order. Neither direction may drift.
    assert (OrderItem.objects.aggregate(total=Sum("quantity"))["total"] or 0) == STOCK
    assert -_logged_total(reason=InventoryReason.ORDER_CONFIRMED) == STOCK

    for order in orders:
        logs = order.inventory_logs.filter(reason=InventoryReason.ORDER_CONFIRMED)
        assert logs.count() == 1, "order {0} moved no stock".format(order.reference)
        assert logs.first().delta == -1

    assert InventoryLog.objects.filter(order__isnull=False).count() == STOCK, (
        "a rolled-back placement left an inventory row behind"
    )


# ---------------------------------------------------------------------------
# Hazard 2 -- deadlock
# ---------------------------------------------------------------------------
@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_orders_holding_the_same_two_variants_in_opposite_order_never_deadlock(
    two_variants,
):
    lower, higher = two_variants
    ascending = [
        {"variant_id": lower.pk, "quantity": 1},
        {"variant_id": higher.pk, "quantity": 1},
    ]
    descending = list(reversed(ascending))

    def build_items(index):
        # Half the shop is buying A then B, the other half B then A. Locked
        # naively in basket order, that is a textbook lock cycle.
        return list(ascending if index % 2 == 0 else descending)

    results = _place_concurrently(
        build_items, count=DEADLOCK_CONTENDERS, key_prefix="deadlock"
    )

    assert not _by_outcome(results, "deadlocked"), (
        "MySQL killed a transaction on a lock cycle -- variants are not being "
        "locked in a deterministic order:\n" + _report(results)
    )
    assert not _by_outcome(results, "crashed"), (
        "a placement failed with something other than a DomainError:\n" + _report(results)
    )

    # Stock was ample, so nothing had a business reason to be refused.
    assert len(_by_outcome(results, "placed")) == DEADLOCK_CONTENDERS, "refusals: {0}".format(
        sorted(result.detail for result in _by_outcome(results, "refused"))
    )

    for variant in (lower, higher):
        variant.refresh_from_db()
        assert variant.stock == DEADLOCK_STOCK - DEADLOCK_CONTENDERS
        assert variant.stock >= 0
        assert inventory_services.logged_stock(variant) == variant.stock

    assert Order.objects.count() == DEADLOCK_CONTENDERS
    assert (
        OrderItem.objects.aggregate(total=Sum("quantity"))["total"]
        == DEADLOCK_CONTENDERS * 2
    )


# ---------------------------------------------------------------------------
# Hazard 3 -- baskets that contend for nothing
# ---------------------------------------------------------------------------
@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_concurrent_orders_for_different_products_all_succeed_with_distinct_references(
    disjoint_variants,
):
    """Twenty-four shoppers, twenty-four different products, one instant.

    This is the busy-Friday case, and it is harsher on placement than the
    oversell case is: orders touching different variants share no lock, so
    nothing serialises them and every piece of state placement *does* share is
    hit flat out.

    It caught a real bug. next_reference() read the year's highest reference
    with a plain SELECT, so all twenty-four read the same number and computed
    the same successor; one INSERT won the unique index and the rest raised
    IntegrityError until PLACEMENT_ATTEMPTS ran out and a raw database
    exception reached the caller. Measured before the fix: 3 orders placed, 21
    crashed, on every run. Nothing about it was rare.
    """
    results = _place_concurrently(
        lambda index: [{"variant_id": disjoint_variants[index].pk, "quantity": 1}],
        count=DISJOINT_CONTENDERS,
        key_prefix="disjoint",
    )

    assert not _broken(results), (
        "a placement that contended with nothing still failed -- a database "
        "exception must never reach the caller:\n" + _report(results)
    )
    assert len(_by_outcome(results, "placed")) == DISJOINT_CONTENDERS, (
        "orders for different products have no reason to refuse each other: {0}".format(
            sorted(result.detail for result in _by_outcome(results, "refused"))
        )
    )

    # References are unique, and the sequence has no holes: allocation under
    # contention must not burn numbers either.
    references = sorted(Order.objects.values_list("reference", flat=True))
    assert len(set(references)) == DISJOINT_CONTENDERS
    assert references == [
        "ORD-{0}-{1:06d}".format(timezone.now().year, n)
        for n in range(1, DISJOINT_CONTENDERS + 1)
    ]

    for variant in disjoint_variants:
        variant.refresh_from_db()
        assert variant.stock == DISJOINT_STOCK - 1
        assert inventory_services.logged_stock(variant) == variant.stock
