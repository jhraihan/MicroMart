"""
Order placement, the status state machine, and cancellation.

Four rules are absolute:

1. Placement is one transaction. Variant rows are locked with
   SELECT ... FOR UPDATE in primary-key order, stock is re-checked inside the
   lock, and totals are recomputed from the locked rows -- so the price
   charged is the price at the instant of sale.
2. Stock moves only on confirmation. Cash on Delivery confirms at placement;
   an online order stays pending until the gateway validates the payment.
3. Everything is snapshotted -- name, variant label, SKU, unit price, the
   shipping address and the tax rate are copied onto the order, so a later
   catalogue or address edit cannot rewrite history.
4. Idempotency is enforced by the unique idempotency_key column. The
   read-before-write below is only the fast path; the IntegrityError branch is
   what survives two simultaneous requests.

transition_order is the only function permitted to write Order.status. It
consults TRANSITIONS and refuses anything absent from it with 422, without
logging -- an illegal transition is not an event that happened.
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.services import addresses as address_services
from apps.cart.services import cart as cart_services
from apps.catalog.services import inventory as inventory_services
from apps.common.phone import InvalidPhoneNumber, normalise_phone
from apps.promotions.services import coupons as coupon_services
from config.exceptions import DomainError

from ..models import (
    TRANSITIONS,
    Actor,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusLog,
    PaymentMethod,
    Shipment,
)
from . import checkout as checkout_services
from . import notifications
from . import totals as totals_services

REFERENCE_PREFIX = "ORD"
REFERENCE_ATTEMPTS = 5

# Retries for a placement lost to a unique-key race (reference or idempotency
# key). Three is generous: each retry re-reads the highest reference issued.
PLACEMENT_ATTEMPTS = 3

# Cancelling at or before packing releases the coupon so the customer can use
# it again (FR-CPN-8). A shipped order that later fails delivery does not --
# the promotion was consumed on merchandise that left the building.
COUPON_RELEASING_STATUSES = frozenset(
    {OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PACKED}
)

ADDRESS_FIELDS = (
    "recipient_name",
    "phone",
    "division",
    "district",
    "upazila",
    "area",
    "street",
    "postcode",
)
REQUIRED_ADDRESS_FIELDS = ("recipient_name", "phone", "division", "district", "street")


# ---------------------------------------------------------------------------
# Reference numbers (FR-ORD-1)
# ---------------------------------------------------------------------------
def next_reference(now=None):
    """
    Human-readable, year-scoped: ORD-2026-000148.

    Derived from the highest reference already issued this year rather than
    from a row count, so deleting a row can never hand out a reference twice.

    The read is a *locking* one, and that is load-bearing. Django runs MySQL at
    READ COMMITTED, so a plain SELECT here is perfectly current -- and still
    wrong, because being current is not the same as being exclusive. Nothing
    stopped twenty simultaneous checkouts from reading the same highest
    reference in the same instant and every one of them computing the same
    successor. Only one INSERT can win the unique index; the rest raise
    IntegrityError, and once PLACEMENT_ATTEMPTS is exhausted that reaches the
    customer as a 500. Measured on the original code, 24 simultaneous
    checkouts of 24 *different* products produced 3 orders and 21 crashes,
    on every run -- orders touching different variants share no variant lock,
    so nothing else was serialising them.

    SELECT ... FOR UPDATE takes an exclusive lock on the row it reads, so the
    read and the INSERT that follows it become one indivisible step for as
    long as there is a row to lock. It is taken last -- after the variant
    locks and the coupon lock -- so every placement acquires locks in the same
    order and no cycle can form.

    Pinned by apps/orders/tests/test_oversell_concurrency.py.
    """
    now = now or timezone.now()
    prefix = "{0}-{1}-".format(REFERENCE_PREFIX, now.year)
    issued = Order.objects.filter(reference__startswith=prefix)
    if transaction.get_connection().in_atomic_block:
        # Outside a transaction a row lock is neither permitted nor meaningful.
        # A read-only caller -- a shell, a report -- still gets a true answer.
        issued = issued.select_for_update()
    last = issued.order_by("-reference").values_list("reference", flat=True).first()
    sequence = 1
    if last:
        try:
            sequence = int(last.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):  # pragma: no cover -- hand-edited data
            sequence = Order.objects.filter(reference__startswith=prefix).count() + 1
    return "{0}{1:06d}".format(prefix, sequence)


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------
def _clean_address(address):
    """Validate and normalise the shipping address copied onto the order."""
    address = dict(address or {})
    cleaned = {key: str(address.get(key) or "").strip() for key in ADDRESS_FIELDS}

    for key in REQUIRED_ADDRESS_FIELDS:
        if not cleaned[key]:
            raise DomainError(
                "This field is required.",
                code="ADDRESS_INCOMPLETE",
                field="shipping_address.{0}".format(key),
                status_code=400,
            )

    try:
        cleaned["phone"] = normalise_phone(cleaned["phone"])
    except InvalidPhoneNumber as exc:
        raise DomainError(
            str(exc),
            code="INVALID_PHONE",
            field="shipping_address.phone",
            status_code=400,
        )
    return cleaned


def _address_from_book(user, address_id):
    """
    FR-CHK-4: check out against a saved address.

    Scoped to the requesting user, so another customer's address id is a 404 --
    never a 403, which would confirm the row exists.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        raise DomainError(
            "Sign in to use a saved address.",
            code="NOT_FOUND",
            field="address_id",
            status_code=404,
        )
    address = user.addresses.filter(pk=address_id).first()
    if address is None:
        raise DomainError(
            "Not found.", code="NOT_FOUND", field="address_id", status_code=404
        )
    return {key: getattr(address, key, "") or "" for key in ADDRESS_FIELDS}


def _contact(*, user, email, phone, address):
    """
    Where the receipt goes. A signed-in customer's account email wins over
    anything typed into the form -- otherwise an order could be attached to one
    account while its notifications went somewhere else entirely.
    """
    if user is not None and getattr(user, "is_authenticated", False):
        email = user.email
    email = (email or "").strip().lower()
    if not email:
        raise DomainError(
            "An email address is required so we can send your receipt.",
            code="EMAIL_REQUIRED",
            field="email",
            status_code=400,
        )

    phone = (phone or "").strip() or address["phone"]
    try:
        phone = normalise_phone(phone)
    except InvalidPhoneNumber as exc:
        raise DomainError(str(exc), code="INVALID_PHONE", field="phone", status_code=400)
    return email, phone


def _existing_for_key(idempotency_key, *, user, email):
    """
    FR-CHK-7: the same key returns the same order.

    Ownership is re-checked before handing the order back. A key is a client
    secret, but it is short and guessable enough that returning someone else's
    order for a colliding key would be an object-level authorisation hole.
    """
    existing = Order.objects.filter(idempotency_key=idempotency_key).first()
    if existing is None:
        return None

    if user is not None and getattr(user, "is_authenticated", False):
        owns = existing.user_id == user.pk
    else:
        owns = existing.user_id is None and existing.email == (email or "").strip().lower()

    if not owns:
        raise DomainError(
            "That idempotency key belongs to a different order.",
            code="IDEMPOTENCY_KEY_CONFLICT",
            field="idempotency_key",
            status_code=409,
        )
    return existing


def place_order(
    *,
    idempotency_key,
    payment_method,
    shipping_address,
    user=None,
    email="",
    phone="",
    items=None,
    coupon_code=None,
    note="",
    cart=None,
    address_id=None,
    save_address=False,
):
    """
    Create an order from a basket. Returns (order, created).

    COD orders are confirmed here and decrement stock. Online orders are left
    pending with stock untouched; apps/payments confirms them once the gateway
    validates the transaction (week 4).
    """
    key = (idempotency_key or "").strip()
    if not key:
        raise DomainError(
            "An idempotency key is required to place an order.",
            code="IDEMPOTENCY_KEY_REQUIRED",
            field="idempotency_key",
            status_code=400,
        )

    if address_id:
        shipping_address = _address_from_book(user, address_id)
        save_address = False  # it is already in the book

    address = _clean_address(shipping_address)
    contact_email, contact_phone = _contact(
        user=user, email=email, phone=phone, address=address
    )

    existing = _existing_for_key(key, user=user, email=contact_email)
    if existing is not None:
        return existing, False

    for attempt in range(PLACEMENT_ATTEMPTS):
        try:
            with transaction.atomic():
                order = _create_order(
                    key=key,
                    payment_method=payment_method,
                    address=address,
                    user=user,
                    email=contact_email,
                    phone=contact_phone,
                    items=items,
                    coupon_code=coupon_code,
                    note=note,
                    cart=cart,
                    save_address=save_address,
                )
            return order, True
        except IntegrityError:
            # Either two requests raced on the unique idempotency_key -- in
            # which case the loser reports the winner's order, which is exactly
            # what the customer wants -- or two placements picked the same
            # reference, which is worth one more attempt.
            existing = _existing_for_key(key, user=user, email=contact_email)
            if existing is not None:
                return existing, False
            if attempt == PLACEMENT_ATTEMPTS - 1:
                raise


def _create_order(
    *,
    key,
    payment_method,
    address,
    user,
    email,
    phone,
    items,
    coupon_code,
    note,
    cart,
    save_address=False,
):
    """The transactional body of place_order. Never call it directly."""
    lines, source_cart = checkout_services.resolve_basket(
        user=user, items=items, cart=cart
    )

    # --- Lock, then re-read. Everything after this point prices from rows this
    # transaction holds, so a concurrent checkout cannot move them underneath.
    locked = inventory_services.lock_variants([line.variant.pk for line in lines])
    quantities = {}
    for line in lines:
        quantities[line.variant.pk] = quantities.get(line.variant.pk, 0) + line.quantity
    inventory_services.assert_stock_available(quantities, locked)

    priced_lines = [
        totals_services.build_line(locked[variant_id], quantity)
        for variant_id, quantity in sorted(quantities.items())
    ]

    totals = totals_services.compute_totals(
        lines=priced_lines,
        district=address["district"],
        coupon_code=coupon_code,
        user=user,
        lock_coupon=True,
    )
    checkout_services.assert_payment_method_allowed(totals, payment_method)

    order = Order.objects.create(
        reference=_reserve_reference(),
        user=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
        email=email,
        phone=phone,
        ship_recipient_name=address["recipient_name"],
        ship_phone=address["phone"],
        ship_division=address["division"],
        ship_district=address["district"],
        ship_upazila=address["upazila"],
        ship_area=address["area"],
        ship_street=address["street"],
        ship_postcode=address["postcode"],
        zone=totals.zone,
        coupon=totals.coupon,
        subtotal=totals.subtotal,
        discount_total=totals.discount_total,
        shipping_total=totals.shipping_total,
        tax_total=totals.tax_total,
        tax_rate_applied=totals.tax_rate,
        grand_total=totals.grand_total,
        payment_method=payment_method,
        status=OrderStatus.PENDING,
        note=(note or "").strip(),
        idempotency_key=key,
    )

    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                variant=line.variant,
                product_name=line.product_name,
                variant_label=line.variant_label,
                sku=line.sku,
                unit_price=line.unit_price,
                quantity=line.quantity,
                line_total=line.line_total,
            )
            for line in totals.lines
        ]
    )

    # Order creation is not a transition -- there is no previous status -- but
    # the timeline needs somewhere to start, so it is logged with a blank
    # from_status.
    OrderStatusLog.objects.create(
        order=order,
        from_status="",
        to_status=OrderStatus.PENDING,
        actor=order.user,
        actor_role=Actor.CUSTOMER,
        note="Order placed",
    )

    if totals.coupon is not None:
        coupon_services.record_redemption(
            coupon=totals.coupon,
            user=user,
            order=order,
            discount_amount=totals.discount_total,
        )

    if payment_method == PaymentMethod.COD:
        # COD confirms immediately: the sale is agreed, so the stock is spoken
        # for. The placement email doubles as the confirmation email, so this
        # transition stays quiet.
        order = transition_order(
            order=order,
            to_status=OrderStatus.CONFIRMED,
            actor=order.user,
            actor_role=Actor.SYSTEM,
            note="Cash on Delivery order placed",
            notify=False,
        )

    if save_address and order.user_id:
        # FR-CHK-4, opt-in. Inside the transaction, so an order that rolls back
        # does not leave a stray address behind.
        address_services.create_address(
            user=order.user, **{key: address[key] for key in ADDRESS_FIELDS}
        )

    if source_cart is not None:
        cart_services.clear_cart(source_cart)

    notifications.send_order_placed(order)
    return order


def _reserve_reference():
    """
    A reference nobody else holds. The unique index is the real guarantee;
    this loop just keeps the common case off the error path.

    next_reference()'s row lock serialises allocation for as long as there is
    a row to lock, but it is a fast path rather than a proof. Two edges remain:
    the first order of a fresh year has no row to lock at all, and an index
    scan that had already positioned itself before it blocked does not go back
    for rows inserted while it waited. Both leave two placements holding the
    same candidate.

    So running out of attempts returns the last candidate instead of raising.
    A busy minute is not a business reason to refuse a customer's order, and
    the failure mode was self-inflicted: a hard refusal here bypassed
    place_order's IntegrityError retry -- the mechanism built for exactly this
    -- and turned recoverable contention into a permanent 422. Let the unique
    index arbitrate; the loser retries on a fresh transaction that reads the
    sequence again.
    """
    reference = next_reference()
    for _ in range(REFERENCE_ATTEMPTS - 1):
        if not Order.objects.filter(reference=reference).exists():
            return reference
        reference = next_reference()
    return reference


# ---------------------------------------------------------------------------
# State machine (PRD 15.1)
# ---------------------------------------------------------------------------
@transaction.atomic
def transition_order(
    *, order, to_status, actor=None, actor_role=Actor.ADMIN, note="", notify=True
):
    """
    The only function permitted to write Order.status.

    Illegal transitions are rejected with 422 and are not logged. An actor
    without the right to make an otherwise-legal transition gets 403 -- that is
    a permissions answer, not a state answer.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    from_status = order.status

    rule = TRANSITIONS.get((from_status, to_status))
    if rule is None:
        raise DomainError(
            "An order that is {0} cannot become {1}.".format(from_status, to_status),
            code="ILLEGAL_STATUS_TRANSITION",
            field="status",
        )

    if actor_role not in rule["actors"]:
        raise DomainError(
            "You are not allowed to make that change.",
            code="TRANSITION_NOT_PERMITTED",
            field="status",
            status_code=403,
        )

    if rule.get("requires_shipment") and not Shipment.objects.filter(order=order).exists():
        raise DomainError(
            "Add a courier and tracking number before marking the order shipped.",
            code="SHIPMENT_REQUIRED",
            field="shipment",
        )

    if rule["stock"] == "decrement":
        inventory_services.decrement_for_order(order, actor=actor)
    elif rule["stock"] == "restore":
        inventory_services.restore_for_order(order, actor=actor)

    if to_status == OrderStatus.CANCELLED and from_status in COUPON_RELEASING_STATUSES:
        coupon_services.release_redemption(order)

    order.status = to_status
    order.save(update_fields=["status", "updated_at"])
    _stamp_shipment(order, to_status)

    OrderStatusLog.objects.create(
        order=order,
        from_status=from_status,
        to_status=to_status,
        actor=actor if (actor is not None and getattr(actor, "pk", None)) else None,
        actor_role=actor_role,
        note=(note or "")[:255],
    )

    if notify:
        notifications.send_status_change(order, from_status=from_status, note=note)
    return order


def confirm_order(order, *, actor=None, actor_role=Actor.SYSTEM, note=""):
    """
    pending -> confirmed. Decrements stock (FR-INV-2).

    Called by COD placement above and, from week 4, by the payment IPN handler
    once SSLCommerz's validation API confirms the money. Both surfaces confirm
    an order the same way because both call this.
    """
    return transition_order(
        order=order,
        to_status=OrderStatus.CONFIRMED,
        actor=actor,
        actor_role=actor_role,
        note=note or "Payment confirmed",
    )


def cancel_order(order, *, actor=None, actor_role=Actor.CUSTOMER, reason=""):
    """
    Cancel an order, restoring stock where it was previously taken (FR-ORD-4).

    The transition table decides whether this is legal for this actor from this
    status -- a customer reaching for a shipped order is refused there, not by
    a duplicate rule here.
    """
    return transition_order(
        order=order,
        to_status=OrderStatus.CANCELLED,
        actor=actor,
        actor_role=actor_role,
        note=reason or "Cancelled",
    )


# ---------------------------------------------------------------------------
# Shipments (FR-ORD-7, PRD 15.1 packed -> shipped)
# ---------------------------------------------------------------------------
# A shipment may be attached, or corrected, while the order is somewhere it
# could plausibly be dispatched from. A pending order has not been paid for or
# accepted yet, and a cancelled or refunded one is going nowhere -- attaching a
# courier to either records a dispatch that did not happen.
SHIPPABLE_STATUSES = frozenset(
    {
        OrderStatus.CONFIRMED,
        OrderStatus.PACKED,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
    }
)


def _stamp_shipment(order, to_status):
    """
    Record *when* the parcel moved, on the transition that moved it.

    Only ever fills a blank: a correction to the courier or tracking number
    after the fact must not rewrite the moment the order actually shipped.
    """
    if to_status not in (OrderStatus.SHIPPED, OrderStatus.DELIVERED):
        return
    shipment = Shipment.objects.filter(order=order).first()
    if shipment is None:
        return

    field = "shipped_at" if to_status == OrderStatus.SHIPPED else "delivered_at"
    if getattr(shipment, field) is None:
        setattr(shipment, field, timezone.now())
        shipment.save(update_fields=[field, "updated_at"])


@transaction.atomic
def record_shipment(*, order, courier_name, tracking_number):
    """
    POST /admin/orders/{reference}/shipment/ -- attach the courier and the
    tracking number (FR-ORD-7).

    Returns the Shipment. This is a prerequisite for `packed -> shipped`, not
    the transition itself: TRANSITIONS marks that pair `requires_shipment`, so
    an admin who marks an order shipped without doing this first is refused by
    the state machine with SHIPMENT_REQUIRED. Keeping the two steps separate is
    what lets the refusal be about the missing record rather than about a
    half-built request body.

    Both fields are mandatory and non-blank. A tracking number nobody can
    track is worse than none at all -- it tells the customer the parcel is
    findable when it is not.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)

    courier_name = (courier_name or "").strip()
    tracking_number = (tracking_number or "").strip()
    for value, field in ((courier_name, "courier_name"), (tracking_number, "tracking_number")):
        if not value:
            raise DomainError(
                "This field is required.",
                code="SHIPMENT_INCOMPLETE",
                field=field,
                status_code=400,
            )

    if order.status not in SHIPPABLE_STATUSES:
        raise DomainError(
            "An order that is {0} cannot be given a courier and tracking number.".format(
                order.status
            ),
            code="SHIPMENT_NOT_ALLOWED",
            field="shipment",
        )

    shipment, _created = Shipment.objects.update_or_create(
        order=order,
        defaults={"courier_name": courier_name, "tracking_number": tracking_number},
    )
    # Attaching a courier to an order that is already shipped is a correction,
    # and a correction still needs a dispatch time if it never got one.
    _stamp_shipment(order, order.status)
    return shipment
