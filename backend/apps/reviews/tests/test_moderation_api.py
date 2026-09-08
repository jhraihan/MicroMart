"""
The public review list and the admin moderation surface (PRD 7.2, 7.3).

Two claims dominate:

* **Only approved reviews are public** (FR-REV-4). A pending or rejected
  review must be absent from the list, not merely styled differently.
* **Moderation is gated on the server** (PRD 10.2). PRD 7.3 gives
  /admin/reviews/ to the Admin role, so a customer *and* a staff user are both
  refused -- hiding the screen in React is not the control.

Both surfaces are asserted to go through the same service: approving over HTTP
must move Product.rating_avg exactly as calling moderate_review directly does,
because it is the same function.
"""
import pytest

from apps.catalog.models import Product
from apps.reviews.models import Review, ReviewStatus
from apps.reviews.services import reviews as review_services

pytestmark = pytest.mark.django_db


def aggregate(product):
    fresh = Product.objects.get(pk=product.pk)
    return str(fresh.rating_avg), fresh.rating_count


# ---------------------------------------------------------------------------
# GET /products/{slug}/reviews/
# ---------------------------------------------------------------------------
def test_the_public_list_shows_approved_reviews_only(
    api, product, write_review, admin, reviews_url
):
    approved = write_review(5)
    write_review(4, approve=False)
    rejected = write_review(1, approve=False)
    review_services.moderate_review(
        review=rejected, decision=review_services.DECISION_REJECT, actor=admin
    )

    response = api.get(reviews_url(product.slug))

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body["results"]] == [approved.pk]
    assert body["count"] == 1


def test_the_public_list_carries_the_summary_beside_the_page(
    api, product, write_review, reviews_url
):
    write_review(5)
    write_review(4)

    body = api.get(reviews_url(product.slug)).json()

    assert body["summary"]["rating_avg"] == "4.50"
    assert body["summary"]["rating_count"] == 2
    assert body["can_review"] is False, "an anonymous reader cannot review"


def test_the_list_is_public_and_needs_no_login(api, product, reviews_url):
    response = api.get(reviews_url(product.slug))

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_a_verified_purchase_badge_is_derived_not_declared(
    api, product, write_review, reviews_url
):
    """
    FR-REV-6: eligibility already guarantees the purchase.

    The badge tracks the proving order on the review, and there is no request
    field that can set it -- posting one is ignored, which is asserted in
    test_eligibility's create path.
    """
    write_review(5)

    row = api.get(reviews_url(product.slug)).json()["results"][0]

    assert row["is_verified_purchase"] is True


def test_the_list_can_be_filtered_by_star_rating(
    api, product, write_review, reviews_url
):
    write_review(5)
    four = write_review(4)

    body = api.get(reviews_url(product.slug), {"rating": 4}).json()

    assert [row["id"] for row in body["results"]] == [four.pk]


@pytest.mark.parametrize(
    "params,code",
    [
        ({"rating": "9"}, "INVALID_FILTER"),
        ({"rating": "many"}, "INVALID_FILTER"),
        ({"sort": "most_helpful"}, "INVALID_SORT"),
    ],
)
def test_a_nonsense_filter_is_a_422_rather_than_being_ignored(
    api, product, reviews_url, params, code
):
    """A filter that quietly does nothing returns a wrong list that looks right."""
    response = api.get(reviews_url(product.slug), params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_the_list_for_a_hidden_product_is_a_404(api, product, reviews_url):
    product.is_active = False
    product.save(update_fields=["is_active"])

    assert api.get(reviews_url(product.slug)).status_code == 404


# ---------------------------------------------------------------------------
# GET /admin/reviews/
# ---------------------------------------------------------------------------
def test_an_anonymous_caller_cannot_read_the_moderation_queue(
    api, moderation_queue_url
):
    assert api.get(moderation_queue_url).status_code == 401


def test_a_customer_is_refused_the_moderation_queue_with_403(
    as_user, customer, moderation_queue_url
):
    response = as_user(customer).get(moderation_queue_url)

    assert response.status_code == 403


def test_a_staff_user_is_refused_too_because_prd_7_3_says_admin(
    as_user, staff_member, moderation_queue_url
):
    """
    PRD 7.3 lists review moderation under the Admin role alone, unlike the
    order endpoints which read "Admin, Staff". Pinned so a later widening is a
    deliberate decision rather than a copy-paste.
    """
    response = as_user(staff_member).get(moderation_queue_url)

    assert response.status_code == 403


def test_the_queue_defaults_to_pending(
    moderator, product, write_review, moderation_queue_url
):
    approved = write_review(5)
    pending = write_review(3, approve=False)

    body = moderator.get(moderation_queue_url).json()

    ids = [row["id"] for row in body["results"]]
    assert pending.pk in ids
    assert approved.pk not in ids


def test_the_queue_can_be_asked_for_any_status(
    moderator, product, write_review, moderation_queue_url
):
    approved = write_review(5)
    pending = write_review(3, approve=False)

    body = moderator.get(moderation_queue_url, {"status": "all"}).json()

    ids = {row["id"] for row in body["results"]}
    assert {approved.pk, pending.pk} <= ids


def test_an_unknown_status_filter_is_a_422(moderator, moderation_queue_url):
    response = moderator.get(moderation_queue_url, {"status": "spam"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FILTER"


def test_the_queue_row_carries_what_a_moderator_needs_to_judge_it(
    moderator, product, write_review, moderation_queue_url
):
    review = write_review(2, approve=False)

    row = moderator.get(moderation_queue_url).json()["results"][0]

    assert row["id"] == review.pk
    assert row["product"]["slug"] == product.slug
    assert row["author_email"] == review.user.email
    assert row["order_reference"] == review.order.reference
    assert row["is_verified_purchase"] is True


# ---------------------------------------------------------------------------
# POST /admin/reviews/{id}/moderate/
# ---------------------------------------------------------------------------
def test_a_customer_cannot_moderate_a_review(
    as_user, customer, product, write_review, moderate_url
):
    review = write_review(1, approve=False)

    response = as_user(customer).post(
        moderate_url(review.pk), {"decision": "approve"}, format="json"
    )

    assert response.status_code == 403
    assert Review.objects.get(pk=review.pk).status == ReviewStatus.PENDING


def test_a_customer_cannot_moderate_their_own_review_either(
    as_user, customer, product, variant, place_order, moderate_url
):
    """Owning the review is not a route around the admin gate."""
    place_order(customer, variant)
    review = review_services.create_review(user=customer, product=product, rating=5)

    response = as_user(customer).post(
        moderate_url(review.pk), {"decision": "approve"}, format="json"
    )

    assert response.status_code == 403
    assert aggregate(product) == ("0.00", 0)


def test_a_staff_user_cannot_moderate(
    as_user, staff_member, product, write_review, moderate_url
):
    review = write_review(1, approve=False)

    response = as_user(staff_member).post(
        moderate_url(review.pk), {"decision": "approve"}, format="json"
    )

    assert response.status_code == 403


def test_an_admin_approving_over_http_updates_the_product_aggregate(
    moderator, admin, product, write_review, moderate_url
):
    """
    The admin surface calls the same service the rest of the system does.

    If it flipped `status` itself, the review would go live with a stale
    rating_avg -- so the aggregate is what is asserted, not the status.
    """
    review = write_review(4, approve=False)
    assert aggregate(product) == ("0.00", 0)

    response = moderator.post(
        moderate_url(review.pk), {"decision": "approve"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["status"] == ReviewStatus.APPROVED
    assert aggregate(product) == ("4.00", 1)
    stored = Review.objects.get(pk=review.pk)
    assert stored.moderated_by_id == admin.pk
    assert stored.moderated_at is not None


def test_an_admin_rejecting_an_approved_review_pulls_it_back_out_of_public_view(
    moderator, api, product, write_review, moderate_url, reviews_url
):
    review = write_review(5)
    assert aggregate(product) == ("5.00", 1)

    moderator.post(moderate_url(review.pk), {"decision": "reject"}, format="json")

    assert aggregate(product) == ("0.00", 0)
    assert api.get(reviews_url(product.slug)).json()["results"] == []


def test_an_unknown_decision_is_rejected(moderator, write_review, moderate_url):
    review = write_review(3, approve=False)

    response = moderator.post(
        moderate_url(review.pk), {"decision": "delete"}, format="json"
    )

    assert response.status_code == 400
    assert Review.objects.get(pk=review.pk).status == ReviewStatus.PENDING


def test_moderating_a_review_that_does_not_exist_is_a_404(moderator, moderate_url):
    response = moderator.post(
        moderate_url(99999999), {"decision": "approve"}, format="json"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
