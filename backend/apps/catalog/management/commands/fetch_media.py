"""
Replace generated placeholder artwork with real, openly-licensed photography.

    python manage.py fetch_media                 # products and brand logos
    python manage.py fetch_media --products      # products only
    python manage.py fetch_media --brands        # brand logos only
    python manage.py fetch_media --force         # refetch what already has one
    python manage.py fetch_media --limit 20      # a sample, for a quick look

Split out from `seed_catalog` on purpose. Seeding is offline, deterministic
and takes seconds; this talks to a third-party API over the network, takes
minutes, and is allowed to partially fail. Bundling the two would mean a
flaky network turned "seed the catalogue" into a broken catalogue.

**Licensing is the point, not an afterthought.** Every image is fetched from
Wikimedia Commons under a licence that permits reuse, and CC BY / CC BY-SA
both require the author and licence to be displayed. So an image is only
written together with its `attribution`, `license_name` and `source_url`, and
the storefront renders those. An image whose licence cannot be confirmed is
skipped rather than risked.

**Exact vs representative.** A product with its own Wikipedia article gets a
photograph of that product. One without gets the lead image of its product
*type* -- a real photo of a real mechanical keyboard standing in for a
specific keyboard we have no photo of. Those are recorded with a
`Representative image` prefix in `alt_text`, and the storefront labels them,
so nothing implies the photo is the exact unit being sold.
"""
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Brand, Product, ProductImage
from apps.catalog.seed_data import wikimedia

# Prefix written into alt_text for a stand-in photo. The storefront reads it
# to decide whether to show the "representative image" note.
REPRESENTATIVE_PREFIX = "Representative image"


def _file_is_stored(field_file):
    """
    True when the field points at a file the storage backend actually holds.

    A database row is not proof that the bytes exist. On a host without a
    persistent disk the media directory starts empty on every deploy, while
    the rows -- and their source_url -- survive in the database. Checking the
    row alone would skip exactly the images that need refetching, leaving the
    storefront pointing at files that are not there.
    """
    if not field_file:
        return False
    try:
        return field_file.storage.exists(field_file.name)
    except (NotImplementedError, OSError):
        # A backend that cannot answer (some remote stores) is taken at its
        # word: the row stands, and --force is the way to refetch.
        return True


def _has_stored_file(images):
    """True when at least one of `images` has its file on disk."""
    return any(_file_is_stored(image.image) for image in images)


class Command(BaseCommand):
    help = "Fetch real openly-licensed product and brand images from Wikimedia."

    def add_arguments(self, parser):
        parser.add_argument("--products", action="store_true", help="Products only.")
        parser.add_argument("--brands", action="store_true", help="Brand logos only.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Refetch even where a real image is already stored.",
        )
        parser.add_argument("--limit", type=int, default=0, help="Stop after N products.")

    def handle(self, *args, **options):
        do_products = options["products"] or not options["brands"]
        do_brands = options["brands"] or not options["products"]

        # Articles resolve to the same handful of files across a category, and
        # a category article is asked for once per product in it. Caching turns
        # ~150 API round trips into ~60.
        self._cache = {}

        if do_products:
            self._fetch_products(options)
        if do_brands:
            self._fetch_brands(options)

        self.stdout.write(self.style.SUCCESS("\nMedia fetch complete."))
        real = ProductImage.objects.exclude(source_url="").count()
        total = ProductImage.objects.count()
        self.stdout.write(f"  Product images from Wikimedia: {real} of {total}")
        self.stdout.write(
            f"  Brand logos from Wikimedia: {Brand.objects.exclude(logo_source_url='').count()}"
            f" of {Brand.objects.count()}"
        )

    # -- products ----------------------------------------------------------
    def _resolve(self, article, is_representative):
        if article not in self._cache:
            self._cache[article] = wikimedia.resolve(
                article, is_representative=is_representative
            )
        return self._cache[article]

    def _fetch_products(self, options):
        products = Product.objects.select_related("brand", "category").order_by("id")
        if options["limit"]:
            products = products[: options["limit"]]

        exact = representative = skipped = failed = 0

        for product in products:
            already_real = _has_stored_file(product.images.exclude(source_url=""))
            if already_real and not options["force"]:
                skipped += 1
                continue

            article, is_representative = wikimedia.article_for_product(
                product.name, product.category.slug if product.category else ""
            )
            if not article:
                failed += 1
                continue

            image = self._resolve(article, is_representative)
            if image is None:
                failed += 1
                self.stdout.write(f"  no image: {product.name[:60]} ({article})")
                continue

            payload = wikimedia.download(image)
            if not payload:
                failed += 1
                continue

            self._store_product_image(product, image, payload)

            if image.is_representative:
                representative += 1
            else:
                exact += 1

            marker = "~" if image.is_representative else "="
            self.stdout.write(f"  {marker} {product.name[:52]:54} {image.file_title[:44]}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nProducts: {exact} exact, {representative} representative, "
                f"{skipped} already had one, {failed} kept their placeholder"
            )
        )

    @transaction.atomic
    def _store_product_image(self, product, image, payload):
        """
        Put the fetched photo in front of the generated placeholders.

        The placeholders are kept rather than deleted: they are the gallery's
        remaining shots, and a product with one real photo and two generated
        angles still has a gallery worth paging through. Only `is_primary` and
        `sort_order` move.
        """
        product.images.update(is_primary=False)
        product.images.filter(source_url="").update(sort_order=10)
        # A refetch must not stack duplicates of the same source.
        product.images.exclude(source_url="").delete()

        alt = (
            f"{REPRESENTATIVE_PREFIX}: {product.name}"
            if image.is_representative
            else product.name
        )

        record = ProductImage(
            product=product,
            alt_text=alt[:255],
            sort_order=0,
            is_primary=True,
            source_url=image.source_url[:500],
            license_name=image.license_name[:80],
            attribution=image.attribution[:255],
        )
        extension = "png" if image.url.lower().endswith(".png") else "jpg"
        record.image.save(
            f"{product.slug}-wm.{extension}", ContentFile(payload), save=False
        )
        record.save()

    # -- brands ------------------------------------------------------------
    def _fetch_brands(self, options):
        fetched = skipped = failed = 0

        for brand in Brand.objects.order_by("name"):
            if (
                brand.logo_source_url
                and _file_is_stored(brand.logo)
                and not options["force"]
            ):
                skipped += 1
                continue

            article = wikimedia.BRAND_ARTICLES.get(brand.name)
            if not article:
                # Deliberate: a brand with no encyclopedia article keeps the
                # generated wordmark rather than borrowing someone else's logo.
                failed += 1
                continue

            # Wikidata's P154, not the article's lead image: a company page
            # leads with a photo of its headquarters, so `pageimages` returns
            # an office block where a mark is wanted.
            image = wikimedia.resolve_logo(article)
            if image is None:
                failed += 1
                continue

            payload = wikimedia.download(image)
            if not payload:
                failed += 1
                continue

            extension = "png" if image.url.lower().endswith(".png") else "jpg"
            brand.logo.save(f"{brand.slug}-wm.{extension}", ContentFile(payload), save=False)
            brand.logo_source_url = image.source_url[:500]
            brand.logo_license_name = image.license_name[:80]
            brand.logo_attribution = image.attribution[:255]
            brand.save(
                update_fields=[
                    "logo", "logo_source_url", "logo_license_name", "logo_attribution",
                ]
            )
            fetched += 1
            self.stdout.write(f"  = {brand.name[:28]:30} {image.file_title[:48]}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nBrands: {fetched} fetched, {skipped} already had one, "
                f"{failed} kept their generated wordmark"
            )
        )
