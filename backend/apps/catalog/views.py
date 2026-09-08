"""
Storefront catalogue endpoints (PRD 7.2, docs/api-contract-catalogue.md).

Views do three things only: read the request, call a service, shape the
response. No filtering, ranking or counting logic lives here -- it is all in
services/catalogue.py so the admin catalogue API can reuse it verbatim.

Everything in this module is public and read-only, so DRF's AllowAny default
stands. Nothing here exposes a field a customer should not see: cost prices,
inventory logs and inactive rows never enter these querysets.
"""
from django.shortcuts import get_object_or_404
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .filters import parse_product_query
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    ProductDetailSerializer,
    ProductListSerializer,
)
from .services import catalogue


class CategoryListView(ListAPIView):
    """GET /api/v1/categories/ -- the full tree, one level of nesting."""

    serializer_class = CategorySerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return catalogue.category_tree()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # One aggregate query for the whole tree instead of one per node.
        context["product_counts"] = catalogue.category_product_counts()
        return context


class BrandListView(ListAPIView):
    """GET /api/v1/brands/"""

    serializer_class = BrandSerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return catalogue.brand_list()


class ProductListView(ListAPIView):
    """GET /api/v1/products/ -- search, filter, facets, sort, paginate."""

    serializer_class = ProductListSerializer
    filter_backends = []  # parsing is explicit; see filters.parse_product_query

    def get_queryset(self):
        # Ids only, and list() paginates exactly this. The card aggregates are
        # correlated subqueries: MySQL runs a SELECT-list subquery for every
        # row that reaches the sort, not for the twenty-four that survive the
        # LIMIT, so they are annotated afterwards by product_list_rows().
        return catalogue.product_list_ids(parse_product_query(self.request.query_params))

    def list(self, request, *args, **kwargs):
        query = parse_product_query(request.query_params)
        ids = self.paginate_queryset(self.get_queryset())
        serializer = self.get_serializer(catalogue.product_list_rows(ids), many=True)
        response = self.get_paginated_response(serializer.data)
        # Facets are counted over the whole filtered set, not the page, and
        # each dimension is blind to its own filter (FR-SRC-2).
        response.data["facets"] = catalogue.product_facets(query)
        return response


class ProductDetailView(RetrieveAPIView):
    """GET /api/v1/products/{slug}/ -- inactive products 404 (FR-CAT-7)."""

    serializer_class = ProductDetailSerializer
    lookup_field = "slug"
    filter_backends = []

    def get_queryset(self):
        return catalogue.product_detail_queryset()


class ProductRelatedView(ListAPIView):
    """GET /api/v1/products/{slug}/related/ -- bare array, no pagination."""

    serializer_class = ProductListSerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        product = get_object_or_404(
            catalogue.storefront_products(), slug=self.kwargs["slug"]
        )
        return catalogue.related_products(product)


@extend_schema(
    tags=["catalogue"],
    responses={200: None},
    summary="Type-ahead suggestions for the search box",
)
class SearchSuggestView(APIView):
    """
    GET /api/v1/search/suggest/?q= -- type-ahead for the header box (FR-SRC-6).

    Three sections in one round trip. `products` carries enough to draw a row
    with a thumbnail and a price, because a suggestion list of bare strings
    makes the shopper open a page to find out whether it was the right one.

    With no `q`, returns the popular-search list so an empty, focused box has
    something useful in it.
    """

    def get(self, request):
        keyword = request.query_params.get("q", "")
        result = catalogue.search_suggestions(keyword)
        return Response(
            {
                "query": result["query"],
                "products": ProductListSerializer(result["products"], many=True).data,
                "categories": CategorySerializer(
                    result["categories"], many=True, context={"product_counts": {}}
                ).data,
                "brands": BrandSerializer(result["brands"], many=True).data,
                "popular": list(catalogue.POPULAR_SEARCHES),
            }
        )


@extend_schema(
    tags=["catalogue"],
    responses={200: None},
    summary="Side-by-side spec matrix for up to four products",
)
class ProductCompareView(APIView):
    """
    GET /api/v1/products/compare/?slugs=a,b,c -- up to four products side by side.

    Returns the products *and* a precomputed spec matrix. The matrix is
    server-side because deciding which rows differ needs the whole set at
    once, and because the client would otherwise have to re-implement the
    grouping rules to line the rows up.
    """

    def get(self, request):
        raw = request.query_params.get("slugs", "")
        slugs = [s.strip() for s in raw.split(",") if s.strip()]
        products = catalogue.compare_products(slugs)
        return Response(
            {
                "count": len(products),
                "max": catalogue.MAX_COMPARE_PRODUCTS,
                "products": ProductDetailSerializer(products, many=True).data,
                "spec_matrix": catalogue.compare_spec_matrix(products),
            }
        )


class ProductBoughtTogetherView(ListAPIView):
    """
    GET /api/v1/products/{slug}/bought-together/

    Real co-purchase data, so an empty array is a normal answer on a young
    catalogue -- the detail page hides the section rather than padding it.
    """

    serializer_class = ProductListSerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        product = get_object_or_404(
            catalogue.storefront_products(), slug=self.kwargs["slug"]
        )
        return catalogue.frequently_bought_together(product)
