"""
Catalogue reads: which products exist, what a filter set admits, how they rank.

Four decisions hold the query plans together:

1. No filter multiplies rows -- category and brand are to-one joins, price and
   stock are EXISTS subqueries. So facets can COUNT without DISTINCT.
2. Per-product aggregates are correlated subqueries rather than JOIN + GROUP
   BY, which keeps the MATCH ... AGAINST relevance score usable in ORDER BY.
3. The list is paginated as bare ids and then hydrated. Otherwise MySQL runs
   the SELECT-list subqueries for every row reaching the sort rather than the
   24 that survive the LIMIT. Pinned by tests/test_list_query_plans.py.
4. The keyword predicate is a UNION of id sets, not an OR chain -- OR-ing a
   FULLTEXT arm with a LIKE arm stops MySQL using either index.

MATCH ... AGAINST has no ORM expression, so those parts are raw SQL. Only
table names are interpolated; every user value is a bound parameter.
"""
from __future__ import annotations

from collections import defaultdict

from django.db.models import (
    Case,
    Count,
    DecimalField,
    Exists,
    F,
    FloatField,
    IntegerField,
    Max,
    Min,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.expressions import RawSQL
from django.db.models.functions import Coalesce

from apps.common.fields import quantize_money
from apps.orders.models import OrderItem, OrderStatus

from ..filters import (
    SORT_BEST_SELLING,
    SORT_NEWEST,
    SORT_PRICE_ASC,
    SORT_PRICE_DESC,
    SORT_RATING,
    SORT_RELEVANCE,
)
from ..models import Brand, Category, Product, ProductImage, ProductSpec, ProductVariant

# FR-CAT-6: a product page shows at most eight related products.
MAX_RELATED_PRODUCTS = 8

# FR-SRC-1: FULLTEXT at or above this length, LIKE below it.
FULLTEXT_MIN_QUERY_LENGTH = 4

# InnoDB does not index tokens shorter than innodb_ft_min_token_size (3 by
# default). A "+tok*" term for an unindexed token matches nothing at all, so
# short tokens are dropped from the boolean expression and left to the LIKE
# arm of the predicate.
FULLTEXT_MIN_TOKEN_LENGTH = 3

# Rating facet thresholds, read as "4 stars and up".
RATING_FACET_VALUES = (5, 4, 3, 2, 1)

# Relevance weights. An exact SKU outranks everything else by a margin no
# full-text score can close, which is what puts an exact SKU or model number in
# first position (FR-SRC-1 acceptance criteria).
_WEIGHT_EXACT_SKU = 1000
_WEIGHT_NAME_MATCH = 100
_WEIGHT_BRAND_MATCH = 25

_MONEY = DecimalField(max_digits=12, decimal_places=2)

# Facet dimension keys. A dimension is excluded from its own facet count so a
# multi-select filter can still be widened (FR-SRC-2).
FACET_BRAND = "brand"
FACET_CATEGORY = "category"
FACET_PRICE = "price"
FACET_STOCK = "in_stock"
FACET_RATING = "rating"

_ORDERINGS = {
    SORT_PRICE_ASC: ("price_min", "id"),
    SORT_PRICE_DESC: ("-price_min", "-id"),
    SORT_NEWEST: ("-created_at", "-id"),
    SORT_RATING: ("-rating_avg", "-rating_count", "-created_at", "-id"),
    SORT_BEST_SELLING: ("-units_sold", "-rating_avg", "-created_at", "-id"),
    SORT_RELEVANCE: ("-relevance", "-rating_avg", "-created_at", "-id"),
}


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
def _active_variants():
    """Correlated subquery over the active variants of the outer product."""
    return ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True)


def _variant_aggregate(expression, output_field):
    """One aggregate over a product's active variants, as a scalar subquery."""
    return Subquery(
        ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True)
        .order_by()  # clear Meta.ordering or it lands in the subquery GROUP BY
        .values("product")
        .annotate(value=expression)
        .values("value")[:1],
        output_field=output_field,
    )


def annotate_product_aggregates(queryset):
    """
    price_min / price_max / total_stock / variant_count / cheapest_compare_at.

    All five are computed in the database, never by walking variants in Python.
    cheapest_compare_at pairs with price_min -- both describe the cheapest
    active variant, which is the one FR-CAT-8 derives the discount badge from.
    """
    cheapest = ProductVariant.objects.filter(
        product=OuterRef("pk"), is_active=True
    ).order_by("price", "id")
    return queryset.annotate(
        price_min=_variant_aggregate(Min("price"), _MONEY),
        price_max=_variant_aggregate(Max("price"), _MONEY),
        total_stock=Coalesce(_variant_aggregate(Sum("stock"), IntegerField()), Value(0)),
        variant_count=Coalesce(
            _variant_aggregate(Count("id"), IntegerField()), Value(0)
        ),
        cheapest_compare_at=Subquery(
            cheapest.values("compare_at_price")[:1], output_field=_MONEY
        ),
    )


def _image_prefetch():
    """Images in display order. Shared by products and by variants."""
    return Prefetch("images", queryset=ProductImage.objects.order_by("sort_order", "id"))


def storefront_products():
    """
    Active products sitting in an active part of the taxonomy (FR-CAT-7).

    Gating on Product.is_active alone let two endpoints in the same contract
    disagree about what exists: /categories/ hides a deactivated category
    while /products/ still listed its products, still offered it as a facet
    row, and still accepted ?category=<that slug> as a filter. Categories nest
    one level, so a child is only visible while its parent is too.

    Brand is treated differently on purpose -- see _brand_facet.
    """
    return Product.objects.filter(is_active=True, category__is_active=True).filter(
        Q(category__parent__isnull=True) | Q(category__parent__is_active=True)
    )


def listable_products():
    """
    What a listing may contain: active, and sellable.

    A product whose variants are all inactive has no price and no stock, so it
    cannot honour the list contract and could not be bought anyway. Detail
    still resolves it -- FR-CAT-7 gates on the product's own flag.
    """
    return storefront_products().filter(Exists(_active_variants()))


def discount_percent(price, compare_at_price):
    """
    FR-CAT-8. Non-zero only when compare-at genuinely exceeds the price.

    Mirrors ProductVariant.discount_percent so the list badge and the variant
    badge can never disagree.
    """
    if price is None or not compare_at_price or compare_at_price <= price:
        return 0
    return int(round((compare_at_price - price) / compare_at_price * 100))


# ---------------------------------------------------------------------------
# Keyword search (FR-SRC-1)
# ---------------------------------------------------------------------------
def _like_pattern(value):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%"


def _tokens(keyword):
    """
    The alphanumeric words of a keyword that MySQL would have indexed.

    Punctuation is stripped rather than escaped because in boolean mode
    -, +, *, ~, <, > and " are operators: a raw SKU such as TUF-16-512 would
    otherwise read as a NOT clause and exclude its own match.
    """
    words = "".join(char if char.isalnum() else " " for char in keyword).split()
    return [word for word in words if len(word) >= FULLTEXT_MIN_TOKEN_LENGTH]


def _boolean_expression(keyword):
    """
    Build a MySQL BOOLEAN MODE expression, e.g. "+asus* +tuf*".

    Every token is required and prefix-matched, so a multi-word query narrows
    rather than widens.
    """
    if len(keyword) < FULLTEXT_MIN_QUERY_LENGTH:
        return ""
    return " ".join("+" + token + "*" for token in _tokens(keyword))


def _search_predicate(keyword):
    """
    A RawSQL subquery of matching product ids, for `pk__in=`.

    It yields ids and nothing else, so it never names the outer table. That
    matters: this predicate is nested one level deeper by _price_facet, and
    Django rewrites table aliases inside a subquery -- a raw fragment naming
    `catalog_product` directly would resolve to a column that no longer
    exists there.

    The subquery is a union of four arms, each free to pick its own access
    path:

    1. product name + description FULLTEXT  -> catalog_product_ft
    2. variant SKU FULLTEXT                 -> catalog_variant_sku_ft
    3. one scan of product joined to brand, covering the substring match on
       name / brand name and the per-token match below
    4. one scan of variant, covering the substring match on SKU

    The LIKE arms are not redundant with the FULLTEXT arms and must not be
    dropped: FULLTEXT matches whole tokens only, so a partial SKU such as
    "507ZC-16" would miss; it is skipped altogether below
    FULLTEXT_MIN_QUERY_LENGTH; and InnoDB updates a FULLTEXT index at commit
    time, so rows written inside an open transaction are invisible to MATCH.

    Arm 3's token chain is what makes "lenovo legion" work. The FULLTEXT arm
    requires *every* token in name+description, so a query whose tokens split
    across the brand and the product name matched nothing at all -- and
    "brand + model" is the commonest query shape a shopper types.

    This goes into WHERE rather than being annotated so the facet queries can
    reuse it. They group by brand and by category, and must not inherit a
    full-text expression in their GROUP BY.
    """
    product_t = Product._meta.db_table
    variant_t = ProductVariant._meta.db_table
    brand_t = Brand._meta.db_table
    like = _like_pattern(keyword)
    boolean_q = _boolean_expression(keyword)
    tokens = _tokens(keyword)

    arms = []
    params = []

    if boolean_q:
        arms.append(
            "SELECT ftp.`id` AS `id` FROM `{p}` ftp "
            "WHERE MATCH(ftp.`name`, ftp.`description`) "
            "AGAINST (%s IN BOOLEAN MODE)".format(p=product_t)
        )
        params.append(boolean_q)
        arms.append(
            "SELECT ftv.`product_id` AS `id` FROM `{v}` ftv "
            "WHERE ftv.`is_active` = 1 "
            "AND MATCH(ftv.`sku`) AGAINST (%s IN BOOLEAN MODE)".format(v=variant_t)
        )
        params.append(boolean_q)

    text_clauses = ["lp.`name` LIKE %s", "lb.`name` LIKE %s"]
    text_params = [like, like]
    if len(tokens) > 1:
        # Multi-word only. One token is already covered by the substring
        # clauses above, so the chain can never widen a single-word search.
        chain = []
        for token in tokens:
            pattern = _like_pattern(token)
            chain.append(
                "(lp.`name` LIKE %s OR lp.`description` LIKE %s "
                "OR lb.`name` LIKE %s)"
            )
            text_params.extend([pattern, pattern, pattern])
        text_clauses.append("(" + " AND ".join(chain) + ")")
    arms.append(
        "SELECT lp.`id` AS `id` FROM `{p}` lp "
        "LEFT JOIN `{b}` lb ON lb.`id` = lp.`brand_id` "
        "WHERE {where}".format(p=product_t, b=brand_t, where=" OR ".join(text_clauses))
    )
    params.extend(text_params)

    arms.append(
        "SELECT lv.`product_id` AS `id` FROM `{v}` lv "
        "WHERE lv.`is_active` = 1 AND lv.`sku` LIKE %s".format(v=variant_t)
    )
    params.append(like)

    # The union is wrapped in an explicit derived table rather than left bare
    # as `id IN (a UNION b)`. Measured on 10,000 products, the bare form makes
    # MySQL re-evaluate the union per candidate row and lands *slower* than
    # the OR chain it replaces (445ms vs 169ms for q=gaming); materialising it
    # once turns that into 139ms.
    return RawSQL(
        "(SELECT `kw`.`id` FROM ({arms}) AS `kw`)".format(arms=" UNION ".join(arms)),
        params,
        output_field=IntegerField(),
    )


def _relevance_expression(keyword):
    """
    Weight-only ranking score for sort=relevance. Added to the list query only.

    Deliberately free of MATCH ... AGAINST. Summing a full-text score into an
    arithmetic expression makes MySQL evaluate the whole term as a DOUBLE,
    which can overflow with "DOUBLE value is out of range" (error 1690) on a
    large catalogue -- and that would 500 the *default* sort of every keyword
    search. The score is applied as a separate ORDER BY term instead, where it
    breaks ties without ever being added to anything. See
    _match_score_expression.
    """
    product_t = Product._meta.db_table
    variant_t = ProductVariant._meta.db_table
    brand_t = Brand._meta.db_table
    like = _like_pattern(keyword)

    parts = []
    params = []

    parts.append(
        "(CASE WHEN EXISTS (SELECT 1 FROM `{v}` rv "
        "WHERE rv.`product_id` = `{p}`.`id` AND rv.`is_active` = 1 "
        "AND rv.`sku` = %s) THEN {w} ELSE 0 END)".format(
            v=variant_t, p=product_t, w=_WEIGHT_EXACT_SKU
        )
    )
    params.append(keyword)

    # A model number such as FX507 lives in the product name, so a name hit is
    # the second-strongest signal after an exact SKU.
    parts.append(
        "(CASE WHEN `{p}`.`name` LIKE %s THEN {w} ELSE 0 END)".format(
            p=product_t, w=_WEIGHT_NAME_MATCH
        )
    )
    params.append(like)

    parts.append(
        "(CASE WHEN EXISTS (SELECT 1 FROM `{b}` rb "
        "WHERE rb.`id` = `{p}`.`brand_id` AND rb.`name` LIKE %s) "
        "THEN {w} ELSE 0 END)".format(b=brand_t, p=product_t, w=_WEIGHT_BRAND_MATCH)
    )
    params.append(like)

    return RawSQL("(" + " + ".join(parts) + ")", params, output_field=IntegerField())


def _match_score_expression(keyword):
    """
    The full-text relevance score, standing alone so it cannot overflow.

    None below the FULLTEXT threshold, where there is no score to rank by.
    It sits *after* the weight sum in ORDER BY, so it reorders products that
    tie on weight but can never lift a brand hit above a name hit, or a name
    hit above an exact SKU (FR-SRC-1 acceptance criteria).

    The score is read out of an index-driven derived table rather than
    recomputed per row. Written inline, MATCH in ORDER BY forces MySQL to
    score every candidate row by hand now that the keyword predicate no
    longer puts the same MATCH in WHERE for it to reuse; measured on 10,000
    products that costs about twice this form (q=gaming: 2044ms inline vs
    1308ms here). Products the full-text arm did not match score NULL, which
    MySQL sorts last under DESC -- the same place a zero score would land.
    """
    boolean_q = _boolean_expression(keyword)
    if not boolean_q:
        return None
    product_t = Product._meta.db_table
    match = "MATCH(`sp`.`name`, `sp`.`description`) AGAINST (%s IN BOOLEAN MODE)"
    return RawSQL(
        "(SELECT `sc`.`score` FROM ("
        "SELECT `sp`.`id` AS `id`, {match} AS `score` FROM `{p}` `sp` "
        "WHERE {match}"
        ") AS `sc` WHERE `sc`.`id` = `{p}`.`id`)".format(match=match, p=product_t),
        [boolean_q, boolean_q],
        output_field=FloatField(),
    )


def _units_sold_expression():
    """
    FR-SRC-3 best_selling: units that actually went out of the door.

    Cancelled and refunded orders sold nothing, so they are excluded.
    """
    sold = (
        OrderItem.objects.filter(variant__product=OuterRef("pk"))
        .exclude(order__status__in=(OrderStatus.CANCELLED, OrderStatus.REFUNDED))
        .order_by()
        .values("variant__product")
        .annotate(total=Sum("quantity"))
        .values("total")[:1]
    )
    return Coalesce(Subquery(sold, output_field=IntegerField()), Value(0))


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def _apply_filters(queryset, query, *, exclude=()):
    """
    Apply every filter in `query` except the named facet dimensions.

    `exclude` is what makes multi-select usable: when counting the brand facet
    the brand filter is dropped, so picking Asus still reports how many Lenovo
    products the remaining filters would allow (FR-SRC-2).
    """
    if query.q:
        queryset = queryset.filter(pk__in=_search_predicate(query.q))

    if query.categories and FACET_CATEGORY not in exclude:
        # Categories nest one level, so a parent slug must also pull in its
        # children's products (FR-CAT-1 acceptance criteria).
        queryset = queryset.filter(
            Q(category__slug__in=query.categories)
            | Q(category__parent__slug__in=query.categories)
        )

    if query.brands and FACET_BRAND not in exclude:
        queryset = queryset.filter(brand__slug__in=query.brands)

    if FACET_PRICE not in exclude and (
        query.min_price is not None or query.max_price is not None
    ):
        # "Within budget" means there is a variant the customer can actually
        # buy at that price, not merely that the product's range overlaps it.
        variants = _active_variants()
        if query.min_price is not None:
            variants = variants.filter(price__gte=query.min_price)
        if query.max_price is not None:
            variants = variants.filter(price__lte=query.max_price)
        queryset = queryset.filter(Exists(variants))

    if query.in_stock and FACET_STOCK not in exclude:
        queryset = queryset.filter(Exists(_active_variants().filter(stock__gt=0)))

    if query.min_rating is not None and FACET_RATING not in exclude:
        queryset = queryset.filter(rating_avg__gte=query.min_rating)

    if query.has_discount:
        # Discount is a property of a *variant*, so this asks whether any
        # sellable variant is genuinely marked down -- the same test
        # discount_percent() applies when drawing the badge. Comparing against
        # the product would need an aggregate and could mark a product "on
        # offer" on the strength of a variant nobody can buy.
        queryset = queryset.filter(
            Exists(
                _active_variants().filter(
                    compare_at_price__isnull=False,
                    compare_at_price__gt=F("price"),
                )
            )
        )

    if query.featured:
        queryset = queryset.filter(is_featured=True)

    return queryset


def _effective_sort(query):
    if query.sort == SORT_RELEVANCE and not query.q:
        return SORT_NEWEST  # nothing to be relevant to
    return query.sort


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------
def product_list_ids(query):
    """
    The filtered, ordered product ids -- what pagination slices (FR-SRC-1..5).

    Deliberately bare. The five card aggregates in
    annotate_product_aggregates are correlated subqueries sitting in the
    SELECT list, and MySQL evaluates a SELECT-list subquery for every row that
    reaches the sort, not for the twenty-four that survive the LIMIT. Annotated
    before pagination they cost |result set| x 5 executions -- measured at
    5,000 products that is a 4,875-row temporary table and ~24,000 subquery
    executions to render one page of 24 cards.

    So the aggregates are not here. Only the terms ORDER BY actually needs are
    annotated, and product_list_rows() puts the rest onto the page after it has
    been narrowed. Sorting by a real column (newest, rating) therefore annotates
    nothing at all.

    This costs one extra round trip -- ids, then rows -- which is the right
    trade: it is a constant, and MySQL cannot take a LIMIT inside an IN
    subquery, so the two cannot be folded into one statement.
    """
    queryset = _apply_filters(listable_products(), query)

    sort = _effective_sort(query)
    ordering = _ORDERINGS[sort]
    if sort == SORT_RELEVANCE:
        queryset = queryset.annotate(relevance=_relevance_expression(query.q))
        match_score = _match_score_expression(query.q)
        if match_score is not None:
            # Two ordering terms, never one summed expression (see
            # _relevance_expression): weights decide, the score breaks ties.
            queryset = queryset.annotate(match_score=match_score)
            ordering = ("-relevance", "-match_score") + ordering[1:]
    elif sort in (SORT_PRICE_ASC, SORT_PRICE_DESC):
        queryset = queryset.annotate(price_min=_variant_aggregate(Min("price"), _MONEY))
    elif sort == SORT_BEST_SELLING:
        queryset = queryset.annotate(units_sold=_units_sold_expression())
    return queryset.order_by(*ordering).values_list("id", flat=True)


def product_list_rows(ids):
    """
    The card rows for `ids`, annotated and prefetched, in exactly that order.

    `ids` is one page -- at most page_size rows -- so the aggregates are
    evaluated a bounded number of times however large the catalogue is.
    The database is free to return an IN () set in any order, so the caller's
    order is reimposed here rather than trusted; the sort already happened in
    product_list_ids and must not be recomputed against a different expression.
    """
    ids = list(ids)
    if not ids:
        return []
    rows = annotate_product_aggregates(
        Product.objects.filter(pk__in=ids).select_related("brand", "category")
    ).prefetch_related(_image_prefetch())
    by_id = {row.pk: row for row in rows}
    return [by_id[pk] for pk in ids if pk in by_id]


def product_detail_queryset():
    """
    Detail rows, with everything the page needs prefetched.

    Inactive products are absent from this queryset, so a lookup against it
    raises 404 rather than rendering a hidden product (FR-CAT-7).
    """
    variants = (
        ProductVariant.objects.filter(is_active=True)
        .order_by("price", "id")
        .prefetch_related(_image_prefetch())
    )
    return annotate_product_aggregates(
        # `component` is a reverse OneToOne, so select_related folds it into
        # the existing join rather than costing a round trip -- a prefetch
        # here would add a query to the endpoint with the tightest budget
        # (PRD §9.1, detail p95 < 400ms). Absent, the descriptor raises
        # RelatedObjectDoesNotExist, which Django deliberately subclasses from
        # AttributeError so `getattr(product, "component", None)` still works.
        storefront_products().select_related("brand", "category", "component")
    ).prefetch_related(
        _image_prefetch(),
        Prefetch(
            "specs",
            queryset=ProductSpec.objects.order_by("group_order", "sort_order", "id"),
        ),
        Prefetch("variants", queryset=variants),
    )


def related_products(product):
    """
    FR-CAT-6: up to eight active products from the same category, excluding
    out-of-stock items and the product itself.
    """
    queryset = (
        listable_products()
        .filter(category_id=product.category_id)
        .exclude(pk=product.pk)
        .filter(Exists(_active_variants().filter(stock__gt=0)))
        .select_related("brand", "category")
    )
    queryset = annotate_product_aggregates(queryset).prefetch_related(_image_prefetch())
    return queryset.order_by("-rating_avg", "-rating_count", "-created_at", "-id")[
        :MAX_RELATED_PRODUCTS
    ]


# ---------------------------------------------------------------------------
# Facets (FR-SRC-2)
# ---------------------------------------------------------------------------
def product_facets(query):
    """Counts for the current result set, each dimension blind to itself."""
    return {
        "brands": _brand_facet(query),
        "categories": _category_facet(query),
        "price": _price_facet(query),
        "in_stock": _stock_facet(query),
        "ratings": _rating_facet(query),
    }


def _facet_base(query, dimension):
    return _apply_filters(listable_products(), query, exclude=(dimension,))


def _brand_facet(query):
    """
    Brands offered as filter rows -- active brands only, matching /brands/.

    Deactivating a brand hides the *facet row*, not the products. A brand is a
    label on sellable stock, not a place in the taxonomy: delisting a shop's
    entire Asus inventory because someone unticked a checkbox on the brand
    record is a far bigger blast radius than the admin asked for, and the
    products remain reachable by category, by search and by URL. A category is
    the opposite case -- it *is* the navigation -- so an inactive one does
    remove its products (see storefront_products).
    """
    rows = (
        _facet_base(query, FACET_BRAND)
        .filter(brand__isnull=False)
        .values("brand__slug", "brand__name", "brand__is_active")
        .annotate(count=Count("id"))
        .order_by("brand__name")
    )
    # is_active is carried out of the group and dropped here rather than
    # filtered in the WHERE clause. A `brand__is_active=True` filter flips
    # MySQL onto a brand-driven plan that re-reads products per brand: on
    # 10,000 products it cost 1406ms against 240ms for this form. Brand is
    # already joined for the slug and the name, so the extra column is free
    # and the grouping is unchanged (a slug identifies one brand).
    return [
        {"slug": row["brand__slug"], "name": row["brand__name"], "count": row["count"]}
        for row in rows
        if row["brand__is_active"]
    ]


def _category_facet(query):
    """
    Counted against the category each product actually sits in. Parents stay
    reachable from /categories/; this facet is for narrowing what is on screen.
    """
    rows = (
        _facet_base(query, FACET_CATEGORY)
        .values("category__slug", "category__name")
        .annotate(count=Count("id"))
        .order_by("category__name")
    )
    return [
        {
            "slug": row["category__slug"],
            "name": row["category__name"],
            "count": row["count"],
        }
        for row in rows
    ]


def _price_facet(query):
    """
    The band the price slider may span -- blind to the price filter itself.

    Aggregated over the variant table in one pass rather than by annotating a
    correlated MIN and MAX onto every product row and aggregating those: the
    annotated form ran two subqueries per product to produce two numbers
    (10,014 subquery executions for a 5,000-product result). The answer is
    identical -- the smallest per-product minimum *is* the global minimum.

    This is the one facet built on storefront_products() rather than
    listable_products(), and the difference is deliberate. listable_products()
    adds EXISTS(active variant), which this query then joins to the variant
    table and re-establishes -- two semijoins over the same rows, which MySQL
    resolves with a duplicate-weedout temporary table (76,000 rows examined at
    20,000 products, for two numbers). Dropping it cannot change the answer: a
    product with no active variant contributes no row to an
    `is_active=True` variant aggregate whether or not it is in the id set.
    Measured at 20,000 products: 152ms -> 90ms, same min and max.

    Every other facet counts *products* and so must keep listable_products();
    only this one counts variants.
    """
    products = (
        _apply_filters(storefront_products(), query, exclude=(FACET_PRICE,))
        .order_by()
        .values("pk")
    )
    row = ProductVariant.objects.filter(
        is_active=True, product__in=products
    ).aggregate(low=Min("price"), high=Max("price"))
    return {"min": _money(row["low"]), "max": _money(row["high"])}


def _stock_facet(query):
    row = (
        _facet_base(query, FACET_STOCK)
        .annotate(_facet_in_stock=Exists(_active_variants().filter(stock__gt=0)))
        .aggregate(
            yes=Count("id", filter=Q(_facet_in_stock=True)),
            no=Count("id", filter=Q(_facet_in_stock=False)),
        )
    )
    return {"true": row["yes"] or 0, "false": row["no"] or 0}


def _rating_facet(query):
    row = _facet_base(query, FACET_RATING).aggregate(
        **{
            "r{0}".format(value): Count("id", filter=Q(rating_avg__gte=value))
            for value in RATING_FACET_VALUES
        }
    )
    return [
        {"value": value, "count": row["r{0}".format(value)] or 0}
        for value in RATING_FACET_VALUES
    ]


def _money(value):
    return None if value is None else str(quantize_money(value))


# ---------------------------------------------------------------------------
# Categories and brands
# ---------------------------------------------------------------------------
def category_tree():
    """Active roots with their active children, one level deep (FR-CAT-1)."""
    children = Category.objects.filter(is_active=True).order_by("sort_order", "name")
    return (
        Category.objects.filter(is_active=True, parent__isnull=True)
        .prefetch_related(Prefetch("children", queryset=children))
        .order_by("sort_order", "name")
    )


def category_product_counts():
    """
    {category_id: listable product count}, a parent including its children.

    Counted over exactly what /products/?category=<slug> would return, so the
    number in the nav matches the number of cards on the page.
    """
    direct = (
        listable_products()
        .order_by()  # Meta.ordering would otherwise join the GROUP BY
        .values("category_id")
        .annotate(total=Count("id"))
    )
    parent_of = dict(Category.objects.values_list("id", "parent_id"))
    counts = defaultdict(int)
    for row in direct:
        category_id = row["category_id"]
        counts[category_id] += row["total"]
        parent_id = parent_of.get(category_id)
        if parent_id is not None:
            counts[parent_id] += row["total"]
    return counts


def brand_list():
    return Brand.objects.filter(is_active=True).order_by("name")


def purchasable_variants():
    """
    Variants a customer may actually add to a cart or buy.

    Reuses storefront_products() rather than re-stating the visibility rule, so
    a variant can never be buyable while its product is unlistable. Stock is
    deliberately *not* part of the predicate: a zero-stock variant still needs
    to resolve so the cart can say "out of stock" instead of "not found".
    """
    return ProductVariant.objects.filter(
        is_active=True, product__in=storefront_products()
    ).select_related(
        "product",
        "product__brand",
        "product__category",
        # is_sellable() checks the parent category's active flag too.
        "product__category__parent",
    )


# ---------------------------------------------------------------------------
# Search-as-you-type (FR-SRC-6)
# ---------------------------------------------------------------------------

# A suggestion drop-down is read at a glance, so it stays short. These caps
# are per-section, not overall.
MAX_SUGGEST_PRODUCTS = 6
MAX_SUGGEST_CATEGORIES = 4
MAX_SUGGEST_BRANDS = 4

# Below this a prefix matches most of the catalogue, so the list is noise.
MIN_SUGGEST_LENGTH = 2

# Shown on an empty search box. Static rather than derived from real traffic:
# there is no analytics store in v1, and inventing "popular" from order counts
# would make the list a bestseller row wearing the wrong label.
POPULAR_SEARCHES = (
    "gaming laptop",
    "ryzen processor",
    "rtx 4060",
    "ssd 1tb",
    "mechanical keyboard",
    "27 inch monitor",
)


def search_suggestions(keyword):
    """
    Type-ahead for the header search box.

    Deliberately *not* the full search: it is a prefix/substring lookup over
    names, model numbers and SKUs, ordered by rating, and it never touches the
    FULLTEXT index. Full-text ranking needs whole tokens, and a shopper three
    characters in has not typed one yet -- running the real ranker on a
    fragment returns worse suggestions more slowly.

    Returns products, categories and brands in one payload so the drop-down is
    a single round trip.
    """
    keyword = (keyword or "").strip()
    if len(keyword) < MIN_SUGGEST_LENGTH:
        return {"query": keyword, "products": [], "categories": [], "brands": []}

    products = (
        listable_products()
        .filter(
            Q(name__icontains=keyword)
            | Q(model_number__icontains=keyword)
            | Q(brand__name__icontains=keyword)
            | Q(variants__sku__icontains=keyword)
        )
        .select_related("brand", "category")
        .distinct()
    )
    products = annotate_product_aggregates(products).prefetch_related(_image_prefetch())
    # A name that *starts* with what was typed is what the shopper meant far
    # more often than one that merely contains it, so it sorts first.
    products = products.annotate(
        starts_with=Case(
            When(name__istartswith=keyword, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by("starts_with", "-rating_avg", "-rating_count", "id")

    categories = (
        Category.objects.filter(is_active=True, name__icontains=keyword)
        .filter(Q(parent__isnull=True) | Q(parent__is_active=True))
        .order_by("name")[:MAX_SUGGEST_CATEGORIES]
    )

    brands = Brand.objects.filter(is_active=True, name__icontains=keyword).order_by("name")[
        :MAX_SUGGEST_BRANDS
    ]

    return {
        "query": keyword,
        "products": list(products[:MAX_SUGGEST_PRODUCTS]),
        "categories": list(categories),
        "brands": list(brands),
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

# Four columns is what fits a desktop table and still reads on a tablet.
# Beyond that the table stops being a comparison and becomes a listing.
MAX_COMPARE_PRODUCTS = 4


def compare_products(slugs):
    """
    Full detail rows for up to four products, in the order asked for.

    Order matters: the compare table's columns are the order the shopper added
    them in, and re-sorting server-side would shuffle the table under them on
    every reload.
    """
    slugs = list(dict.fromkeys(s for s in slugs if s))[:MAX_COMPARE_PRODUCTS]
    if not slugs:
        return []

    rows = {p.slug: p for p in product_detail_queryset().filter(slug__in=slugs)}
    return [rows[slug] for slug in slugs if slug in rows]


def compare_spec_matrix(products):
    """
    The union of every spec key across `products`, grouped, with each
    product's value per row and whether the row actually differs.

    Computed server-side because "which rows differ" needs the whole set, and
    a client that computed it would have to re-implement the grouping rules.
    A product missing a key gets null -- absence is information in a
    comparison, so it is never silently collapsed with a blank value.
    """
    # Keep first-seen group and key order, which follows group_order/sort_order
    # from the prefetch, so the matrix reads like the detail page's own table.
    groups = {}
    for product in products:
        for spec in product.specs.all():
            group = spec.group or "Specifications"
            groups.setdefault(group, {}).setdefault(spec.key, {})
            groups[group][spec.key][product.slug] = spec.value

    matrix = []
    for group, keys in groups.items():
        rows = []
        for key, by_slug in keys.items():
            values = [by_slug.get(p.slug) for p in products]
            rows.append(
                {
                    "key": key,
                    "values": values,
                    # A row where every product says the same thing is noise in
                    # a comparison; the UI dims or hides it.
                    "differs": len({v for v in values}) > 1,
                }
            )
        matrix.append({"group": group, "rows": rows})
    return matrix


# ---------------------------------------------------------------------------
# Frequently bought together
# ---------------------------------------------------------------------------

MAX_BOUGHT_TOGETHER = 3


def frequently_bought_together(product):
    """
    Products that have actually shared an order with this one.

    Real co-purchase data, not a category guess: it counts distinct confirmed
    orders containing both. That means it is empty on a young catalogue, and
    it is allowed to be -- the detail page hides the section rather than
    padding it with a "related" row wearing a stronger claim than it can
    support.
    """
    orders_with_product = OrderItem.objects.filter(
        variant__product_id=product.pk,
        order__status__in=(
            OrderStatus.CONFIRMED,
            OrderStatus.PACKED,
            OrderStatus.SHIPPED,
            OrderStatus.DELIVERED,
        ),
    ).values("order_id")

    counts = (
        OrderItem.objects.filter(order_id__in=Subquery(orders_with_product))
        .exclude(variant__product_id=product.pk)
        .values("variant__product_id")
        .annotate(shared=Count("order_id", distinct=True))
        .order_by("-shared")[: MAX_BOUGHT_TOGETHER * 3]
    )

    ranked = [row["variant__product_id"] for row in counts]
    if not ranked:
        return []

    queryset = (
        listable_products()
        .filter(pk__in=ranked)
        .filter(Exists(_active_variants().filter(stock__gt=0)))
        .select_related("brand", "category")
    )
    queryset = annotate_product_aggregates(queryset).prefetch_related(_image_prefetch())

    by_id = {p.pk: p for p in queryset}
    return [by_id[pk] for pk in ranked if pk in by_id][:MAX_BOUGHT_TOGETHER]
