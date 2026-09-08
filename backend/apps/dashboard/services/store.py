"""
Store settings (PRD 7.3 GET/PATCH /admin/settings/).

`StoreSettings` is a singleton -- `save()` pins pk=1 and `delete()` raises --
so "create or return" and "update" are the same row by construction. Both go
through here so the checkout, the low-stock digest and the admin screen all
read the store's configuration from one function.

**Changing a value here never reaches a placed order.** `tax_rate` and
`cod_max_order_value` feed checkout, and checkout *snapshots* what it used:
`Order.tax_rate_applied` is a column on the order, not a lookup through this
row. Raising VAT tomorrow must not re-price an order placed today, and
apps/dashboard/tests/test_store_settings.py holds that line.
"""
from decimal import Decimal, InvalidOperation

from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from config.exceptions import DomainError

from ..models import StoreSettings

# Percentage points. A negative rate is a discount pretending to be a tax, and
# nothing above 100 is a VAT rate.
TAX_RATE_MIN = Decimal("0")
TAX_RATE_MAX = Decimal("100")

EDITABLE_FIELDS = (
    "store_name",
    "support_email",
    "support_phone",
    "tax_rate",
    "tax_inclusive_pricing",
    "cod_enabled",
    "cod_max_order_value",
    "low_stock_digest_recipients",
)


def get_store_settings():
    """The one row, created on first read (GET /admin/settings/)."""
    return StoreSettings.load()


def _clean_tax_rate(value):
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise DomainError(
            "Enter the VAT rate as a percentage, e.g. 15.00.",
            code="INVALID_TAX_RATE",
            field="tax_rate",
        )
    if rate < TAX_RATE_MIN or rate > TAX_RATE_MAX:
        raise DomainError(
            "The VAT rate must be between 0 and 100 percent.",
            code="INVALID_TAX_RATE",
            field="tax_rate",
        )
    return rate


def _clean_cod_ceiling(value):
    if value in (None, ""):
        return None  # null disables the cap -- documented on the model
    try:
        ceiling = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise DomainError(
            "Enter the Cash on Delivery ceiling as an amount, e.g. 20000.00.",
            code="INVALID_COD_CEILING",
            field="cod_max_order_value",
        )
    if ceiling < 0:
        raise DomainError(
            "The Cash on Delivery ceiling cannot be negative.",
            code="INVALID_COD_CEILING",
            field="cod_max_order_value",
        )
    return ceiling


def _clean_recipients(value):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise DomainError(
            "Digest recipients must be a list of email addresses.",
            code="INVALID_RECIPIENTS",
            field="low_stock_digest_recipients",
        )
    cleaned = []
    for entry in value:
        address = str(entry or "").strip()
        if not address:
            continue
        try:
            validate_email(address)
        except ValidationError:
            raise DomainError(
                "{0} is not a valid email address.".format(address),
                code="INVALID_RECIPIENTS",
                field="low_stock_digest_recipients",
            )
        cleaned.append(address)
    return cleaned


_CLEANERS = {
    "tax_rate": _clean_tax_rate,
    "cod_max_order_value": _clean_cod_ceiling,
    "low_stock_digest_recipients": _clean_recipients,
}


def update_store_settings(**fields):
    """
    PATCH /admin/settings/ -- a partial update of the one row.

    Unknown keys are refused rather than ignored: silently dropping a
    misspelled field would report success for a change that did not happen.
    """
    unknown = sorted(set(fields) - set(EDITABLE_FIELDS))
    if unknown:
        raise DomainError(
            "Unknown setting: {0}.".format(", ".join(unknown)),
            code="UNKNOWN_SETTING",
            field=unknown[0],
            status_code=400,
        )

    settings = StoreSettings.load()
    changed = []
    for key, value in fields.items():
        cleaner = _CLEANERS.get(key)
        setattr(settings, key, cleaner(value) if cleaner else value)
        changed.append(key)

    if changed:
        # save() pins pk=1, so this can only ever be an UPDATE of the one row.
        settings.save()
    return settings
