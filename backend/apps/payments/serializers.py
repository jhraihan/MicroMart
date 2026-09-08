"""
Payment payload shapes (PRD 7.1, 7.2).

Nothing here decides anything. The three output serializers below read fields
off objects the service layer already built, and the one input serializer takes
a single order reference -- never an amount, never a status, never a "paid"
flag. A client that could name its own amount would be naming its own price.
"""
from rest_framework import serializers

from .services import payments as payment_services


class PaymentInitiateSerializer(serializers.Serializer):
    """
    POST /payments/initiate/.

    One field, deliberately. Everything else the gateway needs -- the amount
    above all -- is read from the order the server placed.
    """

    order_reference = serializers.CharField(max_length=24)


class PaymentSessionSerializer(serializers.Serializer):
    """The redirect instruction, plus what was recorded alongside it."""

    order_reference = serializers.CharField(source="order.reference", read_only=True)
    redirect_url = serializers.CharField(read_only=True)
    session_key = serializers.CharField(read_only=True, allow_blank=True)
    amount = serializers.DecimalField(
        source="payment.amount", max_digits=12, decimal_places=2, read_only=True
    )
    currency = serializers.CharField(source="payment.currency", read_only=True)
    payment_status = serializers.CharField(source="payment.status", read_only=True)
    gateway = serializers.SerializerMethodField()

    def get_gateway(self, obj):
        return payment_services.GATEWAY


class IPNResultSerializer(serializers.Serializer):
    """
    What the gateway gets back. Deliberately thin.

    SSLCommerz needs a 200 and nothing else; it retries anything else. So this
    body carries the verdict for our own logs and no order state at all --
    reporting a status here would hand an oracle to anyone who can reach the
    endpoint, which by design is everyone.
    """

    status = serializers.SerializerMethodField()
    reason = serializers.CharField(read_only=True)
    order_reference = serializers.SerializerMethodField()

    def get_status(self, obj):
        return "confirmed" if obj.confirmed else "ignored"

    def get_order_reference(self, obj):
        return obj.order.reference if obj.order is not None else None


class PaymentCallbackSerializer(serializers.Serializer):
    """
    The browser return (FR-PAY-3). Display copy and a link, nothing else.

    `payment_confirmed` is always null and that is the point: this endpoint is
    not allowed to know. A client must read the order itself to find out.
    """

    result = serializers.CharField(read_only=True)
    reference = serializers.CharField(read_only=True, allow_blank=True)
    message = serializers.CharField(read_only=True)
    payment_confirmed = serializers.BooleanField(read_only=True, allow_null=True)
    redirect_url = serializers.CharField(read_only=True)
