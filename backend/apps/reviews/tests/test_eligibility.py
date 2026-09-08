"""
Who may write a review (FR-REV-2, FR-REV-3).

The rule under test is deliberately narrow: **a delivered order, belonging to
this customer, containing this product.** Every neighbouring case is asserted
separately, because each one is a plausible off-by-one in an implementation
that looked right:

* an order that exists but has not been delivered -- every non-delivered
  status is parametrised, so "checks for an order" cannot pass for "checks for
  a delivered order";
* a delivered order for a *different* product;
* somebody else's delivered order;
* a second review for a pair that already has one, refused by the service and,
  independently, by the database.

Assertions are on DomainError codes and HTTP status, never on wording.
"""
import pytest
from django.db import IntegrityError, transaction

from apps.orders.models import OrderStatus
from apps.reviews.models import Review, ReviewStatus
from apps.reviews.services import reviews as review_services
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db

# Every status that is not `delivered`. Parametrised rather than spot-checked:
# the whole point of FR-REV-2 is that only one of the seven earns a review.
NOT_DELIVERED = [
    OrderStatus.PENDING,
    OrderStatus.CONFIRMED,
    OrderStatus.PACKED,
    OrderStatus.SHIPPED,
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
]


def test_a_customer_who_has_never_ordered_the_product_cannot_review_it(
    customer, product
):
    with pytest.raises(DomainError) as exc:
        review_services.create_review(user=customer, product=product, rating=5)

    assert exc.value.code == "PURCHASE_REQUIRED"
    assert Review.objects.count() == 0


@pytest.mark.parametrize("status", NOT_DELIVERED)
def test_an_order_that_is_not_delivered_does_not_entitle_a_review(
    customer, product, variant, place_order, status
):
    place_order(customer, variant, status=status)

    with pytest.raises(DomainError) as exc:
        review_services.create_review(user=customer, product=product, rating=5)

    assert exc.value.code == "PURCHASE_REQUIRED"
    assert Review.objects.count() == 0


def test_a_delivered_order_containing_the_product_entitles_a_review(
    customer, product, variant, place_order
):
    order = place_order(customer, variant, status=OrderStatus.DELIVERED)

    review = review_services.create_review(
        user=customer, product=product, rating=5, title="Great", body="Fast machine."
    )

    assert review.pk is not None
    assert review.order_id == order.pk, "the proving order is recorded on the review"
    assert review.status == ReviewStatus.PENDING, "FR-REV-4: new reviews are pending"


def test_a_delivered_order_for_a_different_product_does_not_entitle_a_review(
    customer, product, other_product, place_order
):
    place_order(
        customer, other_product.variants.get(), status=OrderStatus.DELIVERED
    )

    with pytest.raises(DomainError) as exc:
        review_services.create_review(user=customer, product=product, rating=4)

    assert exc.value.code == "PURCHASE_REQUIRED"


def test_someone_elses_delivered_order_does_not_entitle_a_review(
    customer, other_customer, product, variant, place_order
):
    place_order(other_customer, variant, status=OrderStatus.DELIVERED)

    with pytest.raises(DomainError) as exc:
        review_services.create_review(user=customer, product=product, rating=4)

    assert exc.value.code == "PURCHASE_REQUIRED"


def test_an_anonymous_caller_is_never_eligible(product):
    assert review_services.delivered_purchase(None, product) is None
    assert review_services.can_review(None, product) is False


# ---------------------------------------------------------------------------
# One review per (product, user) -- FR-REV-3
# ---------------------------------------------------------------------------
def test_a_second_review_for_the_same_product_and_customer_is_refused(
    customer, product, variant, place_order
):
    place_order(customer, variant, status=OrderStatus.DELIVERED)
    review_services.create_review(user=customer, product=product, rating=5)

    with pytest.raises(DomainError) as exc:
        review_services.create_review(user=customer, product=product, rating=1)

    assert exc.value.code == "REVIEW_ALREADY_EXISTS"
    assert Review.objects.filter(product=product, user=customer).count() == 1


def test_the_database_refuses_a_second_review_even_when_the_service_is_bypassed(
    customer, product, variant, place_order
):
    """
    The uniqueness rule is a constraint, not merely a check.

    A check-then-insert loses a race; the UniqueConstraint on
    (product, user) is what actually makes the rule true, so it is asserted
    directly rather than inferred from the service refusing.
    """
    place_order(customer, variant, status=OrderStatus.DELIVERED)
    review_services.create_review(user=customer, product=product, rating=5)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Review.objects.create(product=product, user=customer, rating=1)


def test_can_review_is_false_once_a_review_exists(
    customer, product, variant, place_order
):
    """The flag the storefront reads is the same eligibility that gates the write."""
    place_order(customer, variant, status=OrderStatus.DELIVERED)
    assert review_services.can_review(customer, product) is True

    review_services.create_review(user=customer, product=product, rating=5)

    assert review_services.can_review(customer, product) is False


# ---------------------------------------------------------------------------
# The same rules over HTTP
# ---------------------------------------------------------------------------
def test_an_anonymous_caller_cannot_post_a_review(api, product, reviews_url):
    response = api.post(
        reviews_url(product.slug), {"rating": 5}, format="json"
    )

    assert response.status_code == 401


def test_posting_without_a_delivered_order_is_refused_server_side(
    shopper, product, reviews_url
):
    """
    FR-REV-2 is enforced on the server, not by hiding the form.

    A client that posts anyway is refused, which is the whole claim.
    """
    response = shopper.post(reviews_url(product.slug), {"rating": 5}, format="json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PURCHASE_REQUIRED"
    assert Review.objects.count() == 0


def test_a_delivered_purchase_can_post_and_lands_in_the_pending_queue(
    shopper, customer, product, variant, place_order, reviews_url
):
    place_order(customer, variant, status=OrderStatus.DELIVERED)

    response = shopper.post(
        reviews_url(product.slug),
        {"rating": 4, "title": "Solid", "body": "Good battery."},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == ReviewStatus.PENDING
    assert body["is_verified_purchase"] is True, "FR-REV-6: derived from the order"
    assert body["author_name"] == "Rafiq Hasan"
    assert "email" not in str(body), "a public review must not carry an address"


def test_a_review_on_a_hidden_product_is_a_404(
    shopper, customer, product, variant, place_order, reviews_url
):
    place_order(customer, variant, status=OrderStatus.DELIVERED)
    product.is_active = False
    product.save(update_fields=["is_active"])

    response = shopper.post(reviews_url(product.slug), {"rating": 5}, format="json")

    assert response.status_code == 404


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_a_rating_outside_one_to_five_is_rejected(
    shopper, customer, product, variant, place_order, reviews_url, rating
):
    place_order(customer, variant, status=OrderStatus.DELIVERED)

    response = shopper.post(
        reviews_url(product.slug), {"rating": rating}, format="json"
    )

    assert response.status_code == 400
    assert Review.objects.count() == 0


@pytest.mark.parametrize("rating", [0, 6, "five", None])
def test_the_service_validates_the_rating_too(
    customer, product, variant, place_order, rating
):
    """
    The serializer is not the only guard.

    create_review is called from tests, management commands and -- once the
    admin surface grows -- from other services, none of which pass through a
    DRF serializer.
    """
    place_order(customer, variant, status=OrderStatus.DELIVERED)

    with pytest.raises(DomainError) as exc:
        review_services.create_review(user=customer, product=product, rating=rating)

    assert exc.value.code == "INVALID_RATING"
