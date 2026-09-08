"""
Seed the full demo catalogue: taxonomy, brands, 100+ products, specs, images,
reviews and PC-builder profiles.

    python manage.py seed_catalog
    python manage.py seed_catalog --reset-images   # redraw artwork
    python manage.py seed_catalog --no-images      # fast, text only
    python manage.py seed_catalog --no-reviews

Relationship to `seed_demo`: that command seeds the *accounts*, shipping zones,
coupons and store settings a developer needs to place an order, plus seven
hand-written products. This one seeds the *catalogue* at a realistic size. Run
`seed_demo` first for the logins, then this. Neither disturbs the other, and
both are idempotent.

Three properties are deliberate and worth keeping:

* **Idempotent.** Everything is looked up by its natural key (category slug,
  brand slug, product slug, variant SKU). Re-running refreshes prices, specs
  and descriptions but never duplicates a row.
* **Stock is never rewritten on an existing variant.** Something may have sold,
  or an admin may have adjusted it -- and every movement wrote an InventoryLog
  row that must reconcile. Opening stock is only set the first time a variant
  is created, and it goes through the inventory service so the ledger balances
  from row one.
* **Descriptions are generated, not copied.** `build_description()` composes
  original prose from the record's own factual specs. No marketing copy from
  any retailer is reproduced anywhere in this pipeline.
"""
import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.catalog.models import (
    Brand,
    Category,
    ComponentProfile,
    InventoryLog,
    InventoryReason,
    Product,
    ProductImage,
    ProductSpec,
    ProductVariant,
)
from apps.catalog.seed_data import images as art
from apps.catalog.seed_data.products import PRODUCTS
from apps.catalog.seed_data.taxonomy import BRANDS, CATEGORY_TREE
from apps.reviews.models import Review, ReviewStatus

User = get_user_model()

# Extra gallery shots per product, beyond the primary.
GALLERY_ANGLES = 2

# Review authors. Seeded reviews need real users because Review has a FK and a
# unique (product, user) -- these are plainly-named demo accounts with an
# unusable password, so none of them can be signed into.
REVIEWER_NAMES = [
    "Rafiq Hasan", "Nusrat Jahan", "Tanvir Ahmed", "Sadia Islam",
    "Imran Kabir", "Mehnaz Rahman", "Shakil Mahmud", "Farhana Akter",
    "Arif Chowdhury", "Rumana Sultana", "Jubayer Alam", "Tasnim Nahar",
]

# Review bodies, keyed by rating band. Picked deterministically per (product,
# reviewer) so re-seeding does not reshuffle the ratings and move rating_avg.
REVIEW_BODIES = {
    5: [
        "Exactly what I expected and it arrived sealed. Delivery to Dhaka took two days.",
        "Working perfectly after a month of daily use. No complaints at all.",
        "Genuine product with proper warranty paperwork. Would buy from here again.",
        "Well packed and the price was better than the shops in Elephant Road.",
    ],
    4: [
        "Does the job well. Only wish the box had included a longer cable.",
        "Good value for the money. Setup took a little longer than I expected.",
        "Happy with it overall. Delivery outside Dhaka took an extra day.",
        "Solid performance so far. Build quality is decent for this price.",
    ],
    3: [
        "It works, but it runs warmer than I expected under load.",
        "Average. Fine for light use, though I would size up if you do heavy work.",
        "Does what it says. Nothing special, nothing wrong either.",
    ],
}


def build_description(record):
    """
    Compose an original product description from the record's own facts.

    This is the piece that keeps the catalogue clean: it reads the structured
    specs -- processor, capacity, refresh rate -- and writes sentences around
    them. Nothing is lifted from a retailer's page, and the output changes
    when the specs change rather than drifting away from them.
    """
    name = record["name"]
    brand = record["brand"]
    specs = record["specs"]

    def spec(*keys):
        """First matching spec value across every group, or None."""
        for rows in specs.values():
            for key, value in rows:
                if key in keys:
                    return value
        return None

    paragraphs = []

    kind = spec("Type") or "product"
    opening = f"The {name} is a {kind.lower()} from {brand}"
    room = spec("Suitable Room Size")
    if room:
        opening += f", sized for a room of {room.lower()}"
    paragraphs.append(opening + ".")

    # Performance sentence, assembled only from the fields present.
    bits = []
    processor = spec("Processor", "Chipset")
    if processor:
        bits.append(f"it runs on {processor}")
    ram = spec("RAM", "Memory Size", "Capacity")
    if ram:
        bits.append(f"with {ram}")
    storage = spec("Storage")
    if storage:
        bits.append(f"and {storage} of storage")
    if bits:
        paragraphs.append(("Inside, " + ", ".join(bits) + ".").replace(", and", " and"))

    # Display sentence.
    size, resolution = spec("Size", "Screen Size"), spec("Resolution")
    if size and resolution:
        display = f"The {size} display runs at {resolution}"
        refresh = spec("Refresh Rate")
        if refresh and refresh != "60Hz":
            display += f" and refreshes at {refresh}, which keeps motion clean in fast scenes"
        paragraphs.append(display + ".")

    # Battery or power.
    battery = spec("Capacity", "Rated Life", "Playback Time")
    if battery and "mAh" in str(battery):
        paragraphs.append(f"A {battery} battery keeps it going between charges.")

    if record["highlights"]:
        paragraphs.append("Worth knowing: " + record["highlights"][0][0].lower()
                          + record["highlights"][0][1:] + ".")

    warranty = record["warranty"]
    if warranty:
        years = warranty // 12
        term = f"{years}-year" if years >= 1 and warranty % 12 == 0 else f"{warranty}-month"
        paragraphs.append(
            f"Supplied with an official {term} warranty and full after-sales support."
        )

    return "\n\n".join(paragraphs)


class Command(BaseCommand):
    help = "Seed the full demo catalogue (categories, brands, 100+ products, images, reviews)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-images", action="store_true",
            help="Skip artwork generation. Much faster; products render with no image.",
        )
        parser.add_argument(
            "--reset-images", action="store_true",
            help="Redraw artwork for products that already have some.",
        )
        parser.add_argument(
            "--no-reviews", action="store_true", help="Skip seeding demo reviews.",
        )

    def handle(self, *args, **options):
        # Deterministic: the same catalogue every run, so screenshots and
        # tests do not shift underneath anyone.
        self.random = random.Random(20260823)
        self.options = options

        actor = User.objects.filter(role="admin").order_by("id").first()

        self._reconcile_legacy_taxonomy()
        categories = self._seed_categories()
        brands = self._seed_brands()
        self._seed_products(categories, brands, actor)
        self._backfill_missing_images()
        if not options["no_reviews"]:
            self._seed_reviews()

        self.stdout.write(self.style.SUCCESS("\nCatalogue seed complete."))
        self.stdout.write(f"  Categories: {Category.objects.count()}")
        self.stdout.write(f"  Brands:     {Brand.objects.count()}")
        self.stdout.write(f"  Products:   {Product.objects.count()}")
        self.stdout.write(f"  Variants:   {ProductVariant.objects.count()}")
        self.stdout.write(f"  Images:     {ProductImage.objects.count()}")
        self.stdout.write(f"  Specs:      {ProductSpec.objects.count()}")
        self.stdout.write(f"  Builder profiles: {ComponentProfile.objects.count()}")
        self.stdout.write(f"  Reviews:    {Review.objects.count()}")

    # -- taxonomy ----------------------------------------------------------
    @transaction.atomic
    def _reconcile_legacy_taxonomy(self):
        """
        Fold the original `seed_demo` category slugs into the shared taxonomy.

        An early `seed_demo` used plural slugs ("laptops", "smartphones"), and
        a database seeded before this command existed carries both sets --
        which showed up in the storefront as a "Laptops" tab sitting next to a
        "Laptop" one. Products are moved across first (Product.category is
        PROTECT, so the delete would refuse otherwise), then the emptied
        legacy row is removed.

        Idempotent and self-retiring: on a database that never saw the old
        slugs, and on every run after the first, this does nothing.
        """
        remap = {
            "laptops": "laptop",
            "gaming-laptops": "gaming-laptop",
            "ultrabooks": "ultrabook",
            "smartphones": "mobile-phone",
            "components": "component",
            "graphics-cards": "graphics-card",
        }

        moved = removed = 0
        for old_slug, new_slug in remap.items():
            old = Category.objects.filter(slug=old_slug).first()
            if old is None:
                continue

            target, _ = Category.objects.get_or_create(
                slug=new_slug, defaults={"name": new_slug.replace("-", " ").title()}
            )
            moved += Product.objects.filter(category=old).update(category=target)
            # A legacy parent may still own legacy children; they are remapped
            # by their own pass, so anything left here is re-parented rather
            # than orphaned by the SET_NULL on delete.
            Category.objects.filter(parent=old).update(parent=None)
            old.delete()
            removed += 1

        if removed:
            self.stdout.write(
                self.style.WARNING(
                    f"Retired {removed} legacy categories, moved {moved} products."
                )
            )

    @transaction.atomic
    def _seed_categories(self):
        created = {}
        order = 0
        for name, slug, blurb, children in CATEGORY_TREE:
            parent, _ = Category.objects.update_or_create(
                slug=slug,
                defaults={"name": name, "sort_order": order, "is_active": True},
            )
            self._attach_category_tile(parent, blurb)
            created[slug] = parent
            order += 1

            for child_order, (child_name, child_slug) in enumerate(children):
                child, _ = Category.objects.update_or_create(
                    slug=child_slug,
                    defaults={
                        "name": child_name,
                        "parent": parent,
                        "sort_order": child_order,
                        "is_active": True,
                    },
                )
                self._attach_category_tile(child, "")
                created[child_slug] = child

        self.stdout.write(f"Categories: {len(created)}")
        return created

    def _attach_category_tile(self, category, blurb):
        if self.options["no_images"]:
            return
        if category.image and not self.options["reset_images"]:
            return
        accent = f"#{(abs(hash(category.slug)) % 0x555555 + 0x223355):06x}"
        payload = art.render_category_tile(name=category.name, accent=accent)
        category.image.save(f"{category.slug}.png", ContentFile(payload), save=True)

    @transaction.atomic
    def _seed_brands(self):
        created = {}
        for name, accent in BRANDS:
            slug = slugify(name)
            brand, _ = Brand.objects.update_or_create(
                slug=slug, defaults={"name": name, "is_active": True}
            )
            if not self.options["no_images"] and (
                not brand.logo or self.options["reset_images"]
            ):
                payload = art.render_brand_logo(name=name, accent=accent)
                brand.logo.save(f"{slug}.png", ContentFile(payload), save=True)
            created[name] = brand
        self.stdout.write(f"Brands: {len(created)}")
        return created

    # -- products ----------------------------------------------------------
    def _seed_products(self, categories, brands, actor):
        accents = dict(BRANDS)
        new_variants = 0

        for index, record in enumerate(PRODUCTS, start=1):
            # Written per product rather than in one big transaction: the
            # image work is slow, and a failure halfway should leave the
            # products that already landed intact rather than rolling back an
            # hour of rendering.
            with transaction.atomic():
                new_variants += self._seed_one_product(
                    record, categories, brands, accents, actor
                )
            if index % 25 == 0:
                self.stdout.write(f"  ... {index}/{len(PRODUCTS)} products")

        self.stdout.write(
            f"Products: {Product.objects.count()} ({new_variants} new variants)"
        )

    def _seed_one_product(self, record, categories, brands, accents, actor):
        slug = slugify(record["name"])
        product, _ = Product.objects.update_or_create(
            slug=slug,
            defaults={
                "name": record["name"],
                "category": categories[record["category"]],
                "brand": brands[record["brand"]],
                "description": build_description(record),
                "model_number": record["model"],
                "highlights": record["highlights"],
                "warranty_months": record["warranty"],
                "is_featured": record["featured"],
                "is_active": True,
            },
        )

        self._seed_specs(product, record)
        self._seed_component(product, record)
        new_variants = self._seed_variants(product, record, actor)
        self._seed_images(product, record, accents)
        return new_variants

    def _seed_specs(self, product, record):
        """
        Specs are replaced wholesale on every run.

        They have no natural key of their own (a product can legitimately
        carry the same key twice under different groups), and the set is tiny,
        so a delete-and-rewrite is both simpler and more correct than a diff.
        """
        product.specs.all().delete()
        rows = []
        for group_order, (group, entries) in enumerate(record["specs"].items()):
            for sort_order, (key, value) in enumerate(entries):
                rows.append(
                    ProductSpec(
                        product=product,
                        group=group,
                        key=key,
                        value=value,
                        group_order=group_order,
                        sort_order=sort_order,
                    )
                )
        ProductSpec.objects.bulk_create(rows)

    def _seed_component(self, product, record):
        spec = record["component"]
        if not spec:
            # A product that used to be a build part and no longer is should
            # lose its profile, or the builder would keep offering it.
            ComponentProfile.objects.filter(product=product).delete()
            return
        ComponentProfile.objects.update_or_create(product=product, defaults=spec)

    def _seed_variants(self, product, record, actor):
        sku_base = product.slug.upper().replace("-", "")[:24]
        rows = record["variants"] or [
            ("STD", "", record["price"], record["was"], record["stock"], 1000)
        ]

        new_count = 0
        for suffix, label, price, compare_at, stock, weight in rows:
            sku = f"TT-{sku_base}-{suffix}"
            variant = ProductVariant.objects.filter(sku=sku).first()

            if variant is None:
                variant = ProductVariant.objects.create(
                    product=product,
                    sku=sku,
                    option_label=label,
                    price=Decimal(str(price)),
                    compare_at_price=Decimal(str(compare_at)) if compare_at else None,
                    stock=0,
                    weight_grams=weight,
                    is_active=True,
                )
                new_count += 1
                if stock:
                    # Through the ledger, so sum(InventoryLog.delta) reconciles
                    # to stock from the very first row.
                    variant.stock = stock
                    variant.save(update_fields=["stock"])
                    InventoryLog.objects.create(
                        variant=variant,
                        delta=stock,
                        reason=InventoryReason.INITIAL,
                        actor=actor,
                        note="Seeded opening stock",
                    )
            else:
                # Refresh price and label, but never stock -- see the module
                # docstring.
                variant.option_label = label
                variant.price = Decimal(str(price))
                variant.compare_at_price = Decimal(str(compare_at)) if compare_at else None
                variant.weight_grams = weight
                variant.product = product
                variant.save(
                    update_fields=[
                        "option_label", "price", "compare_at_price",
                        "weight_grams", "product",
                    ]
                )
        return new_count

    def _seed_images(self, product, record, accents):
        if self.options["no_images"]:
            return
        existing = product.images.count()
        if existing and not self.options["reset_images"]:
            return
        if existing:
            product.images.all().delete()

        accent = accents.get(record["brand"], "#3749bb")
        for angle in range(1 + GALLERY_ANGLES):
            payload = art.render_product_image(
                slug=product.slug,
                name=product.name,
                brand=record["brand"],
                category_slug=record["category"],
                accent=accent,
                angle=angle,
            )
            image = ProductImage(
                product=product,
                alt_text=f"{product.name} - view {angle + 1}",
                sort_order=angle,
                is_primary=(angle == 0),
            )
            image.image.save(
                f"{product.slug}-{angle}.png", ContentFile(payload), save=False
            )
            image.save()

    def _backfill_missing_images(self):
        """
        Give artwork to any product that still has none.

        Catches the handful seeded by `seed_demo`, which is not driven by this
        command's product table. Without it those cards render an empty grey
        panel next to 111 illustrated ones, which reads as a broken image
        rather than a deliberate absence.

        Scoped to products with *zero* images on purpose -- it must never
        touch a product whose photographs someone actually uploaded.
        """
        if self.options["no_images"]:
            return

        accents = dict(BRANDS)
        missing = (
            Product.objects.filter(images__isnull=True)
            .select_related("brand", "category")
            .distinct()
        )

        count = 0
        for product in missing:
            brand_name = product.brand.name if product.brand else "MicroMart"
            for angle in range(1 + GALLERY_ANGLES):
                payload = art.render_product_image(
                    slug=product.slug,
                    name=product.name,
                    brand=brand_name,
                    category_slug=product.category.slug if product.category else "",
                    accent=accents.get(brand_name, "#3749bb"),
                    angle=angle,
                )
                image = ProductImage(
                    product=product,
                    alt_text=f"{product.name} - view {angle + 1}",
                    sort_order=angle,
                    is_primary=(angle == 0),
                )
                image.image.save(
                    f"{product.slug}-{angle}.png", ContentFile(payload), save=False
                )
                image.save()
            count += 1

        if count:
            self.stdout.write(f"Backfilled artwork for {count} products")

    # -- reviews -----------------------------------------------------------
    def _seed_reviews(self):
        """
        Seed approved reviews so ratings, the rating facet and the star
        display have something real behind them.

        These are written directly rather than through the review service on
        purpose: the service enforces "the reviewer must have a delivered
        order containing this product" (FR-REV-1), which is exactly right for
        the API and impossible for seed data that has no order history. The
        rule is not weakened -- this is a management command writing fixtures,
        and the endpoint still refuses an unqualified review.
        """
        reviewers = []
        for name in REVIEWER_NAMES:
            email = f"{slugify(name)}@demo.micromart.test"
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"full_name": name, "role": "customer", "is_email_verified": True},
            )
            if created:
                # No usable password: these are display names on reviews, not
                # accounts anyone should be able to sign into.
                user.set_unusable_password()
                user.save(update_fields=["password"])
            reviewers.append(user)

        written = 0
        for product in Product.objects.all().only("id", "slug"):
            rng = random.Random(product.slug)
            if rng.random() < 0.25:
                continue  # a quarter of the catalogue has no reviews yet

            for reviewer in rng.sample(reviewers, rng.randint(1, 4)):
                rating = rng.choices([5, 4, 3], weights=[6, 3, 1])[0]
                body = rng.choice(REVIEW_BODIES[rating])
                _, created = Review.objects.get_or_create(
                    product=product,
                    user=reviewer,
                    defaults={
                        "rating": rating,
                        "title": "",
                        "body": body,
                        "status": ReviewStatus.APPROVED,
                    },
                )
                written += int(created)

        self._recompute_ratings()
        self.stdout.write(f"Reviews: {Review.objects.count()} ({written} new)")

    def _recompute_ratings(self):
        """
        Refresh the denormalised rating_avg / rating_count from approved rows.

        Only approved reviews count (FR-REV-5), which is the same rule the
        review service applies -- restated here rather than imported because
        this rewrites every product in one pass rather than one at a time.
        """
        from django.db.models import Avg, Count

        stats = (
            Review.objects.filter(status=ReviewStatus.APPROVED)
            .values("product_id")
            .annotate(avg=Avg("rating"), total=Count("id"))
        )
        by_product = {row["product_id"]: row for row in stats}

        updates = []
        for product in Product.objects.all().only("id", "rating_avg", "rating_count"):
            row = by_product.get(product.pk)
            product.rating_avg = round(Decimal(str(row["avg"])), 2) if row else Decimal("0")
            product.rating_count = row["total"] if row else 0
            updates.append(product)
        Product.objects.bulk_update(updates, ["rating_avg", "rating_count"], batch_size=200)
