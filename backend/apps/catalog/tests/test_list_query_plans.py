"""
Shape guards for the product list query (PRD 9.1, and the week-2 review's two
sort findings).

test_query_counts.py pins how *many* queries a request costs. This file pins
what they *are*, which is the half that decayed unnoticed: the list used to
annotate five correlated per-row aggregates -- price_min, price_max,
total_stock, variant_count, cheapest_compare_at -- onto the queryset that
pagination then sliced. MySQL evaluates a SELECT-list subquery once for every
row that reaches the sort, not once for the twenty-four that survive the
LIMIT, so drawing one page of cards cost 5 x |result set| subquery executions
and a temporary table holding the entire result set.

The query count never moved while that was true. A count-only guard therefore
cannot see this regression return, which is why these tests read the compiled
SQL and the MySQL plan instead.

Two invariants, and the difference between them is the point:

* The card aggregates must not appear before the LIMIT at all. Bounded by the
  page, they are 24 x 5 executions however large the catalogue grows.
* `sort=price_asc` and `sort=best_selling` genuinely need one per-product
  figure to sort on, so exactly one correlated subquery per result row is
  allowed for them -- and it is the only one allowed. Sorting on a real column
  (newest, rating) must correlate nothing.
"""
import pytest
from django.db import connection
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.catalog.filters import (
    SORT_BEST_SELLING,
    SORT_NEWEST,
    SORT_PRICE_ASC,
    SORT_PRICE_DESC,
    SORT_RATING,
    parse_product_query,
)
from apps.catalog.services import catalogue
from apps.catalog.views import ProductListView
from config.pagination import PageNumberPagination

from .factories import make_brand, make_category, make_product, place_order

pytestmark = pytest.mark.django_db

PAGE_SIZE = PageNumberPagination.page_size

# Sorts that order on a real Product column, so nothing may correlate.
COLUMN_SORTS = (SORT_NEWEST, SORT_RATING)
# Sorts that order on a per-product figure the schema does not hold.
DERIVED_SORTS = (SORT_PRICE_ASC, SORT_PRICE_DESC, SORT_BEST_SELLING)

# Every alias annotate_product_aggregates adds. None of them may reach the
# query pagination slices; product_list_rows() puts them on the page instead.
CARD_AGGREGATES = (
    "price_min",
    "price_max",
    "total_stock",
    "variant_count",
    "cheapest_compare_at",
)


def _sql(queryset):
    sql, params = queryset.query.sql_with_params()
    return sql, params


def _select_list(sql):
    """Everything between SELECT and the first FROM at depth zero."""
    depth = 0
    for index in range(len(sql)):
        char = sql[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and sql.startswith(" FROM ", index):
            return sql[:index]
    raise AssertionError("no top-level FROM in: {0}".format(sql))


def _view_queryset(params):
    """
    Exactly what ProductListView hands to the paginator.

    Asserted through the view rather than through the service so that a view
    which goes back to paginating fully annotated rows fails here even while
    the cheap service function still exists beside it, unused.
    """
    view = ProductListView()
    view.request = Request(APIRequestFactory().get("/api/v1/products/", params))
    view.format_kwarg = None
    return view.get_queryset()


def _tree_plan(queryset):
    sql, params = _sql(queryset)
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN FORMAT=TREE " + sql, params)
        return "\n".join(row[0] for row in cursor.fetchall())


def _correlated_subqueries(plan):
    """
    How many subqueries MySQL will re-run per outer row.

    MySQL flattens an uncorrelated EXISTS into a semijoin and says so in the
    plan, so this counts only what actually stayed dependent -- which is why
    the guard reads the plan rather than the SQL. listable_products()'s
    EXISTS(active variant) is in every one of these statements and is not
    supposed to be counted.
    """
    return plan.lower().count("dependent")


@pytest.fixture
def catalogue_page():
    """More products than fit on one page, so a per-row cost would show."""
    category = make_category("Laptops", "laptops")
    child = make_category("Gaming Laptops", "gaming-laptops", parent=category)
    brand = make_brand("Asus", "asus")
    products = []
    for index in range(PAGE_SIZE * 3):
        product = make_product(
            child if index % 2 else category,
            brand=brand,
            name="Product {0:03d}".format(index),
            slug="product-{0:03d}".format(index),
            rating_avg="{0}.00".format(index % 5),
            variants=[
                {"sku": "SKU-{0}-A".format(index), "price": "1000.00", "stock": 4},
                {"sku": "SKU-{0}-B".format(index), "price": "2000.00", "stock": 2},
            ],
        )
        products.append(product)
    place_order([(products[0].variants.first(), 9)])
    place_order([(products[1].variants.first(), 3)])
    return products


# ---------------------------------------------------------------------------
# The paginated query
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sort", COLUMN_SORTS + DERIVED_SORTS)
def test_the_query_pagination_slices_selects_ids_and_nothing_else(sort):
    """
    The whole fix in one assertion.

    Anything else in this SELECT list is evaluated for every row of the result
    set to render a page of twenty-four, which is exactly the cost the week-2
    review measured. Widening it is a performance change, not a cosmetic one,
    so it should have to fail a test first.
    """
    query = parse_product_query({"sort": sort})
    sql, _ = _sql(catalogue.product_list_ids(query))

    assert _select_list(sql) == "SELECT `catalog_product`.`id` AS `id`"


@pytest.mark.parametrize("sort", COLUMN_SORTS + DERIVED_SORTS)
def test_no_card_aggregate_is_annotated_before_the_limit(sort):
    """The named aliases, checked directly -- a clearer failure than the above."""
    query = parse_product_query({"sort": sort})
    sql, _ = _sql(catalogue.product_list_ids(query))

    present = [alias for alias in CARD_AGGREGATES if "`{0}`".format(alias) in sql]
    assert present == [], (
        "{0} annotated onto the pre-LIMIT query by sort={1}; move it into "
        "product_list_rows() so it costs one page, not one catalogue".format(present, sort)
    )


@pytest.mark.parametrize("sort", COLUMN_SORTS)
def test_a_sort_on_a_real_column_correlates_nothing_per_product(sort, catalogue_page):
    """
    Zero, not "few". newest and rating order on Product columns, so once the
    card aggregates are out of the way MySQL streams the join straight into a
    bounded sort -- no correlated subquery and no temporary table holding the
    result set. This is the control that proves the next test is not passing
    vacuously.
    """
    plan = _tree_plan(_view_queryset({"sort": sort})[:PAGE_SIZE])

    assert _correlated_subqueries(plan) == 0, plan


@pytest.mark.parametrize("sort", DERIVED_SORTS)
def test_a_derived_sort_correlates_only_its_own_sort_term(sort, catalogue_page):
    """
    price_asc and best_selling rank on a figure Product does not store, so one
    correlated subquery is the honest cost of computing it. One, not six: the
    other five were the card aggregates, and they are gone.

    If this ever has to be relaxed, the fix is a denormalised column on
    Product maintained by the services that already own those writes -- never
    a second subquery here.
    """
    plan = _tree_plan(_view_queryset({"sort": sort})[:PAGE_SIZE])

    assert _correlated_subqueries(plan) <= 1, plan


@pytest.mark.parametrize("sort", COLUMN_SORTS + DERIVED_SORTS)
def test_the_view_paginates_ids_not_rows(sort):
    """
    The regression this whole file exists for was a *view* change waiting to
    happen: paginate a queryset carrying the card aggregates and the cost per
    page becomes a cost per catalogue, with the query count unmoved.
    """
    sql, _ = _sql(_view_queryset({"sort": sort}))

    assert _select_list(sql) == "SELECT `catalog_product`.`id` AS `id`"


# ---------------------------------------------------------------------------
# The hydration query
# ---------------------------------------------------------------------------
def test_the_card_aggregates_are_evaluated_once_per_page_row(catalogue_page):
    """
    product_list_rows() runs the aggregates against a fixed id list, so the
    number of rows they are evaluated over is the page size no matter how big
    the catalogue is -- an IN () of twenty-four ids cannot fan out.

    Asserted here is that the bounded query still produces the whole card:
    moving work off the hot path is only a fix if nothing was dropped with it.
    """
    query = parse_product_query({"sort": SORT_PRICE_ASC})
    ids = list(catalogue.product_list_ids(query)[:PAGE_SIZE])
    assert len(ids) == PAGE_SIZE

    rows = catalogue.product_list_rows(ids)

    assert [row.pk for row in rows] == ids, "the page must keep the sort order"
    # Cheap proof the aggregates really did arrive from the database.
    assert all(row.price_min is not None for row in rows)
    assert all(row.variant_count == 2 for row in rows)


def test_a_page_of_rows_is_returned_in_the_order_it_was_asked_for(catalogue_page):
    """
    IN () has no order. product_list_rows reimposes the caller's, because the
    sort already happened in product_list_ids and recomputing it here against
    a different expression is how the two silently disagree.
    """
    ids = [product.pk for product in catalogue_page[:5]]

    forwards = [row.pk for row in catalogue.product_list_rows(ids)]
    backwards = [row.pk for row in catalogue.product_list_rows(list(reversed(ids)))]

    assert forwards == ids
    assert backwards == list(reversed(ids))


def test_an_empty_page_costs_no_query(django_assert_num_queries):
    with django_assert_num_queries(0):
        assert catalogue.product_list_rows([]) == []
