"""Money is always DECIMAL(12,2). No floats anywhere near a price (PRD §6.5)."""
from decimal import Decimal

from django.db import models

MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2
ZERO = Decimal("0.00")


class MoneyField(models.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", MONEY_MAX_DIGITS)
        kwargs.setdefault("decimal_places", MONEY_DECIMAL_PLACES)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("max_digits", None)
        kwargs.pop("decimal_places", None)
        return name, path, args, kwargs


def quantize_money(value):
    """Round a Decimal to 2dp using banker's-safe ROUND_HALF_UP."""
    from decimal import ROUND_HALF_UP

    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
