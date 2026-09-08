"""
Stock movement.

Every path that moves stock goes through record_movement, because the
append-only InventoryLog is only trustworthy if nothing writes
ProductVariant.stock behind its back. Summing a variant's deltas must
reconcile to its current stock.

The oversell guard lives here too: lock_variants issues SELECT ... FOR UPDATE
in primary-key order. The ordering is not decoration -- two concurrent
checkouts holding overlapping baskets in different orders would deadlock, and
MySQL resolves that by killing one transaction at random.
"""
from collections import OrderedDict

from django.db.models import F, Sum

from config.exceptions import DomainError

from ..models import InventoryLog, InventoryReason, ProductVariant


def lock_variants(variant_ids):
    """
    Lock the given variant rows for the rest of the transaction.

    Returns {id: variant} carrying the freshest stock and price the database
    holds. Re-locking rows this transaction already holds is a no-op, so a
    service that calls this defensively costs nothing.
    """
    ids = sorted({int(value) for value in variant_ids})
    if not ids:
        return OrderedDict()
    rows = (
        ProductVariant.objects.select_for_update()
        .select_related("product")
        .filter(pk__in=ids)
        .order_by("pk")
    )
    return OrderedDict((row.pk, row) for row in rows)


def record_movement(*, variant, delta, reason, actor=None, order=None, note=""):
    """
    Apply one stock delta and write its audit row. Never do one without
    the other.

    Assumes the caller holds the row lock and has already checked sufficiency;
    a negative result is refused here as a last line of defence, before the
    database CHECK (stock >= 0) would refuse it far less legibly.
    """
    delta = int(delta)
    if delta == 0:
        return None

    new_stock = variant.stock + delta
    if new_stock < 0:
        raise DomainError(
            "{0} ({1}) has only {2} left.".format(
                variant.product.name, variant.label, variant.stock
            ),
            code="INSUFFICIENT_STOCK",
            field="items",
        )

    ProductVariant.objects.filter(pk=variant.pk).update(stock=F("stock") + delta)
    variant.stock = new_stock  # keep the in-memory row honest for the caller

    return InventoryLog.objects.create(
        variant=variant,
        delta=delta,
        reason=reason,
        actor=actor if (actor is not None and getattr(actor, "pk", None)) else None,
        order=order,
        note=note[:255],
    )


def quantities_by_variant(order):
    """Total quantity per variant on the order, ignoring deleted variants."""
    totals = {}
    for item in order.items.all():
        if item.variant_id is None:
            # The variant was deleted from the catalogue after purchase. The
            # order line still reads correctly from its snapshot, but there is
            # no stock row left to move.
            continue
        totals[item.variant_id] = totals.get(item.variant_id, 0) + item.quantity
    return totals


# The wire vocabulary for "why can this line not be bought right now".
# docs/api-contract-cart-checkout-orders.md fixes these three strings, and the
# storefront switches on them directly (CartLine.jsx issueText), so they are
# part of the API surface rather than an internal enum.
ISSUE_OUT_OF_STOCK = "out_of_stock"
ISSUE_INSUFFICIENT_STOCK = "insufficient_stock"
ISSUE_UNAVAILABLE = "unavailable"


def is_sellable(variant):
    """
    Is this variant offerable at all today?

    Deactivating a category has to withdraw everything under it, so the whole
    chain is checked -- variant, product, category and the category's parent.
    This is the single definition; the cart and the checkout quote both call
    it so a line cannot be unbuyable in one surface and buyable in the other.
    """
    product = variant.product
    category = product.category
    parent_ok = category.parent is None or category.parent.is_active
    return bool(
        variant.is_active and product.is_active and category.is_active and parent_ok
    )


def availability(variant, quantity):
    """
    `(available_stock, is_available, issue)` for one basket line.

    Read-only: this reports on stock, it never reserves any. Cart-add and
    quoting both ask this question, and neither is allowed to move stock
    (FR-CRT-3) -- reservation happens only at order confirmation.
    """
    if not is_sellable(variant):
        return 0, False, ISSUE_UNAVAILABLE

    stock = max(0, int(variant.stock))
    quantity = int(quantity)
    if stock <= 0:
        return 0, False, ISSUE_OUT_OF_STOCK
    if stock < quantity:
        return stock, False, ISSUE_INSUFFICIENT_STOCK
    return stock, True, None


def assert_stock_available(quantities, locked):
    """
    Re-check availability inside the lock (FR-INV-4).

    `quantities` is {variant_id: qty}; `locked` is the map from lock_variants.
    The first shortfall raises, naming the offending product -- the checkout
    acceptance criterion is that the offending line is named, not merely that
    placement "failed".
    """
    for variant_id, quantity in sorted(quantities.items()):
        variant = locked.get(variant_id)
        if variant is None:
            raise DomainError(
                "An item in your order is no longer available.",
                code="VARIANT_UNAVAILABLE",
                field="items",
            )
        if not variant.is_active or not variant.product.is_active:
            raise DomainError(
                "{0} ({1}) is no longer available.".format(
                    variant.product.name, variant.label
                ),
                code="VARIANT_UNAVAILABLE",
                field="items",
            )
        if variant.stock < quantity:
            raise DomainError(
                "Only {0} left of {1} ({2}). Please reduce the quantity.".format(
                    variant.stock, variant.product.name, variant.label
                ),
                code="INSUFFICIENT_STOCK",
                field="items",
            )


def decrement_for_order(order, *, actor=None):
    """
    Take an order's items out of stock (FR-INV-2) -- on confirmation only,
    never on add-to-cart.

    Locks, re-checks, then applies. Must already be inside transaction.atomic;
    it is called from the order state machine, which is.
    """
    quantities = quantities_by_variant(order)
    locked = lock_variants(quantities)
    assert_stock_available(quantities, locked)

    logs = []
    for variant_id, quantity in sorted(quantities.items()):
        logs.append(
            record_movement(
                variant=locked[variant_id],
                delta=-quantity,
                reason=InventoryReason.ORDER_CONFIRMED,
                actor=actor,
                order=order,
                note="Order {0} confirmed".format(order.reference),
            )
        )
    return logs


def restore_for_order(order, *, actor=None):
    """
    Put an order's items back (FR-INV-3). The exact inverse of
    decrement_for_order, and deliberately in the same module -- a restore path
    that drifted from the decrement path is how phantom stock appears.
    """
    quantities = quantities_by_variant(order)
    locked = lock_variants(quantities)

    logs = []
    for variant_id, quantity in sorted(quantities.items()):
        variant = locked.get(variant_id)
        if variant is None:  # pragma: no cover -- variant deleted post-purchase
            continue
        logs.append(
            record_movement(
                variant=variant,
                delta=quantity,
                reason=InventoryReason.ORDER_CANCELLED,
                actor=actor,
                order=order,
                note="Order {0} cancelled".format(order.reference),
            )
        )
    return logs


def adjust_stock(*, variant, delta, reason, actor=None, note=""):
    """
    Manual adjustment with a mandatory reason (FR-INV-8). The admin surface in
    week 5 calls this; it lives here so it cannot grow a second copy.
    """
    if not reason:
        raise DomainError(
            "A reason is required for a manual stock adjustment.",
            code="REASON_REQUIRED",
            field="reason",
        )
    locked = lock_variants([variant.pk])
    return record_movement(
        variant=locked[variant.pk],
        delta=delta,
        reason=reason,
        actor=actor,
        note=note,
    )


def low_stock_variants():
    """
    Active variants at or below their own threshold (FR-INV-6, FR-INV-7).

    Zero-stock variants are included: "at or below" is the wording, and a
    variant that has already run out is the most urgent line in the digest.
    """
    return (
        ProductVariant.objects.filter(
            is_active=True,
            product__is_active=True,
            stock__lte=F("low_stock_threshold"),
        )
        .select_related("product", "product__brand")
        .order_by("stock", "product__name", "id")
    )


def logged_stock(variant):
    """Sum of a variant's logged deltas -- must reconcile to variant.stock."""
    total = InventoryLog.objects.filter(variant=variant).aggregate(total=Sum("delta"))
    return total["total"] or 0
