"""
The totals engine -- the single source of truth for money.

compute_totals is called by the cart view, the checkout quote, order placement
and the admin surface. One implementation, because a second would eventually
disagree and the customer would be charged whichever number lost.

Client-supplied totals are never read. The client sends what it wants to buy;
the server decides what that costs.

    subtotal    = sum(unit_price * quantity)
    discount    = coupon applied to eligible lines
    net         = subtotal - discount
    shipping    = zone rate on net and total weight
    tax         = tax_rate on net
    grand_total = net + shipping + tax

Tax is charged on merchandise, not delivery -- shipping is a pass-through
courier charge. When prices already include VAT, the tax line reports the
portion inside net rather than adding it again.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from apps.catalog.services import inventory as inventory_services
from apps.common.fields import quantize_money
from apps.dashboard.models import StoreSettings
from apps.promotions.services import coupons as coupon_services
from apps.shipping.services import rates as shipping_services
from config.exceptions import DomainError

ZERO = Decimal("0.00")
HUNDRED = Decimal("100")

# A single line may not exceed this. Not a stock rule -- a sanity bound that
# keeps a fat-fingered or hostile quantity out of the money arithmetic.
MAX_LINE_QUANTITY = 99


@dataclass(frozen=True)
class BasketLine:
    """
    One priced line. The snapshot fields are carried from the moment the line
    is built so that OrderItem can copy them verbatim at placement -- the same
    values that were quoted are the values that are charged and stored.
    """

    variant: object
    quantity: int
    unit_price: Decimal
    product_name: str
    variant_label: str
    sku: str
    weight_grams: int = 0

    @property
    def line_total(self):
        return quantize_money(self.unit_price * self.quantity)

    @property
    def line_weight_grams(self):
        return int(self.weight_grams or 0) * int(self.quantity)

    # --- Availability -----------------------------------------------------
    # Reported, never reserved. A quote tells the shopper what they can buy
    # right now; only order confirmation moves stock (FR-CRT-3).
    @property
    def _availability(self):
        return inventory_services.availability(self.variant, self.quantity)

    @property
    def available_stock(self):
        return self._availability[0]

    @property
    def is_available(self):
        return self._availability[1]

    @property
    def issue(self):
        return self._availability[2]


@dataclass(frozen=True)
class Totals:
    lines: list
    subtotal: Decimal
    discount_total: Decimal
    shipping_total: Decimal
    tax_rate: Decimal
    tax_total: Decimal
    tax_inclusive: bool
    grand_total: Decimal
    total_weight_grams: int
    zone: object = None
    coupon: object = None
    free_shipping_applied: bool = False
    shipping_known: bool = False
    settings: object = field(default=None, repr=False)

    @property
    def item_count(self):
        return sum(line.quantity for line in self.lines)


def build_line(variant, quantity):
    """
    Price one variant at today's catalogue price.

    Price is read from the variant row, never from the request: a client that
    could name its own unit price would be a pricing API, not a shop.
    """
    quantity = int(quantity)
    if quantity < 1:
        raise DomainError(
            "Quantity must be at least 1.", code="INVALID_QUANTITY", field="quantity"
        )
    if quantity > MAX_LINE_QUANTITY:
        raise DomainError(
            "A single line is limited to {0} units.".format(MAX_LINE_QUANTITY),
            code="QUANTITY_TOO_LARGE",
            field="quantity",
        )
    return BasketLine(
        variant=variant,
        quantity=quantity,
        unit_price=Decimal(variant.price),
        product_name=variant.product.name,
        variant_label=variant.label,
        sku=variant.sku,
        weight_grams=variant.weight_grams,
    )


def build_lines(pairs):
    """`pairs` is an iterable of (variant, quantity)."""
    return [build_line(variant, quantity) for variant, quantity in pairs]


def subtotal_of(lines):
    return quantize_money(sum((line.line_total for line in lines), ZERO))


def weight_of(lines):
    return sum(line.line_weight_grams for line in lines)


def compute_totals(
    *,
    lines,
    district=None,
    coupon_code=None,
    user=None,
    settings=None,
    lock_coupon=False,
):
    """
    Price a basket end to end.

    `district` may be omitted while the customer is still browsing the cart --
    shipping is then reported as 0 with `shipping_known=False`, which the cart
    renders as "calculated at checkout". Placement always supplies it, so an
    order can never be created with an unpriced delivery.

    `lock_coupon` takes a row lock on the coupon while validating, which order
    placement uses to serialise redemptions against its usage cap.
    """
    lines = list(lines)
    if not lines:
        raise DomainError(
            "Your cart is empty.", code="CART_EMPTY", field="items", status_code=422
        )

    settings = settings or StoreSettings.load()

    subtotal = subtotal_of(lines)
    total_weight = weight_of(lines)

    coupon = None
    discount_total = ZERO
    if coupon_code:
        coupon = coupon_services.find_coupon(coupon_code, for_update=lock_coupon)
        discount_total = coupon_services.validate_coupon(
            coupon=coupon, lines=lines, subtotal=subtotal, user=user
        )

    net = quantize_money(subtotal - discount_total)

    zone = None
    shipping_total = ZERO
    free_shipping_applied = False
    shipping_known = False
    if district:
        zone = shipping_services.resolve_zone(district)
        quote = shipping_services.quote_shipping(
            zone=zone, subtotal=net, weight_grams=total_weight
        )
        shipping_total = quantize_money(quote.amount)
        free_shipping_applied = quote.free_shipping_applied
        shipping_known = True

    tax_rate = Decimal(settings.tax_rate or 0)
    tax_inclusive = bool(settings.tax_inclusive_pricing)
    tax_total = _tax_on(net, tax_rate, tax_inclusive)

    if tax_inclusive:
        grand_total = quantize_money(net + shipping_total)
    else:
        grand_total = quantize_money(net + shipping_total + tax_total)

    return Totals(
        lines=lines,
        subtotal=subtotal,
        discount_total=quantize_money(discount_total),
        shipping_total=shipping_total,
        tax_rate=tax_rate,
        tax_total=tax_total,
        tax_inclusive=tax_inclusive,
        grand_total=grand_total,
        total_weight_grams=total_weight,
        zone=zone,
        coupon=coupon,
        free_shipping_applied=free_shipping_applied,
        shipping_known=shipping_known,
        settings=settings,
    )


def _tax_on(net, rate, inclusive):
    """
    VAT on the discounted merchandise total.

    Tax-exclusive: net * rate.
    Tax-inclusive: the VAT already contained in net, i.e. net - net / (1 + rate).
    """
    rate = Decimal(rate or 0)
    net = Decimal(net)
    if rate <= ZERO or net <= ZERO:
        return ZERO
    if inclusive:
        divisor = Decimal("1") + (rate / HUNDRED)
        return quantize_money(net - (net / divisor))
    return quantize_money(net * (rate / HUNDRED))


__all__ = [
    "BasketLine",
    "MAX_LINE_QUANTITY",
    "Totals",
    "build_line",
    "build_lines",
    "compute_totals",
    "subtotal_of",
    "weight_of",
]
