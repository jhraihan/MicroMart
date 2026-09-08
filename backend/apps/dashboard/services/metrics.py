"""
Admin dashboard aggregation (PRD 7.3 GET /admin/dashboard/, US-A1).

Three rules shape this module.

**Revenue is only money the store actually agreed to take.** `REVENUE_STATUSES`
is confirmed, packed, shipped and delivered. A `pending` order has not been
paid for and has not moved stock -- for an online order it is an abandoned
checkout, and counting it would report income that never arrives. `cancelled`
and `refunded` are excluded for the obvious reason: a refunded sale that still
counts is a revenue figure that can only ever go up. The list is exported so
the customers report can compute lifetime value with the same definition
rather than inventing a second one.

**No tile scans the order table.** The three windows are one aggregate query
with conditional sums, the trend is one grouped query, the awaiting-action
counts are one more, and the low-stock count is a fourth. Four queries, always
-- adding an order does not add a query, and neither does asking for 90 days
of trend instead of 30. Pinned by apps/dashboard/tests/test_query_counts.py.

**Days are local days, computed in Python.** MySQL on this deployment has no
timezone tables loaded (`SELECT CONVERT_TZ(now(), 'UTC', 'Asia/Dhaka')` returns
NULL), so Django's `__date` lookups and a bare `TruncDate` would silently
group every row into one NULL bucket. Window boundaries are therefore worked
out with `timezone.localtime`, and the trend's day bucket shifts the stored UTC
timestamp by the current local offset before `DATE()` sees it -- which is the
same arithmetic, expressed somewhere the database can index-scan it.
"""
from datetime import timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.db.models import (
    Case,
    Count,
    DateTimeField,
    DecimalField,
    ExpressionWrapper,
    F,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.catalog.services import inventory as inventory_services
from apps.orders.models import Order, OrderStatus
from config.exceptions import DomainError

CURRENCY = "BDT"
ZERO = Decimal("0.00")

# Money the store has agreed to take. See the module docstring -- this is a
# deliberate choice, not an oversight, and the customers report shares it.
REVENUE_STATUSES = (
    OrderStatus.CONFIRMED,
    OrderStatus.PACKED,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
)

# "Awaiting action" is work on the admin's desk: an order that is neither
# terminal nor already handed to a courier. A shipped order is waiting on the
# courier, not on the store.
AWAITING_ACTION_STATUSES = (
    OrderStatus.PENDING,
    OrderStatus.CONFIRMED,
    OrderStatus.PACKED,
)

TREND_DAYS_DEFAULT = 30
TREND_DAYS_MAX = 365


def money_output_field():
    """
    Aggregate output. Wider than MoneyField's DECIMAL(12,2) on purpose: one
    order is capped at twelve digits, a year of them is not.
    """
    return DecimalField(max_digits=16, decimal_places=2)


def _sum_money(expression):
    """Sum that answers 0.00 rather than None when nothing matched."""
    return Coalesce(Sum(expression), Value(ZERO), output_field=money_output_field())


def _money(value):
    return (value if value is not None else ZERO).quantize(Decimal("0.01"))


def local_day_start(moment):
    """Local midnight of the day `moment` falls in, as an aware datetime."""
    return timezone.localtime(moment).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def parse_trend_days(value, default=TREND_DAYS_DEFAULT):
    """`?days=` for the trend series. Malformed input is 422, never ignored."""
    if value in (None, ""):
        return default
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise DomainError(
            "days must be a whole number of days.",
            code="INVALID_FILTER",
            field="days",
        )
    if days < 1 or days > TREND_DAYS_MAX:
        raise DomainError(
            "days must be between 1 and {0}.".format(TREND_DAYS_MAX),
            code="INVALID_FILTER",
            field="days",
        )
    return days


def _window(revenue, orders):
    revenue = _money(revenue)
    orders = int(orders or 0)
    return {
        "revenue": revenue,
        "orders": orders,
        # Reported rather than left to the client, because the client would
        # have to parse two decimal strings into floats to divide them.
        "average_order_value": (
            (revenue / orders).quantize(Decimal("0.01")) if orders else ZERO
        ),
    }


def revenue_windows(now=None):
    """
    Revenue and order count for today, the last 7 days and the last 30 days
    (US-A1), in one query.

    A window is whole local days including today: "last 7 days" starts at local
    midnight six days ago, so a figure quoted at 09:00 covers the same calendar
    days as one quoted at 23:00 and does not slide under the reader.
    """
    now = now or timezone.now()
    today_start = local_day_start(now)
    week_start = today_start - timedelta(days=6)
    month_start = today_start - timedelta(days=29)

    aggregates = Order.objects.filter(
        status__in=REVENUE_STATUSES, placed_at__gte=month_start
    ).aggregate(
        today_revenue=_sum_money(
            Case(When(placed_at__gte=today_start, then=F("grand_total")))
        ),
        today_orders=Count(Case(When(placed_at__gte=today_start, then=1))),
        week_revenue=_sum_money(
            Case(When(placed_at__gte=week_start, then=F("grand_total")))
        ),
        week_orders=Count(Case(When(placed_at__gte=week_start, then=1))),
        month_revenue=_sum_money("grand_total"),
        month_orders=Count("id"),
    )

    return {
        "today": _window(aggregates["today_revenue"], aggregates["today_orders"]),
        "last_7_days": _window(aggregates["week_revenue"], aggregates["week_orders"]),
        "last_30_days": _window(
            aggregates["month_revenue"], aggregates["month_orders"]
        ),
    }


def revenue_trend(days=TREND_DAYS_DEFAULT, now=None):
    """
    One point per local day for the chart (US-A1), oldest first, in one query.

    Days with no orders are filled with zeros here rather than left out. A
    sparse series draws a line straight from Tuesday to Friday and reads as
    steady trade across a three-day outage.
    """
    now = now or timezone.now()
    today_start = local_day_start(now)
    first_day_start = today_start - timedelta(days=days - 1)
    offset = timezone.localtime(now).utcoffset() or timedelta(0)

    rows = (
        Order.objects.filter(
            status__in=REVENUE_STATUSES, placed_at__gte=first_day_start
        )
        .annotate(
            day=TruncDate(
                ExpressionWrapper(
                    F("placed_at") + offset, output_field=DateTimeField()
                ),
                # Matching the connection's own timezone name suppresses the
                # CONVERT_TZ() Django would otherwise emit -- see the module
                # docstring. The shift above has already done the conversion.
                tzinfo=dt_timezone.utc,
            )
        )
        .values("day")
        .annotate(revenue=_sum_money("grand_total"), orders=Count("id"))
    )
    by_day = {row["day"]: row for row in rows}

    series = []
    for index in range(days):
        day = (first_day_start + timedelta(days=index)).date()
        row = by_day.get(day)
        series.append(
            {
                "date": day,
                "revenue": _money(row["revenue"]) if row else ZERO,
                "orders": int(row["orders"]) if row else 0,
            }
        )
    return series


def orders_awaiting_action():
    """
    How much is sitting on the admin's desk (US-A1), broken down, in one query.
    """
    counts = Order.objects.filter(status__in=AWAITING_ACTION_STATUSES).aggregate(
        **{
            status.value: Count(Case(When(status=status, then=1)))
            for status in AWAITING_ACTION_STATUSES
        }
    )
    counts = {key: int(value or 0) for key, value in counts.items()}
    counts["total"] = sum(counts.values())
    return counts


def low_stock_count():
    """
    Variants at or below their own threshold (US-A1, FR-INV-6).

    Counted through the same `low_stock_variants()` the cron digest emails, so
    the number on the dashboard and the number in the inbox cannot disagree.
    """
    return inventory_services.low_stock_variants().count()


def dashboard_snapshot(*, days=TREND_DAYS_DEFAULT, now=None):
    """Everything GET /admin/dashboard/ renders. Four queries, always."""
    now = now or timezone.now()
    windows = revenue_windows(now=now)
    return {
        "generated_at": now,
        "currency": CURRENCY,
        "revenue_statuses": [status.value for status in REVENUE_STATUSES],
        "today": windows["today"],
        "last_7_days": windows["last_7_days"],
        "last_30_days": windows["last_30_days"],
        "trend_days": days,
        "trend": revenue_trend(days=days, now=now),
        "orders_awaiting_action": orders_awaiting_action(),
        "low_stock_count": low_stock_count(),
    }
