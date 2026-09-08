"""
Catalogue entities (PRD §6.2).

The load-bearing rule here: price and stock live on ProductVariant, never on
Product. Every product has at least one variant -- a default one when it has no
real options -- so pricing and stock logic never branches on "does this product
have variants".
"""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.fields import MoneyField
from apps.common.models import TimeStampedModel


class Category(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    image = models.ImageField(upload_to="categories/", blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "catalog_category"
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"
        indexes = [models.Index(fields=["parent", "is_active"])]

    def __str__(self):
        return self.name

    def clean(self):
        # One level of nesting only -- a child may not itself have a parent.
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError({"parent": "A category cannot be its own parent."})
            if self.parent.parent_id is not None:
                raise ValidationError({"parent": "Categories nest one level deep only."})
            if self.pk and self.children.exists():
                raise ValidationError(
                    {"parent": "This category has children, so it cannot become a child."}
                )


class Brand(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    logo = models.ImageField(upload_to="brands/", blank=True, null=True)
    # Same provenance rule as ProductImage. A brand logo is additionally a
    # *trademark*, which copyright licensing does not touch: it is shown here
    # to identify the manufacturer whose goods are being sold, which is
    # nominative use, and never as this store's own mark.
    logo_source_url = models.URLField(max_length=500, blank=True)
    logo_license_name = models.CharField(max_length=80, blank=True)
    logo_attribution = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "catalog_brand"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(TimeStampedModel):
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True)
    description = models.TextField(blank=True)
    # The manufacturer's own model designation ("FX507ZC4-HN109"). Distinct
    # from SKU, which is ours and lives on the variant: shoppers search and
    # compare on the model number, warranty claims quote it, and it is the
    # one identifier that survives a re-SKU.
    model_number = models.CharField(max_length=120, blank=True, db_index=True)
    # Scannable selling points for the top of the detail page, ahead of the
    # full spec table. A list of plain strings; empty is normal.
    highlights = models.JSONField(default=list, blank=True)
    warranty_months = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # Merchandising flag the storefront rows read (`?featured=true`). Kept off
    # `is_active` on purpose -- featuring is an editorial choice, visibility is
    # not.
    is_featured = models.BooleanField(default=False, db_index=True)

    # Denormalised for list performance; recomputed on review approval only.
    rating_avg = models.DecimalField(
        max_digits=3, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    rating_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "catalog_product"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["brand", "is_active"]),
            models.Index(fields=["-created_at"]),
            models.Index(fields=["is_featured", "is_active"]),
        ]

    def __str__(self):
        return self.name

    @property
    def default_variant(self):
        return self.variants.filter(is_active=True).order_by("price", "id").first()


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, unique=True)
    option_label = models.CharField(
        max_length=120,
        blank=True,
        help_text="e.g. 8GB / 512GB / Space Grey. Blank for a default variant.",
    )
    price = MoneyField(validators=[MinValueValidator(0)])
    compare_at_price = MoneyField(null=True, blank=True, validators=[MinValueValidator(0)])
    stock = models.IntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    weight_grams = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "catalog_product_variant"
        ordering = ["price", "id"]
        indexes = [
            models.Index(fields=["product", "is_active"]),
            models.Index(fields=["stock"]),
        ]
        constraints = [
            # Database-level backstop under the application's oversell guard
            # (PRD §6.5). The service layer's SELECT ... FOR UPDATE is the
            # primary defence; this catches anything that bypasses it.
            models.CheckConstraint(
                condition=models.Q(stock__gte=0), name="variant_stock_non_negative"
            ),
        ]

    def __str__(self):
        return f"{self.sku} ({self.option_label or 'default'})"

    @property
    def label(self):
        return self.option_label or "Default"

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def is_low_stock(self):
        return 0 < self.stock <= self.low_stock_threshold

    @property
    def discount_percent(self):
        if not self.compare_at_price or self.compare_at_price <= self.price:
            return 0
        return int(
            round((self.compare_at_price - self.price) / self.compare_at_price * 100)
        )


class ProductImage(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="images",
        help_text="Variant-specific image. Falls back to product images when null.",
    )
    image = models.ImageField(upload_to="products/%Y/%m/")
    alt_text = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    # --- Provenance ---
    #
    # Filled in when an image comes from an external library (Wikimedia
    # Commons) rather than being shot or generated by the store. CC BY and
    # CC BY-SA both *require* the author and licence to be shown wherever the
    # work is used, so this is not metadata for its own sake -- it is the
    # condition on which the image may legally appear at all. An image with a
    # blank `source_url` is the store's own and needs no credit.
    source_url = models.URLField(max_length=500, blank=True)
    license_name = models.CharField(max_length=80, blank=True)
    attribution = models.CharField(
        max_length=255, blank=True, help_text="Author, as the licence requires it to be shown."
    )

    class Meta:
        db_table = "catalog_product_image"
        ordering = ["sort_order", "id"]
        indexes = [models.Index(fields=["product", "sort_order"])]

    def __str__(self):
        return f"Image for product {self.product_id}"


class ProductSpec(models.Model):
    """
    Renders the specification table on the product detail page.

    `group` is what makes the table readable on a 45-row laptop listing: rows
    are banded under a heading ("General", "Performance", "Display") instead
    of running as one undifferentiated list. It is a free-text label rather
    than a choices field precisely because the groups differ per category --
    a monitor has "Panel", a PSU has "Efficiency", and neither wants the
    other's vocabulary. An empty group is legal and renders under a single
    unnamed band, so nothing has to be backfilled.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="specs")
    group = models.CharField(max_length=80, blank=True)
    key = models.CharField(max_length=120)
    value = models.CharField(max_length=500)
    # Ordering is (group_order, sort_order) so a group stays contiguous even
    # when its rows were entered out of order.
    group_order = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "catalog_product_spec"
        ordering = ["group_order", "sort_order", "id"]

    def __str__(self):
        return f"{self.key}: {self.value}"


class InventoryReason(models.TextChoices):
    ORDER_CONFIRMED = "order_confirmed", "Order confirmed"
    ORDER_CANCELLED = "order_cancelled", "Order cancelled"
    RESTOCK = "restock", "Restock"
    MANUAL_ADJUSTMENT = "manual_adjustment", "Manual adjustment"
    DAMAGE = "damage", "Damage / loss"
    INITIAL = "initial", "Initial stock"


class InventoryLog(models.Model):
    """
    Append-only. Every stock movement writes a row, and summing deltas must
    reconcile to the variant's current stock -- a cheap integrity check
    (PRD §6.4).
    """

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="inventory_logs"
    )
    delta = models.IntegerField(help_text="Negative for a decrement.")
    reason = models.CharField(max_length=32, choices=InventoryReason.choices)
    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inventory_logs",
    )
    order = models.ForeignKey(
        "orders.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inventory_logs",
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "catalog_inventory_log"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["variant", "-created_at"])]

    def __str__(self):
        return f"variant {self.variant_id} {self.delta:+d} ({self.reason})"


class ComponentSlot(models.TextChoices):
    """
    The PC-builder slots a product can occupy.

    A slot is *not* a category. Categories are navigation and are free to be
    renamed, nested or merged by whoever runs the shop; a slot is the key the
    compatibility rules are written against, so it has to be a closed set the
    code can switch on.
    """

    CPU = "cpu", "Processor"
    COOLER = "cooler", "CPU cooler"
    MOTHERBOARD = "motherboard", "Motherboard"
    RAM = "ram", "Memory"
    GPU = "gpu", "Graphics card"
    SSD = "ssd", "SSD"
    HDD = "hdd", "Hard drive"
    PSU = "psu", "Power supply"
    CASE = "case", "Case"
    MONITOR = "monitor", "Monitor"
    KEYBOARD = "keyboard", "Keyboard"
    MOUSE = "mouse", "Mouse"


class ComponentProfile(models.Model):
    """
    Machine-readable build attributes for a product that can go in a PC.

    These are deliberately *separate* from ProductSpec. A spec row is prose
    aimed at a human ("DDR5 5600MHz, 2x16GB"); these are normalised scalars
    the compatibility rules compare. Parsing the former to get the latter is
    how build checkers end up quietly wrong, so the two are stored apart and
    the seed writes both.

    Every field is optional. A profile with only `slot` set is valid and
    simply participates in no compatibility rule -- which is exactly right for
    a mouse.
    """

    product = models.OneToOneField(
        Product, on_delete=models.CASCADE, related_name="component"
    )
    slot = models.CharField(max_length=16, choices=ComponentSlot.choices, db_index=True)

    # --- CPU / motherboard ---
    socket = models.CharField(
        max_length=32, blank=True, help_text="AM5, LGA1700, ... (CPU and motherboard)"
    )
    # A cooler fits many sockets, so it carries a list rather than one value.
    supported_sockets = models.JSONField(default=list, blank=True)

    # --- Memory ---
    ram_type = models.CharField(max_length=16, blank=True, help_text="DDR4, DDR5")
    ram_slots = models.PositiveSmallIntegerField(null=True, blank=True)
    max_ram_gb = models.PositiveIntegerField(null=True, blank=True)
    capacity_gb = models.PositiveIntegerField(
        null=True, blank=True, help_text="Total capacity of a memory kit or drive."
    )
    module_count = models.PositiveSmallIntegerField(null=True, blank=True)

    # --- Physical fit ---
    form_factor = models.CharField(
        max_length=24, blank=True, help_text="ATX, Micro-ATX, Mini-ITX (motherboard)"
    )
    supported_form_factors = models.JSONField(
        default=list, blank=True, help_text="What a case accepts."
    )
    length_mm = models.PositiveIntegerField(
        null=True, blank=True, help_text="Card length (GPU)."
    )
    max_gpu_length_mm = models.PositiveIntegerField(
        null=True, blank=True, help_text="Longest card a case takes."
    )
    height_mm = models.PositiveIntegerField(
        null=True, blank=True, help_text="Cooler height."
    )
    max_cooler_height_mm = models.PositiveIntegerField(null=True, blank=True)

    # --- Power ---
    # `power_watts` is what this part *draws*; `wattage` is what a PSU
    # *supplies*. Two names because conflating them is the classic bug.
    power_watts = models.PositiveIntegerField(null=True, blank=True)
    tdp_watts = models.PositiveIntegerField(null=True, blank=True)
    cooler_max_tdp_watts = models.PositiveIntegerField(null=True, blank=True)
    wattage = models.PositiveIntegerField(null=True, blank=True)
    efficiency_rating = models.CharField(
        max_length=24, blank=True, help_text="80+ Bronze, 80+ Gold, ..."
    )

    class Meta:
        db_table = "catalog_component_profile"
        indexes = [
            models.Index(fields=["slot", "socket"]),
            models.Index(fields=["slot", "ram_type"]),
        ]

    def __str__(self):
        return f"{self.product_id} ({self.slot})"
