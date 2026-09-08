"""
Order reads (PRD 7.2 for the customer surface, 7.3 for the admin one).

Every *customer* queryset here is scoped to an owner *before* the reference is
matched. That ordering is the whole point: filtering by owner first means
another customer's reference simply does not exist for this request, so the
miss surfaces as 404. A 403 would confirm the order is real and leak the
reference space (PRD 10.2).

There are two owners a customer-surface reader can present, and both go
through the same prefetches: a signed-in customer, scoped by `user`
(`get_customer_order`), and a guest, scoped by the email that placed the order
(`get_guest_order`).

The admin readers below are deliberately in this module rather than in
apps/dashboard/: they are order reads, they share the prefetch definitions
with the customer surface, and a second copy of `with_details` is how the two
surfaces start disagreeing about what an order detail contains. The admin
readers are *not* user-scoped -- that is the difference, and it is stated once,
here, instead of being reinvented in a view.
"""
from django.db.models import Prefetch, Q

from apps.common.phone import InvalidPhoneNumber, normalise_phone
from config.exceptions import DomainError

from ..models import Order, OrderItem, OrderStatus, OrderStatusLog, PaymentMethod


def _items_prefetch():
    return Prefetch(
        "items",
        queryset=OrderItem.objects.select_related("variant", "variant__product").order_by("id"),
    )


def with_details(queryset):
    """Everything an order *detail* screen renders, in a constant query count."""
    return queryset.select_related("zone", "coupon", "shipment", "payment", "user").prefetch_related(
        _items_prefetch(),
        Prefetch(
            "status_logs",
            queryset=OrderStatusLog.objects.select_related("actor").order_by("created_at", "id"),
        ),
    )


def with_line_items(queryset):
    """
    The lighter list-row shape: lines, but not the status timeline.

    An order *list* renders a line summary and never the audit trail, so
    prefetching status_logs for every row on the page would be work nobody
    reads.
    """
    return queryset.select_related("zone", "coupon", "shipment", "payment", "user").prefetch_related(
        _items_prefetch()
    )


# ---------------------------------------------------------------------------
# Customer surface (PRD 7.2)
# ---------------------------------------------------------------------------
def customer_orders(user):
    """GET /orders/ -- this customer's orders, newest first."""
    return with_details(Order.objects.filter(user=user)).order_by("-placed_at", "-id")


def get_customer_order(user, reference):
    """GET /orders/{reference}/ -- or a 404-shaped error."""
    order = customer_orders(user).filter(reference=(reference or "").strip()).first()
    if order is None:
        raise DomainError("Not found.", code="NOT_FOUND", status_code=404)
    return order


def guest_orders():
    """
    Orders with no account behind them.

    The `user__isnull=True` filter is the security boundary of the guest read,
    not a convenience: a registered customer's order must never be reachable
    by quoting their email address, because that is an authentication bypass
    on a real account -- the address is the account's identifier, and the
    password is what is supposed to stand between it and a reader.
    """
    return with_details(Order.objects.filter(user__isnull=True))


def get_guest_order(reference, email):
    """
    GET /orders/{reference}/?email= -- the guest read, or a 404-shaped error.

    Why it exists: a guest who completes checkout and is sent to the payment
    gateway comes back on a full navigation from another origin, with no
    session and with the SPA's query cache gone. Without this they cannot see
    the order they just paid for. The shape is the one frozen in
    docs/api-contract-cart-checkout-orders.md.

    The capability is the **pair**. A reference alone is not enough, because a
    reference is short, sequential and printed on every receipt; the email is
    what makes it a secret rather than a guess. Any miss -- unknown reference,
    wrong email, or an order that belongs to an account -- is the same 404
    with the same body, so the endpoint never answers "is this reference
    real?".

    The email is compared case-insensitively, because a shopper who typed
    `Guest@Example.com` at checkout will not retype it identically, but
    *wholly*: Django escapes `%` and `_` when it builds the `iexact` LIKE, so
    no prefix, suffix or wildcard can stand in for the address.
    """
    reference = (reference or "").strip()
    email = (email or "").strip()
    if not reference or not email:
        raise DomainError("Not found.", code="NOT_FOUND", status_code=404)

    order = guest_orders().filter(reference=reference, email__iexact=email).first()
    if order is None:
        raise DomainError("Not found.", code="NOT_FOUND", status_code=404)
    return order


def detail_for_response(order):
    """
    Re-read a just-written order with the detail prefetches attached.

    Deliberately not user-scoped: it is only ever called with an order this
    request just created, including a guest's, which has no user to scope to.
    """
    return with_details(Order.objects.all()).get(pk=order.pk)


def timeline(order):
    """
    The append-only status history, oldest first (FR-ORD-5).

    Rendered as-is: the log is the timeline. Deriving a timeline from the
    current status instead would invent events that never happened.
    """
    return list(order.status_logs.all())


# ---------------------------------------------------------------------------
# Admin surface (PRD 7.3, US-A3, US-T1)
# ---------------------------------------------------------------------------
VALID_STATUSES = frozenset(OrderStatus.values)
VALID_PAYMENT_METHODS = frozenset(PaymentMethod.values)


def _parse_statuses(statuses):
    """
    `?status=packed`, `?status=confirmed&status=packed`, or
    `?status=confirmed,packed` -- a React multi-select produces the second and
    a hand-typed URL the third, and neither caller should have to know which
    the server prefers.
    """
    if not statuses:
        return None
    if isinstance(statuses, str):
        statuses = [statuses]
    cleaned = []
    for entry in statuses:
        cleaned.extend(part.strip().lower() for part in str(entry).split(","))
    cleaned = [value for value in cleaned if value]
    if not cleaned:
        return None
    unknown = [value for value in cleaned if value not in VALID_STATUSES]
    if unknown:
        raise DomainError(
            "Unknown order status: {0}.".format(", ".join(sorted(unknown))),
            code="INVALID_FILTER",
            field="status",
        )
    return cleaned


def _parse_payment_method(payment_method):
    if not payment_method:
        return None
    value = str(payment_method).strip().lower()
    if not value:
        return None
    if value not in VALID_PAYMENT_METHODS:
        raise DomainError(
            "Unknown payment method: {0}.".format(value),
            code="INVALID_FILTER",
            field="payment_method",
        )
    return value


def search_filter(term):
    """
    US-T1: a support agent has a reference, a phone number, or an email.

    US-A3 adds the customer's name. All four are one box, because the person
    on the phone does not know which of them the system considers the key.

    A phone number is normalised before it is matched (`+8801712345678` and
    `01712345678` are the same subscriber, and only one of those forms is
    stored) and then matched *exactly*. The free-text arm stays `icontains`
    so a partial reference still finds the order.
    """
    term = (term or "").strip()
    if not term:
        return None

    condition = (
        Q(reference__icontains=term)
        | Q(email__icontains=term)
        | Q(ship_recipient_name__icontains=term)
        | Q(user__full_name__icontains=term)
        | Q(phone__icontains=term)
        | Q(ship_phone__icontains=term)
    )
    try:
        normalised = normalise_phone(term)
    except InvalidPhoneNumber:
        pass
    else:
        condition |= Q(phone=normalised) | Q(ship_phone=normalised)
    return condition


def admin_orders(
    *,
    statuses=None,
    payment_method=None,
    placed_from=None,
    placed_to=None,
    search=None,
):
    """
    GET /admin/orders/ -- every order, filtered and searched (US-A3).

    `placed_from` / `placed_to` are timezone-aware datetimes computed by the
    caller, not dates: MySQL on this deployment has no timezone tables loaded,
    so a `__date` lookup would emit CONVERT_TZ and quietly compare against
    NULL. Boundaries are worked out in Python, where the local day is known.
    """
    queryset = Order.objects.all()

    parsed_statuses = _parse_statuses(statuses)
    if parsed_statuses:
        queryset = queryset.filter(status__in=parsed_statuses)

    parsed_method = _parse_payment_method(payment_method)
    if parsed_method:
        queryset = queryset.filter(payment_method=parsed_method)

    if placed_from is not None:
        queryset = queryset.filter(placed_at__gte=placed_from)
    if placed_to is not None:
        queryset = queryset.filter(placed_at__lt=placed_to)

    condition = search_filter(search)
    if condition is not None:
        # Every arm of the search is a forward FK or a column on the order, so
        # nothing multiplies rows today. `distinct()` is kept because the
        # obvious next search term is a product name, which joins through
        # items and does.
        queryset = queryset.filter(condition).distinct()

    return with_line_items(queryset).order_by("-placed_at", "-id")


def get_admin_order(reference):
    """
    GET /admin/orders/{reference}/ -- any order, by reference.

    Not user-scoped, and that is the intended difference from
    `get_customer_order`: an admin is allowed to read every order. A reference
    that does not exist is still a 404 rather than an empty 200.
    """
    order = (
        with_details(Order.objects.all())
        .filter(reference=(reference or "").strip())
        .first()
    )
    if order is None:
        raise DomainError("Not found.", code="NOT_FOUND", status_code=404)
    return order
