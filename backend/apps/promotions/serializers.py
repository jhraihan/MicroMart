"""
Coupon payload shapes for the admin surface (PRD 7.3, US-A5).

These translate only. What a coupon may be worth, when it may run, what it
may be scoped to and whether its code may change are all decided in
services/coupons.py -- the same module the storefront validator lives in, so
the admin cannot create a coupon checkout would consider malformed.

Two shapes here are derived rather than stored, on purpose:

* **`redemption_count` is counted from CouponRedemption on every read**
  (US-A5's "a redemption count is visible per coupon"). A stored counter can
  drift from the rows it claims to count, and those rows are what enforce the
  usage caps -- so the number on the screen and the number the cap is applied
  from are the same query.
* **`status`** is computed from `is_active` and the validity window rather
  than stored, because `validate_coupon` computes it that way too. A stored
  flag would need a cron job to go stale-free.

The write serializers deliberately carry almost no validation of their own:
bounds, windows, scopes and code shape are the service's rules, and their
stable DomainError codes (PRD 7.1) are the client's contract. Restating them
here would create a second opinion that could drift -- and the service is also
reachable from a management command, where no serializer runs at all.
"""
from rest_framework import serializers

from apps.common.fields import quantize_money

from .models import Coupon, DiscountType, ScopeType
from .services import coupons as coupon_services

MONEY_KWARGS = {"max_digits": 12, "decimal_places": 2}


class CouponSerializer(serializers.ModelSerializer):
    """One coupon as the admin list and detail read it."""

    value = serializers.DecimalField(read_only=True, **MONEY_KWARGS)
    max_discount = serializers.DecimalField(read_only=True, **MONEY_KWARGS)
    min_order_value = serializers.DecimalField(read_only=True, **MONEY_KWARGS)
    status = serializers.SerializerMethodField()
    redemption_count = serializers.SerializerMethodField()
    redeemed_value = serializers.SerializerMethodField()
    remaining_uses = serializers.SerializerMethodField()

    class Meta:
        model = Coupon
        fields = [
            "id",
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
            "status",
            "redemption_count",
            "redeemed_value",
            "remaining_uses",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_status(self, obj):
        return coupon_services.coupon_status(obj)

    def get_redemption_count(self, obj):
        # The annotation when the row came from admin_coupons(), the model's
        # own COUNT(*) otherwise. Both read CouponRedemption; neither reads a
        # stored counter.
        counted = getattr(obj, "redemptions_used", None)
        return obj.redemption_count if counted is None else counted

    def get_redeemed_value(self, obj):
        total = getattr(obj, "redeemed_value", None)
        return str(quantize_money(total or 0))

    def get_remaining_uses(self, obj):
        # Null is "unlimited", which is not the same number as 0 and must not
        # render as one.
        if obj.usage_limit is None:
            return None
        return max(0, obj.usage_limit - self.get_redemption_count(obj))


class CouponCreateSerializer(serializers.Serializer):
    """POST /admin/coupons/ -- the five fields a coupon cannot exist without."""

    code = serializers.CharField(max_length=coupon_services.CODE_MAX_LENGTH)
    discount_type = serializers.ChoiceField(choices=DiscountType.choices)
    value = serializers.DecimalField(**MONEY_KWARGS)
    max_discount = serializers.DecimalField(
        required=False, allow_null=True, **MONEY_KWARGS
    )
    min_order_value = serializers.DecimalField(required=False, **MONEY_KWARGS)
    valid_from = serializers.DateTimeField()
    valid_until = serializers.DateTimeField()
    usage_limit = serializers.IntegerField(required=False, allow_null=True)
    per_user_limit = serializers.IntegerField(required=False)
    scope_type = serializers.ChoiceField(choices=ScopeType.choices, required=False)
    scope_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    is_active = serializers.BooleanField(required=False)


class CouponUpdateSerializer(CouponCreateSerializer):
    """
    PATCH /admin/coupons/{id}/ -- a partial edit, so every field is optional.

    Absent means "leave alone". The service still judges the *whole* coupon the
    edit would produce, so a two-key PATCH that would make the coupon
    malformed is refused.
    """

    code = serializers.CharField(max_length=coupon_services.CODE_MAX_LENGTH, required=False)
    discount_type = serializers.ChoiceField(
        choices=DiscountType.choices, required=False
    )
    value = serializers.DecimalField(required=False, **MONEY_KWARGS)
    valid_from = serializers.DateTimeField(required=False)
    valid_until = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Send at least one field to change.")
        return attrs
