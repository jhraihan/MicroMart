"""
Coupon validation and redemption (PRD 5.10, FR-CPN-1..8).

Every rejection carries its own stable code (FR-CPN-7) so the checkout UI can
say *why* a code failed rather than "invalid coupon". Codes never change;
messages may.

`lines` here is any iterable of objects exposing `.variant` (a ProductVariant,
or None) and `.line_total` (Decimal). Deliberately duck-typed: the cart, the
checkout quote and order placement all pass their own line objects, and a
shared import would tie promotions to orders and orders to promotions.

Discount is computed on the *eligible* lines only (FR-CPN-3): a coupon scoped
to Laptops must not discount the mouse in the same basket.
"""
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.common.fields import quantize_money
from config.exceptions import DomainError

from ..models import Coupon, CouponRedemption, DiscountType, ScopeType

ZERO = Decimal("0.00")


def canonical_code(value):
    """
    The single place a coupon code is folded to its stored form.

    Both directions go through it: every admin write normalises with it before
    saving, and `find_coupon` normalises the shopper's input with it before
    matching. One function means "SAVE10" and "save10" cannot become two rows,
    and the storefront lookup cannot drift away from what the admin stored.
    """
    return (value or "").strip().upper()


def find_coupon(code, *, for_update=False):
    """Look a code up case-insensitively. Codes are stored uppercased."""
    cleaned = canonical_code(code)
    if not cleaned:
        raise DomainError(
            "Enter a coupon code.", code="COUPON_REQUIRED", field="coupon_code"
        )

    queryset = Coupon.objects.all()
    if for_update:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(code=cleaned)
    except Coupon.DoesNotExist:
        raise DomainError(
            f"Coupon {cleaned} is not a valid code.",
            code="COUPON_NOT_FOUND",
            field="coupon_code",
        )


def _scoped_category_ids(coupon):
    """Category scope covers a category and its children, as category pages do."""
    from apps.catalog.models import Category

    ids = {int(value) for value in coupon.scope_ids or [] if str(value).isdigit()}
    if not ids:
        return ids
    children = Category.objects.filter(parent_id__in=ids).values_list("id", flat=True)
    return ids | set(children)


def line_is_eligible(coupon, line):
    if coupon.scope_type == ScopeType.ALL:
        return True
    variant = getattr(line, "variant", None)
    if variant is None:
        return False
    if coupon.scope_type == ScopeType.PRODUCT:
        ids = {int(value) for value in coupon.scope_ids or [] if str(value).isdigit()}
        return variant.product_id in ids
    if coupon.scope_type == ScopeType.CATEGORY:
        return variant.product.category_id in _scoped_category_ids(coupon)
    return False  # pragma: no cover -- guarded by the field's choices


def eligible_subtotal(coupon, lines):
    total = sum(
        (Decimal(line.line_total) for line in lines if line_is_eligible(coupon, line)),
        ZERO,
    )
    return quantize_money(total)


def compute_discount(coupon, eligible_total):
    """
    The money a coupon takes off, before any check on whether it may.

    A discount can never exceed the eligible merchandise it discounts -- a
    BDT 500 fixed coupon against a BDT 300 eligible line takes 300, not 500,
    and certainly never turns into store credit.
    """
    eligible_total = Decimal(eligible_total)
    if eligible_total <= ZERO:
        return ZERO

    if coupon.discount_type == DiscountType.PERCENT:
        raw = eligible_total * (Decimal(coupon.value) / Decimal("100"))
        if coupon.max_discount is not None:
            raw = min(raw, Decimal(coupon.max_discount))
    else:
        raw = Decimal(coupon.value)

    return quantize_money(min(raw, eligible_total))


def validate_coupon(*, coupon, lines, subtotal, user=None):
    """
    Run every constraint and return the discount amount (FR-CPN-4).

    Called on each recalculation *and* again inside the order transaction, so a
    coupon that expires or hits its cap between quote and placement is caught
    at placement rather than honoured.
    """
    from django.utils import timezone

    if not coupon.is_active:
        raise DomainError(
            f"Coupon {coupon.code} is no longer available.",
            code="COUPON_INACTIVE",
            field="coupon_code",
        )

    now = timezone.now()
    if now < coupon.valid_from:
        raise DomainError(
            f"Coupon {coupon.code} is not active yet.",
            code="COUPON_NOT_YET_VALID",
            field="coupon_code",
        )
    if now > coupon.valid_until:
        raise DomainError(
            f"Coupon {coupon.code} has expired.",
            code="COUPON_EXPIRED",
            field="coupon_code",
        )

    subtotal = Decimal(subtotal)
    if subtotal < Decimal(coupon.min_order_value):
        raise DomainError(
            f"Coupon {coupon.code} needs a minimum order of "
            f"{quantize_money(coupon.min_order_value)}.",
            code="COUPON_MIN_ORDER_NOT_MET",
            field="coupon_code",
        )

    if coupon.usage_limit is not None:
        if CouponRedemption.objects.filter(coupon=coupon).count() >= coupon.usage_limit:
            raise DomainError(
                f"Coupon {coupon.code} has reached its usage limit.",
                code="COUPON_USAGE_LIMIT_REACHED",
                field="coupon_code",
            )

    # A guest has no identity to count against, so the per-user cap is only
    # enforceable for authenticated customers. The total usage cap above is
    # what bounds guest redemption.
    if user is not None and getattr(user, "is_authenticated", False) and coupon.per_user_limit:
        used = CouponRedemption.objects.filter(coupon=coupon, user=user).count()
        if used >= coupon.per_user_limit:
            raise DomainError(
                f"You have already used coupon {coupon.code}.",
                code="COUPON_USER_LIMIT_REACHED",
                field="coupon_code",
            )

    discount = compute_discount(coupon, eligible_subtotal(coupon, lines))
    if discount <= ZERO:
        raise DomainError(
            f"Coupon {coupon.code} does not apply to anything in your cart.",
            code="COUPON_NOT_APPLICABLE",
            field="coupon_code",
        )
    return discount


def record_redemption(*, coupon, user, order, discount_amount):
    """FR-CPN-5: one redemption row per order, which is what enforces the caps."""
    return CouponRedemption.objects.create(
        coupon=coupon,
        user=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
        order=order,
        discount_amount=quantize_money(discount_amount),
    )


@transaction.atomic
def release_redemption(order):
    """
    FR-CPN-8: cancelling before shipment restores the usage count.

    The row is deleted rather than flagged -- the model has no released_at
    column, and Order.coupon still records which code the cancelled order used,
    so promotion reporting keeps its history either way.
    """
    deleted, _ = CouponRedemption.objects.filter(order=order).delete()
    return deleted > 0


# Coupon management (admin CRUD).
#
# validate_definition runs on every create and update, so a malformed coupon
# cannot be stored -- the shopper is the one who would find out otherwise.
#
# A redeemed coupon's code is immutable, and coupons are retired rather than
# deleted: orders reference the coupon, so a rename or a delete would rewrite
# what historical orders say they used.

# Codes are typed by hand on a phone, printed on flyers and read out over the
# counter, so the character set is deliberately narrow: anything a whitespace
# or a lookalike could break is refused at the door rather than becoming a
# code no shopper can enter.
CODE_MIN_LENGTH = 3
CODE_MAX_LENGTH = 32
CODE_PATTERN = re.compile(
    r"^[A-Z0-9][A-Z0-9_-]{%d,%d}$" % (CODE_MIN_LENGTH - 1, CODE_MAX_LENGTH - 1)
)

# Lifecycle labels for the admin list. They partition the table exactly --
# every coupon is in one and only one of them -- so `?status=` and the
# `status` field on a row can never disagree.
STATUS_ACTIVE = "active"
STATUS_SCHEDULED = "scheduled"
STATUS_EXPIRED = "expired"
STATUS_INACTIVE = "inactive"
STATUS_ALL = "all"

STATUS_CHOICES = (STATUS_ACTIVE, STATUS_SCHEDULED, STATUS_EXPIRED, STATUS_INACTIVE)

# Fields that make up a coupon's definition. Anything not in here (redemption
# count, timestamps) is derived and cannot be written.
DEFINITION_FIELDS = (
    "code",
    "discount_type",
    "value",
    "max_discount",
    "min_order_value",
    "valid_from",
    "valid_until",
    "usage_limit",
    "per_user_limit",
    "scope_type",
    "scope_ids",
    "is_active",
)

# A create must state these; an update inherits whatever it does not restate.
REQUIRED_ON_CREATE = ("code", "discount_type", "value", "valid_from", "valid_until")

CREATE_DEFAULTS = {
    "max_discount": None,
    "min_order_value": ZERO,
    "usage_limit": None,
    "per_user_limit": 1,
    "scope_type": ScopeType.ALL,
    "scope_ids": (),
    "is_active": True,
}


def normalise_code(value):
    """Fold a code to its stored form and refuse one no shopper could type."""
    code = canonical_code(value)
    if not code:
        raise DomainError(
            "A coupon needs a code.", code="COUPON_CODE_INVALID", field="code"
        )
    if not CODE_PATTERN.match(code):
        raise DomainError(
            "A coupon code is {0}-{1} characters of letters, digits, hyphen or "
            "underscore, with no spaces.".format(CODE_MIN_LENGTH, CODE_MAX_LENGTH),
            code="COUPON_CODE_INVALID",
            field="code",
        )
    return code


def coupon_status(coupon, *, now=None):
    """Which of the four lifecycle states a coupon is in right now."""
    now = now or timezone.now()
    if not coupon.is_active:
        return STATUS_INACTIVE
    if now < coupon.valid_from:
        return STATUS_SCHEDULED
    if now > coupon.valid_until:
        return STATUS_EXPIRED
    return STATUS_ACTIVE


def _money(value, *, field, label):
    try:
        return quantize_money(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        raise DomainError(
            "{0} must be an amount.".format(label),
            code="COUPON_VALUE_INVALID",
            field=field,
        )


def _whole_number(value, *, field, error_code, label):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise DomainError(
            "{0} must be a whole number.".format(label), code=error_code, field=field
        )
    if number < 1:
        raise DomainError(
            "{0} must be at least 1. To stop a coupon being used, switch it off "
            "instead.".format(label),
            code=error_code,
            field=field,
        )
    return number


def _clean_scope(scope_type, raw_ids):
    """
    Normalise and *verify* a scope.

    Ids are stored as ints because `_scoped_category_ids` and
    `line_is_eligible` above read them as ints, and existence is checked
    because a scope pointing at a deleted category is a coupon that answers
    COUPON_NOT_APPLICABLE to every shopper who tries it -- a promotion the
    owner believes is running and nobody can use.
    """
    if scope_type == ScopeType.ALL:
        # Ids are meaningless for a catalogue-wide coupon. Dropping them keeps
        # a switch back to a scoped type from silently reviving stale targets.
        return []

    ids = []
    for value in raw_ids or []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise DomainError(
                "Scope ids must be whole numbers.",
                code="COUPON_SCOPE_INVALID",
                field="scope_ids",
            )
        if number < 1:
            raise DomainError(
                "Scope ids must be whole numbers.",
                code="COUPON_SCOPE_INVALID",
                field="scope_ids",
            )
        ids.append(number)

    ids = sorted(set(ids))
    if not ids:
        raise DomainError(
            "A {0}-scoped coupon needs at least one {0}.".format(scope_type),
            code="COUPON_SCOPE_REQUIRED",
            field="scope_ids",
        )

    from apps.catalog.models import Category, Product

    model = Category if scope_type == ScopeType.CATEGORY else Product
    found = set(model.objects.filter(id__in=ids).values_list("id", flat=True))
    missing = [str(value) for value in ids if value not in found]
    if missing:
        raise DomainError(
            "No {0} with id {1}.".format(scope_type, ", ".join(missing)),
            code="COUPON_SCOPE_UNKNOWN",
            field="scope_ids",
        )
    return ids


def validate_definition(fields, *, current=None):
    """
    Turn a partial admin payload into a complete, legal coupon definition.

    `current` is the coupon being edited, and every field the payload does not
    mention is inherited from it -- so a PATCH is judged as the whole coupon it
    would produce, not as the two keys it happened to send. A coupon that would
    be malformed *after* the edit is refused even when the edit itself looks
    innocent.

    Returns a dict of model field values. Raises DomainError with a stable
    code (PRD 7.1) on the first rule broken.
    """
    unknown = sorted(set(fields) - set(DEFINITION_FIELDS))
    if unknown:
        raise DomainError(
            "Unknown coupon field: {0}.".format(", ".join(unknown)),
            code="COUPON_FIELD_UNKNOWN",
            field=unknown[0],
        )

    def take(name):
        if name in fields:
            return fields[name]
        if current is not None:
            return getattr(current, name)
        if name in REQUIRED_ON_CREATE:
            raise DomainError(
                "{0} is required.".format(name),
                code="COUPON_FIELD_REQUIRED",
                field=name,
            )
        return CREATE_DEFAULTS[name]

    data = {"code": normalise_code(take("code"))}

    discount_type = take("discount_type")
    if discount_type not in DiscountType.values:
        raise DomainError(
            "A coupon is either a percentage or a fixed amount.",
            code="COUPON_DISCOUNT_TYPE_INVALID",
            field="discount_type",
        )
    data["discount_type"] = discount_type

    value = _money(take("value"), field="value", label="The discount")
    if value <= ZERO:
        raise DomainError(
            "A discount has to be worth something.",
            code="COUPON_VALUE_INVALID",
            field="value",
        )
    if discount_type == DiscountType.PERCENT and value > Decimal("100"):
        # compute_discount() clamps a >100% coupon to the eligible subtotal, so
        # this would not hand out store credit -- but it would advertise a
        # discount the basket can never reach, which is a pricing lie.
        raise DomainError(
            "A percentage discount cannot be more than 100%.",
            code="COUPON_PERCENT_INVALID",
            field="value",
        )
    data["value"] = value

    max_discount = take("max_discount")
    if max_discount is not None:
        if discount_type != DiscountType.PERCENT:
            # compute_discount() ignores it for a fixed coupon. Accepting it
            # would show the admin a cap that does nothing.
            raise DomainError(
                "A discount cap only applies to a percentage coupon.",
                code="COUPON_MAX_DISCOUNT_NOT_APPLICABLE",
                field="max_discount",
            )
        max_discount = _money(
            max_discount, field="max_discount", label="The discount cap"
        )
        if max_discount <= ZERO:
            raise DomainError(
                "A discount cap has to be worth something.",
                code="COUPON_MAX_DISCOUNT_INVALID",
                field="max_discount",
            )
    data["max_discount"] = max_discount

    min_order_value = _money(
        take("min_order_value"), field="min_order_value", label="The minimum order"
    )
    if min_order_value < ZERO:
        raise DomainError(
            "A minimum order value cannot be negative.",
            code="COUPON_MIN_ORDER_INVALID",
            field="min_order_value",
        )
    data["min_order_value"] = min_order_value

    valid_from = take("valid_from")
    valid_until = take("valid_until")
    if valid_from is None or valid_until is None:
        raise DomainError(
            "A coupon needs a start and an end.",
            code="COUPON_WINDOW_INVALID",
            field="valid_until",
        )
    if valid_until <= valid_from:
        # validate_coupon() would answer COUPON_NOT_YET_VALID before the start
        # and COUPON_EXPIRED after the end, so a backwards window is a coupon
        # that is refused at every instant of its life.
        raise DomainError(
            "A coupon has to end after it starts.",
            code="COUPON_WINDOW_INVALID",
            field="valid_until",
        )
    data["valid_from"] = valid_from
    data["valid_until"] = valid_until

    usage_limit = take("usage_limit")
    data["usage_limit"] = (
        None
        if usage_limit is None
        else _whole_number(
            usage_limit,
            field="usage_limit",
            error_code="COUPON_USAGE_LIMIT_INVALID",
            label="The total usage limit",
        )
    )

    # Zero is refused rather than stored: validate_coupon() reads a falsy
    # per_user_limit as "no per-user cap", so a 0 typed by an admin who meant
    # "nobody" would silently mean "everybody, without limit".
    data["per_user_limit"] = _whole_number(
        take("per_user_limit"),
        field="per_user_limit",
        error_code="COUPON_PER_USER_LIMIT_INVALID",
        label="The per-customer limit",
    )

    scope_type = take("scope_type")
    if scope_type not in ScopeType.values:
        raise DomainError(
            "A coupon is scoped to the whole catalogue, to categories, or to "
            "products.",
            code="COUPON_SCOPE_TYPE_INVALID",
            field="scope_type",
        )
    data["scope_type"] = scope_type
    data["scope_ids"] = _clean_scope(scope_type, take("scope_ids"))

    data["is_active"] = bool(take("is_active"))
    return data


def _assert_code_is_free(code, *, exclude_pk=None):
    queryset = Coupon.objects.filter(code=code)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    if queryset.exists():
        raise DomainError(
            "Coupon code {0} is already in use.".format(code),
            code="COUPON_CODE_TAKEN",
            field="code",
        )


def _run_model_validators(coupon):
    """
    A backstop, not the validation.

    Every rule an admin can break has its own code above. This catches what is
    left -- column lengths, choice sets, the model's own MinValueValidators --
    so a bad definition is a 422 with a field name rather than a database
    error the client cannot read.
    """
    try:
        coupon.full_clean(validate_unique=False)
    except ValidationError as exc:
        field, messages = next(iter(exc.message_dict.items()))
        raise DomainError(
            str(messages[0]),
            code="COUPON_INVALID",
            field=None if field == "__all__" else field,
        )


def create_coupon(**fields):
    """CRUD create for /admin/coupons/ (US-A5)."""
    data = validate_definition(fields)
    _assert_code_is_free(data["code"])

    coupon = Coupon(**data)
    _run_model_validators(coupon)
    try:
        with transaction.atomic():
            coupon.save()
    except IntegrityError:
        # The unique index arbitrates the race the check above cannot.
        raise DomainError(
            "Coupon code {0} is already in use.".format(data["code"]),
            code="COUPON_CODE_TAKEN",
            field="code",
        )
    return coupon


def update_coupon(coupon, **fields):
    """
    CRUD update for /admin/coupons/{id}/.

    Editing what a coupon is worth changes what it does *next*; it never
    touches an order already placed, because the discount is snapshotted onto
    the order and onto its redemption row at placement.

    The one field an edit cannot reach is the code of a coupon that has
    already been redeemed -- Order.coupon is a reference, so renaming it would
    change which code a historical order reports having used.
    """
    data = validate_definition(fields, current=coupon)

    if data["code"] != coupon.code and coupon.redemptions.exists():
        raise DomainError(
            "Coupon {0} has already been used, so its code is fixed. Switch it "
            "off and create a new one instead.".format(coupon.code),
            code="COUPON_CODE_IMMUTABLE",
            field="code",
        )
    _assert_code_is_free(data["code"], exclude_pk=coupon.pk)

    for name, value in data.items():
        setattr(coupon, name, value)
    _run_model_validators(coupon)
    try:
        with transaction.atomic():
            coupon.save()
    except IntegrityError:
        raise DomainError(
            "Coupon code {0} is already in use.".format(data["code"]),
            code="COUPON_CODE_TAKEN",
            field="code",
        )
    return coupon


def deactivate_coupon(coupon):
    """
    CRUD delete for /admin/coupons/{id}/ -- retire, never destroy.

    A hard delete would cascade CouponRedemption away and SET_NULL every
    placed order's coupon, i.e. rewrite history to hide a promotion that
    really ran. An inactive coupon is refused by validate_coupon with
    COUPON_INACTIVE, which is what "deleted" needs to mean here. Idempotent.
    """
    if coupon.is_active:
        coupon.is_active = False
        coupon.save(update_fields=["is_active", "updated_at"])
    return coupon


def admin_coupons(*, status=None, search=None):
    """
    The admin list queryset (PRD 7.3), redemption counts included.

    The count is aggregated from CouponRedemption on every read rather than
    kept in a column, because a counter that is incremented can drift from the
    rows it claims to count -- and those rows are what enforce the usage caps.
    """
    queryset = Coupon.objects.annotate(
        redemptions_used=Count("redemptions", distinct=True),
        redeemed_value=Sum("redemptions__discount_amount"),
    )

    now = timezone.now()
    if status == STATUS_ACTIVE:
        queryset = queryset.filter(
            is_active=True, valid_from__lte=now, valid_until__gte=now
        )
    elif status == STATUS_SCHEDULED:
        queryset = queryset.filter(is_active=True, valid_from__gt=now)
    elif status == STATUS_EXPIRED:
        queryset = queryset.filter(is_active=True, valid_until__lt=now)
    elif status == STATUS_INACTIVE:
        queryset = queryset.filter(is_active=False)

    if search:
        # icontains, not contains: Django escapes % and _ for a LIKE lookup, so a
        # search box cannot be turned into a wildcard.
        queryset = queryset.filter(code__icontains=canonical_code(search))

    return queryset.order_by("-created_at", "-id")


def get_admin_coupon(coupon_id):
    """One coupon for the admin surface, or a 404-shaped error."""
    coupon = admin_coupons().filter(pk=coupon_id).first()
    if coupon is None:
        raise DomainError("Not found.", code="NOT_FOUND", status_code=404)
    return coupon
