"""
The 30-day edit window and what an edit costs (FR-REV-3, FR-REV-4, FR-REV-5).

Time is frozen and advanced explicitly by the `clock` fixture -- never slept,
and never faked by back-dating `created_at` behind Django's back. Both
instants are named in the test, which is the only way a window test says what
it means.

The three claims here:

1. inside the window an edit succeeds;
2. an edit sends the review back to `pending` and strips its moderation
   stamp -- otherwise "approve, then rewrite the body" publishes unmoderated
   text;
3. the product aggregate loses the edited review's contribution at the same
   moment, because it is no longer approved.
"""
import pytest

from apps.catalog.models import Product
from apps.orders.models import OrderStatus
from apps.reviews.models import REVIEW_EDIT_WINDOW_DAYS, Review, ReviewStatus
from apps.reviews.services import reviews as review_services
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture
def approved_review(clock, customer, product, variant, place_order, admin):
    """A review written at the frozen epoch and approved on the spot."""
    place_order(customer, variant, status=OrderStatus.DELIVERED)
    review = review_services.create_review(
        user=customer, product=product, rating=5, title="Great", body="Fast machine."
    )
    return review_services.moderate_review(
        review=review, decision=review_services.DECISION_APPROVE, actor=admin
    )


def _reload(product):
    return Product.objects.get(pk=product.pk)


def test_an_edit_inside_the_window_succeeds(clock, customer, approved_review, product):
    clock.advance(days=29)

    updated = review_services.update_review(
        user=customer, review_id=approved_review.pk, rating=3, body="Fan is loud."
    )

    assert updated.rating == 3
    assert updated.body == "Fan is loud."


def test_an_edit_on_the_last_day_of_the_window_is_still_allowed(
    clock, customer, approved_review
):
    """
    The boundary is inclusive: `now - created_at <= 30 days`.

    Asserted explicitly because an off-by-one here is invisible until a
    customer hits it on exactly the wrong day.
    """
    clock.advance(days=REVIEW_EDIT_WINDOW_DAYS)

    updated = review_services.update_review(
        user=customer, review_id=approved_review.pk, rating=2
    )

    assert updated.rating == 2


def test_an_edit_returns_the_review_to_pending_and_clears_its_moderation_stamp(
    clock, customer, approved_review
):
    assert approved_review.status == ReviewStatus.APPROVED
    assert approved_review.moderated_at is not None
    clock.advance(days=1)

    updated = review_services.update_review(
        user=customer, review_id=approved_review.pk, body="Second thoughts."
    )

    assert updated.status == ReviewStatus.PENDING, "FR-REV-4: an edit is re-moderated"
    assert updated.moderated_at is None
    assert updated.moderated_by_id is None


def test_an_edit_removes_the_review_from_the_product_aggregate(
    clock, customer, approved_review, product
):
    """
    FR-REV-5: only approved reviews count, and an edited review is not
    approved any more -- so the rating it was holding up must go with it.
    """
    before = _reload(product)
    assert (str(before.rating_avg), before.rating_count) == ("5.00", 1)
    clock.advance(days=2)

    review_services.update_review(user=customer, review_id=approved_review.pk, rating=1)

    fresh = _reload(product)
    assert str(fresh.rating_avg) == "0.00"
    assert fresh.rating_count == 0


def test_an_edit_the_day_after_the_window_closes_is_refused(
    clock, customer, approved_review
):
    clock.advance(days=REVIEW_EDIT_WINDOW_DAYS + 1)

    with pytest.raises(DomainError) as exc:
        review_services.update_review(
            user=customer, review_id=approved_review.pk, rating=1, body="Changed my mind."
        )

    assert exc.value.code == "REVIEW_EDIT_WINDOW_CLOSED"


def test_a_refused_edit_changes_nothing_at_all(
    clock, customer, approved_review, product
):
    clock.advance(days=REVIEW_EDIT_WINDOW_DAYS + 1)

    with pytest.raises(DomainError):
        review_services.update_review(
            user=customer, review_id=approved_review.pk, rating=1, body="Changed my mind."
        )

    stored = Review.objects.get(pk=approved_review.pk)
    assert stored.rating == 5
    assert stored.body == "Fast machine."
    assert stored.status == ReviewStatus.APPROVED
    assert _reload(product).rating_count == 1, "the aggregate was not disturbed either"


# ---------------------------------------------------------------------------
# The same window over HTTP, and object-level authorisation
# ---------------------------------------------------------------------------
def test_the_author_can_patch_inside_the_window(
    clock, as_user, customer, approved_review, review_url
):
    clock.advance(days=5)

    response = as_user(customer).patch(
        review_url(approved_review.pk), {"rating": 4}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rating"] == 4
    assert body["status"] == ReviewStatus.PENDING


def test_a_patch_after_the_window_is_a_422_with_a_stable_code(
    clock, as_user, customer, approved_review, review_url
):
    clock.advance(days=REVIEW_EDIT_WINDOW_DAYS + 1)

    response = as_user(customer).patch(
        review_url(approved_review.pk), {"rating": 4}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REVIEW_EDIT_WINDOW_CLOSED"


def test_editing_someone_elses_review_is_a_404_not_a_403(
    clock, as_user, other_customer, approved_review, review_url
):
    """
    PRD 10.2: a 403 would confirm the review exists and leak the id space.

    The 404 must be indistinguishable from the one an id that never existed
    produces -- so both are asserted.
    """
    response = as_user(other_customer).patch(
        review_url(approved_review.pk), {"rating": 1}, format="json"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert Review.objects.get(pk=approved_review.pk).rating == 5


def test_editing_a_review_that_does_not_exist_is_the_same_404(
    as_user, other_customer, review_url
):
    response = as_user(other_customer).patch(
        review_url(99999999), {"rating": 1}, format="json"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_deleting_someone_elses_review_is_a_404_too(
    as_user, other_customer, approved_review, review_url
):
    response = as_user(other_customer).delete(review_url(approved_review.pk))

    assert response.status_code == 404
    assert Review.objects.filter(pk=approved_review.pk).exists()


def test_an_author_withdrawing_their_review_takes_its_rating_with_it(
    as_user, customer, approved_review, product, review_url
):
    """FR-REV-5's `removal` limb -- the aggregate is recomputed on delete."""
    assert _reload(product).rating_count == 1

    response = as_user(customer).delete(review_url(approved_review.pk))

    assert response.status_code == 204
    assert not Review.objects.filter(pk=approved_review.pk).exists()
    fresh = _reload(product)
    assert str(fresh.rating_avg) == "0.00"
    assert fresh.rating_count == 0
