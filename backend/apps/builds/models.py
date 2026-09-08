"""
Saved PC builds (the PC Builder feature).

A build is a *snapshot of intent*, not an order. It records which variants a
shopper picked and what the compatibility checker said at the time. It never
reserves stock and never fixes a price -- prices are re-read from the variant
every time the build is opened, exactly as a cart does, so a build shared in
March does not quote January's price.
"""
import secrets

from django.conf import settings
from django.db import models

from apps.catalog.models import ComponentSlot
from apps.common.models import TimeStampedModel


def generate_share_token():
    # 22 URL-safe chars (~132 bits). Unguessable, so a share link is the
    # capability -- there is no other authorisation on a public build.
    return secrets.token_urlsafe(16)


class PCBuild(TimeStampedModel):
    """
    One saved configuration.

    `user` is nullable so a guest can save and share a build. That is the
    whole point of the share link: the person you send it to is, by
    definition, not signed in as you.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="pc_builds",
    )
    name = models.CharField(max_length=120, default="My build")
    share_token = models.CharField(
        max_length=32, unique=True, default=generate_share_token, editable=False
    )
    # Whether the checker was happy when this was last saved. Advisory only --
    # it is recomputed on every read, because the catalogue may have moved.
    is_compatible = models.BooleanField(default=True)
    estimated_watts = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "builds_pc_build"
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self):
        return f"{self.name} ({self.share_token})"


class PCBuildItem(models.Model):
    """
    One slot of a build.

    Unique on (build, slot): a build holds at most one part per slot, which is
    what makes the builder a form rather than a cart. Storage is the exception
    the UI handles by offering an SSD slot and an HDD slot separately, so the
    constraint still holds.
    """

    build = models.ForeignKey(PCBuild, on_delete=models.CASCADE, related_name="items")
    slot = models.CharField(max_length=16, choices=ComponentSlot.choices)
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.CASCADE, related_name="build_items"
    )
    quantity = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = "builds_pc_build_item"
        ordering = ["slot"]
        constraints = [
            models.UniqueConstraint(fields=["build", "slot"], name="one_part_per_slot"),
        ]

    def __str__(self):
        return f"{self.slot}: variant {self.variant_id}"
