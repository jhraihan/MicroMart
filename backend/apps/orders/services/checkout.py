"""
Checkout: turning "what is in the basket" into a priced, payable quote
(PRD 5.4, 5.5, 5.12).

Nothing here writes. The quote endpoint and order placement both call
`resolve_basket` and `compute_totals`, so the figure a customer is shown and
the figure they are charged come from the same code with the same inputs. A
quote that disagreed with placement would be a promise the shop then broke.

Payment-method availability is decided here too, because it depends on all
three of the store settings, the resolved shipping zone and the grand total --
none of which a React component can be trusted to evaluate (FR-PAY-1).
"""
from dataclasses import dataclass, field
from decimal import Decimal

from apps.cart.services import cart as cart_services
from apps.dashboard.models import StoreSettings
from config.exceptions import DomainError

from ..models import PaymentMethod
from . import totals as totals_services


def resolve_basket(*, user=None, items=None, cart=None):
    """
    Priced lines plus the server cart they came from, if any.

    An explicit `items` payload always wins: it is how a guest checks out, and
    how a signed-in customer buys straight from a product page without
    disturbing their cart. Otherwise an authenticated customer's server cart is
    used, unavailable lines already excluded.
    """
    if items:
        return cart_services.lines_from_items(items), None

    if user is not None and getattr(user, "is_authenticated", False):
        cart = cart or cart_services.get_cart(user)
        view = cart_services.read_cart(cart)
        lines = view.purchasable_lines
        if not lines:
            raise DomainError(
                "Your cart is empty.", code="CART_EMPTY", field="items"
            )
        return lines, cart

    raise DomainError(
        "Send the items you want to buy.", code="ITEMS_REQUIRED", field="items"
    )


def cod_availability(totals):
    """
    (available, code, message) for Cash on Delivery (FR-PAY-1, FR-SHP-5).

    Three independent gates: the store switch, the zone's own policy, and the
    order-value ceiling. Each has its own stable code so checkout can explain
    which one blocked it.
    """
    settings = totals.settings or StoreSettings.load()

    if not settings.cod_enabled:
        return False, "COD_DISABLED", "Cash on Delivery is currently unavailable."

    if totals.zone is not None and not totals.zone.cod_allowed:
        return (
            False,
            "COD_NOT_ALLOWED_IN_ZONE",
            "Cash on Delivery is not available for {0}.".format(totals.zone.name),
        )

    cap = settings.cod_max_order_value
    if cap is not None and Decimal(totals.grand_total) > Decimal(cap):
        return (
            False,
            "COD_LIMIT_EXCEEDED",
            "Cash on Delivery is available on orders up to {0}. "
            "Please pay online for this order.".format(Decimal(cap)),
        )

    return True, None, None


def assert_payment_method_allowed(totals, payment_method):
    """Refuse an unpayable method at placement, with the gate's own code."""
    if payment_method not in PaymentMethod.values:
        raise DomainError(
            "Choose a valid payment method.",
            code="INVALID_PAYMENT_METHOD",
            field="payment_method",
        )
    if payment_method == PaymentMethod.COD:
        available, code, message = cod_availability(totals)
        if not available:
            raise DomainError(message, code=code, field="payment_method")


def payment_options(totals):
    """The payment section of a quote, in display order."""
    cod_available, cod_code, cod_message = cod_availability(totals)
    return [
        {
            "method": PaymentMethod.COD.value,
            "label": PaymentMethod.COD.label,
            "available": cod_available,
            "unavailable_code": cod_code,
            "unavailable_reason": cod_message,
        },
        {
            "method": PaymentMethod.ONLINE.value,
            "label": PaymentMethod.ONLINE.label,
            "available": True,
            "unavailable_code": None,
            "unavailable_reason": None,
        },
    ]


# Codes the quote absorbs rather than failing on -- the shopper can fix
# either while the rest of the basket stays priced. Placement is not tolerant
# of them: an order must never be created with an unpriced delivery.
TOLERATED_ZONE_CODES = frozenset({"SHIPPING_ZONE_UNAVAILABLE", "DISTRICT_REQUIRED"})
NOTICE_NO_SHIPPING_ZONE = "NO_SHIPPING_ZONE"


@dataclass(frozen=True)
class Quote:
    """
    A priced basket plus the server's own verdict on whether it can be bought.

    `can_place_order` is computed here rather than in the client because it is
    the same question placement will ask; deriving it twice is how a checkout
    that offers a button the API then refuses gets built (FR-CRT-4).
    """

    totals: object
    payment_options: list
    coupon_error: dict = None
    notices: list = field(default_factory=list)

    @property
    def can_place_order(self):
        lines = list(self.totals.lines)
        if not lines:
            return False
        if not all(line.is_available for line in lines):
            return False
        if not self.totals.shipping_known:
            return False
        return any(option["available"] for option in self.payment_options)


def quote(*, user=None, items=None, district=None, coupon_code=None, cart=None):
    """
    POST /checkout/quote/. Server-computed totals for a basket, an address and
    a coupon -- the only totals the checkout page is allowed to display.

    A bad coupon or an undeliverable district must not blank out the figures a
    shopper is reading: both come back as a `coupon_error` or a notice with
    the basket still priced. Losing the whole quote over a typo is how a
    shopper loses their place in a checkout.
    """
    lines, _cart = resolve_basket(user=user, items=items, cart=cart)

    coupon_error = None
    notices = []
    drop_coupon = False
    drop_district = False

    while True:
        try:
            totals = totals_services.compute_totals(
                lines=lines,
                district=None if drop_district else district,
                coupon_code=None if drop_coupon else coupon_code,
                user=user,
            )
            break
        except DomainError as exc:
            code = exc.code or ""
            if code.startswith("COUPON_") and not drop_coupon:
                # The code stays exactly as the coupon service raised it, so a
                # client can branch on the same value here and at placement.
                drop_coupon = True
                coupon_error = {"code": code, "message": exc.message}
                continue
            if code in TOLERATED_ZONE_CODES and not drop_district:
                drop_district = True
                notices.append(
                    {
                        "code": NOTICE_NO_SHIPPING_ZONE,
                        "message": exc.message,
                        "field": "district",
                    }
                )
                continue
            raise

    return Quote(
        totals=totals,
        payment_options=payment_options(totals),
        coupon_error=coupon_error,
        notices=notices,
    )
