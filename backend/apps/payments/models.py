"""
Payment records (PRD §6.3, §10.3).

No card data ever touches this application -- SSLCommerz hosted checkout keeps
PCI scope minimal. What is stored here is the gateway's own transaction
identifier and its raw response, retained for reconciliation and disputes.
"""
from django.db import models

from apps.common.fields import MoneyField


class PaymentStatus(models.TextChoices):
    INITIATED = "initiated", "Initiated"
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"


class Payment(models.Model):
    order = models.OneToOneField(
        "orders.Order", on_delete=models.CASCADE, related_name="payment"
    )
    method = models.CharField(max_length=16)
    gateway_txn_id = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
        help_text="SSLCommerz val_id / bank_tran_id once validated.",
    )
    session_key = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
        help_text="Gateway session token returned by the initiate call.",
    )
    amount = MoneyField()
    currency = models.CharField(max_length=3, default="BDT")
    status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.INITIATED
    )
    raw_response = models.JSONField(
        default=dict, blank=True, help_text="Retained for gateway reconciliation."
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "payments_payment"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"{self.method} {self.amount} {self.currency} ({self.status})"

    @property
    def is_paid(self):
        return self.status == PaymentStatus.PAID
