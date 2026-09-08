"""
Server-side cart.

The rule this module protects: adding to a cart never reserves stock. Nothing
here writes ProductVariant.stock or an InventoryLog row. Quantities are
clamped to what is on hand so the customer is not surprised at checkout, but
that clamp holds nothing back -- stock moves only on order confirmation.

Availability is re-derived on every read. A cart is a wish, not a promise, so
a line that went inactive is reported with a notice rather than silently
deleted.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.catalog.models import ProductVariant
from apps.catalog.services import catalogue
from apps.catalog.services import inventory as inventory_services
from apps.common.fields import quantize_money
from apps.orders.services import totals as totals_services
from config.exceptions import DomainError

from ..models import Cart, CartItem

ZERO = Decimal("0.00")

# Notice codes. Stable, safe to branch on.
#
# Separate from a line's `issue`: a notice says what changed since the customer
# last looked, an issue describes the line right now.
NOTICE_QUANTITY_CLAMPED = "QUANTITY_CLAMPED"
NOTICE_ITEM_UNAVAILABLE = "ITEM_UNAVAILABLE"
NOTICE_ITEM_OUT_OF_STOCK = "ITEM_OUT_OF_STOCK"


@dataclass
class CartLine:
    """One cart row plus everything the storefront needs to render it."""

    item: CartItem
    variant: object
    available_stock: int
    is_available: bool
    issue: str = None
    line: object = None  # totals.BasketLine when the line is purchasable

    @property
    def quantity(self):
        """What the cart row says. The clamped figure is effective_quantity."""
        return self.item.quantity

    @property
    def effective_quantity(self):
        """What can actually be bought right now -- quantity, trimmed to stock."""
        return self.line.quantity if self.line is not None else self.item.quantity

    @property
    def unit_price(self):
        return Decimal(self.variant.price)

    @property
    def line_total(self):
        return quantize_money(self.unit_price * self.effective_quantity)


@dataclass
class CartView:
    cart: Cart
    lines: list
    notices: list = field(default_factory=list)

    @property
    def item_count(self):
        return sum(line.effective_quantity for line in self.lines if line.is_available)

    @property
    def subtotal(self):
        return quantize_money(
            sum((line.line_total for line in self.lines if line.is_available), ZERO)
        )

    @property
    def purchasable_lines(self):
        return [line.line for line in self.lines if line.is_available]


def get_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def _items(cart):
    return (
        cart.items.select_related(
            "variant",
            "variant__product",
            "variant__product__brand",
            # inventory.is_sellable() walks product -> category -> parent for
            # every line. Without these two the availability check costs an
            # extra pair of queries per cart line.
            "variant__product__category",
            "variant__product__category__parent",
        )
        .prefetch_related("variant__images", "variant__product__images")
        .order_by("-created_at", "-id")
    )


def _notice(code, message, *, item_id=None, variant_id=None):
    return {
        "code": code,
        "message": message,
        "item_id": item_id,
        "variant_id": variant_id,
    }


def _is_purchasable(variant):
    # One definition, in the catalogue's inventory service, so the cart and
    # the checkout quote cannot disagree about what is sellable.
    return inventory_services.is_sellable(variant)


def read_cart(cart):
    """
    Current cart with availability re-checked (FR-CRT-5).

    Unavailable lines are kept in the payload and excluded from the subtotal --
    they are shown struck through, not quietly dropped.
    """
    lines, notices = [], []
    for item in _items(cart):
        variant = item.variant
        purchasable = _is_purchasable(variant)
        stock = max(0, variant.stock)

        if not purchasable:
            lines.append(
                CartLine(
                    item=item,
                    variant=variant,
                    available_stock=0,
                    is_available=False,
                    issue=inventory_services.ISSUE_UNAVAILABLE,
                )
            )
            notices.append(
                _notice(
                    NOTICE_ITEM_UNAVAILABLE,
                    "{0} is no longer available and was not counted in your total.".format(
                        variant.product.name
                    ),
                    item_id=item.pk,
                    variant_id=variant.pk,
                )
            )
            continue

        if stock <= 0:
            lines.append(
                CartLine(
                    item=item,
                    variant=variant,
                    available_stock=0,
                    is_available=False,
                    issue=inventory_services.ISSUE_OUT_OF_STOCK,
                )
            )
            notices.append(
                _notice(
                    NOTICE_ITEM_OUT_OF_STOCK,
                    "{0} ({1}) is out of stock.".format(
                        variant.product.name, variant.label
                    ),
                    item_id=item.pk,
                    variant_id=variant.pk,
                )
            )
            continue

        if item.quantity > stock:
            notices.append(
                _notice(
                    NOTICE_QUANTITY_CLAMPED,
                    "Only {0} left of {1} ({2}).".format(
                        stock, variant.product.name, variant.label
                    ),
                    item_id=item.pk,
                    variant_id=variant.pk,
                )
            )

        lines.append(
            CartLine(
                item=item,
                variant=variant,
                available_stock=stock,
                is_available=True,
                issue=(
                    inventory_services.ISSUE_INSUFFICIENT_STOCK
                    if item.quantity > stock
                    else None
                ),
                line=totals_services.build_line(variant, min(item.quantity, stock)),
            )
        )

    return CartView(cart=cart, lines=lines, notices=notices)


def resolve_variant(variant_id):
    """A purchasable variant, or a 404-shaped error. Never a 403."""
    try:
        return catalogue.purchasable_variants().get(pk=variant_id)
    except (ProductVariant.DoesNotExist, ValueError, TypeError):
        raise DomainError(
            "That product is not available.",
            code="VARIANT_NOT_FOUND",
            field="variant_id",
            status_code=404,
        )


def _clamp(variant, quantity):
    """
    Trim a requested quantity to what exists, and say so.

    Returns (quantity, notice_or_None). Clamping reserves nothing -- it only
    stops the cart from displaying a quantity that could never be fulfilled.
    """
    stock = max(0, variant.stock)
    if stock <= 0:
        raise DomainError(
            "{0} ({1}) is out of stock.".format(variant.product.name, variant.label),
            code="OUT_OF_STOCK",
            field="variant_id",
        )

    ceiling = min(stock, totals_services.MAX_LINE_QUANTITY)
    if quantity > ceiling:
        return ceiling, _notice(
            NOTICE_QUANTITY_CLAMPED,
            "Only {0} left of {1} ({2}), so the quantity was adjusted.".format(
                stock, variant.product.name, variant.label
            ),
            variant_id=variant.pk,
        )
    return quantity, None


@transaction.atomic
def add_item(*, cart, variant_id, quantity=1):
    """
    Add a variant, summing with any line the cart already holds for it
    (FR-CRT-3). Adds nothing to inventory's ledger -- see the module docstring.
    """
    quantity = _positive_quantity(quantity)
    variant = resolve_variant(variant_id)

    item = cart.items.filter(variant=variant).first()
    requested = quantity + (item.quantity if item else 0)
    final_quantity, notice = _clamp(variant, requested)

    if item is None:
        item = CartItem.objects.create(
            cart=cart, variant=variant, quantity=final_quantity
        )
    else:
        item.quantity = final_quantity
        item.save(update_fields=["quantity", "updated_at"])

    cart.save(update_fields=["updated_at"])
    view = read_cart(cart)
    if notice:
        view.notices.insert(0, dict(notice, item_id=item.pk))
    return view


@transaction.atomic
def update_item(*, cart, item_id, quantity):
    """Change a line's quantity. Removal is DELETE, not quantity 0."""
    quantity = _positive_quantity(quantity)
    item = _get_item(cart, item_id)
    final_quantity, notice = _clamp(item.variant, quantity)

    item.quantity = final_quantity
    item.save(update_fields=["quantity", "updated_at"])
    cart.save(update_fields=["updated_at"])

    view = read_cart(cart)
    if notice:
        view.notices.insert(0, dict(notice, item_id=item.pk))
    return view


@transaction.atomic
def remove_item(*, cart, item_id):
    _get_item(cart, item_id).delete()
    cart.save(update_fields=["updated_at"])
    return read_cart(cart)


@transaction.atomic
def merge_guest_cart(*, cart, items):
    """
    FR-CRT-2: on login the guest cart merges in, quantities sum, and any line
    over available stock is clamped with a visible notice.

    Unavailable variants are reported and skipped rather than failing the whole
    merge -- losing a whole cart because one line went inactive is a worse
    outcome than losing the line.
    """
    notices = []
    for entry in items or []:
        variant_id = entry.get("variant_id")
        quantity = entry.get("quantity", 1)
        try:
            quantity = _positive_quantity(quantity)
            variant = resolve_variant(variant_id)
            existing = cart.items.filter(variant=variant).first()
            requested = quantity + (existing.quantity if existing else 0)
            final_quantity, notice = _clamp(variant, requested)
        except DomainError as exc:
            notices.append(
                _notice(exc.code, exc.message, variant_id=_as_int(variant_id))
            )
            continue

        if existing is None:
            existing = CartItem.objects.create(
                cart=cart, variant=variant, quantity=final_quantity
            )
        else:
            existing.quantity = final_quantity
            existing.save(update_fields=["quantity", "updated_at"])

        if notice:
            notices.append(dict(notice, item_id=existing.pk))

    cart.save(update_fields=["updated_at"])
    view = read_cart(cart)
    view.notices = notices + view.notices
    return view


@transaction.atomic
def clear_cart(cart):
    """Emptied once an order is placed from it."""
    cart.items.all().delete()
    cart.save(update_fields=["updated_at"])
    return cart


def lines_from_items(items):
    """
    Priced lines for an arbitrary [{variant_id, quantity}] payload.

    This is how a guest checkout is priced: the browser holds the cart, so the
    server takes the ids and quantities and prices them itself. Nothing but the
    variant id and the quantity is read from the client.
    """
    pairs = []
    seen = {}
    for entry in items or []:
        variant = resolve_variant(entry.get("variant_id"))
        quantity = _positive_quantity(entry.get("quantity", 1))
        # A payload naming the same variant twice is one line, not two.
        if variant.pk in seen:
            seen[variant.pk] += quantity
        else:
            seen[variant.pk] = quantity
            pairs.append(variant)

    return [
        totals_services.build_line(variant, seen[variant.pk]) for variant in pairs
    ]


def _get_item(cart, item_id):
    """
    Scoped to this cart, so another customer's line is 404 and never 403 --
    a 403 would confirm the row exists (PRD 10.2).
    """
    item = (
        cart.items.select_related("variant", "variant__product", "variant__product__category")
        .filter(pk=_as_int(item_id))
        .first()
    )
    if item is None:
        raise DomainError(
            "Not found.", code="NOT_FOUND", field=None, status_code=404
        )
    return item


def _positive_quantity(quantity):
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise DomainError(
            "Quantity must be a whole number.",
            code="INVALID_QUANTITY",
            field="quantity",
        )
    if quantity < 1:
        raise DomainError(
            "Quantity must be at least 1.", code="INVALID_QUANTITY", field="quantity"
        )
    if quantity > totals_services.MAX_LINE_QUANTITY:
        raise DomainError(
            "A single line is limited to {0} units.".format(
                totals_services.MAX_LINE_QUANTITY
            ),
            code="QUANTITY_TOO_LARGE",
            field="quantity",
        )
    return quantity


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
