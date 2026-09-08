"""
Query-parameter parsing for the admin coupon list (PRD 7.3).

Same job and conventions as apps/reviews/filters.py and apps/catalog/filters.py:
turn an untrusted QueryDict into a validated value object, and raise
DomainError on nonsense rather than dropping it. A filter that quietly does
nothing returns a wrong list that looks right -- and on this screen a wrong
list is an admin who thinks a promotion is off when it is running.
"""
from __future__ import annotations

from dataclasses import dataclass

from config.exceptions import DomainError

from .services.coupons import STATUS_ALL, STATUS_CHOICES

MAX_SEARCH_LENGTH = 32


@dataclass(frozen=True)
class CouponQuery:
    """Normalised parameters for GET /admin/coupons/."""

    status: str | None = None
    search: str = ""


def _single(params, name):
    value = params.get(name)
    return "" if value is None else str(value).strip()


def parse_coupon_query(params) -> CouponQuery:
    """
    Validate ?status= and ?search=.

    Defaults to every coupon, unlike the review moderation queue: this screen
    is the coupon *register*, not a work queue, and an admin opening it is as
    likely to be looking for an expired code as a live one.
    """
    return CouponQuery(status=_status(params), search=_search(params))


def _status(params):
    raw = _single(params, "status").lower()
    if not raw or raw == STATUS_ALL:
        return None
    if raw not in STATUS_CHOICES:
        raise DomainError(
            "status must be one of: {0}.".format(
                ", ".join(list(STATUS_CHOICES) + [STATUS_ALL])
            ),
            code="INVALID_FILTER",
            field="status",
        )
    return raw


def _search(params):
    raw = _single(params, "search")
    if len(raw) > MAX_SEARCH_LENGTH:
        raise DomainError(
            "search is at most {0} characters.".format(MAX_SEARCH_LENGTH),
            code="INVALID_FILTER",
            field="search",
        )
    return raw
