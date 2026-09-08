"""
Query-parameter parsing for the review lists (FR-REV-7, PRD 7.3).

Same job and same conventions as apps/catalog/filters.py: turn an untrusted
QueryDict into a validated value object, and raise DomainError on nonsense
rather than dropping it. A filter that quietly does nothing returns a wrong
list that looks right.
"""
from __future__ import annotations

from dataclasses import dataclass

from config.exceptions import DomainError

from .models import ReviewStatus
from .services.reviews import (
    RATING_MAX,
    RATING_MIN,
    SORT_OLDEST,
    SORT_RATING_HIGH,
    SORT_RATING_LOW,
    SORT_RECENT,
)

SORT_CHOICES = (SORT_RECENT, SORT_OLDEST, SORT_RATING_HIGH, SORT_RATING_LOW)

# ?status=all on the moderation queue means "every state", which is not a
# ReviewStatus value and must not be matched against the column.
STATUS_ALL = "all"


@dataclass(frozen=True)
class ReviewQuery:
    """Normalised parameters for the public review list."""

    rating: int | None = None
    sort: str = SORT_RECENT


def _single(params, name):
    value = params.get(name)
    return "" if value is None else str(value).strip()


def parse_review_query(params) -> ReviewQuery:
    """Validate ?rating=&sort= for GET /products/{slug}/reviews/."""
    return ReviewQuery(rating=_rating(params, "rating"), sort=_sort(params))


def parse_moderation_status(params):
    """
    Validate ?status= for GET /admin/reviews/.

    Defaults to `pending`, because that endpoint is the moderation *queue*:
    an admin opening it wants what is waiting, not the whole archive.
    Returns None for `all`, which the service reads as "no status filter".
    """
    raw = _single(params, "status").lower()
    if not raw:
        return ReviewStatus.PENDING
    if raw == STATUS_ALL:
        return None
    if raw not in ReviewStatus.values:
        raise DomainError(
            "status must be one of: {0}.".format(
                ", ".join(list(ReviewStatus.values) + [STATUS_ALL])
            ),
            code="INVALID_FILTER",
            field="status",
        )
    return raw


def _rating(params, name):
    raw = _single(params, name)
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise DomainError(
            "{0} must be a whole number of stars.".format(name),
            code="INVALID_FILTER",
            field=name,
        )
    if not RATING_MIN <= value <= RATING_MAX:
        raise DomainError(
            "{0} must be between {1} and {2}.".format(name, RATING_MIN, RATING_MAX),
            code="INVALID_FILTER",
            field=name,
        )
    return value


def _sort(params):
    raw = _single(params, "sort").lower()
    if not raw:
        return SORT_RECENT
    if raw not in SORT_CHOICES:
        raise DomainError(
            "sort must be one of: {0}.".format(", ".join(SORT_CHOICES)),
            code="INVALID_SORT",
            field="sort",
        )
    return raw
