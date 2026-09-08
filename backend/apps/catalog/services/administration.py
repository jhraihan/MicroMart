"""
Catalogue administration (PRD 4.3 US-A2/US-A4, 7.3 /admin/products, /admin/variants,
/admin/categories, /admin/brands, /admin/inventory).

Every rule the admin catalogue enforces lives in this module, for the same
reason services/catalogue.py owns the storefront's rules: the admin API and the
storefront API call the same functions, so a rule cannot hold on one surface
and not the other. Views translate HTTP; serializers shape payloads; nothing
below decides anything.

Four invariants are load-bearing here, and each of them is the thing a naive
CRUD implementation gets wrong:

1. **Stock is not a writable column.** Nothing in this module assigns
   ProductVariant.stock. Every movement goes through
   services/inventory.record_movement, which writes the append-only
   InventoryLog row in the same breath, so `sum(InventoryLog.delta)` keeps
   reconciling to `ProductVariant.stock`. A PATCH carrying `stock` is refused
   (STOCK_NOT_WRITABLE) rather than ignored -- an ignored write looks like it
   worked, and the admin walks away believing a number that never moved.
   The one exception is variant *creation*, where an opening quantity is
   written through the same ledger with reason `initial`, exactly as
   `manage.py import_startech` already does.

2. **Deleting deactivates.** Products, variants, categories and brands all
   answer DELETE by clearing `is_active`. Orders snapshot their lines, so a
   hard delete would not corrupt order history -- but it would drop the
   OrderItem.variant FK the reporting side reads, and PROTECT on
   Product.category would turn a category delete into a 500 the moment the
   category had ever been used.

3. **A product always keeps at least one active variant** (FR-CAT-4). Price
   and stock live on the variant, so a product with none is a product with no
   price -- unbuyable, unlistable, and invisible to every aggregate in
   services/catalogue.py. Creation therefore requires a variant, and the last
   active one cannot be deactivated.

4. **Categories nest one level** (FR-CAT-1). Enforced here rather than only in
   Category.clean(), so the refusal arrives as the {"error": {...}} envelope
   with a stable code instead of a Django ValidationError.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q
from django.utils.text import slugify

from config.exceptions import DomainError

from ..models import (
    Brand,
    Category,
    InventoryReason,
    Product,
    ProductImage,
    ProductSpec,
    ProductVariant,
)
from . import inventory as inventory_services

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 5 MB. Product photography from a phone camera lands well under this; anything
# above it is an unresized original that would cost every shopper on a mobile
# connection (PRD 9.1).
MAX_IMAGE_BYTES = 5 * 1024 * 1024

#: Reasons an admin may select on a manual adjustment. `order_confirmed` and
#: `order_cancelled` are deliberately absent: those two are written by the
#: order state machine and only by it, and a hand-typed one would put a stock
#: movement in the ledger that no order can account for. `initial` is absent
#: for the same reason -- it belongs to variant creation and the importer.
MANUAL_ADJUSTMENT_REASONS = (
    InventoryReason.RESTOCK,
    InventoryReason.MANUAL_ADJUSTMENT,
    InventoryReason.DAMAGE,
)

# Fields update_product will write. Anything else in the payload is a caller
# error, not a silent no-op.
PRODUCT_FIELDS = (
    "name",
    "slug",
    "description",
    "warranty_months",
    "is_active",
)

VARIANT_FIELDS = (
    "sku",
    "option_label",
    "price",
    "compare_at_price",
    "low_stock_threshold",
    "weight_grams",
    "is_active",
)


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------
def unique_slug(model, value, *, fallback="item", exclude_pk=None):
    """
    A slug that is free on `model`, derived from `value`.

    The admin form may leave the slug blank, and a name in Bengali or one made
    entirely of punctuation slugifies to the empty string -- which would then
    collide with every other such product. `fallback` keeps the column
    populated in that case.
    """
    base = slugify(value or "")[:200] or fallback
    candidate = base
    suffix = 2
    while True:
        taken = model.objects.filter(slug=candidate)
        if exclude_pk is not None:
            taken = taken.exclude(pk=exclude_pk)
        if not taken.exists():
            return candidate
        candidate = "{0}-{1}".format(base, suffix)
        suffix += 1


# ---------------------------------------------------------------------------
# Taxonomy -- categories
# ---------------------------------------------------------------------------
def admin_categories():
    """Every category, active or not, with its product count."""
    return (
        Category.objects.select_related("parent")
        .annotate(product_count=Count("products", distinct=True))
        .order_by("sort_order", "name")
    )


def _resolve_parent(parent_id):
    if parent_id in (None, ""):
        return None
    try:
        return Category.objects.get(pk=parent_id)
    except Category.DoesNotExist:
        raise DomainError(
            "That parent category does not exist.",
            code="CATEGORY_NOT_FOUND",
            field="parent_id",
        )


def _assert_one_level(category, parent):
    """
    FR-CAT-1: the taxonomy is exactly two levels deep.

    Three separate ways to break it, and all three have to be refused, because
    the storefront's visibility predicate walks `category -> parent` and stops:
    a grandchild's products would never be withdrawn when the root is
    deactivated.
    """
    if parent is None:
        return
    if category is not None and parent.pk == category.pk:
        raise DomainError(
            "A category cannot be its own parent.",
            code="CATEGORY_SELF_PARENT",
            field="parent_id",
        )
    if parent.parent_id is not None:
        raise DomainError(
            "Categories nest one level deep only, and '{0}' is already a "
            "sub-category.".format(parent.name),
            code="CATEGORY_NESTING_TOO_DEEP",
            field="parent_id",
        )
    if category is not None and category.pk and category.children.exists():
        raise DomainError(
            "'{0}' has sub-categories, so it cannot become one itself.".format(
                category.name
            ),
            code="CATEGORY_HAS_CHILDREN",
            field="parent_id",
        )


@transaction.atomic
def create_category(*, name, slug=None, parent_id=None, sort_order=0, is_active=True,
                    image=None, actor=None):
    parent = _resolve_parent(parent_id)
    _assert_one_level(None, parent)
    category = Category(
        name=name,
        slug=slug or unique_slug(Category, name, fallback="category"),
        parent=parent,
        sort_order=sort_order,
        is_active=is_active,
    )
    if image is not None:
        category.image = image
    _save_unique(category, field="slug", code="SLUG_TAKEN")
    return category


@transaction.atomic
def update_category(category, *, actor=None, **fields):
    if "parent_id" in fields:
        parent = _resolve_parent(fields.pop("parent_id"))
        _assert_one_level(category, parent)
        category.parent = parent
    for name in ("name", "slug", "sort_order", "is_active", "image"):
        if name in fields and fields[name] is not None:
            setattr(category, name, fields[name])
    _save_unique(category, field="slug", code="SLUG_TAKEN")
    return category


@transaction.atomic
def deactivate_category(category, *, actor=None):
    """
    DELETE means deactivate. Product.category is PROTECT, so a real delete is
    a 500 waiting for the first category anyone has used; and a category is a
    place in the navigation, so hiding it withdraws what sits under it
    (the rule services/inventory.is_sellable already implements).
    """
    if category.is_active:
        category.is_active = False
        category.save(update_fields=["is_active", "updated_at"])
    return category


# ---------------------------------------------------------------------------
# Taxonomy -- brands
# ---------------------------------------------------------------------------
def admin_brands():
    return Brand.objects.annotate(
        product_count=Count("products", distinct=True)
    ).order_by("name")


@transaction.atomic
def create_brand(*, name, slug=None, is_active=True, logo=None, actor=None):
    brand = Brand(
        name=name,
        slug=slug or unique_slug(Brand, name, fallback="brand"),
        is_active=is_active,
    )
    if logo is not None:
        brand.logo = logo
    _save_unique(brand, field="slug", code="SLUG_TAKEN")
    return brand


@transaction.atomic
def update_brand(brand, *, actor=None, **fields):
    for name in ("name", "slug", "is_active", "logo"):
        if name in fields and fields[name] is not None:
            setattr(brand, name, fields[name])
    _save_unique(brand, field="slug", code="SLUG_TAKEN")
    return brand


@transaction.atomic
def deactivate_brand(brand, *, actor=None):
    """
    Deactivate, never delete. Product.brand is SET_NULL, so a hard delete would
    quietly strip the brand off every product carrying it -- and unlike a
    category, an inactive brand does not withdraw its products from sale; it
    only leaves the brand facet.
    """
    if brand.is_active:
        brand.is_active = False
        brand.save(update_fields=["is_active", "updated_at"])
    return brand


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
def admin_products(query=None):
    """
    The admin product list: every product, active or not, with the aggregates
    the list screen renders.

    Deliberately a *constant* number of queries regardless of page size --
    aggregates are annotations and the two child collections are prefetches,
    so a 24-row page costs what a 1-row page costs (PRD 9.1, and the bar
    apps/cart/tests/test_query_counts.py sets).
    """
    queryset = (
        Product.objects.select_related("category", "category__parent", "brand")
        .annotate(
            variant_count=Count("variants", distinct=True),
            active_variant_count=Count(
                "variants", filter=Q(variants__is_active=True), distinct=True
            ),
            image_count=Count("images", distinct=True),
        )
        .prefetch_related(
            Prefetch(
                "variants",
                queryset=ProductVariant.objects.order_by("price", "id"),
            ),
            Prefetch(
                "images",
                queryset=ProductImage.objects.order_by("-is_primary", "sort_order", "id"),
            ),
        )
    )
    if query is None:
        return queryset.order_by("-created_at", "-id")

    # Every variant-shaped filter below is an EXISTS subquery rather than a
    # join, for the reason services/catalogue.py states at the top: a join to a
    # multi-valued relation multiplies rows, which would both need .distinct()
    # and quietly deflate the Count(...) annotations above -- a product with
    # four variants would report `variant_count: 1` the moment someone searched
    # for one of its SKUs.
    if query.q:
        matching_sku = ProductVariant.objects.filter(
            product_id=OuterRef("pk"), sku__icontains=query.q
        )
        queryset = queryset.filter(
            Q(name__icontains=query.q)
            | Q(slug__icontains=query.q)
            | Q(Exists(matching_sku))
        )
    if query.category:
        queryset = queryset.filter(
            Q(category__slug=query.category) | Q(category__parent__slug=query.category)
        )
    if query.brand:
        queryset = queryset.filter(brand__slug=query.brand)
    if query.is_active is not None:
        queryset = queryset.filter(is_active=query.is_active)
    if query.low_stock:
        running_low = ProductVariant.objects.filter(
            product_id=OuterRef("pk"),
            is_active=True,
            stock__lte=F("low_stock_threshold"),
        )
        queryset = queryset.filter(Exists(running_low))

    return queryset.order_by(*_PRODUCT_ORDERINGS[query.sort])


_PRODUCT_ORDERINGS = {
    "newest": ("-created_at", "-id"),
    "oldest": ("created_at", "id"),
    "name": ("name", "id"),
    "updated": ("-updated_at", "-id"),
}


def admin_product_detail_queryset():
    return admin_products().prefetch_related("specs")


def _resolve_category(category_id, *, required=True):
    if category_id in (None, ""):
        if required:
            raise DomainError(
                "A product needs a category.",
                code="CATEGORY_REQUIRED",
                field="category_id",
            )
        return None
    try:
        return Category.objects.get(pk=category_id)
    except Category.DoesNotExist:
        raise DomainError(
            "That category does not exist.",
            code="CATEGORY_NOT_FOUND",
            field="category_id",
        )


def _resolve_brand(brand_id):
    if brand_id in (None, ""):
        return None
    try:
        return Brand.objects.get(pk=brand_id)
    except Brand.DoesNotExist:
        raise DomainError(
            "That brand does not exist.", code="BRAND_NOT_FOUND", field="brand_id"
        )


@transaction.atomic
def create_product(*, name, category_id, variants, brand_id=None, slug=None,
                   description="", warranty_months=0, is_active=True, specs=None,
                   actor=None):
    """
    Create a product together with its opening variants (US-A2).

    **A product with no variants is refused, not auto-filled.** FR-CAT-4 says a
    product without options carries a single *default* variant -- but a default
    variant still needs a price and an SKU, and neither can be invented
    server-side without putting a placeholder into the catalogue that would
    eventually be snapshotted onto a real order line. So the caller supplies at
    least one, and a product with no options simply sends one variant with a
    blank `option_label`.
    """
    if not variants:
        raise DomainError(
            "A product needs at least one variant -- price and stock live on "
            "the variant. A product without options takes a single default one.",
            code="PRODUCT_REQUIRES_VARIANT",
            field="variants",
        )

    category = _resolve_category(category_id)
    brand = _resolve_brand(brand_id)

    product = Product(
        category=category,
        brand=brand,
        name=name,
        slug=slug or unique_slug(Product, name, fallback="product"),
        description=description or "",
        warranty_months=warranty_months or 0,
        is_active=is_active,
    )
    _save_unique(product, field="slug", code="SLUG_TAKEN")

    replace_specs(product, specs or [])
    for spec in variants:
        create_variant(product=product, actor=actor, **spec)

    return product


@transaction.atomic
def update_product(product, *, actor=None, specs=None, **fields):
    if "category_id" in fields:
        product.category = _resolve_category(fields.pop("category_id"))
    if "brand_id" in fields:
        product.brand = _resolve_brand(fields.pop("brand_id"))

    for name in PRODUCT_FIELDS:
        if name in fields and fields[name] is not None:
            setattr(product, name, fields[name])

    _save_unique(product, field="slug", code="SLUG_TAKEN")

    # Specs are a list, so "present in the payload" means "replace the whole
    # table". Omitting the key leaves the existing rows alone; sending [] is
    # how the admin clears them.
    if specs is not None:
        replace_specs(product, specs)

    return product


@transaction.atomic
def deactivate_product(product, *, actor=None):
    """
    DELETE /admin/products/{id}/ -- deactivate (FR-CAT-7), never destroy.

    Placed orders snapshot product name, variant label, SKU and unit price, so
    a deactivated product cannot rewrite anything already sold; the point of
    keeping the row is that the OrderItem.variant FK, the review history and
    the inventory ledger all stay attached to something real.
    """
    if product.is_active:
        product.is_active = False
        product.save(update_fields=["is_active", "updated_at"])
    return product


def replace_specs(product, specs):
    """Swap the whole specification table for the given rows (US-A2)."""
    product.specs.all().delete()
    ProductSpec.objects.bulk_create(
        [
            ProductSpec(
                product=product,
                key=row["key"],
                value=row["value"],
                sort_order=row.get("sort_order", index),
            )
            for index, row in enumerate(specs)
        ]
    )
    return product.specs.all()


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------
def admin_variants(query=None):
    queryset = ProductVariant.objects.select_related(
        "product", "product__brand", "product__category"
    )
    if query is None:
        return queryset.order_by("product__name", "price", "id")
    return _apply_variant_filters(queryset, query).order_by(
        *(("stock", "product__name", "id") if query.low_stock
          else ("product__name", "price", "id"))
    )


def _apply_variant_filters(queryset, query):
    if not query.include_inactive:
        queryset = queryset.filter(is_active=True, product__is_active=True)
    if query.q:
        queryset = queryset.filter(
            Q(sku__icontains=query.q) | Q(product__name__icontains=query.q)
        )
    if query.category:
        queryset = queryset.filter(
            Q(product__category__slug=query.category)
            | Q(product__category__parent__slug=query.category)
        )
    if query.product_id is not None:
        queryset = queryset.filter(product_id=query.product_id)
    if query.low_stock:
        queryset = queryset.filter(stock__lte=F("low_stock_threshold"))
    return queryset


def _assert_sku_free(sku, *, exclude_pk=None):
    taken = ProductVariant.objects.filter(sku=sku)
    if exclude_pk is not None:
        taken = taken.exclude(pk=exclude_pk)
    if taken.exists():
        raise DomainError(
            "SKU '{0}' is already in use.".format(sku),
            code="SKU_TAKEN",
            field="sku",
        )


def _clean_sku(sku):
    sku = (sku or "").strip()
    if not sku:
        raise DomainError(
            "A variant needs an SKU.", code="SKU_REQUIRED", field="sku"
        )
    return sku


def _assert_price_sane(price, compare_at_price):
    if price is not None and Decimal(price) < 0:
        raise DomainError(
            "Price cannot be negative.", code="INVALID_PRICE", field="price"
        )
    if compare_at_price is not None and Decimal(compare_at_price) < 0:
        raise DomainError(
            "Compare-at price cannot be negative.",
            code="INVALID_PRICE",
            field="compare_at_price",
        )


@transaction.atomic
def create_variant(*, product, sku, price, actor=None, stock=0, option_label="",
                   compare_at_price=None, low_stock_threshold=5, weight_grams=0,
                   is_active=True):
    """
    Add a variant, and write its opening stock through the ledger.

    `stock` is accepted *here alone*. It is not assigned to the column: it goes
    through inventory.record_movement with reason `initial`, so a variant that
    opens at 12 units has a +12 row behind it and the ledger reconciles from
    the very first second of its life. Every later movement arrives through
    /admin/inventory/adjust/.
    """
    sku = _clean_sku(sku)
    _assert_sku_free(sku)
    _assert_price_sane(price, compare_at_price)

    opening = int(stock or 0)
    if opening < 0:
        raise DomainError(
            "Opening stock cannot be negative.",
            code="INVALID_STOCK",
            field="stock",
        )

    variant = ProductVariant(
        product=product,
        sku=sku,
        option_label=option_label or "",
        price=price,
        compare_at_price=compare_at_price,
        stock=0,
        low_stock_threshold=low_stock_threshold if low_stock_threshold is not None else 5,
        weight_grams=weight_grams or 0,
        is_active=is_active,
    )
    _save_unique(variant, field="sku", code="SKU_TAKEN")

    if opening:
        inventory_services.record_movement(
            variant=variant,
            delta=opening,
            reason=InventoryReason.INITIAL,
            actor=actor,
            note="Opening stock for {0}".format(variant.sku),
        )
    return variant


@transaction.atomic
def update_variant(variant, *, actor=None, **fields):
    """
    Edit a variant's price, SKU, label and low-stock threshold.

    `stock` is refused outright. It is the one column on this model that has an
    append-only ledger behind it, and a PATCH that set it directly would leave
    `sum(InventoryLog.delta)` disagreeing with `ProductVariant.stock` forever
    after -- silently, and with no row saying who moved it or why. Quietly
    dropping the key would be worse than refusing it: the admin would read the
    200, believe the number changed, and stop looking.
    """
    if "stock" in fields:
        raise DomainError(
            "Stock is not editable here. Use /api/v1/admin/inventory/adjust/, "
            "which records the movement and its reason.",
            code="STOCK_NOT_WRITABLE",
            field="stock",
        )

    if "sku" in fields and fields["sku"] is not None:
        fields["sku"] = _clean_sku(fields["sku"])
        _assert_sku_free(fields["sku"], exclude_pk=variant.pk)

    _assert_price_sane(fields.get("price"), fields.get("compare_at_price"))

    # A variant is only allowed to leave circulation while another one is still
    # carrying the product's price.
    if fields.get("is_active") is False and variant.is_active:
        _assert_not_last_active_variant(variant)

    for name in VARIANT_FIELDS:
        if name in fields:
            value = fields[name]
            if value is None and name not in ("compare_at_price",):
                continue
            setattr(variant, name, value)

    _save_unique(variant, field="sku", code="SKU_TAKEN")
    return variant


def _assert_not_last_active_variant(variant):
    siblings = ProductVariant.objects.filter(
        product_id=variant.product_id, is_active=True
    ).exclude(pk=variant.pk)
    if not siblings.exists():
        raise DomainError(
            "This is the product's only active variant. Every product keeps at "
            "least one, because price and stock live on the variant -- add a "
            "replacement first, or deactivate the product instead.",
            code="LAST_VARIANT",
            field="variant_id",
        )


@transaction.atomic
def deactivate_variant(variant, *, actor=None):
    """DELETE /admin/variants/{id}/ -- deactivate, and never the last one."""
    if variant.is_active:
        _assert_not_last_active_variant(variant)
        variant.is_active = False
        variant.save(update_fields=["is_active", "updated_at"])
    return variant


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
def product_images(product):
    return product.images.select_related("variant").order_by("sort_order", "id")


def _assert_image_acceptable(upload):
    if upload is None:
        raise DomainError(
            "An image file is required.", code="IMAGE_REQUIRED", field="image"
        )
    size = getattr(upload, "size", None)
    if size is not None and size > MAX_IMAGE_BYTES:
        raise DomainError(
            "Images must be {0} MB or smaller.".format(MAX_IMAGE_BYTES // (1024 * 1024)),
            code="IMAGE_TOO_LARGE",
            field="image",
        )


def _resolve_variant_for_image(product, variant_id):
    if variant_id in (None, ""):
        return None
    variant = ProductVariant.objects.filter(
        pk=variant_id, product_id=product.pk
    ).first()
    if variant is None:
        raise DomainError(
            "That variant does not belong to this product.",
            code="VARIANT_NOT_FOUND",
            field="variant_id",
        )
    return variant


@transaction.atomic
def add_product_image(product, *, image, alt_text="", variant_id=None,
                      is_primary=False, sort_order=None, actor=None):
    """
    Attach one image (US-A2: multiple, reorderable, one primary).

    The file itself is proved to be an image by the serializer's ImageField,
    which opens it with Pillow -- a .txt renamed to .jpg never reaches here.
    Size is capped in this module because it is a catalogue policy, not a
    parsing rule.
    """
    _assert_image_acceptable(image)
    variant = _resolve_variant_for_image(product, variant_id)

    if sort_order is None:
        last = product.images.order_by("-sort_order").first()
        sort_order = 0 if last is None else last.sort_order + 1

    row = ProductImage.objects.create(
        product=product,
        variant=variant,
        image=image,
        alt_text=alt_text or "",
        sort_order=sort_order,
        is_primary=False,
    )
    _settle_primary(product, prefer_id=row.pk if is_primary else None)
    row.refresh_from_db()
    return row


@transaction.atomic
def reorder_product_images(product, *, order, primary_id=None, actor=None):
    """
    Re-sequence a product's images.

    Only `sort_order` moves. The primary flag is a separate decision and is
    left exactly where it was unless `primary_id` names a new one -- a reorder
    that silently promoted whatever landed first would make "primary" mean
    "top-left in the last drag", which is not what it means anywhere else.
    """
    existing = list(product.images.all())
    known = {row.pk for row in existing}
    requested = [int(value) for value in order]

    if len(set(requested)) != len(requested):
        raise DomainError(
            "The same image is listed twice.",
            code="IMAGE_ORDER_DUPLICATE",
            field="order",
        )
    unknown = [pk for pk in requested if pk not in known]
    if unknown:
        raise DomainError(
            "Image {0} does not belong to this product.".format(unknown[0]),
            code="IMAGE_NOT_FOUND",
            field="order",
        )
    if set(requested) != known:
        raise DomainError(
            "The new order must list every one of this product's {0} images.".format(
                len(known)
            ),
            code="IMAGE_ORDER_INCOMPLETE",
            field="order",
        )

    by_id = {row.pk: row for row in existing}
    for position, pk in enumerate(requested):
        row = by_id[pk]
        if row.sort_order != position:
            row.sort_order = position
            row.save(update_fields=["sort_order", "updated_at"])

    _settle_primary(product, prefer_id=primary_id)
    return product_images(product)


@transaction.atomic
def set_primary_image(product, image_id, *, actor=None):
    if not product.images.filter(pk=image_id).exists():
        raise DomainError(
            "That image does not belong to this product.",
            code="IMAGE_NOT_FOUND",
            field="primary_id",
        )
    _settle_primary(product, prefer_id=image_id)
    return product_images(product)


@transaction.atomic
def delete_product_image(product, image_id, *, actor=None):
    """
    Remove one image for real -- an image is not snapshotted onto an order, so
    there is nothing historical to preserve. If it was the primary, the next
    image in order inherits the flag rather than the product losing its card
    photo.
    """
    row = product.images.filter(pk=image_id).first()
    if row is None:
        raise DomainError(
            "That image does not belong to this product.",
            code="IMAGE_NOT_FOUND",
            field="image_id",
        )
    row.delete()
    _settle_primary(product)
    return product_images(product)


def _settle_primary(product, *, prefer_id=None):
    """
    Exactly one primary image while a product has any (FR-CAT list cards read
    it, and ProductListSerializer.get_primary_image falls back to the first
    image only because this can transiently be empty during an import).
    """
    rows = list(product.images.order_by("sort_order", "id"))
    if not rows:
        return

    chosen = None
    if prefer_id is not None:
        chosen = next((row for row in rows if row.pk == int(prefer_id)), None)
    if chosen is None:
        chosen = next((row for row in rows if row.is_primary), None)
    if chosen is None:
        chosen = rows[0]

    for row in rows:
        wanted = row.pk == chosen.pk
        if row.is_primary != wanted:
            row.is_primary = wanted
            row.save(update_fields=["is_primary", "updated_at"])


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
def inventory_rows(query):
    """
    GET /admin/inventory/ -- stock across variants, with a low-stock filter
    (US-A4).

    The low-stock arm is `inventory.low_stock_variants()` verbatim when no
    other filter narrows it, so the number the dashboard alerts on and the
    number this list shows can never disagree.
    """
    queryset = ProductVariant.objects.select_related(
        "product", "product__brand", "product__category"
    )
    return _apply_variant_filters(queryset, query).order_by(
        *(("stock", "product__name", "id") if query.low_stock
          else ("product__name", "sku", "id"))
    )


def inventory_summary():
    """Counts the inventory screen leads with, over the whole catalogue."""
    sellable = ProductVariant.objects.filter(is_active=True, product__is_active=True)
    return {
        "variant_count": sellable.count(),
        "low_stock_count": inventory_services.low_stock_variants().count(),
        "out_of_stock_count": sellable.filter(stock__lte=0).count(),
    }


def get_variant_for_adjustment(variant_id):
    variant = ProductVariant.objects.select_related("product").filter(
        pk=variant_id
    ).first()
    if variant is None:
        raise DomainError(
            "That variant does not exist.",
            code="VARIANT_NOT_FOUND",
            field="variant_id",
        )
    return variant


@transaction.atomic
def apply_manual_adjustment(*, variant_id, delta, reason, actor=None, note=""):
    """
    POST /admin/inventory/adjust/ -- a manual movement with a mandatory reason
    (FR-INV-8).

    Delegates the movement itself to inventory.adjust_stock, which takes the
    row lock and writes the InventoryLog row. What this function adds is the
    admin-surface policy: which reasons a human may pick, and that a no-op
    adjustment is a mistake rather than a success.
    """
    variant = get_variant_for_adjustment(variant_id)

    if not reason:
        raise DomainError(
            "A reason is required for a manual stock adjustment.",
            code="REASON_REQUIRED",
            field="reason",
        )
    if reason not in [choice.value for choice in MANUAL_ADJUSTMENT_REASONS]:
        raise DomainError(
            "reason must be one of: {0}. Order-driven movements are written by "
            "the order service, not by hand.".format(
                ", ".join(choice.value for choice in MANUAL_ADJUSTMENT_REASONS)
            ),
            code="INVALID_REASON",
            field="reason",
        )

    delta = int(delta)
    if delta == 0:
        raise DomainError(
            "An adjustment of zero moves nothing.",
            code="INVALID_DELTA",
            field="delta",
        )

    log = inventory_services.adjust_stock(
        variant=variant, delta=delta, reason=reason, actor=actor, note=note or ""
    )
    variant.refresh_from_db()
    return variant, log


def variant_ledger(variant, *, limit=50):
    """Recent movements for one variant -- the audit trail beside the number."""
    return variant.inventory_logs.select_related("actor", "order").order_by(
        "-created_at", "-id"
    )[:limit]


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------
def _save_unique(instance, *, field, code):
    """
    Save, turning a lost unique-index race into a per-field 422.

    The application checks for a duplicate first, but two admins saving the
    same SKU a millisecond apart both pass that check and one of them hits the
    index. An IntegrityError reaching the handler is a 500; this makes it the
    same field error the first admin would have seen.
    """
    try:
        with transaction.atomic():
            instance.save()
    except IntegrityError:
        raise DomainError(
            "That {0} is already in use.".format(field),
            code=code,
            field=field,
        )
    return instance
