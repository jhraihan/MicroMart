"""
N+1 guard (PRD 9.1: product list p95 < 500ms, detail p95 < 400ms).

The bar is not "few queries" but "a constant number of queries": the same
request against 3 products and against 40 must cost the same, or the p95
budget quietly evaporates as the catalogue grows.
"""
import pytest

from .factories import make_brand, make_category, make_image, make_product, make_spec

pytestmark = pytest.mark.django_db

# Measured, not guessed: count + page ids + page rows + image prefetch + five
# facet queries.
#
# Nine, not eight. The page costs two round trips on purpose: the ids are
# paginated bare and the card aggregates are annotated onto the twenty-four
# rows that survived (catalogue.product_list_ids). Annotated before the LIMIT
# they were one query -- and five correlated subqueries per row of the whole
# result set. One extra constant query buys away a cost that scaled with the
# catalogue, which is the trade this budget exists to protect. MySQL will not
# take a LIMIT inside an IN subquery, so the two cannot be folded back into one.
LIST_QUERY_BUDGET = 9
DETAIL_QUERY_BUDGET = 5
RELATED_QUERY_BUDGET = 3
CATEGORY_QUERY_BUDGET = 4


def build_catalogue(size, *, images=True):
    category = make_category("Laptops", "laptops")
    child = make_category("Gaming Laptops", "gaming-laptops", parent=category)
    brands = [make_brand("Brand {0}".format(index), "brand-{0}".format(index)) for index in range(3)]
    products = []
    for index in range(size):
        product = make_product(
            child if index % 2 else category,
            brand=brands[index % len(brands)],
            name="Product {0:03d}".format(index),
            slug="product-{0:03d}".format(index),
            rating_avg="{0}.00".format(index % 5),
            rating_count=index,
            variants=[
                {"sku": "SKU-{0}-A".format(index), "price": "1000.00", "stock": 4},
                {"sku": "SKU-{0}-B".format(index), "price": "2000.00", "stock": 2},
            ],
        )
        if images:
            make_image(product, is_primary=True, alt_text="front")
            make_image(product, sort_order=1, alt_text="side")
        products.append(product)
    return products


def test_product_list_query_count_is_bounded(
    api, products_url, django_assert_num_queries
):
    build_catalogue(3)

    with django_assert_num_queries(LIST_QUERY_BUDGET):
        response = api.get(products_url)

    assert response.status_code == 200


def test_product_list_query_count_does_not_grow_with_the_catalogue(
    api, products_url, django_assert_num_queries
):
    # Forty products, two variants and two images each. A per-product query
    # would put this well past the budget.
    build_catalogue(40)

    with django_assert_num_queries(LIST_QUERY_BUDGET):
        payload = api.get(products_url).json()

    assert payload["count"] == 40
    assert len(payload["results"]) == 24


def test_filtered_and_sorted_list_stays_inside_the_same_budget(
    api, products_url, django_assert_num_queries
):
    build_catalogue(30)

    with django_assert_num_queries(LIST_QUERY_BUDGET):
        api.get(
            products_url,
            {
                "category": "laptops",
                "brand": ["brand-0", "brand-1"],
                "min_price": "500",
                "max_price": "5000",
                "in_stock": "true",
                "sort": "price_asc",
            },
        )


def test_search_results_stay_inside_the_same_budget(
    api, products_url, django_assert_num_queries
):
    build_catalogue(30)

    with django_assert_num_queries(LIST_QUERY_BUDGET):
        api.get(products_url, {"q": "Product"})


def test_the_two_reviewed_sorts_stay_inside_the_same_budget(
    api, products_url, django_assert_num_queries
):
    """
    price_asc and best_selling are the two the week-2 review measured over
    budget (docs/HANDOFF.md 4). Both rank on a figure Product does not store,
    so both are the ones most likely to grow a per-row cost again.
    """
    build_catalogue(40)

    for sort in ("price_asc", "best_selling"):
        with django_assert_num_queries(LIST_QUERY_BUDGET):
            response = api.get(products_url, {"sort": sort})
        assert response.status_code == 200, sort


def test_a_deep_page_costs_no_more_queries_than_the_first(
    api, products_url, django_assert_num_queries
):
    """
    Deep-page cost was the other half of the finding: the whole result set was
    materialised before the offset was applied, so page 2 paid for page 1 all
    over again. The query count was always constant here -- what was not was
    the work inside it -- so this pins the count and
    test_list_query_plans.py pins the shape.
    """
    build_catalogue(120)

    for sort in ("price_asc", "best_selling", "newest"):
        with django_assert_num_queries(LIST_QUERY_BUDGET):
            payload = api.get(products_url, {"sort": sort, "page": "5"}).json()
        assert len(payload["results"]) == 24, sort


def test_product_detail_query_count_is_bounded(
    api, detail_url, django_assert_num_queries
):
    products = build_catalogue(5)
    subject = products[0]
    for index in range(6):
        make_spec(subject, "Key {0}".format(index), "Value {0}".format(index))
    for variant in subject.variants.all():
        make_image(subject, variant=variant, alt_text="variant shot")

    with django_assert_num_queries(DETAIL_QUERY_BUDGET):
        response = api.get(detail_url(subject.slug))

    assert response.status_code == 200


def test_related_endpoint_does_not_query_per_product(
    api, related_url, django_assert_num_queries
):
    products = build_catalogue(12)
    subject = products[0]

    with django_assert_num_queries(RELATED_QUERY_BUDGET):
        rows = api.get(related_url(subject.slug)).json()

    assert len(rows) == 5


def test_category_tree_does_not_query_per_node(
    api, categories_url, django_assert_num_queries
):
    build_catalogue(4)
    root = make_category("Peripherals", "peripherals")
    for index in range(8):
        make_category(
            "Child {0}".format(index), "child-{0}".format(index), parent=root
        )

    with django_assert_num_queries(CATEGORY_QUERY_BUDGET):
        api.get(categories_url)
