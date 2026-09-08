"""
Transactional order email (FR-ORD-6).

Sent inline -- there is no Celery, no Redis and no job queue in v1, which is a
deliberate scope decision, not an oversight. Two consequences are designed for
rather than hoped away:

1. **Every send is scheduled with transaction.on_commit.** An email announcing
   an order that was rolled back is worse than no email, and SMTP latency
   inside an open transaction would hold the variant row locks that the
   oversell guard depends on.
2. **fail_silently is on.** A refused mail server must never turn a paid,
   stock-decremented order into a 500. The failure is logged instead.

Templates live in backend/templates/email/. Plain text only: an order
confirmation is a receipt, and a receipt that renders in every mail client
beats one that looks nice in three of them.
"""
import logging

from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string, select_template

from apps.dashboard.models import StoreSettings

from ..models import OrderStatus

logger = logging.getLogger(__name__)

STATUS_SUBJECTS = {
    OrderStatus.PENDING: "Order {reference} received",
    OrderStatus.CONFIRMED: "Order {reference} confirmed",
    OrderStatus.PACKED: "Order {reference} is being packed",
    OrderStatus.SHIPPED: "Order {reference} has shipped",
    OrderStatus.DELIVERED: "Order {reference} delivered",
    OrderStatus.CANCELLED: "Order {reference} cancelled",
    OrderStatus.REFUNDED: "Order {reference} refunded",
}


def _context(order, **extra):
    store = StoreSettings.load()
    context = {
        "order": order,
        "items": list(order.items.all()),
        "store": store,
        "currency_symbol": django_settings.CURRENCY_SYMBOL,
        "order_url": "{0}/orders/{1}".format(
            django_settings.FRONTEND_BASE_URL.rstrip("/"), order.reference
        ),
        "shipment": getattr(order, "shipment", None),
    }
    context.update(extra)
    return context


def _dispatch(*, subject, body, recipient):
    if not recipient:
        return False
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=True,
        )
    except Exception:  # pragma: no cover -- fail_silently already swallows SMTP
        logger.exception("Order email could not be sent to %s", recipient)
        return False
    return True


def send_order_placed(order):
    """
    The placement receipt. For a COD order this is also the confirmation --
    placement and confirmation are the same instant, and two emails one second
    apart reads as a bug to the customer.
    """
    body = render_to_string("email/order_placed.txt", _context(order))
    subject = STATUS_SUBJECTS.get(order.status, "Order {reference} update").format(
        reference=order.reference
    )
    transaction.on_commit(
        lambda: _dispatch(subject=subject, body=body, recipient=order.email)
    )


def send_status_change(order, *, from_status, note=""):
    """One email per legal transition (FR-ORD-6)."""
    template = select_template(
        [
            "email/order_status_{0}.txt".format(order.status),
            "email/order_status_changed.txt",
        ]
    )
    body = template.render(
        _context(order, from_status=from_status, note=note, status=order.status)
    )
    subject = STATUS_SUBJECTS.get(order.status, "Order {reference} update").format(
        reference=order.reference
    )
    transaction.on_commit(
        lambda: _dispatch(subject=subject, body=body, recipient=order.email)
    )


def send_low_stock_digest(*, variants, recipients):
    """
    FR-INV-7. Called by the cron-invoked management command, never by a
    request, so it sends immediately rather than on commit.
    """
    if not recipients:
        return 0
    store = StoreSettings.load()
    body = render_to_string(
        "email/low_stock_digest.txt",
        {
            "variants": variants,
            "store": store,
            "count": len(variants),
            "currency_symbol": django_settings.CURRENCY_SYMBOL,
            "admin_url": "{0}/admin/inventory".format(
                django_settings.FRONTEND_BASE_URL.rstrip("/")
            ),
        },
    )
    subject = "[{0}] {1} variant(s) at or below the low-stock threshold".format(
        store.store_name, len(variants)
    )
    sent = 0
    for recipient in recipients:
        if _dispatch(subject=subject, body=body, recipient=recipient):
            sent += 1
    return sent
