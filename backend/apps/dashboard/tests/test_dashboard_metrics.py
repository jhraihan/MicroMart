"""
Dashboard metrics (PRD 4.3 US-A1, 7.3 GET /admin/dashboard/).

"Dashboard shows revenue and order count for today, last 7 days, and last 30
days; a trend chart; counts of orders awaiting action; a low-stock count."

The tests that matter most here are the ones about *what counts as revenue*.
A revenue tile is only meaningful next to its definition, and the definition
chosen -- confirmed, packed, shipped, delivered -- is a judgement call that a
future reader is entitled to see asserted rather than inferred.
"""
from decimal import Decimal

import pytest
from rest_framework import status

from apps.dashboard.services import metrics as metric_services
from apps.orders.models import OrderStatus, PaymentMethod

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# What counts as revenue
# ---------------------------------------------------------------------------
def test_revenue_counts_confirmed_packed_shipped_and_delivered_orders(
    make_order, days_ago
):
    for state in (
        OrderStatus.CONFIRMED,
        OrderStatus.PACKED,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
    ):
        make_order(status=state, grand_total="1000.00", placed_at=days_ago(0))

    windows = metric_services.revenue_windows()

    assert windows["today"]["revenue"] == Decimal("4000.00")
    assert windows["today"]["orders"] == 4


def test_a_cancelled_order_never_inflates_revenue(make_order, days_ago):
    """
    The rule that makes the number trustworthy: revenue must be able to go
    down. A cancelled sale that still counts is a figure that only ever rises.
    """
    make_order(status=OrderStatus.DELIVERED, grand_total="1000.00", placed_at=days_ago(0))
    make_order(status=OrderStatus.CANCELLED, grand_total="9999.00", placed_at=days_ago(0))

    windows = metric_services.revenue_windows()

    assert windows["today"]["revenue"] == Decimal("1000.00")
    assert windows["today"]["orders"] == 1


def test_a_refunded_order_never_inflates_revenue(make_order, days_ago):
    make_order(status=OrderStatus.DELIVERED, grand_total="1000.00", placed_at=days_ago(0))
    make_order(status=OrderStatus.REFUNDED, grand_total="5000.00", placed_at=days_ago(0))

    assert metric_services.revenue_windows()["today"]["revenue"] == Decimal("1000.00")


def test_a_pending_order_is_not_counted_as_revenue_because_no_money_has_arrived(
    make_order, days_ago
):
    """
    A pending order is an online checkout that has not been paid for
    (FR-PAY-7) -- it has not even moved stock. Counting it would report income
    from an abandoned basket.
    """
    make_order(
        status=OrderStatus.PENDING,
        payment_method=PaymentMethod.ONLINE,
        grand_total="7500.00",
        placed_at=days_ago(0),
    )

    windows = metric_services.revenue_windows()

    assert windows["today"]["revenue"] == Decimal("0.00")
    assert windows["today"]["orders"] == 0


def test_the_payload_publishes_which_statuses_it_counted(admin_client, dashboard_url):
    response = admin_client.get(dashboard_url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["revenue_statuses"] == [
        "confirmed",
        "packed",
        "shipped",
        "delivered",
    ]


# ---------------------------------------------------------------------------
# The three windows
# ---------------------------------------------------------------------------
def test_the_three_windows_widen_rather_than_partition_the_same_orders(
    make_order, days_ago
):
    """
    Today's orders are also in the 7-day figure, and both are in the 30-day
    figure. Each window is a period ending now, not a bucket.
    """
    make_order(status=OrderStatus.DELIVERED, grand_total="100.00", placed_at=days_ago(0))
    make_order(status=OrderStatus.DELIVERED, grand_total="200.00", placed_at=days_ago(3))
    make_order(status=OrderStatus.DELIVERED, grand_total="400.00", placed_at=days_ago(20))

    windows = metric_services.revenue_windows()

    assert windows["today"]["revenue"] == Decimal("100.00")
    assert windows["last_7_days"]["revenue"] == Decimal("300.00")
    assert windows["last_30_days"]["revenue"] == Decimal("700.00")
    assert (windows["today"]["orders"], windows["last_7_days"]["orders"]) == (1, 2)
    assert windows["last_30_days"]["orders"] == 3


def test_an_order_older_than_thirty_days_falls_out_of_every_window(
    make_order, days_ago
):
    make_order(status=OrderStatus.DELIVERED, grand_total="900.00", placed_at=days_ago(45))

    windows = metric_services.revenue_windows()

    assert windows["last_30_days"]["revenue"] == Decimal("0.00")
    assert windows["last_30_days"]["orders"] == 0


def test_the_windows_are_whole_local_days_so_a_figure_does_not_slide_during_the_day(
    make_order, days_ago
):
    """
    "Last 7 days" starts at local midnight six days ago, not 168 hours ago.
    An order placed at 12:00 six days back is inside the window whether it is
    read at 09:00 or at 23:00 today.
    """
    make_order(status=OrderStatus.DELIVERED, grand_total="500.00", placed_at=days_ago(6))
    make_order(status=OrderStatus.DELIVERED, grand_total="800.00", placed_at=days_ago(7))

    windows = metric_services.revenue_windows()

    assert windows["last_7_days"]["revenue"] == Decimal("500.00")
    assert windows["last_30_days"]["revenue"] == Decimal("1300.00")


def test_an_empty_store_reports_zero_rather_than_null(admin_client, dashboard_url):
    """None would render as "--" on the tile; 0.00 is the true answer."""
    response = admin_client.get(dashboard_url)

    assert response.data["today"]["revenue"] == "0.00"
    assert response.data["today"]["orders"] == 0
    assert response.data["today"]["average_order_value"] == "0.00"


# ---------------------------------------------------------------------------
# Money on the wire
# ---------------------------------------------------------------------------
def test_every_money_figure_crosses_the_wire_as_a_decimal_string(
    admin_client, dashboard_url, make_order, days_ago
):
    make_order(status=OrderStatus.DELIVERED, grand_total="1234.50", placed_at=days_ago(0))

    response = admin_client.get(dashboard_url)

    for window in ("today", "last_7_days", "last_30_days"):
        assert isinstance(response.data[window]["revenue"], str), window
        assert isinstance(response.data[window]["average_order_value"], str), window
    assert response.data["today"]["revenue"] == "1234.50"
    assert all(isinstance(point["revenue"], str) for point in response.data["trend"])


def test_the_average_order_value_is_computed_in_decimal(make_order, days_ago):
    make_order(status=OrderStatus.DELIVERED, grand_total="100.00", placed_at=days_ago(0))
    make_order(status=OrderStatus.DELIVERED, grand_total="200.00", placed_at=days_ago(0))
    make_order(status=OrderStatus.DELIVERED, grand_total="100.00", placed_at=days_ago(0))

    average = metric_services.revenue_windows()["today"]["average_order_value"]

    assert type(average) is Decimal
    assert average == Decimal("133.33")


# ---------------------------------------------------------------------------
# Trend series
# ---------------------------------------------------------------------------
def test_the_trend_series_has_one_point_per_day_oldest_first(admin_client, dashboard_url):
    response = admin_client.get(dashboard_url)

    trend = response.data["trend"]
    assert len(trend) == 30
    dates = [point["date"] for point in trend]
    assert dates == sorted(dates)


def test_a_day_with_no_trade_is_a_zero_point_not_a_missing_one(
    make_order, days_ago
):
    """
    A sparse series draws a straight line from Tuesday to Friday and reads as
    steady trade across a three-day outage.
    """
    make_order(status=OrderStatus.DELIVERED, grand_total="600.00", placed_at=days_ago(2))

    series = metric_services.revenue_trend(days=5)

    assert len(series) == 5
    assert [point["revenue"] for point in series] == [
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("600.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    ]
    assert [point["orders"] for point in series] == [0, 0, 1, 0, 0]


def test_the_trend_buckets_orders_by_local_day_not_by_utc_day(make_order, days_ago):
    """
    Dhaka is UTC+6, so an order placed at 03:00 local is stored as 21:00 the
    *previous* UTC day. Grouping on the raw stored timestamp would file it
    under yesterday, and the daily figures would disagree with the tiles.

    This is not hypothetical: MySQL on this deployment has no timezone tables
    loaded, so `TruncDate` without the shift in metrics.py would group every
    row into a single NULL bucket.
    """
    make_order(status=OrderStatus.DELIVERED, grand_total="450.00", placed_at=days_ago(0, hour=3))

    series = metric_services.revenue_trend(days=3)

    assert series[-1]["revenue"] == Decimal("450.00"), (
        "an order placed at 03:00 local was not filed under today: {0}".format(series)
    )
    assert all(point["date"] is not None for point in series)


def test_the_trend_window_is_selectable_and_bounded(admin_client, dashboard_url):
    response = admin_client.get(dashboard_url, {"days": 7})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["trend_days"] == 7
    assert len(response.data["trend"]) == 7


@pytest.mark.parametrize("bad", ["0", "-3", "999", "week", "7.5"])
def test_a_malformed_days_parameter_is_refused_rather_than_silently_ignored(
    admin_client, dashboard_url, bad
):
    response = admin_client.get(dashboard_url, {"days": bad})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.data["error"]["code"] == "INVALID_FILTER"
    assert response.data["error"]["field"] == "days"


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def test_orders_awaiting_action_counts_work_on_the_admins_desk(make_order, days_ago):
    """
    Pending, confirmed and packed are waiting on the store. A shipped order is
    waiting on the courier, and the terminal states are waiting on nobody.
    """
    make_order(status=OrderStatus.PENDING, placed_at=days_ago(1))
    make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(1))
    make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(2))
    make_order(status=OrderStatus.PACKED, placed_at=days_ago(3))
    make_order(status=OrderStatus.SHIPPED, placed_at=days_ago(4))
    make_order(status=OrderStatus.DELIVERED, placed_at=days_ago(5))
    make_order(status=OrderStatus.CANCELLED, placed_at=days_ago(6))

    counts = metric_services.orders_awaiting_action()

    assert counts == {"pending": 1, "confirmed": 2, "packed": 1, "total": 4}


def test_the_awaiting_action_count_ignores_how_old_the_order_is(make_order, days_ago):
    """An order stuck since March is exactly the one the tile exists to surface."""
    make_order(status=OrderStatus.CONFIRMED, placed_at=days_ago(200))

    assert metric_services.orders_awaiting_action()["total"] == 1


def test_the_low_stock_count_matches_the_digest_definition(make_variant):
    make_variant(stock=0, low_stock_threshold=5)
    make_variant(stock=5, low_stock_threshold=5)
    make_variant(stock=6, low_stock_threshold=5)

    assert metric_services.low_stock_count() == 2


def test_the_dashboard_reports_the_low_stock_count(admin_client, dashboard_url, make_variant):
    make_variant(stock=1, low_stock_threshold=5)

    response = admin_client.get(dashboard_url)

    assert response.data["low_stock_count"] == 1
    assert response.data["orders_awaiting_action"]["total"] == 0
