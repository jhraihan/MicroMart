"""
Load the catalogue scraped by `scripts/scrape_startech.py` into the database.

Development seeding only -- it fills the storefront with a realistic BDT
catalogue so listing, filtering, search and the admin tables can be exercised
against real volume. Run the scraper first:

    python scripts/scrape_startech.py --per-category 8
    python manage.py import_startech

Idempotent: every row is looked up by its natural key (category slug, brand
slug, product slug, variant SKU). Re-running refreshes names, prices, specs and
images but never resets stock you have deliberately changed -- stock is only
written when a variant is first created, and then through an InventoryLog row
so the ledger reconciles from the start.
"""
import json
import zlib
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.catalog.models import (
    Brand,
    Category,
    InventoryLog,
    InventoryReason,
    Product,
    ProductImage,
    ProductSpec,
    ProductVariant,
)

User = get_user_model()

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[4] / "scripts" / "data"

# Source stock is a label, not a number. Anything that is not on the shelf right
# now imports as zero so the oversell guard and the low-stock digest have
# something honest to work with.
IN_STOCK_LABELS = ("in stock",)
STOCK_MIN, STOCK_MAX = 4, 45


def stock_for(slug: str, status: str) -> int:
    """
    Deterministic pseudo-stock for an in-stock product.

    Derived from the slug rather than random so a re-import of an unchanged
    catalogue produces the same numbers and does not churn the ledger.
    """
    if not any(label in status.lower() for label in IN_STOCK_LABELS):
        return 0
    return STOCK_MIN + zlib.crc32(slug.encode()) % (STOCK_MAX - STOCK_MIN + 1)


def build_description(product: dict, category_name: str | None) -> str:
    """
    A factual description assembled from the scraped key-feature bullets.

    The source site's marketing prose is deliberately not copied; what lands
    here is the specification summary plus a one-line lead.
    """
    brand = product.get("brand") or ""
    noun = category_name.lower() if category_name else "product"
    lead = f"{product['name']} is a {noun}"
    lead += f" from {brand}." if brand else "."

    features = [f for f in product.get("features") or [] if f]
    if not features:
        return lead
    bullets = "\n".join(f"- {feature}" for feature in features)
    return f"{lead}\n\nKey features:\n{bullets}"


def sku_for(product: dict) -> str:
    code = (product.get("code") or "").strip()
    if not code:
        code = str(zlib.crc32(product["slug"].encode()))
    return f"ST-{code}"[:64]


class Command(BaseCommand):
    help = "Import the scraped startech.com.bd catalogue (development seeding)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            default=str(DEFAULT_DATA_DIR),
            help="Directory holding startech_catalog.json and images/.",
        )
        parser.add_argument(
            "--limit", type=int, default=None, help="Import only the first N products."
        )
        parser.add_argument(
            "--no-images", action="store_true", help="Skip attaching product photos."
        )
        parser.add_argument(
            "--prune-empty-categories",
            action="store_true",
            help="Deactivate imported categories that ended up with no products.",
        )
        parser.add_argument(
            "--flush",
            action="store_true",
            help=(
                "Delete every product, variant, brand and category first. Order "
                "history survives (OrderItem snapshots its data), but carts and "
                "reviews referencing those products do not."
            ),
        )

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"])
        payload_path = data_dir / "startech_catalog.json"
        if not payload_path.exists():
            raise CommandError(
                f"{payload_path} not found -- run scripts/scrape_startech.py first."
            )
        payload = json.loads(payload_path.read_text(encoding="utf-8"))

        products = payload.get("products", [])
        if options["limit"]:
            products = products[: options["limit"]]

        self.stdout.write(
            f"Loaded {payload_path.name}: {len(payload.get('categories', []))} categories, "
            f"{len(products)} products (scraped {payload.get('scraped_at', 'unknown')})."
        )

        if options["flush"]:
            self._flush()

        actor = User.objects.filter(is_superuser=True).order_by("id").first()

        with transaction.atomic():
            categories = self._import_categories(payload.get("categories", []))
            brands = self._import_brands(payload.get("brands", []), products)

        # Images are written outside the single big transaction so a failure
        # part-way through does not roll back thousands of rows of catalogue.
        created, updated, skipped = self._import_products(
            products,
            categories,
            brands,
            actor,
            data_dir,
            attach_images=not options["no_images"],
        )

        if options["prune_empty_categories"]:
            self._prune_empty_categories(categories)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. products: {created} created, {updated} updated, {skipped} skipped."
            )
        )
        self.stdout.write(
            "  This is scraped third-party data for development only -- do not "
            "ship it as production catalogue content."
        )

    # ------------------------------------------------------------------
    def _flush(self):
        self.stdout.write(self.style.WARNING("Flushing catalogue ..."))
        ProductImage.objects.all().delete()
        ProductSpec.objects.all().delete()
        InventoryLog.objects.all().delete()
        ProductVariant.objects.all().delete()
        Product.objects.all().delete()
        Category.objects.all().delete()
        Brand.objects.all().delete()

    # ------------------------------------------------------------------
    def _import_categories(self, rows):
        """Roots first, then children, so a child always finds its parent."""
        by_slug: dict[str, Category] = {}
        ordered = sorted(rows, key=lambda r: (r["parent_slug"] is not None, r["sort_order"]))
        known = {row["slug"] for row in rows}

        for row in ordered:
            parent = None
            parent_slug = row["parent_slug"]
            if parent_slug and parent_slug in known:
                parent = by_slug.get(parent_slug)
                # The model allows one level only; a child of a child is
                # re-pointed at the grandparent.
                if parent and parent.parent_id:
                    parent = parent.parent

            category, _ = Category.objects.update_or_create(
                slug=row["slug"][:140],
                defaults={
                    "name": row["name"][:120],
                    "parent": parent,
                    "sort_order": row["sort_order"],
                    "is_active": True,
                },
            )
            by_slug[row["slug"]] = category

        roots = sum(1 for c in by_slug.values() if c.parent_id is None)
        self.stdout.write(f"Categories: {len(by_slug)} ({roots} root)")
        return by_slug

    # ------------------------------------------------------------------
    def _import_brands(self, brand_rows, products):
        """
        Only brands that a product actually claims are created -- the source
        index lists hundreds the scrape never touched.
        """
        slug_by_name = {row["name"].lower(): row["slug"] for row in brand_rows}
        wanted = {
            product["brand"].strip()
            for product in products
            if (product.get("brand") or "").strip()
        }

        by_name: dict[str, Brand] = {}
        for name in sorted(wanted):
            slug = slug_by_name.get(name.lower()) or slugify(name)
            if not slug:
                continue
            brand, _ = Brand.objects.update_or_create(
                slug=slug[:140], defaults={"name": name[:120], "is_active": True}
            )
            by_name[name.lower()] = brand

        self.stdout.write(f"Brands: {len(by_name)}")
        return by_name

    # ------------------------------------------------------------------
    def _import_products(self, products, categories, brands, actor, data_dir, attach_images):
        created = updated = skipped = 0
        used_skus: set[str] = set()

        for index, row in enumerate(products, start=1):
            category = categories.get(row.get("category_slug") or "")
            if category is None:
                skipped += 1
                continue
            if not row.get("price"):
                skipped += 1
                continue

            sku = self._unique_sku(sku_for(row), row["slug"][:280], used_skus)
            used_skus.add(sku)

            with transaction.atomic():
                product, was_created = Product.objects.update_or_create(
                    slug=row["slug"][:280],
                    defaults={
                        "name": row["name"][:255],
                        "category": category,
                        "brand": brands.get((row.get("brand") or "").strip().lower()),
                        "description": build_description(row, category.name),
                        "warranty_months": row.get("warranty_months") or 0,
                        "is_active": True,
                    },
                )
                self._sync_variant(product, row, sku, actor, was_created)
                self._sync_specs(product, row)
                if attach_images:
                    self._sync_images(product, row, data_dir)

            created += was_created
            updated += not was_created
            if index % 100 == 0:
                self.stdout.write(f"  {index}/{len(products)} ...")

        return created, updated, skipped

    # ------------------------------------------------------------------
    @staticmethod
    def _unique_sku(sku, product_slug, used_skus):
        """
        SKUs are unique across the whole table, so a source product code that
        collides with a *different* product's variant has to be suffixed. The
        suffix is derived from the slug rather than the loop index so it stays
        the same on every re-import.
        """
        taken = (
            ProductVariant.objects.filter(sku=sku)
            .exclude(product__slug=product_slug)
            .exists()
        )
        if sku not in used_skus and not taken:
            return sku
        return f"{sku[:52]}-{zlib.crc32(product_slug.encode()) % 100000}"[:64]

    # ------------------------------------------------------------------
    def _sync_variant(self, product, row, sku, actor, product_is_new):
        price = Decimal(row["price"])
        compare_at = Decimal(row["compare_at_price"]) if row.get("compare_at_price") else None
        if compare_at is not None and compare_at <= price:
            compare_at = None

        variant = product.variants.filter(sku=sku).first() or product.variants.first()
        if variant is None:
            variant = ProductVariant.objects.create(
                product=product,
                sku=sku,
                option_label="",
                price=price,
                compare_at_price=compare_at,
                stock=0,
                weight_grams=row.get("weight_grams") or 0,
                is_active=True,
            )
            # Opening balance goes through the ledger so summing InventoryLog
            # deltas reconciles to stock from the very first row.
            opening = stock_for(row["slug"], row.get("status") or "")
            if opening:
                variant.stock = opening
                variant.save(update_fields=["stock"])
                InventoryLog.objects.create(
                    variant=variant,
                    delta=opening,
                    reason=InventoryReason.INITIAL,
                    actor=actor,
                    note="Imported from the startech.com.bd development scrape",
                )
            return variant

        # Existing variant: refresh pricing only. Stock stays as it is, because
        # anything that moved it wrote an InventoryLog row we must not orphan.
        variant.price = price
        variant.compare_at_price = compare_at
        variant.weight_grams = row.get("weight_grams") or variant.weight_grams
        variant.is_active = True
        variant.save(update_fields=["price", "compare_at_price", "weight_grams", "is_active"])
        return variant

    # ------------------------------------------------------------------
    def _sync_specs(self, product, row):
        specs = row.get("specs") or []
        if not specs:
            return
        product.specs.all().delete()
        ProductSpec.objects.bulk_create(
            ProductSpec(
                product=product,
                key=spec["key"][:120],
                value=spec["value"][:500],
                sort_order=order,
            )
            for order, spec in enumerate(specs)
        )

    # ------------------------------------------------------------------
    def _sync_images(self, product, row, data_dir):
        if product.images.exists():
            return
        for order, relative in enumerate(row.get("images") or []):
            path = data_dir / relative
            if not path.exists():
                continue
            image = ProductImage(
                product=product,
                alt_text=product.name[:255],
                sort_order=order,
                is_primary=(order == 0),
            )
            with path.open("rb") as handle:
                image.image.save(f"{product.slug[:80]}-{order}{path.suffix}", File(handle), save=False)
            image.save()

    # ------------------------------------------------------------------
    def _prune_empty_categories(self, categories):
        """
        A child with no products is noise in the nav; a root stays visible as
        long as one of its children still has something.
        """
        deactivated = 0
        for category in categories.values():
            if category.parent_id is None:
                continue
            if not category.products.filter(is_active=True).exists():
                Category.objects.filter(pk=category.pk).update(is_active=False)
                deactivated += 1

        for category in categories.values():
            if category.parent_id is not None:
                continue
            has_own = category.products.filter(is_active=True).exists()
            has_child = category.children.filter(is_active=True).exists()
            if not has_own and not has_child:
                Category.objects.filter(pk=category.pk).update(is_active=False)
                deactivated += 1

        self.stdout.write(f"Deactivated {deactivated} empty categories.")
