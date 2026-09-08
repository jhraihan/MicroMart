"""
Fixtures for the reviews and wishlist suite (PRD 5.8, 5.9).

Written in the style of apps/cart/tests/conftest.py: every test builds the
rows it asserts on, and the two values these tests turn on -- order *status*
and elapsed *time* -- are always stated by the test that depends on them.

`clock` is the fixture that matters most. The 30-day edit window is a rule
about elapsed time, and the only honest way to test one is to name both
instants. Sleeping would test the test runner's patience instead, and a review
written "31 days ago" by back-dating `created_at` behind Django's back would
be asserting on a row the application could not have produced.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.catalog.tests import factories
from apps.orders.models import Order, OrderStatus
from apps.reviews.services import reviews as review_services

PASSWORD = "Str0ngPass!2026"

# An arbitrary but fixed instant. Nothing depends on the date itself -- only on
# the intervals measured from it.
EPOCH = datetime(2026, 8, 22, 9, 0, tzinfo=dt_timezone.utc)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
class Clock:
    """A hand-cranked `timezone.now`."""

    def __init__(self, start):
        self.now = start

    def set(self, value):
        self.now = value
        return self.now

    def advance(self, **kwargs):
        self.now = self.now + timedelta(**kwargs)
        return self.now


@pytest.fixture
def clock(monkeypatch):
    """
    Freeze and advance `django.utils.timezone.now`.

    Patched on the module rather than on each caller because Django's
    auto_now_add reads `timezone.now()` at write time -- so a Review created
    under this fixture carries the frozen `created_at`, and advancing the
    clock afterwards is genuinely elapsed time as far as the application can
    tell. simplejwt keeps its own UTC clock, so tokens are unaffected.
    """
    instance = Clock(EPOCH)
    monkeypatch.setattr(timezone, "now", lambda: instance.now)
    return instance


# ---------------------------------------------------------------------------
# Clients and people
# ---------------------------------------------------------------------------
@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="shopper@example.com", password=PASSWORD, full_name="Rafiq Hasan"
    )


@pytest.fixture
def other_customer(db):
    """A second shopper, so cross-account leaks have somewhere to leak from."""
    return User.objects.create_user(
        email="someone-else@example.com", password=PASSWORD, full_name="Nadia Karim"
    )


@pytest.fixture
def admin(db):
    return User.objects.create_user(
        email="owner@example.com", password=PASSWORD, role=Role.ADMIN
    )


@pytest.fixture
def staff_member(db):
    """
    Staff, not admin. PRD 7.3 gives review moderation to the Admin role alone,
    so this user must be refused -- which is only meaningful if someone
    asserts it.
    """
    return User.objects.create_user(
        email="helper@example.com", password=PASSWORD, role=Role.STAFF
    )


@pytest.fixture
def shopper(api, customer):
    return _authenticated(api, customer)


@pytest.fixture
def moderator(api, admin):
    return _authenticated(api, admin)


def _authenticated(api, user):
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def as_user(api):
    """Re-point the shared client at whoever the test needs next."""

    def _as(user):
        api.force_authenticate(user=user)
        return api

    return _as


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@pytest.fixture
def category(db):
    return factories.make_category("Laptops", "laptops")


@pytest.fixture
def product(category):
    """One buyable product: 1000.00 BDT, 10 on hand, no reviews yet."""
    return factories.make_product(
        category,
        name="Asus Vivobook Go 15",
        slug="asus-vivobook-go-15",
        sku="VIVO-8-512",
        price="1000.00",
        stock=10,
    )


@pytest.fixture
def variant(product):
    return product.variants.get()


@pytest.fixture
def other_product(category):
    """A second product, so "bought something" is not mistaken for "bought this"."""
    return factories.make_product(
        category,
        name="Logitech MX Master 3S",
        slug="logitech-mx-master-3s",
        sku="MX-MASTER-3S",
        price="250.50",
        stock=4,
    )


@pytest.fixture
def build_product(category):
    """Build a product at the price and stock a test needs to name."""

    def _build(**kwargs):
        return factories.make_product(category, **kwargs)

    return _build


# ---------------------------------------------------------------------------
# Purchases -- what eligibility is decided from
# ---------------------------------------------------------------------------
@pytest.fixture
def place_order():
    """
    An order for `user` containing `variant`, in the status the test names.

    Built through the catalogue factory so the OrderItem carries a real
    variant FK -- which is what review eligibility matches on. An item whose
    variant is null proves nothing about which product was bought.
    """

    def _place(user, variant, *, status=OrderStatus.DELIVERED, quantity=1):
        order = factories.place_order([(variant, quantity)], status=status)
        Order.objects.filter(pk=order.pk).update(user=user)
        order.refresh_from_db()
        return order

    return _place


@pytest.fixture
def buyer(place_order, product, db):
    """
    A customer who has taken delivery of `product`, and may therefore review it.

    Each call makes a *new* customer, because one review per (product, user)
    means a product with three reviews needs three people.
    """
    counter = {"n": 0}

    def _buyer(for_product=None, *, status=OrderStatus.DELIVERED):
        counter["n"] += 1
        user = User.objects.create_user(
            email="buyer{0}@example.com".format(counter["n"]),
            password=PASSWORD,
            full_name="Buyer {0}".format(counter["n"]),
        )
        target = for_product or product
        place_order(user, target.variants.first(), status=status)
        return user

    return _buyer


@pytest.fixture
def write_review(buyer, product):
    """
    An approved-by-default review helper for aggregate arithmetic tests.

    Goes through the services rather than Review.objects.create, so a test
    about the aggregate is exercising the real write path -- including the
    recompute it is asserting on.
    """

    def _write(rating, *, for_product=None, approve=True, author=None, moderator=None):
        target = for_product or product
        user = author or buyer(target)
        review = review_services.create_review(
            user=user, product=target, rating=rating, title="", body=""
        )
        if approve:
            review_services.moderate_review(
                review=review,
                decision=review_services.DECISION_APPROVE,
                actor=moderator,
            )
        return review

    return _write


# ---------------------------------------------------------------------------
# Routes (apps/reviews/urls.py, apps/reviews/admin_urls.py)
# ---------------------------------------------------------------------------
@pytest.fixture
def reviews_url():
    return lambda slug: reverse("reviews:product-review-list", kwargs={"slug": slug})


@pytest.fixture
def review_url():
    return lambda pk: reverse("reviews:review-detail", kwargs={"pk": pk})


@pytest.fixture
def wishlist_url():
    return reverse("reviews:wishlist")


@pytest.fixture
def wishlist_item_url():
    return lambda product_id: reverse(
        "reviews:wishlist-item", kwargs={"product_id": product_id}
    )


@pytest.fixture
def moderation_queue_url():
    return reverse("reviews_admin:review-list")


@pytest.fixture
def moderate_url():
    return lambda pk: reverse("reviews_admin:review-moderate", kwargs={"pk": pk})
