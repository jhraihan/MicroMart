"""
Reviews and wishlist (PRD §5.8, §5.9, §6.4).

A review requires a delivered order containing the product -- order_fk is what
proves the purchase, and the check is enforced server-side, never merely hidden
in the UI. Only approved reviews count toward Product.rating_avg /
rating_count.
"""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import TimeStampedModel

# A review may be edited by its author within this window (PRD §5.8).
REVIEW_EDIT_WINDOW_DAYS = 30


class ReviewStatus(models.TextChoices):
    PENDING = "pending", "Pending moderation"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class Review(TimeStampedModel):
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="reviews"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="reviews"
    )
    order = models.ForeignKey(
        "orders.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviews",
        help_text="The delivered order that proves the purchase.",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=150, blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderated_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="moderated_reviews",
    )

    class Meta:
        db_table = "reviews_review"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "user"], name="unique_review_per_product_user"
            ),
        ]
        indexes = [
            models.Index(fields=["product", "status"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.rating}* on product {self.product_id}"

    @property
    def is_editable(self):
        from datetime import timedelta

        from django.utils import timezone

        return timezone.now() - self.created_at <= timedelta(
            days=REVIEW_EDIT_WINDOW_DAYS
        )


class WishlistItem(models.Model):
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="wishlist_items"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="wishlist_items"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "reviews_wishlist_item"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "product"], name="unique_wishlist_user_product"
            ),
        ]

    def __str__(self):
        return f"user {self.user_id} -> product {self.product_id}"
