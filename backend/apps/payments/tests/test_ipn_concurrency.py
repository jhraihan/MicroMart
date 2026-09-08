"""
Two IPNs for one order, arriving at the same instant (FR-PAY-5).

SSLCommerz retries a notification it did not get a 200 for, and a retry that
overtakes the original is a normal event, not an exotic one -- a slow first
request and its retry can be in flight together. If both handlers could read a
pending order before either wrote a confirmed one, the order would decrement
stock twice, log two confirmations, and the ledger would stop reconciling.

Everything mechanical in this file is load-bearing, and it is the same set of
choices apps/orders/tests/test_oversell_concurrency.py makes for the same
reasons:

* **@pytest.mark.django_db(transaction=True) is mandatory.** Inside pytest's
  default wrapping transaction every worker shares one connection and one open
  transaction, SELECT ... FOR UPDATE contends with nothing, and this file would
  pass while proving nothing at all.
* **Real threads on real connections**, each closed on the way out -- left
  open, CONN_MAX_AGE keeps them alive holding locks and the run hangs.
* **A threading.Barrier releases every worker at one instant.** Without it the
  threads start staggered, serialise on their own, and the contention this file
  is about never happens.

The gateway stub answers every worker identically and without touching the
database, so the only shared state in play is the order row and its payment --
which is exactly the state the lock is supposed to protect.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import NamedTuple

import pytest
from django.db import OperationalError, connection
from django.db.models import Sum

from apps.catalog.models import InventoryLog, InventoryReason
from apps.orders.models import OrderStatus, OrderStatusLog
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import payments as payment_services
from config.exceptions import DomainError

# MySQL's own numbers. 1213 is a genuine lock cycle, 1205 a lock wait that ran
# out of patience. Both mean the locking strategy failed, and they are reported
# apart from an ordinary crash so a failure message says which.
MYSQL_DEADLOCK = 1213
MYSQL_LOCK_WAIT_TIMEOUT = 1205
LOCK_ERRNOS = (MYSQL_DEADLOCK, MYSQL_LOCK_WAIT_TIMEOUT)

CONTENDERS = 8
BARRIER_TIMEOUT = 30
WORKER_TIMEOUT = 180


class Attempt(NamedTuple):
    index: int
    outcome: str  # confirmed | ignored | deadlocked | crashed
    detail: str


@pytest.fixture
def paid_order(gateway, online_order):
    """An order with a session open, committed, awaiting its notification."""
    payment_services.initiate_payment(order_reference=online_order.reference)
    gateway.will_validate(order=online_order)
    return online_order


def _deliver(*, index, notification, barrier):
    """One worker: wait for the others, deliver one IPN, close the connection."""
    try:
        barrier.wait(timeout=BARRIER_TIMEOUT)
        result = payment_services.handle_ipn(dict(notification))
        return Attempt(
            index, "confirmed" if result.confirmed else "ignored", result.reason
        )
    except DomainError as exc:
        return Attempt(index, "ignored", exc.code)
    except OperationalError as exc:
        errno = exc.args[0] if exc.args else None
        outcome = "deadlocked" if errno in LOCK_ERRNOS else "crashed"
        return Attempt(index, outcome, "OperationalError {0}: {1}".format(errno, exc))
    except Exception as exc:  # noqa: BLE001 -- classified here, asserted on below
        return Attempt(index, "crashed", "{0}: {1}".format(type(exc).__name__, exc))
    finally:
        connection.close()


def _deliver_concurrently(notification, *, count):
    barrier = threading.Barrier(count)
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [
            pool.submit(_deliver, index=index, notification=notification, barrier=barrier)
            for index in range(count)
        ]
        return [future.result(timeout=WORKER_TIMEOUT) for future in futures]


def _by_outcome(results, outcome):
    return [result for result in results if result.outcome == outcome]


def _report(results):
    broken = _by_outcome(results, "deadlocked") + _by_outcome(results, "crashed")
    return "\n".join(
        "  worker {0}: {1} -- {2}".format(r.index, r.outcome, r.detail) for r in broken
    )


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_notifications_for_one_order_confirm_it_exactly_once(
    gateway, paid_order, variant
):
    notification = gateway.notification()

    results = _deliver_concurrently(notification, count=2)

    assert not _report(results), "workers failed in ways no gateway should see:\n" + _report(results)

    confirmed = _by_outcome(results, "confirmed")
    assert len(confirmed) == 1, (
        "exactly one notification may confirm; the other must find the order "
        "already confirmed and do nothing (FR-PAY-5). Outcomes: {0}".format(
            [(r.outcome, r.detail) for r in results]
        )
    )
    assert _by_outcome(results, "ignored")[0].detail == (
        payment_services.REASON_ALREADY_CONFIRMED
    )

    paid_order.refresh_from_db()
    assert paid_order.status == OrderStatus.CONFIRMED

    variant.refresh_from_db()
    assert variant.stock == 8, "two units left the shelf once, not twice"


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_a_burst_of_notifications_writes_one_confirmation_one_decrement_and_one_ledger_row(
    gateway, paid_order, variant
):
    """
    Eight at once rather than two, because a lock that merely narrows the
    window can survive a pair by luck and cannot survive eight.
    """
    notification = gateway.notification()

    results = _deliver_concurrently(notification, count=CONTENDERS)

    assert not _report(results), "workers failed in ways no gateway should see:\n" + _report(results)
    assert len(_by_outcome(results, "confirmed")) == 1
    assert len(_by_outcome(results, "ignored")) == CONTENDERS - 1

    # Every loser must find the order *already confirmed*, which is the shape
    # of a clean replay. Anything else -- an illegal-transition refusal, say --
    # means the losers got past the status read before the winner committed,
    # and the order state machine caught what this handler should have.
    assert {r.detail for r in _by_outcome(results, "ignored")} == {
        payment_services.REASON_ALREADY_CONFIRMED
    }

    confirmations = OrderStatusLog.objects.filter(
        order=paid_order, to_status=OrderStatus.CONFIRMED
    )
    assert confirmations.count() == 1, (
        "OrderStatusLog is append-only, so a second confirmation would be a "
        "permanent lie in the audit trail (FR-ORD-5)"
    )

    movements = InventoryLog.objects.filter(
        variant=variant, reason=InventoryReason.ORDER_CONFIRMED
    )
    assert movements.count() == 1
    assert movements.first().delta == -2

    # The reconciliation check the whole inventory design exists to support.
    variant.refresh_from_db()
    logged = InventoryLog.objects.filter(variant=variant).aggregate(
        total=Sum("delta")
    )["total"]
    assert logged == variant.stock == 8

    payment = Payment.objects.get(order=paid_order)
    assert payment.status == PaymentStatus.PAID
    assert payment.amount == Decimal("2000.00")
    assert Payment.objects.filter(order=paid_order).count() == 1
