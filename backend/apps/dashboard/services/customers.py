"""
Customer directory for the admin surface (PRD 7.3 GET /admin/customers/).

Lifetime value uses `metrics.REVENUE_STATUSES` -- the same definition the
dashboard tiles use. That import is the point of the module: two reports
disagreeing about whether a cancelled order counts is exactly the drift the
service layer exists to prevent.

Guest orders carry no user (`Order.user` is nullable for guest checkout), so
they can never be attributed to a row here. `guest_order_count` on the payload
says how many were left out rather than letting the totals quietly not add up.
"""
from django.db.models import Count, Max, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.accounts.models import Role, User
from apps.orders.models import Order

from .metrics import REVENUE_STATUSES, ZERO, money_output_field


def _search_filter(term):
    term = (term or "").strip()
    if not term:
        return None
    return (
        Q(email__icontains=term)
        | Q(full_name__icontains=term)
        | Q(phone__icontains=term)
    )


def customer_directory(*, search=None):
    """
    Every customer with their order count and lifetime value (US-A2/US-A1's
    "customers" tile), highest value first.

    One join, several aggregates over it -- `order_count` and `lifetime_value`
    read the same `orders` relation, so there is no second join to inflate the
    sum. Annotated in the database rather than counted in Python, because the
    page is a list of customers and the alternative is a query per row.
    """
    revenue_only = Q(orders__status__in=REVENUE_STATUSES)

    queryset = User.objects.filter(role=Role.CUSTOMER).annotate(
        order_count=Count("orders", distinct=True),
        paid_order_count=Count("orders", filter=revenue_only, distinct=True),
        lifetime_value=Coalesce(
            Sum("orders__grand_total", filter=revenue_only),
            Value(ZERO),
            output_field=money_output_field(),
        ),
        last_order_at=Max("orders__placed_at"),
    )

    condition = _search_filter(search)
    if condition is not None:
        queryset = queryset.filter(condition)

    return queryset.order_by("-lifetime_value", "-order_count", "id")


def guest_order_count():
    """Orders that belong to nobody in the directory, so the gap is visible."""
    return Order.objects.filter(user__isnull=True).count()
