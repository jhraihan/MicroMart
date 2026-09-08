"""
The denormalised rating on Product (FR-REV-4, FR-REV-5).

`Product.rating_avg` / `rating_count` are a cache of a query, and a cache that
can drift silently is worse than no cache. So the arithmetic is asserted
exactly -- not "went up", not "is about right", but the precise two-decimal
figure the approved reviews imply -- and the pending and rejected states are
each shown to move it by nothing at all.

Every write goes through the services, so what is under test is the real path
a moderator's click takes, not a hand-built Review row.
"""
import pytest

from apps.catalog.models import Product
from apps.reviews.models import ReviewStatus
from apps.reviews.services import reviews as review_services

pytestmark = pytest.mark.django_db


def aggregate(product):
    """(rating_avg as a string, rating_count) straight from the database."""
    fresh = Product.objects.get(pk=product.pk)
    return str(fresh.rating_avg), fresh.rating_count


def test_a_product_with_no_reviews_reads_zero(product):
    assert aggregate(product) == ("0.00", 0)


def test_a_pending_review_moves_the_aggregate_by_nothing(product, write_review):
    write_review(5, approve=False)

    assert aggregate(product) == ("0.00", 0)


def test_approving_a_review_is_what_makes_it_count(product, write_review, admin):
    review = write_review(5, approve=False)
    assert aggregate(product) == ("0.00", 0)

    review_services.moderate_review(
        review=review, decision=review_services.DECISION_APPROVE, actor=admin
    )

    assert aggregate(product) == ("5.00", 1)


def test_rejecting_a_pending_review_still_moves_it_by_nothing(
    product, write_review, admin
):
    review = write_review(1, approve=False)

    review_services.moderate_review(
        review=review, decision=review_services.DECISION_REJECT, actor=admin
    )

    assert aggregate(product) == ("0.00", 0)
    assert review.status == ReviewStatus.REJECTED


def test_two_approved_reviews_average_exactly(product, write_review):
    write_review(5)
    write_review(4)

    # (5 + 4) / 2 = 4.5
    assert aggregate(product) == ("4.50", 2)


def test_a_recurring_average_is_rounded_half_up_to_two_places(product, write_review):
    """
    (5 + 4 + 2) / 3 = 3.666... -> 3.67.

    Stated as an exact expectation because the alternative -- reading AVG()
    back as a float -- produces 3.6666666666666665 and rounds inconsistently
    against the star breakdown printed beside it.
    """
    write_review(5)
    write_review(4)
    write_review(2)

    assert aggregate(product) == ("3.67", 3)


def test_rejecting_an_approved_review_removes_its_contribution(
    product, write_review, admin
):
    five = write_review(5)
    write_review(4)
    write_review(2)
    assert aggregate(product) == ("3.67", 3)

    review_services.moderate_review(
        review=five, decision=review_services.DECISION_REJECT, actor=admin
    )

    # (4 + 2) / 2 = 3.00
    assert aggregate(product) == ("3.00", 2)


def test_re_approving_a_rejected_review_puts_its_contribution_back(
    product, write_review, admin
):
    five = write_review(5)
    write_review(1)
    review_services.moderate_review(
        review=five, decision=review_services.DECISION_REJECT, actor=admin
    )
    assert aggregate(product) == ("1.00", 1)

    review_services.moderate_review(
        review=five, decision=review_services.DECISION_APPROVE, actor=admin
    )

    assert aggregate(product) == ("3.00", 2)


def test_the_aggregate_counts_only_this_products_reviews(
    product, other_product, write_review
):
    """A shared recompute that forgot to scope by product would pass everything above."""
    write_review(5)
    write_review(1, for_product=other_product)

    assert aggregate(product) == ("5.00", 1)
    assert aggregate(other_product) == ("1.00", 1)


def test_a_pending_and_a_rejected_review_are_both_invisible_to_the_public_list(
    product, write_review, admin
):
    approved = write_review(5)
    pending = write_review(4, approve=False)
    rejected = write_review(3, approve=False)
    review_services.moderate_review(
        review=rejected, decision=review_services.DECISION_REJECT, actor=admin
    )

    visible = list(review_services.approved_reviews(product))

    assert [row.pk for row in visible] == [approved.pk]
    assert pending.pk not in {row.pk for row in visible}


def test_the_summary_breakdown_agrees_with_the_stored_aggregate(
    product, write_review
):
    write_review(5)
    write_review(5)
    write_review(3)

    summary = review_services.rating_summary(product)

    # (5 + 5 + 3) / 3 = 4.333... -> 4.33
    assert summary["rating_avg"] == "4.33"
    assert summary["rating_count"] == 3
    assert summary["breakdown"] == [
        {"rating": 5, "count": 2},
        {"rating": 4, "count": 0},
        {"rating": 3, "count": 1},
        {"rating": 2, "count": 0},
        {"rating": 1, "count": 0},
    ]
    assert (summary["rating_avg"], summary["rating_count"]) == aggregate(product)


def test_a_rejected_review_is_absent_from_the_breakdown_as_well(
    product, write_review, admin
):
    write_review(5)
    rejected = write_review(1, approve=False)
    review_services.moderate_review(
        review=rejected, decision=review_services.DECISION_REJECT, actor=admin
    )

    summary = review_services.rating_summary(product)

    assert summary["rating_count"] == 1
    assert {row["rating"]: row["count"] for row in summary["breakdown"]}[1] == 0


def test_recompute_is_idempotent(product, write_review):
    """
    Derived, not incremented.

    Calling it twice must land on the same figure -- which is exactly what an
    increment-based implementation would fail.
    """
    write_review(4)
    write_review(5)
    first = aggregate(product)

    review_services.recompute_product_rating(product)
    review_services.recompute_product_rating(product)

    assert aggregate(product) == first == ("4.50", 2)
