"""
The customer directory (PRD 7.3 GET /admin/customers/).

"Customers with order count and lifetime value."

Lifetime value shares `metrics.REVENUE_STATUSES` with the dashboard tiles on
purpose, and the test that matters most here is the one that proves it: two
reports disagreeing about whether a cancelled order counts is exactly the
drift the service layer exists to prevent.
"""
from decimal import Decimal

import pytest
from rest_framework import status

from apps.accounts.models import User
from apps.dashboard.services import customers as customer_services
from apps.dashboard.services import metrics as metric_services
from apps.orders.models import OrderStatus

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPass!2026"


def rows_by_email(response):
    return {row["email"]: row for row in response.data["results"]}


def test_the_directory_reports_order_count_and_lifetime_value(
    admin_client, customers_url, customer, make_order, days_ago
):
    make_order(user=customer, status=OrderStatus.DELIVERED, grand_total="1500.00", placed_at=days_ago(2))
    make_order(user=customer, status=OrderStatus.SHIPPED, grand_total="2500.00", placed_at=days_ago(1))

    response = admin_client.get(customers_url)

    row = rows_by_email(response)[customer.email]
    assert response.status_code == status.HTTP_200_OK
    assert row["order_count"] == 2
    assert row["lifetime_value"] == "4000.00"
    assert row["full_name"] == "Rafiq Hasan"


def test_lifetime_value_uses_the_same_revenue_definition_as_the_dashboard(
    admin_client, customers_url, dashboard_url, customer, make_order, days_ago
):
    """
    The one test that ties the two reports together. If someone widens or
    narrows REVENUE_STATUSES, both numbers move -- and if someone gives the
    customer report its own list, this fails.
    """
    make_order(user=customer, status=OrderStatus.DELIVERED, grand_total="1000.00", placed_at=days_ago(1))
    make_order(user=customer, status=OrderStatus.CANCELLED, grand_total="9999.00", placed_at=days_ago(1))
    make_order(user=customer, status=OrderStatus.REFUNDED, grand_total="8888.00", placed_at=days_ago(1))
    make_order(user=customer, status=OrderStatus.PENDING, grand_total="7777.00", placed_at=days_ago(1))

    directory = admin_client.get(customers_url)
    dashboard = admin_client.get(dashboard_url)

    row = rows_by_email(directory)[customer.email]
    assert row["lifetime_value"] == "1000.00"
    assert row["lifetime_value"] == dashboard.data["last_7_days"]["revenue"]


def test_the_order_count_includes_orders_that_earned_nothing(
    admin_client, customers_url, customer, make_order, days_ago
):
    """
    "How many times has this person ordered" and "how much have they spent"
    are different questions. A support agent looking at a serial canceller
    needs to see both, so the payload carries `order_count` beside
    `paid_order_count`.
    """
    make_order(user=customer, status=OrderStatus.DELIVERED, grand_total="1000.00", placed_at=days_ago(1))
    make_order(user=customer, status=OrderStatus.CANCELLED, grand_total="500.00", placed_at=days_ago(1))

    row = rows_by_email(admin_client.get(customers_url))[customer.email]

    assert row["order_count"] == 2
    assert row["paid_order_count"] == 1
    assert row["lifetime_value"] == "1000.00"


def test_a_customer_who_has_never_ordered_is_listed_with_zero_not_omitted(
    admin_client, customers_url, customer
):
    row = rows_by_email(admin_client.get(customers_url))[customer.email]

    assert row["order_count"] == 0
    assert row["lifetime_value"] == "0.00"
    assert row["last_order_at"] is None


def test_the_directory_is_ordered_by_lifetime_value(
    admin_client, customers_url, make_order, days_ago
):
    big = User.objects.create_user(email="big@example.com", password=PASSWORD)
    small = User.objects.create_user(email="small@example.com", password=PASSWORD)
    make_order(user=small, status=OrderStatus.DELIVERED, grand_total="100.00", placed_at=days_ago(1))
    make_order(user=big, status=OrderStatus.DELIVERED, grand_total="90000.00", placed_at=days_ago(1))

    emails = [row["email"] for row in admin_client.get(customers_url).data["results"]]

    assert emails[:2] == ["big@example.com", "small@example.com"]


def test_staff_and_admins_are_not_customers(admin_client, customers_url, admin, staff_member, customer):
    """
    The directory answers "who buys from us". The owner's own account is not
    an entry in it.
    """
    emails = {row["email"] for row in admin_client.get(customers_url).data["results"]}

    assert emails == {customer.email}


def test_a_guest_order_is_not_attributed_to_anybody(
    admin_client, customers_url, customer, make_order, days_ago
):
    """
    Guest checkout is permitted (FR-CHK-5) and leaves `Order.user` null, so
    those orders can never appear against a directory row. `guest_order_count`
    exists so the gap is visible rather than a silent shortfall.
    """
    make_order(user=None, status=OrderStatus.DELIVERED, grand_total="5000.00", placed_at=days_ago(1))
    make_order(user=customer, status=OrderStatus.DELIVERED, grand_total="1000.00", placed_at=days_ago(1))

    row = rows_by_email(admin_client.get(customers_url))[customer.email]

    assert row["lifetime_value"] == "1000.00"
    assert customer_services.guest_order_count() == 1


@pytest.mark.parametrize("term", ["rafiq", "shopper@example.com", "01712345678"])
def test_the_directory_is_searchable_by_name_email_or_phone(
    admin_client, customers_url, customer, term
):
    User.objects.create_user(
        email="other@example.com", password=PASSWORD, full_name="Kamal Uddin"
    )

    response = admin_client.get(customers_url, {"q": term})

    assert [row["email"] for row in response.data["results"]] == [customer.email]


def test_lifetime_value_is_a_decimal_string_never_a_float(
    admin_client, customers_url, customer, make_order, days_ago
):
    make_order(user=customer, status=OrderStatus.DELIVERED, grand_total="1234.56", placed_at=days_ago(1))

    row = rows_by_email(admin_client.get(customers_url))[customer.email]

    assert isinstance(row["lifetime_value"], str)
    assert row["lifetime_value"] == "1234.56"


def test_the_service_returns_decimals_so_arithmetic_stays_exact(
    customer, make_order, days_ago
):
    make_order(user=customer, status=OrderStatus.DELIVERED, grand_total="0.10", placed_at=days_ago(1))
    make_order(user=customer, status=OrderStatus.DELIVERED, grand_total="0.20", placed_at=days_ago(1))

    row = customer_services.customer_directory().get(pk=customer.pk)

    assert type(row.lifetime_value) is Decimal
    assert row.lifetime_value == Decimal("0.30")


def test_the_revenue_definition_is_exported_rather_than_duplicated():
    """A cheap structural check that the two modules share one list object."""
    assert customer_services.REVENUE_STATUSES is metric_services.REVENUE_STATUSES
