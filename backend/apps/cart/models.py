
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import TimeStampedModel


class Cart(models.Model):
    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="cart"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cart_cart"

    def __str__(self):
        return f"Cart for {self.user_id}"

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.CASCADE, related_name="cart_items"
    )
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        db_table = "cart_item"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "variant"], name="unique_cart_variant"
            ),
        ]

    def __str__(self):
        return f"{self.quantity} x variant {self.variant_id}"
