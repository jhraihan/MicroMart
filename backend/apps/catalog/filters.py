"""
Query-parameter parsing for the product list endpoint (FR-SRC-1..5).

This module does one job: turn an untrusted QueryDict into a validated,
normalised value object. It deliberately knows nothing about querysets, SQL or
facets -- what those parameters *mean* is decided in services/catalogue.py, so
the storefront and any future admin surface can reuse the same rules.

Bad input raises DomainError rather than being silently dropped: a filter that
quietly does nothing returns a wrong result set that looks right, which is far
harder to notice than a 422.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from config.exceptions import DomainError

# ---------------------------------------------------------------------------
# Sort options (FR-SRC-3)
# ---------------------------------------------------------------------------
SORT_RELEVANCE = "relevance"
SORT_PRICE_ASC = "price_asc"
SORT_PRICE_DESC = "price_desc"
SORT_NEWEST = "newest"
SORT_RATING = "rating"
SORT_BEST_SELLING = "best_selling"

SORT_CHOICES = (
    SORT_RELEVANCE,
    SORT_PRICE_ASC,
    SORT_PRICE_DESC,
    SORT_NEWEST,
    SORT_RATING,
    SORT_BEST_SELLING,
)

# A keyword longer than this is a paste accident, not a search.
MAX_QUERY_LENGTH = 128

MIN_RATING = 1
MAX_RATING = 5

_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ProductQuery:
    """Normalised, already-validated product list parameters."""

    q: str = ""
    categories: tuple[str, ...] = ()
    brands: tuple[str, ...] = ()
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    in_stock: bool = False
    min_rating: int | None = None
    # "On offer": the cheapest sellable variant carries a compare-at price
    # above its own price. Defined against the same variant the card's badge
    # is drawn from, so a product can never be filtered in and then render
    # without a discount badge.
    has_discount: bool = False
    # Editorial merchandising flag, read by the homepage rows.
    featured: bool = False
    sort: str = SORT_NEWEST

    @property
    def is_search(self) -> bool:
        return bool(self.q)


def parse_product_query(params) -> ProductQuery:
    """Validate ?q=&category=&brand=&min_price=... into a ProductQuery."""
    q = _clean_keyword(_single(params, "q"))
    min_price = _decimal(params, "min_price")
    max_price = _decimal(params, "max_price")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise DomainError(
            "min_price cannot be greater than max_price.",
            code="INVALID_PRICE_RANGE",
            field="min_price",
        )
    return ProductQuery(
        q=q,
        categories=_slugs(params, "category"),
        brands=_slugs(params, "brand"),
        min_price=min_price,
        max_price=max_price,
        in_stock=_boolean(params, "in_stock"),
        min_rating=_rating(params, "min_rating"),
        has_discount=_boolean(params, "has_discount"),
        featured=_boolean(params, "featured"),
        sort=_sort(params, has_keyword=bool(q)),
    )


# ---------------------------------------------------------------------------
# Field readers
# ---------------------------------------------------------------------------
def _values(params, name) -> list[str]:
    """Every value for `name`, whether repeated (?a=1&a=2) or CSV (?a=1,2)."""
    getlist = getattr(params, "getlist", None)
    if getlist is not None:
        raw = getlist(name)
    else:
        # A plain dict, as a management command or a test would pass.
        raw = params.get(name, [])
        raw = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for value in raw:
        out.extend(part.strip() for part in str(value).split(","))
    return [value for value in out if value]


def _single(params, name) -> str:
    values = _values(params, name)
    return values[0] if values else ""


def _clean_keyword(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()[:MAX_QUERY_LENGTH]


def _slugs(params, name) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in _values(params, name):
        slug = value.lower()
        if not _SLUG_RE.match(slug):
            raise DomainError(
                f"'{value}' is not a valid {name} slug.",
                code="INVALID_FILTER",
                field=name,
            )
        seen[slug] = None
    return tuple(seen)


def _decimal(params, name) -> Decimal | None:
    raw = _single(params, name)
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise DomainError(
            f"{name} must be a decimal number.", code="INVALID_FILTER", field=name
        )
    if not value.is_finite() or value < 0:
        raise DomainError(
            f"{name} must be zero or greater.", code="INVALID_FILTER", field=name
        )
    return value


def _boolean(params, name) -> bool:
    raw = _single(params, name).lower()
    if not raw:
        return False
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise DomainError(
        f"{name} must be true or false.", code="INVALID_FILTER", field=name
    )


def _rating(params, name) -> int | None:
    raw = _single(params, name)
    if not raw:
        return None
    try:
        value = int(Decimal(raw))
    except (InvalidOperation, ValueError):
        raise DomainError(
            f"{name} must be a whole number between {MIN_RATING} and {MAX_RATING}.",
            code="INVALID_FILTER",
            field=name,
        )
    if not MIN_RATING <= value <= MAX_RATING:
        raise DomainError(
            f"{name} must be between {MIN_RATING} and {MAX_RATING}.",
            code="INVALID_FILTER",
            field=name,
        )
    return value


def _sort(params, *, has_keyword: bool) -> str:
    raw = _single(params, "sort").lower()
    if not raw:
        # Relevance is meaningless without a keyword, so an unsorted browse
        # falls back to newest (FR-SRC-3).
        return SORT_RELEVANCE if has_keyword else SORT_NEWEST
    if raw not in SORT_CHOICES:
        raise DomainError(
            f"sort must be one of: {', '.join(SORT_CHOICES)}.",
            code="INVALID_SORT",
            field="sort",
        )
    return raw


# ---------------------------------------------------------------------------
# Admin surface (PRD 7.3)
# ---------------------------------------------------------------------------
# The admin lists answer a different question from the storefront's -- "what is
# in the catalogue", not "what can be bought" -- so they carry their own value
# objects rather than overloading ProductQuery with an `include_inactive` flag
# that must never be reachable from a public URL.

ADMIN_SORT_NEWEST = "newest"
ADMIN_SORT_OLDEST = "oldest"
ADMIN_SORT_NAME = "name"
ADMIN_SORT_UPDATED = "updated"

ADMIN_PRODUCT_SORT_CHOICES = (
    ADMIN_SORT_NEWEST,
    ADMIN_SORT_OLDEST,
    ADMIN_SORT_NAME,
    ADMIN_SORT_UPDATED,
)


@dataclass(frozen=True)
class AdminProductQuery:
    """Normalised parameters for GET /admin/products/."""

    q: str = ""
    category: str = ""
    brand: str = ""
    is_active: bool | None = None
    low_stock: bool = False
    sort: str = ADMIN_SORT_NEWEST


@dataclass(frozen=True)
class InventoryQuery:
    """
    Normalised parameters for GET /admin/inventory/ and GET /admin/variants/.

    One shape for both, because they are the same rows read for two reasons --
    and a filter that meant something different on each screen is precisely the
    drift the service layer exists to prevent.
    """

    q: str = ""
    category: str = ""
    product_id: int | None = None
    low_stock: bool = False
    include_inactive: bool = False


def parse_admin_product_query(params) -> AdminProductQuery:
    return AdminProductQuery(
        q=_clean_keyword(_single(params, "q")),
        category=_optional_slug(params, "category"),
        brand=_optional_slug(params, "brand"),
        is_active=_tristate(params, "is_active"),
        low_stock=_boolean(params, "low_stock"),
        sort=_admin_sort(params),
    )


def parse_inventory_query(params) -> InventoryQuery:
    return InventoryQuery(
        q=_clean_keyword(_single(params, "q")),
        category=_optional_slug(params, "category"),
        product_id=_optional_int(params, "product"),
        low_stock=_boolean(params, "low_stock"),
        include_inactive=_boolean(params, "include_inactive"),
    )


def _optional_slug(params, name) -> str:
    slugs = _slugs(params, name)
    return slugs[0] if slugs else ""


def _tristate(params, name) -> bool | None:
    """`true`, `false`, or absent meaning "do not filter on this at all"."""
    raw = _single(params, name).lower()
    if not raw:
        return None
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise DomainError(
        f"{name} must be true or false.", code="INVALID_FILTER", field=name
    )


def _optional_int(params, name) -> int | None:
    raw = _single(params, name)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise DomainError(
            f"{name} must be a whole number.", code="INVALID_FILTER", field=name
        )


def _admin_sort(params) -> str:
    raw = _single(params, "sort").lower()
    if not raw:
        return ADMIN_SORT_NEWEST
    if raw not in ADMIN_PRODUCT_SORT_CHOICES:
        raise DomainError(
            f"sort must be one of: {', '.join(ADMIN_PRODUCT_SORT_CHOICES)}.",
            code="INVALID_SORT",
            field="sort",
        )
    return raw
