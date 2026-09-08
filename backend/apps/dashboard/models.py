"""
Store settings (PRD §7.3 GET/PATCH /admin/settings/).

A single row holding the values that are still open owner or accountant
decisions -- VAT rate (§14 Q2), COD ceiling (§14 Q4), free-shipping threshold
(§14 Q3). Keeping them in the database rather than in settings.py means the
answers can land without a redeploy, and the order snapshot records whichever
rate was live at placement.
"""
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.fields import MoneyField
from apps.common.models import TimeStampedModel


class StoreSettings(TimeStampedModel):
    store_name = models.CharField(max_length=120, default="MicroMart")
    support_email = models.EmailField(blank=True)
    support_phone = models.CharField(max_length=20, blank=True)

    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="VAT percentage applied at checkout. Snapshotted onto each order.",
    )
    tax_inclusive_pricing = models.BooleanField(
        default=False, help_text="True when catalogue prices already include VAT."
    )

    cod_enabled = models.BooleanField(default=True)
    cod_max_order_value = MoneyField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Orders above this cannot use Cash on Delivery. Null disables the cap.",
    )

    low_stock_digest_recipients = models.JSONField(
        default=list,
        blank=True,
        help_text="Email addresses for the cron-invoked low-stock digest.",
    )

    class Meta:
        db_table = "dashboard_store_settings"
        verbose_name_plural = "store settings"

    def __str__(self):
        return self.store_name

    def save(self, *args, **kwargs):
        # Singleton: there is exactly one store.
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Store settings cannot be deleted.")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
