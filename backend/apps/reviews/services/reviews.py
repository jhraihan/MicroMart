"""
Reviews.

Four rules, all enforced here rather than in a view or the UI:

1. Only a delivered purchase earns a review. Eligibility is a query against
   OrderItem on an order this customer owns whose status is delivered. The
   proving order is stored on the review, which is also where the Verified
   Purchase badge comes from -- the badge is a consequence of eligibility,
   never a flag anyone can set.
2. One review per (product, user), backed by a UniqueConstraint. The author
   may edit it for REVIEW_EDIT_WINDOW_DAYS; after that the edit is refused
   rather than silently ignored.
3. Every write lands in pending, and an edited review returns to pending --
   otherwise "approve, then rewrite the body" is an unmoderated channel.
4. recompute_product_rating is the only writer of rating_avg / rating_count,
   and it counts approved reviews only.

Authorisation misses raise a 404-shaped DomainError, never 403.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.catalog.models import Product
from apps.orders.models import OrderItem, OrderStatus
from config.exceptions import DomainError

from ..models import REVIEW_EDIT_WINDOW_DAYS, Review, ReviewStatus

RATING_MIN = 1
RATING_MAX = 5
RATING_VALUES = (5, 4, 3, 2, 1)

MAX_TITLE_LENGTH = 150
MAX_BODY_LENGTH = 4000

ZERO_RATING = Decimal("0.00")
_RATING_QUANTUM = Decimal("0.01")

# Sort options for the public list (FR-REV-7).
#
# "Most helpful" is deliberately absent: there is no helpfulness vote on
# Review, so a `helpful` sort could only be faked from some other column. That
# half of FR-REV-7 is P2 and needs a model change; inventing a proxy for it
# would be worse than not offering it.
SORT_RECENT = "recent"
SORT_OLDEST = "oldest"
SORT_RATING_HIGH = "rating_high"
SORT_RATING_LOW = "rating_low"

_ORDERINGS = {
    SORT_RECENT: ("-created_at", "-id"),
    SORT_OLDEST: ("created_at", "id"),
    SORT_RATING_HIGH: ("-rating", "-created_at", "-id"),
    SORT_RATING_LOW: ("rating", "-created_at", "-id"),
}

# Moderation decisions -- the wire vocabulary for POST /admin/reviews/{id}/moderate/.
DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"

_DECISIONS = {
    DECISION_APPROVE: ReviewStatus.APPROVED,
    DECISION_REJECT: ReviewStatus.REJECTED,
}


# ---------------------------------------------------------------------------
# Eligibility (FR-REV-2)
# ---------------------------------------------------------------------------
def delivered_purchase(user, product):
    """
    The delivered order that entitles `user` to review `product`, or None.

    Matched on OrderItem.variant -> product rather than on the snapshotted
    product name: the name is a copy taken at purchase time and two products
    may share one, so it proves nothing about identity. An order line whose
    variant was later deleted therefore cannot earn a review -- correct, since
    nothing links it to a catalogue row any more.

    `order__user=user` scopes the search to this customer's own orders before
    anything else, which is the same ordering the order history uses.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    item = (
        OrderItem.objects.filter(
            order__user=user,
            order__status=OrderStatus.DELIVERED,
            variant__product=product,
        )
        .select_related("order")
        .order_by("-order__placed_at", "-id")
        .first()
    )
    return item.order if item is not None else None


def can_review(user, product):
    """
    May this customer write a review for this product right now?

    False once they already have one, so the storefront offers "edit your
    review" instead of a form that would 422. The same function answers the
    UI's question and gates the write, so the two cannot disagree.
    """
    if delivered_purchase(user, product) is None:
        return False
    return not Review.objects.filter(product=product, user=user).exists()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def _base_queryset():
    """Every read in this module starts here, storefront and admin alike."""
    return Review.objects.select_related(
        "user", "product", "product__brand", "order", "moderated_by"
    )


def approved_reviews(product, *, rating=None, sort=SORT_RECENT):
    """
    The publicly visible reviews of one product (FR-REV-4).

    Approved only. A pending review is invisible even to its own author here;
    the author gets it back from the create/edit response instead, which is
    where the "awaiting moderation" state belongs.
    """
    queryset = _base_queryset().filter(product=product, status=ReviewStatus.APPROVED)
    if rating is not None:
        queryset = queryset.filter(rating=rating)
    return queryset.order_by(*_ORDERINGS.get(sort, _ORDERINGS[SORT_RECENT]))


def moderation_queue(*, status=ReviewStatus.PENDING):
    """
    GET /admin/reviews/?status=pending -- oldest first, so the queue drains
    in the order customers wrote it.

    `status=None` means every review regardless of state.
    """
    queryset = _base_queryset()
    if status is not None:
        queryset = queryset.filter(status=status)
    return queryset.order_by("created_at", "id")


def rating_summary(product):
    """
    The star breakdown shown beside a product's review list.

    Counted over approved reviews with the same arithmetic
    recompute_product_rating uses, so the number on the product card and the
    number above the review list are the same number.
    """
    row = Review.objects.filter(product=product, status=ReviewStatus.APPROVED).aggregate(
        count=Count("id"),
        total=Sum("rating"),
        **{
            "r{0}".format(value): Count("id", filter=Q(rating=value))
            for value in RATING_VALUES
        },
    )
    count = row["count"] or 0
    average = _average(row["total"] or 0, count)
    return {
        "rating_avg": str(average),
        "rating_count": count,
        "breakdown": [
            {"rating": value, "count": row["r{0}".format(value)] or 0}
            for value in RATING_VALUES
        ],
    }


def get_review(review_id):
    """Any review by id -- admin only. Customers go through get_own_review."""
    review = _base_queryset().filter(pk=review_id).first()
    if review is None:
        raise DomainError("Not found.", code="NOT_FOUND", status_code=404)
    return review


def get_own_review(user, review_id):
    """
    This customer's own review, or a 404-shaped error.

    Scoped to `user` *before* the id is matched. That ordering is the whole
    point: someone else's review simply does not exist for this request, so
    the miss is a 404 and never a 403 (PRD 10.2).
    """
    review = _base_queryset().filter(pk=review_id, user=user).first()
    if review is None:
        raise DomainError("Not found.", code="NOT_FOUND", status_code=404)
    return review


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def _validate_rating(rating):
    try:
        value = int(rating)
    except (TypeError, ValueError):
        raise DomainError(
            "A rating must be a whole number of stars.",
            code="INVALID_RATING",
            field="rating",
        )
    if not RATING_MIN <= value <= RATING_MAX:
        raise DomainError(
            "A rating must be between {0} and {1} stars.".format(RATING_MIN, RATING_MAX),
            code="INVALID_RATING",
            field="rating",
        )
    return value


def _clean_text(value, limit):
    return (value or "").strip()[:limit]


@transaction.atomic
def create_review(*, user, product, rating, title="", body=""):
    """
    Write a review for a delivered purchase (FR-REV-1..4).

    Deliberately does *not* recompute the product aggregate: the new review is
    pending, so the approved set is unchanged. Recomputing here would be a
    no-op that reads as though a pending review might count.
    """
    order = delivered_purchase(user, product)
    if order is None:
        raise DomainError(
            "You can review this product once an order containing it has been delivered.",
            code="PURCHASE_REQUIRED",
            field="product",
        )

    value = _validate_rating(rating)
    if Review.objects.filter(product=product, user=user).exists():
        raise DomainError(
            "You have already reviewed this product. Edit that review instead.",
            code="REVIEW_ALREADY_EXISTS",
            field="product",
        )

    try:
        # Nested atomic so the UniqueConstraint losing a race rolls back to a
        # savepoint instead of poisoning the outer transaction.
        with transaction.atomic():
            review = Review.objects.create(
                product=product,
                user=user,
                order=order,
                rating=value,
                title=_clean_text(title, MAX_TITLE_LENGTH),
                body=_clean_text(body, MAX_BODY_LENGTH),
                status=ReviewStatus.PENDING,
            )
    except IntegrityError:
        raise DomainError(
            "You have already reviewed this product. Edit that review instead.",
            code="REVIEW_ALREADY_EXISTS",
            field="product",
        )
    return review


@transaction.atomic
def update_review(*, user, review_id, rating=None, title=None, body=None):
    """
    Edit one's own review inside the 30-day window (FR-REV-3, FR-REV-4).

    Two consequences that are easy to skip and must not be:

    * the review returns to `pending`, because an approved review whose text
      can be rewritten afterwards is an unmoderated publishing channel; and
    * the product aggregate is recomputed, because a review that *was*
      approved has just left the approved set.
    """
    review = get_own_review(user, review_id)

    # One definition of the window, on the model, so the API and Django Admin
    # cannot disagree about whether a review is still editable.
    if not review.is_editable:
        raise DomainError(
            "A review can be edited for {0} days after it is written.".format(
                REVIEW_EDIT_WINDOW_DAYS
            ),
            code="REVIEW_EDIT_WINDOW_CLOSED",
            field="review",
        )

    if rating is not None:
        review.rating = _validate_rating(rating)
    if title is not None:
        review.title = _clean_text(title, MAX_TITLE_LENGTH)
    if body is not None:
        review.body = _clean_text(body, MAX_BODY_LENGTH)

    review.status = ReviewStatus.PENDING
    review.moderated_at = None
    review.moderated_by = None
    review.save(
        update_fields=[
            "rating",
            "title",
            "body",
            "status",
            "moderated_at",
            "moderated_by",
            "updated_at",
        ]
    )
    recompute_product_rating(review.product)
    return review


@transaction.atomic
def delete_review(*, user, review_id):
    """
    The author withdraws their review -- the "removal" limb of FR-REV-5.

    Scoped through get_own_review, so someone else's review is a 404.
    """
    review = get_own_review(user, review_id)
    product = review.product
    review.delete()
    recompute_product_rating(product)
    return product


@transaction.atomic
def moderate_review(*, review, decision, actor=None):
    """
    Approve or reject one review (FR-REV-4), then recompute the aggregate.

    The only way a review becomes publicly visible, and the only way it stops
    being. Called by the admin API; Django Admin keeps `status` read-only so
    nothing can reach it another way and leave rating_avg stale.
    """
    status = _DECISIONS.get(decision)
    if status is None:
        raise DomainError(
            "A moderation decision must be one of: {0}.".format(
                ", ".join(sorted(_DECISIONS))
            ),
            code="INVALID_MODERATION_DECISION",
            field="decision",
        )

    review.status = status
    review.moderated_at = timezone.now()
    review.moderated_by = actor if getattr(actor, "pk", None) else None
    review.save(
        update_fields=["status", "moderated_at", "moderated_by", "updated_at"]
    )
    recompute_product_rating(review.product)
    return review


# ---------------------------------------------------------------------------
# The denormalised aggregate (FR-REV-5)
# ---------------------------------------------------------------------------
def _average(total, count):
    """
    Exact decimal mean, half-up to two places.

    Summed and divided as Decimal rather than read from AVG(): Django resolves
    Avg() over an integer column to a float, and a float mean is one rounding
    step away from a rating that disagrees with the star breakdown printed
    next to it.
    """
    if not count:
        return ZERO_RATING
    return (Decimal(int(total)) / Decimal(int(count))).quantize(
        _RATING_QUANTUM, rounding=ROUND_HALF_UP
    )


def recompute_product_rating(product):
    """
    Recompute Product.rating_avg / rating_count from approved reviews.

    **The single writer of both columns**, called from every path that can
    change the approved set: moderation, edit and delete. Derived, never
    incremented -- an increment can drift, and a drifted rating is invisible
    until someone counts by hand.

    Written with an UPDATE rather than product.save() so it cannot clobber a
    concurrently edited name or price, and mirrored onto the in-memory
    instance so a caller holding it does not read a stale figure.
    """
    row = Review.objects.filter(
        product=product, status=ReviewStatus.APPROVED
    ).aggregate(total=Sum("rating"), count=Count("id"))
    count = row["count"] or 0
    average = _average(row["total"] or 0, count)

    Product.objects.filter(pk=product.pk).update(
        rating_avg=average, rating_count=count
    )
    product.rating_avg = average
    product.rating_count = count
    return average, count
