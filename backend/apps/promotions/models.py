"""
Coupons and redemptions (PRD §5.10, §6.4).

One coupon per order -- no stacking. Validation happens server-side on every
recalculation and again at placement; the redemption row is what enforces
per-user caps and powers promotion reporting.
"""
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.common.fields import MoneyField
from apps.common.models import TimeStampedModel


class DiscountType(models.TextChoices):
    PERCENT = "percent", "Percentage"
    FIXED = "fixed", "Fixed amount"


class ScopeType(models.TextChoices):
    ALL = "all", "Entire catalogue"
    CATEGORY = "category", "Specific categories"
    PRODUCT = "product", "Specific products"


class Coupon(TimeStampedModel):
    code = models.CharField(max_length=32, unique=True)
    discount_type = models.CharField(max_length=16, choices=DiscountType.choices)
    value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Percentage points for percent coupons, BDT for fixed.",
    )
    max_discount = MoneyField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Caps a percentage discount. Ignored for fixed coupons.",
    )
    min_order_value = MoneyField(default=0, validators=[MinValueValidator(0)])
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    usage_limit = models.PositiveIntegerField(
        null=True, blank=True, help_text="Total redemptions allowed. Null is unlimited."
    )
    per_user_limit = models.PositiveIntegerField(default=1)
    scope_type = models.CharField(
        max_length=16, choices=ScopeType.choices, default=ScopeType.ALL
    )
    scope_ids = models.JSONField(
        default=list, blank=True, help_text="Category or product IDs when scoped."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "promotions_coupon"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["is_active", "valid_until"])]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        # Codes are compared case-insensitively, so they are stored uppercased
        # and every lookup uppercases its input.
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    @property
    def is_within_window(self):
        now = timezone.now()
        return self.valid_from <= now <= self.valid_until

    @property
    def redemption_count(self):
        return self.redemptions.count()


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(
        Coupon, on_delete=models.CASCADE, related_name="redemptions"
    )
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="coupon_redemptions",
    )
    order = models.OneToOneField(
        "orders.Order", on_delete=models.CASCADE, related_name="coupon_redemption"
    )
    discount_amount = MoneyField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "promotions_coupon_redemption"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["coupon", "user"])]

    def __str__(self):
        return f"{self.coupon_id} -> order {self.order_id}"
