"""
N+1 guard for the two requests a product detail page makes (PRD 9.1: detail
p95 < 400ms).

Same bar as apps/catalog/tests/test_query_counts.py and
apps/cart/tests/test_query_counts.py: not "few queries" but a *constant*
number. A product with one review and a product with twenty must cost the
same, or the review panel quietly eats the detail budget as the catalogue
ages -- and reviews are the one thing on that page that grows without anybody
editing the product.

Two surfaces are measured because the page fetches both:

* GET /products/{slug}/         -- rating_avg / rating_count are denormalised
  columns (PRD 6.2), so this must not touch reviews_review at all; and
* GET /products/{slug}/reviews/ -- the list, plus rating_summary's aggregate
  and can_review's eligibility probe, which are counted once each per request
  and never once per row.
"""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

pytestmark = pytest.mark.django_db


def detail_url(product):
    return reverse("catalog:product-detail", kwargs={"slug": product.slug})


def count_queries(client, url):
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url)
    assert response.status_code == 200, response.data
    return len(captured), captured


def write_approved(write_review, product, how_many, ratings=(5, 4, 3, 2, 1)):
    """`how_many` approved reviews by `how_many` distinct delivered buyers."""
    for index in range(how_many):
        write_review(ratings[index % len(ratings)], for_product=product)


def test_the_review_list_costs_the_same_for_one_review_and_for_twenty(
    api, reviews_url, product, write_review
):
    write_approved(write_review, product, 1)
    one, _ = count_queries(api, reviews_url(product.slug))

    write_approved(write_review, product, 19)
    twenty, captured = count_queries(api, reviews_url(product.slug))

    assert twenty == one, (
        "Reading the review list got more expensive as reviews were added: "
        "{0} queries for one review, {1} for twenty. Something on the row is "
        "lazy-loading -- check the select_related in "
        "reviews.services.reviews._base_queryset.\n{2}".format(
            one,
            twenty,
            "\n".join(query["sql"][:160] for query in captured.captured_queries),
        )
    )


def test_the_review_list_is_constant_for_a_signed_in_eligible_reviewer(
    as_user, reviews_url, product, write_review, buyer
):
    """
    `can_review` runs an eligibility query per request. Signed in is the more
    expensive branch -- signed out short-circuits before touching OrderItem --
    so the constancy that matters is measured there.
    """
    reader = buyer(product)
    client = as_user(reader)

    write_approved(write_review, product, 1)
    one, _ = count_queries(client, reviews_url(product.slug))

    write_approved(write_review, product, 19)
    twenty, _ = count_queries(client, reviews_url(product.slug))

    assert twenty == one, (
        "The signed-in review list grew from {0} to {1} queries between one "
        "review and twenty.".format(one, twenty)
    )


def test_the_product_detail_response_never_reads_the_review_table(
    api, product, write_review
):
    """
    FR-REV-5 denormalises the aggregate onto Product precisely so the detail
    request does not pay for it. If this fails, someone has replaced the
    stored columns with a live aggregate and the p95 budget went with it.
    """
    write_approved(write_review, product, 20)

    count, captured = count_queries(api, detail_url(product))

    review_queries = [
        query
        for query in captured.captured_queries
        if "reviews_review" in query["sql"]
    ]
    assert review_queries == [], (
        "Product detail read reviews_review {0} time(s); rating_avg and "
        "rating_count are stored columns.".format(len(review_queries))
    )


def test_product_detail_costs_the_same_with_one_review_and_with_twenty(
    api, product, write_review
):
    write_approved(write_review, product, 1)
    one, _ = count_queries(api, detail_url(product))

    write_approved(write_review, product, 19)
    twenty, _ = count_queries(api, detail_url(product))

    assert twenty == one, (
        "Product detail grew from {0} to {1} queries between one review and "
        "twenty.".format(one, twenty)
    )
