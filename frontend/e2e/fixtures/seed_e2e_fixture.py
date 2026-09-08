"""
The catalogue rows the E2E suite buys from. Executed via `manage.py shell -c`.

Why this exists at all: these tests run against the DEV database, not a test
database, and placing an order permanently decrements stock. Pointing the
buying-path specs at a `seed_demo` product would drain it over a few dozen
runs and then start failing for reasons that are not defects -- and it would
quietly distort the demo catalogue's stock figures along the way. So the suite
buys its own product instead.

Everything is looked up by natural key and topped back up to a floor, so
running this a hundred times leaves exactly one product, two variants and a
stock level the specs can rely on.

**Stock moves through apps.catalog.services.inventory, never by assignment.**
Writing `ProductVariant.stock` directly here would break the append-only
InventoryLog reconciliation (PRD 6.4) that the whole inventory design exists
to protect -- a fixture is not an excuse to bypass the service layer.

Prints one marked line of JSON so the Node side can pick it out of Django's
startup noise.
"""
import base64
import json

from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction

from apps.catalog.models import (
    Category,
    InventoryReason,
    Product,
    ProductImage,
    ProductVariant,
)
from apps.catalog.services import inventory as inventory_services

PRODUCT_SLUG = "e2e-harness-test-device"
PRODUCT_NAME = "E2E Harness Test Device"

# The variant the checkout specs buy. Stocked deep enough that a run never
# runs it down mid-suite, and topped back up on the next run.
BUYABLE_SKU = "E2E-HARNESS-STD"
BUYABLE_PRICE = Decimal("1200.00")
BUYABLE_STOCK_FLOOR = 200

# The variant the cart-rendering spec uses to prove the quantity stepper is
# capped at available stock. Its stock is the assertion, so it is small and
# exact -- and nothing in the suite orders it, so it stays put.
CAPPED_SKU = "E2E-HARNESS-LTD"
CAPPED_PRICE = Decimal("1500.00")
CAPPED_STOCK = 3
# Above the stock, so the detail page shows the "Only 3 left" badge rather
# than a bare "In stock" -- is_low_stock is `0 < stock <= threshold`.
CAPPED_THRESHOLD = 5

# An 8x8 PNG. The cart line renders a real <img> only when the API hands it a
# URL, and the dev database ships with zero ProductImage rows -- so without
# this the image half of the cart contract could not be tested at all.
PNG_8X8 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAJUlEQVR4nGP8z8Dwn4"
    "GKgImaho0aOGrgqIGjBo4aOGrgqIGDwUAAr7EDkfKrJUEAAAAASUVORK5CYII="
)


def ensure_stock(variant, target):
    """Move `variant` to exactly `target` units, through the service layer."""
    delta = target - variant.stock
    if delta == 0:
        return 0
    inventory_services.adjust_stock(
        variant=variant,
        delta=delta,
        reason=(
            InventoryReason.RESTOCK if delta > 0 else InventoryReason.MANUAL_ADJUSTMENT
        ),
        note="E2E harness fixture top-up",
    )
    return delta


with transaction.atomic():
    # Hang the fixture off a category that already exists rather than adding a
    # tile to the storefront's category nav. Deterministic pick, so the
    # product does not wander between runs.
    category = Category.objects.filter(is_active=True).order_by("id").first()
    if category is None:
        category = Category.objects.create(
            name="E2E Fixtures", slug="e2e-fixtures", is_active=True
        )

    product, _ = Product.objects.get_or_create(
        slug=PRODUCT_SLUG,
        defaults={
            "name": PRODUCT_NAME,
            "category": category,
            # Deliberately no brand: one less facet entry perturbed in a
            # catalogue the browse specs also read.
            "brand": None,
            "description": (
                "Fixture product created by the Playwright end-to-end suite. "
                "It exists so the buying-path tests never have to spend the "
                "demo catalogue's stock. Safe to delete; the suite recreates it."
            ),
            "warranty_months": 12,
            "is_active": True,
        },
    )

    # Re-assert the fields a spec asserts on, in case a previous run (or a
    # human poking at the admin) moved them.
    if not product.is_active or product.name != PRODUCT_NAME:
        product.is_active = True
        product.name = PRODUCT_NAME
        product.save(update_fields=["is_active", "name", "updated_at"])

    buyable, _ = ProductVariant.objects.get_or_create(
        sku=BUYABLE_SKU,
        defaults={
            "product": product,
            "option_label": "Standard",
            "price": BUYABLE_PRICE,
            "stock": 0,
            "low_stock_threshold": 5,
            "is_active": True,
        },
    )
    capped, _ = ProductVariant.objects.get_or_create(
        sku=CAPPED_SKU,
        defaults={
            "product": product,
            "option_label": "Limited Edition",
            "price": CAPPED_PRICE,
            "stock": 0,
            "low_stock_threshold": CAPPED_THRESHOLD,
            "is_active": True,
        },
    )

    # Re-assert on every run, not only at creation: get_or_create leaves an
    # existing row exactly as it found it, so a variant seeded by an earlier
    # version of this file would keep values the specs no longer expect.
    for variant, price, threshold in (
        (buyable, BUYABLE_PRICE, 5),
        (capped, CAPPED_PRICE, CAPPED_THRESHOLD),
    ):
        if (
            variant.price != price
            or variant.low_stock_threshold != threshold
            or not variant.is_active
        ):
            variant.price = price
            variant.low_stock_threshold = threshold
            variant.is_active = True
            variant.save(
                update_fields=["price", "low_stock_threshold", "is_active", "updated_at"]
            )

    # Only top up when it has actually been spent, so a normal run writes no
    # inventory rows at all.
    if buyable.stock < BUYABLE_STOCK_FLOOR:
        ensure_stock(buyable, BUYABLE_STOCK_FLOOR)
    ensure_stock(capped, CAPPED_STOCK)

    if not product.images.exists():
        image = ProductImage(
            product=product,
            alt_text="E2E harness fixture image",
            is_primary=True,
            sort_order=0,
        )
        image.image.save("e2e-harness-fixture.png", ContentFile(PNG_8X8), save=True)

    buyable.refresh_from_db()
    capped.refresh_from_db()

    payload = {
        "productSlug": product.slug,
        "productName": product.name,
        # The product's OWN category, not the one just resolved: on a
        # re-run get_or_create leaves an existing product where it is, and
        # a spec that filtered by the resolved slug would look in the
        # wrong place.
        "categorySlug": product.category.slug,
        "buyable": {
            "id": buyable.pk,
            "sku": buyable.sku,
            "label": buyable.option_label,
            "price": str(buyable.price),
            "stock": buyable.stock,
        },
        "capped": {
            "id": capped.pk,
            "sku": capped.sku,
            "label": capped.option_label,
            "price": str(capped.price),
            "stock": capped.stock,
        },
    }

print("E2E_FIXTURE_JSON " + json.dumps(payload))
