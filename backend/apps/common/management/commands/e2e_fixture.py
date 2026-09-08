"""
Fixtures for the Playwright end-to-end suite (frontend/e2e/).

**A test-support command, never a production one.** It exists because a
browser test cannot reach into the database, and because a suite that depends
on a particular seeded row is a suite that goes red the first time somebody
ships that row's order. Every fixture below mints its *own* product, variant,
order or review with a unique suffix, so two runs never collide and no
assertion has to be made about a global count.

Everything is built through the same services the API calls -- placement for
orders, administration for products, inventory for stock, reviews for the
moderation queue -- so a fixture can never put the database into a state the
application itself could not reach. In particular stock still moves only
through the ledger, and an order still walks the PRD §15.1 state machine one
legal transition at a time.

Each subcommand prints a single JSON object on stdout and nothing else, so the
caller can `JSON.parse` it:

    .venv/bin/python manage.py e2e_fixture staff
    .venv/bin/python manage.py e2e_fixture order --payment online
    .venv/bin/python manage.py e2e_fixture order --advance-to delivered
    .venv/bin/python manage.py e2e_fixture product
    .venv/bin/python manage.py e2e_fixture pending-review
    .venv/bin/python manage.py e2e_fixture token --email admin@example.com

`token` mints a real JWT pair through the very code the login view uses
(accounts/cookies.issue_tokens). It is there for one reason: DRF throttles the
`auth` scope at 10/min, and a suite that signs in through the endpoint in every
test spends its whole budget on plumbing and then goes red on a 429 that means
nothing. Sign-in itself is still covered by browser tests that drive the real
form; everything else takes the token and gets on with the thing it is actually
testing.
"""
import json
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings

from apps.accounts.cookies import issue_tokens
from apps.accounts.models import Role
from apps.catalog.models import Category, Product, ProductVariant
from apps.catalog.services import administration
from apps.dashboard.models import StoreSettings
from apps.orders.models import Actor, OrderStatus, PaymentMethod
from apps.orders.services import placement as placement_services
from apps.reviews.models import Review, ReviewStatus
from apps.reviews.services import reviews as review_services
from apps.shipping.models import ShippingZone

User = get_user_model()

# The fixtures land in their own corner of the taxonomy so a developer looking
# at the dev catalogue can tell at a glance what a test made and what they did.
E2E_CATEGORY = ("E2E Fixtures", "e2e-fixtures")

# A district that must resolve to a ShippingZone, or placement refuses the
# order with NO_SHIPPING_ZONE. seed_demo puts Dhaka in one; _ensure_zone below
# makes sure of it on a database that was seeded differently.
FIXTURE_DISTRICT = "Dhaka"

ADDRESS = {
    "recipient_name": "E2E Runner",
    "phone": "01712345678",
    "division": "Dhaka",
    "district": FIXTURE_DISTRICT,
    "upazila": "Dhanmondi",
    "area": "Road 7",
    "street": "House 42, Road 7, Dhanmondi",
    "postcode": "1209",
}

# How many fixture products stay on the storefront.
#
# Every `product` and `order` fixture mints a fresh one, so an unbounded pool
# grows by roughly twenty per suite run and eventually swamps the demo
# catalogue -- which is not just untidy: the storefront specs read the first
# page of `/search?page_size=100`, and a few runs' worth of fixtures is enough
# to push THEIR fixture off it and turn a passing browse spec red for a reason
# that has nothing to do with browsing. (Observed, not theorised: it happened.)
#
# So the pool is capped. Older fixtures are DEACTIVATED, never deleted --
# orders snapshot what they sold but the OrderItem FK, the review history and
# the inventory ledger all stay attached to a real row (FR-CAT-7). The cap is
# comfortably more than one run creates, so a fixture is never retired while a
# test is still using it.
FIXTURE_POOL_LIMIT = 40

# The forward path through PRD §15.1, and the only order in which these
# fixtures ever walk it.
FORWARD = [
    OrderStatus.CONFIRMED,
    OrderStatus.PACKED,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
]


# The caller slices its JSON out from between these. See handle().
FENCE_OPEN = "<<<E2E_FIXTURE_JSON"
FENCE_CLOSE = "E2E_FIXTURE_JSON>>>"


def token():
    """Short, unique, and legal in a slug, an SKU and an email local part."""
    return uuid.uuid4().hex[:8]


class Command(BaseCommand):
    help = "Mint isolated fixtures for the Playwright e2e suite. Dev only."

    def add_arguments(self, parser):
        parser.add_argument(
            "what",
            choices=[
                "staff",
                "customer",
                "product",
                "order",
                "pending-review",
                "token",
            ],
        )
        parser.add_argument("--email", default="")
        parser.add_argument("--password", default="E2ePass!2026")
        parser.add_argument(
            "--payment",
            choices=[PaymentMethod.COD.value, PaymentMethod.ONLINE.value],
            default=PaymentMethod.ONLINE.value,
            help=(
                "online leaves the order pending, which is what a test that "
                "walks the whole pipeline needs. cod confirms at placement."
            ),
        )
        parser.add_argument(
            "--advance-to",
            default="",
            choices=["", *[status.value for status in FORWARD]],
            help="Walk the new order forward to this status, one legal step at a time.",
        )
        parser.add_argument("--stock", type=int, default=25)
        parser.add_argument("--quantity", type=int, default=1)
        parser.add_argument("--rating", type=int, default=5)

    def handle(self, *args, **options):
        handler = {
            "staff": self.make_staff,
            "customer": self.make_customer,
            "product": self.make_product,
            "order": self.make_order,
            "pending-review": self.make_pending_review,
            "token": self.make_token,
        }[options["what"]]

        # Cap the fixture pool before anything else, in its own transaction.
        if options["what"] in {"product", "order", "pending-review"}:
            self._retire_old_fixtures()

        # Order placement and every status change send mail inline (no queue in
        # v1, deliberately). Dev's console backend would print each message
        # straight into the stdout the caller is trying to parse, so the mail
        # goes to a locmem outbox for the life of the command instead. The
        # notification path still runs -- it is just not shouted over the answer.
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        ):
            payload = handler(options)

        # Fenced rather than bare, because Django is entitled to print warnings
        # on the same stream and a fixture that fails to parse is a test that
        # fails for no reason anybody can see.
        self.stdout.write(FENCE_OPEN)
        self.stdout.write(json.dumps(payload, default=str))
        self.stdout.write(FENCE_CLOSE)

    # -- shared scaffolding -------------------------------------------------
    def _admin(self):
        """
        The actor recorded against fixture writes.

        Every ledger row and status log wants a real actor, and attributing
        them to the seeded owner keeps the audit trail honest about what made
        them rather than leaving a blank.
        """
        admin = User.objects.filter(role=Role.ADMIN).order_by("pk").first()
        if admin is None:
            raise CommandError(
                "No admin user exists. Run manage.py seed_demo first."
            )
        return admin

    def _category(self):
        category, _ = Category.objects.get_or_create(
            slug=E2E_CATEGORY[1],
            defaults={"name": E2E_CATEGORY[0], "is_active": True, "sort_order": 900},
        )
        if not category.is_active:
            # A previous test may have deactivated it; an inactive category
            # hides everything inside it and would break the storefront half
            # of the review spec.
            category.is_active = True
            category.save(update_fields=["is_active", "updated_at"])
        return category

    def _ensure_zone(self):
        """A zone covering FIXTURE_DISTRICT, or placement cannot price delivery."""
        for zone in ShippingZone.objects.all():
            if zone.matches_district(FIXTURE_DISTRICT):
                return zone
        return ShippingZone.objects.create(
            name="E2E Dhaka",
            flat_rate=Decimal("60.00"),
            per_kg_rate=Decimal("0.00"),
            base_weight_grams=1000,
            cod_allowed=True,
            districts=[FIXTURE_DISTRICT],
            sort_order=900,
        )

    def _retire_old_fixtures(self):
        """
        Withdraw all but the newest FIXTURE_POOL_LIMIT fixture products.

        Called from handle() *before* the subcommand's own transaction opens,
        and committing in one of its own. Done inside the fixture's atomic
        block instead, these UPDATEs would hold row locks for as long as the
        rest of the fixture takes -- including an order placement, which takes
        `SELECT ... FOR UPDATE` on its variants -- and hand anything else
        touching this shared dev database a lock wait for no reason.
        """
        category = self._category()
        newest = list(
            Product.objects.filter(category=category)
            .order_by("-pk")
            .values_list("pk", flat=True)[:FIXTURE_POOL_LIMIT]
        )
        stale = (
            Product.objects.filter(category=category, is_active=True)
            .exclude(pk__in=newest)
            .order_by("pk")
        )
        admin = self._admin()
        retired = 0
        with transaction.atomic():
            for product in stale:
                administration.deactivate_product(product, actor=admin)
                retired += 1

            # Reviews are pruned rather than merely hidden. A withdrawn
            # product's review still sits in the moderation queue, and a queue
            # filling up with fixture noise is both useless to a developer and
            # a trap for a test: `/admin/reviews/` pages at 24, so a spec that
            # looks for the review it just made stops finding it on page one.
            # Deleting them keeps that queue the size of the fixture pool.
            orphaned = Review.objects.filter(product__category=category).exclude(
                product_id__in=newest
            )
            touched = list(
                Product.objects.filter(
                    pk__in=set(orphaned.values_list("product_id", flat=True))
                )
            )
            orphaned.delete()
            for product in touched:
                # rating_avg / rating_count are denormalised, so the single
                # writer has to be told (FR-REV-5).
                review_services.recompute_product_rating(product)

        return retired

    def _make_product(self, *, stock, price="4500.00", active=True):
        suffix = token()
        product = administration.create_product(
            name="E2E Widget {0}".format(suffix),
            category_id=self._category().pk,
            description="A fixture product created by the Playwright suite.",
            is_active=active,
            actor=self._admin(),
            specs=[{"key": "Fixture", "value": suffix, "sort_order": 0}],
            variants=[
                {
                    "sku": "E2E-{0}".format(suffix.upper()),
                    "option_label": "Standard",
                    "price": Decimal(price),
                    "stock": stock,
                    "low_stock_threshold": 5,
                    "weight_grams": 500,
                }
            ],
        )
        return product, product.variants.get()

    def _product_payload(self, product, variant):
        return {
            "product_id": product.pk,
            "product_name": product.name,
            "product_slug": product.slug,
            "variant_id": variant.pk,
            "sku": variant.sku,
            "price": str(variant.price),
            "stock": variant.stock,
            "low_stock_threshold": variant.low_stock_threshold,
            "category_slug": product.category.slug,
        }

    def _place(self, *, variant, quantity, payment, user=None, email=""):
        self._ensure_zone()
        StoreSettings.load()
        order, _created = placement_services.place_order(
            idempotency_key="e2e-{0}".format(uuid.uuid4().hex),
            payment_method=payment,
            shipping_address=dict(ADDRESS),
            user=user,
            email=email,
            phone=ADDRESS["phone"],
            items=[{"variant_id": variant.pk, "quantity": quantity}],
        )
        return order

    def _advance(self, order, to_status):
        """
        Walk the state machine forward, one legal step at a time.

        Never sets `status` directly: `packed -> shipped` needs a courier
        first, stock has to move on confirmation, and every step owes an
        OrderStatusLog row. Short-circuiting any of that would build a fixture
        the application could not have produced.
        """
        admin = self._admin()
        target_index = FORWARD.index(OrderStatus(to_status))

        while order.status != to_status:
            current = OrderStatus(order.status)
            # PENDING is not in FORWARD -- it is where an order starts, so the
            # next step from it is the first entry rather than the one after.
            next_index = (
                0 if current == OrderStatus.PENDING else FORWARD.index(current) + 1
            )
            if next_index > target_index:
                raise CommandError(
                    "Cannot walk a {0} order forward to {1}.".format(
                        order.status, to_status
                    )
                )
            step = FORWARD[next_index]
            if step == OrderStatus.SHIPPED:
                # packed -> shipped is marked requires_shipment in TRANSITIONS,
                # so the courier record is the prerequisite, not a field on the
                # transition.
                placement_services.record_shipment(
                    order=order,
                    courier_name="Sundarban",
                    tracking_number="E2E{0}".format(token().upper()),
                )
            order = placement_services.transition_order(
                order=order,
                to_status=step,
                actor=admin,
                actor_role=Actor.ADMIN,
                note="e2e fixture",
            )
        return order

    def _order_payload(self, order):
        order.refresh_from_db()
        return {
            "reference": order.reference,
            "status": order.status,
            "payment_method": order.payment_method,
            "grand_total": str(order.grand_total),
            "email": order.email,
            "item_count": order.items.count(),
            "admin_url": "/admin/orders/{0}".format(order.reference),
        }

    # -- subcommands --------------------------------------------------------
    @transaction.atomic
    def make_staff(self, options):
        """
        A STAFF-role account: may read orders and move their status, nothing
        else (PRD §4.3 US-A8). `is_staff` stays False -- that flag is Django
        Admin access and is a different thing entirely.
        """
        email = options["email"] or "e2e-staff@example.test"
        return self._upsert_user(
            email=email,
            password=options["password"],
            role=Role.STAFF,
            full_name="E2E Fulfilment Staff",
        )

    @transaction.atomic
    def make_customer(self, options):
        email = options["email"] or "e2e-customer-{0}@example.test".format(token())
        return self._upsert_user(
            email=email,
            password=options["password"],
            role=Role.CUSTOMER,
            full_name="E2E Customer",
        )

    def _upsert_user(self, *, email, password, role, full_name):
        user, created = User.objects.get_or_create(
            email=email.lower(),
            defaults={"full_name": full_name, "role": role, "is_email_verified": True},
        )
        # Unlike seed_demo, the password IS reset every time. A fixture account
        # whose password drifted from what the test types is a test that fails
        # for a reason that has nothing to do with the feature.
        user.role = role
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.set_password(password)
        user.save()
        refresh, access = issue_tokens(user)
        return {
            "id": user.pk,
            "email": user.email,
            "password": password,
            "role": user.role,
            "created": created,
            "access": access,
            "refresh": refresh,
        }

    def make_token(self, options):
        email = (options["email"] or "").strip().lower()
        if not email:
            raise CommandError("token needs --email.")
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError("No user with email {0}.".format(email))
        refresh, access = issue_tokens(user)
        return {
            "id": user.pk,
            "email": user.email,
            "role": user.role,
            "access": access,
            "refresh": refresh,
        }

    @transaction.atomic
    def make_product(self, options):
        product, variant = self._make_product(stock=options["stock"])
        return self._product_payload(product, variant)

    @transaction.atomic
    def make_order(self, options):
        product, variant = self._make_product(stock=options["stock"])
        order = self._place(
            variant=variant,
            quantity=options["quantity"],
            payment=options["payment"],
            email="e2e-order-{0}@example.test".format(token()),
        )
        if options["advance_to"]:
            order = self._advance(order, options["advance_to"])
        payload = self._order_payload(order)
        payload.update(self._product_payload(product, ProductVariant.objects.get(pk=variant.pk)))
        return payload

    @transaction.atomic
    def make_pending_review(self, options):
        """
        A product nobody has reviewed, plus one review of it sitting in the
        moderation queue.

        The order behind it is walked all the way to `delivered` through the
        real state machine, because FR-REV-2 is enforced server-side: without
        a delivered order containing the product, create_review refuses.
        """
        product, variant = self._make_product(stock=options["stock"])
        reviewer = self._upsert_user(
            email="e2e-reviewer-{0}@example.test".format(token()),
            password=options["password"],
            role=Role.CUSTOMER,
            full_name="E2E Reviewer",
        )
        user = User.objects.get(pk=reviewer["id"])
        order = self._place(
            variant=variant,
            quantity=1,
            payment=PaymentMethod.COD.value,
            user=user,
        )
        order = self._advance(order, OrderStatus.DELIVERED.value)

        suffix = token()
        review = review_services.create_review(
            user=user,
            product=product,
            rating=options["rating"],
            title="Fixture review {0}".format(suffix),
            body="Written by the Playwright suite so moderation has something to moderate.",
        )
        product.refresh_from_db()
        payload = self._product_payload(product, ProductVariant.objects.get(pk=variant.pk))
        payload.update(
            {
                "review_id": review.pk,
                "review_title": review.title,
                "review_status": review.status,
                "review_rating": review.rating,
                "reviewer_email": user.email,
                "reviewer_password": reviewer["password"],
                "order_reference": order.reference,
                "rating_avg": str(product.rating_avg),
                "rating_count": product.rating_count,
                "storefront_url": "/p/{0}".format(product.slug),
            }
        )
        # Nothing is approved yet, so the product must still read as unrated.
        assert product.rating_count == 0, "a pending review must not count"
        assert (
            Review.objects.get(pk=review.pk).status == ReviewStatus.PENDING
        ), "a new review must land in the moderation queue"
        return payload
