"""
Cost guards for the admin surface (PRD 9.1).

The bar here, as in apps/cart/tests/test_query_counts.py, is not "few queries"
but a *constant* number. A dashboard is the first screen an admin opens and
the one they leave on a second monitor -- the whole point of aggregating in
the database is that its cost does not grow with the order table. A tile that
walked the orders would look fine on the seven seeded fixtures and fall over
on the first real trading month.

The order list is held to the same bar for a different reason: it is the one
admin screen that renders many rows, so a lazy relation on the row serializer
turns one page into fifty queries.
"""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.dashboard.services import customers as customer_services
from apps.dashboard.services import metrics as metric_services
from apps.orders.models import OrderStatus

pytestmark = pytest.mark.django_db

# Measured, not guessed. One conditional-aggregate query for the three revenue
# windows, one grouped query for the trend, one for the awaiting-action
# counts, one for the low-stock count.
DASHBOARD_QUERY_BUDGET = 4


def fill(make_order, days_ago, count, *, start=0):
    """`count` delivered orders spread over the last fortnight."""
    for index in range(start, start + count):
        make_order(
            status=OrderStatus.DELIVERED,
            grand_total="1000.00",
            placed_at=days_ago(index % 14),
        )


def snapshot_queries(**kwargs):
    with CaptureQueriesContext(connection) as captured:
        metric_services.dashboard_snapshot(**kwargs)
    return len(captured)


def test_the_dashboard_costs_a_constant_number_of_queries_as_orders_pile_up(
    make_order, days_ago
):
    fill(make_order, days_ago, 3)
    few = snapshot_queries()

    fill(make_order, days_ago, 40, start=3)
    many = snapshot_queries()

    assert many == few, (
        "the dashboard got more expensive as orders were added: {0} queries "
        "for 3 orders, {1} for 43. A tile is iterating the order table "
        "instead of aggregating it.".format(few, many)
    )
    assert many <= DASHBOARD_QUERY_BUDGET, (
        "the dashboard cost {0} queries, budget is {1}".format(
            many, DASHBOARD_QUERY_BUDGET
        )
    )


def test_a_longer_trend_window_does_not_cost_more_queries(make_order, days_ago):
    """
    Asking for 90 days instead of 30 must not become 90 queries. The series is
    one GROUP BY and the empty days are filled in Python.
    """
    fill(make_order, days_ago, 10)

    assert snapshot_queries(days=90) == snapshot_queries(days=7)


def test_the_dashboard_endpoint_itself_stays_flat(
    admin_client, dashboard_url, make_order, days_ago
):
    """
    The service is only half the story -- authentication, permissions and
    serialization all run per request. Measured through the view so a lazy
    relation added to the payload later is caught here.
    """
    fill(make_order, days_ago, 2)
    with CaptureQueriesContext(connection) as first:
        admin_client.get(dashboard_url)

    fill(make_order, days_ago, 30, start=2)
    with CaptureQueriesContext(connection) as second:
        admin_client.get(dashboard_url)

    assert len(second) == len(first), (
        "GET /admin/dashboard/ cost {0} queries with 2 orders and {1} with 32".format(
            len(first), len(second)
        )
    )


def test_the_order_list_costs_the_same_for_one_row_as_for_a_full_page(
    admin_client, orders_url, make_order, days_ago
):
    """
    Every row renders its lines, its customer and the transitions the state
    machine would accept. Without the prefetches in
    apps/orders/services/history.py that is three lazy loads per row.
    """
    make_order(placed_at=days_ago(1))
    with CaptureQueriesContext(connection) as one_row:
        admin_client.get(orders_url)

    for index in range(15):
        make_order(placed_at=days_ago(index % 10))
    with CaptureQueriesContext(connection) as sixteen_rows:
        response = admin_client.get(orders_url)

    assert len(response.data["results"]) == 16
    assert len(sixteen_rows) == len(one_row), (
        "GET /admin/orders/ cost {0} queries for one row and {1} for sixteen. "
        "Something on the row serializer is lazy-loading.".format(
            len(one_row), len(sixteen_rows)
        )
    )


def test_the_customer_directory_annotates_rather_than_counting_per_row(
    make_order, days_ago, customer
):
    """
    Order count and lifetime value are annotations on one join. Computed in
    Python they would be a query per customer, which is exactly the shape of
    an admin list that dies at a thousand accounts.
    """
    from apps.accounts.models import Role, User

    for index in range(12):
        shopper = User.objects.create_user(
            email="shopper{0}@example.com".format(index),
            password="Str0ngPass!2026",
            role=Role.CUSTOMER,
        )
        make_order(
            user=shopper, status=OrderStatus.DELIVERED, placed_at=days_ago(index % 5)
        )

    with CaptureQueriesContext(connection) as captured:
        rows = list(customer_services.customer_directory())

    assert len(rows) == 13
    assert len(captured) == 1, (
        "reading {0} customers cost {1} queries".format(len(rows), len(captured))
    )
