"""
Seed a realistic development catalogue (PRD §12.1, week 1 exit criteria).

Also seeds the two logins the dev login page offers one-tap fill for: an admin
and a plain customer. The customer exists so the transactional path -- cart,
checkout, order placement -- can be exercised by a non-staff user, which is
what the storefront actually ships to.

Idempotent: every object is looked up by its natural key, so running this
repeatedly neither duplicates rows nor resets stock you have deliberately
changed. Stock is set through the inventory service so InventoryLog reconciles
from the very first row. An account that already exists keeps the password it
has -- pass the flag again on a fresh database if you need the default back.

    python manage.py seed_demo
    python manage.py seed_demo --admin-password 'something-else'
    python manage.py seed_demo --customer-email me@example.com --customer-password 'something-else'
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Address, Role
from apps.accounts.services.addresses import create_address
from apps.catalog.models import (
    Brand,
    Category,
    InventoryLog,
    InventoryReason,
    Product,
    ProductSpec,
    ProductVariant,
)
from apps.dashboard.models import StoreSettings
from apps.promotions.models import Coupon, DiscountType, ScopeType
from apps.shipping.models import ShippingZone

User = get_user_model()

# Slugs here MUST match apps/catalog/seed_data/taxonomy.py. The two commands
# seed the same store: when they disagreed, the storefront grew a "Laptops"
# category beside a "Laptop" one and the nav showed both.
CATEGORIES = [
    ("Laptop", "laptop", None),
    ("Gaming Laptop", "gaming-laptop", "laptop"),
    ("Ultrabook", "ultrabook", "laptop"),
    ("Mobile Phone", "mobile-phone", None),
    ("Component", "component", None),
    ("Graphics Card", "graphics-card", "component"),
    ("Accessories", "accessories", None),
]

BRANDS = ["Asus", "Lenovo", "HP", "Samsung", "Xiaomi", "Logitech", "NVIDIA"]

# (name, slug, category slug, brand, warranty months, [(sku suffix, label, price, compare_at, stock, weight_g)])
PRODUCTS = [
    (
        "Asus TUF Gaming F15 FX507",
        "asus-tuf-gaming-f15-fx507",
        "gaming-laptop",
        "Asus",
        24,
        "A 15.6in 144Hz gaming laptop with a 12th-gen Core i7 and RTX 4060 graphics, "
        "built to the TUF military-grade durability standard.",
        [
            ("16-512", "16GB / 512GB", "142000.00", "155000.00", 12, 2200),
            ("16-1TB", "16GB / 1TB", "156000.00", "168000.00", 7, 2200),
            ("32-1TB", "32GB / 1TB", "178000.00", None, 3, 2250),
        ],
        [
            ("Processor", "Intel Core i7-12700H"),
            ("Graphics", "NVIDIA GeForce RTX 4060 8GB"),
            ("Display", "15.6in FHD 144Hz IPS"),
            ("Battery", "90Wh, up to 8 hours"),
        ],
    ),
    (
        "Lenovo IdeaPad Slim 3",
        "lenovo-ideapad-slim-3",
        "ultrabook",
        "Lenovo",
        12,
        "A light 14in everyday notebook with a Ryzen 5 processor, aimed at students "
        "and office work rather than gaming.",
        [
            ("8-256", "8GB / 256GB", "62000.00", "68000.00", 25, 1400),
            ("16-512", "16GB / 512GB", "78000.00", None, 14, 1400),
        ],
        [
            ("Processor", "AMD Ryzen 5 7520U"),
            ("Display", "14in FHD IPS"),
            ("Weight", "1.4 kg"),
        ],
    ),
    (
        "HP Pavilion x360 14",
        "hp-pavilion-x360-14",
        "ultrabook",
        "HP",
        12,
        "A convertible 14in touchscreen laptop that folds flat into tablet mode.",
        [("8-512", "8GB / 512GB", "89000.00", "95000.00", 9, 1600)],
        [("Processor", "Intel Core i5-1335U"), ("Display", "14in FHD touch")],
    ),
    (
        "Samsung Galaxy S24",
        "samsung-galaxy-s24",
        "mobile-phone",
        "Samsung",
        12,
        "A 6.2in flagship phone with a 50MP main camera and seven years of "
        "guaranteed OS updates.",
        [
            ("8-128-BLK", "8GB / 128GB / Onyx Black", "112000.00", "125000.00", 18, 170),
            ("8-256-BLK", "8GB / 256GB / Onyx Black", "124000.00", None, 11, 170),
            ("8-256-VLT", "8GB / 256GB / Cobalt Violet", "124000.00", None, 4, 170),
        ],
        [
            ("Display", "6.2in Dynamic AMOLED 2X, 120Hz"),
            ("Camera", "50MP + 12MP + 10MP"),
            ("Battery", "4000mAh"),
        ],
    ),
    (
        "Xiaomi Redmi Note 13 Pro",
        "xiaomi-redmi-note-13-pro",
        "mobile-phone",
        "Xiaomi",
        12,
        "A mid-range phone with a 200MP camera and 67W fast charging.",
        [
            ("8-256", "8GB / 256GB", "34500.00", "38000.00", 40, 190),
            ("12-512", "12GB / 512GB", "42000.00", None, 22, 190),
        ],
        [("Camera", "200MP main"), ("Charging", "67W wired")],
    ),
    (
        "NVIDIA GeForce RTX 4070 Super",
        "nvidia-geforce-rtx-4070-super",
        "graphics-card",
        "NVIDIA",
        36,
        "A 12GB GDDR6X graphics card for 1440p gaming with ray tracing and DLSS 3.",
        [("12G", "12GB GDDR6X", "88000.00", "94000.00", 2, 1100)],
        [("Memory", "12GB GDDR6X"), ("Interface", "PCIe 4.0 x16")],
    ),
    (
        "Logitech MX Master 3S",
        "logitech-mx-master-3s",
        "accessories",
        "Logitech",
        24,
        "A quiet, high-precision wireless mouse that pairs with up to three devices.",
        [
            ("GRAPH", "Graphite", "13500.00", "15000.00", 30, 141),
            ("PALE", "Pale Grey", "13500.00", None, 0, 141),
        ],
        [("Sensor", "8000 DPI Darkfield"), ("Battery", "70 days per charge")],
    ),
]

SHIPPING_ZONES = [
    {
        "name": "Inside Dhaka",
        "flat_rate": "60.00",
        "per_kg_rate": "20.00",
        "base_weight_grams": 1000,
        "cod_allowed": True,
        "districts": ["Dhaka", "Gazipur", "Narayanganj"],
        "sort_order": 1,
    },
    {
        "name": "Outside Dhaka",
        "flat_rate": "120.00",
        "per_kg_rate": "30.00",
        "base_weight_grams": 1000,
        "cod_allowed": True,
        "districts": [
            "Chattogram", "Khulna", "Rajshahi", "Sylhet", "Barishal",
            "Rangpur", "Mymensingh", "Cumilla", "Bogura", "Jashore",
        ],
        "sort_order": 2,
    },
]

# A home address for the demo shopper, so checkout has something to preselect
# instead of making every test run retype one. The district must sit inside a
# seeded ShippingZone above, or the quote comes back with NO_SHIPPING_ZONE.
SHOPPER_ADDRESS = {
    "recipient_name": "Demo Shopper",
    "phone": "01712345678",
    "division": "Dhaka",
    "district": "Dhaka",
    "upazila": "Dhanmondi",
    "area": "Road 7",
    "street": "House 42, Road 7, Dhanmondi",
    "postcode": "1209",
}


class Command(BaseCommand):
    help = (
        "Seed development data: catalogue, shipping zones, a coupon, "
        "an admin user, and a customer user."
    )

    def add_arguments(self, parser):
        parser.add_argument("--admin-email", default="admin@example.com")
        parser.add_argument("--admin-password", default="ChangeMe!2026")
        parser.add_argument("--customer-email", default="shopper@example.com")
        parser.add_argument("--customer-password", default="Str0ngPass!2026")

    @transaction.atomic
    def handle(self, *args, **options):
        settings_row = StoreSettings.load()
        self.stdout.write(f"Store settings ready: {settings_row.store_name}")

        admin = self._seed_admin(options["admin_email"], options["admin_password"])
        customer = self._seed_customer(
            options["customer_email"], options["customer_password"]
        )
        self._seed_customer_address(customer)
        categories = self._seed_categories()
        brands = self._seed_brands()
        self._seed_products(categories, brands, admin)
        self._seed_shipping_zones()
        self._seed_coupons()

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))
        self.stdout.write(f"  Admin login: {options['admin_email']} / {options['admin_password']}")
        self.stdout.write(
            f"  Customer login: {options['customer_email']} / {options['customer_password']}"
        )
        self.stdout.write(
            "  Rates and VAT are placeholders -- PRD §14 Q2/Q3 are still open."
        )

    def _seed_admin(self, email, password):
        admin, created = User.objects.get_or_create(
            email=email,
            defaults={
                "full_name": "Store Owner",
                "role": "admin",
                "is_staff": True,
                "is_superuser": True,
                "is_email_verified": True,
            },
        )
        if created:
            admin.set_password(password)
            admin.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"Created admin {email}"))
        else:
            self.stdout.write(f"Admin {email} already exists -- password left alone")
        return admin

    def _seed_customer(self, email, password):
        """A plain shopper: no Django Admin, no staff role, nothing privileged."""
        customer, created = User.objects.get_or_create(
            email=email,
            defaults={
                "full_name": "Demo Shopper",
                "phone": SHOPPER_ADDRESS["phone"],
                "role": Role.CUSTOMER,
                "is_staff": False,
                "is_superuser": False,
                "is_email_verified": True,
            },
        )
        if created:
            customer.set_password(password)
            customer.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"Created customer {email}"))
        else:
            self.stdout.write(f"Customer {email} already exists -- password left alone")
        return customer

    def _seed_customer_address(self, customer):
        # Natural key is (user, street): re-running never duplicates the row, and
        # an address book the developer has since edited is left as they left it.
        # Goes through the service so the default-address rule stays in one place.
        exists = Address.objects.filter(
            user=customer, street=SHOPPER_ADDRESS["street"]
        ).exists()
        if not exists:
            create_address(user=customer, **SHOPPER_ADDRESS)
            self.stdout.write(f"Address seeded for {customer.email}")

    def _seed_categories(self):
        created = {}
        for name, slug, parent_slug in CATEGORIES:
            category, _ = Category.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "sort_order": len(created)},
            )
            if parent_slug and category.parent_id is None:
                category.parent = created[parent_slug]
                category.save(update_fields=["parent"])
            created[slug] = category
        self.stdout.write(f"Categories: {len(created)}")
        return created

    def _seed_brands(self):
        created = {}
        for name in BRANDS:
            slug = name.lower().replace(" ", "-")
            brand, _ = Brand.objects.get_or_create(slug=slug, defaults={"name": name})
            created[name] = brand
        self.stdout.write(f"Brands: {len(created)}")
        return created

    def _seed_products(self, categories, brands, actor):
        variant_count = 0
        for name, slug, cat_slug, brand_name, warranty, description, variants, specs in PRODUCTS:
            product, created = Product.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "category": categories[cat_slug],
                    "brand": brands[brand_name],
                    "description": description,
                    "warranty_months": warranty,
                },
            )
            if created:
                ProductSpec.objects.bulk_create(
                    [
                        ProductSpec(product=product, key=key, value=value, sort_order=i)
                        for i, (key, value) in enumerate(specs)
                    ]
                )

            sku_base = slug.upper().replace("-", "")[:24]
            for suffix, label, price, compare_at, stock, weight in variants:
                sku = f"{sku_base}-{suffix}"
                variant, v_created = ProductVariant.objects.get_or_create(
                    sku=sku,
                    defaults={
                        "product": product,
                        "option_label": label,
                        "price": Decimal(price),
                        "compare_at_price": Decimal(compare_at) if compare_at else None,
                        "stock": 0,
                        "weight_grams": weight,
                    },
                )
                if v_created:
                    variant_count += 1
                    # Route the opening stock through a logged movement so
                    # summing InventoryLog.delta reconciles to stock from row one.
                    if stock:
                        variant.stock = stock
                        variant.save(update_fields=["stock"])
                        InventoryLog.objects.create(
                            variant=variant,
                            delta=stock,
                            reason=InventoryReason.INITIAL,
                            actor=actor,
                            note="Seeded opening stock",
                        )
        self.stdout.write(
            f"Products: {Product.objects.count()} ({variant_count} new variants)"
        )

    def _seed_shipping_zones(self):
        for spec in SHIPPING_ZONES:
            ShippingZone.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "flat_rate": Decimal(spec["flat_rate"]),
                    "per_kg_rate": Decimal(spec["per_kg_rate"]),
                    "base_weight_grams": spec["base_weight_grams"],
                    "cod_allowed": spec["cod_allowed"],
                    "districts": spec["districts"],
                    "sort_order": spec["sort_order"],
                },
            )
        self.stdout.write(f"Shipping zones: {ShippingZone.objects.count()}")

    def _seed_coupons(self):
        now = timezone.now()
        Coupon.objects.get_or_create(
            code="WELCOME10",
            defaults={
                "discount_type": DiscountType.PERCENT,
                "value": Decimal("10.00"),
                "max_discount": Decimal("2000.00"),
                "min_order_value": Decimal("5000.00"),
                "valid_from": now,
                "valid_until": now + timedelta(days=90),
                "per_user_limit": 1,
                "scope_type": ScopeType.ALL,
            },
        )
        Coupon.objects.get_or_create(
            code="FLAT500",
            defaults={
                "discount_type": DiscountType.FIXED,
                "value": Decimal("500.00"),
                "min_order_value": Decimal("10000.00"),
                "valid_from": now,
                "valid_until": now + timedelta(days=30),
                "per_user_limit": 2,
                "scope_type": ScopeType.ALL,
            },
        )
        self.stdout.write(f"Coupons: {Coupon.objects.count()}")
