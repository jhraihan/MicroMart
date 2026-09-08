"""
Review and wishlist endpoints (PRD 7.2 storefront, 7.3 admin).

Views read the request, call a service, shape the response. Nothing they
appear to enforce is enforced here: purchase eligibility, the one-per-product
rule, the 30-day edit window, the pending-on-edit rule and the rating
recomputation all live in services/reviews.py, and the admin moderation view
calls the *same* moderate_review the rest of the system would -- so approving
a review from the dashboard and approving it from anywhere else can never
mean two different things.

Access notes:

* The public review list is AllowAny and shows approved reviews only.
* Writing, editing and the whole wishlist require authentication.
* Moderation is gated by IsAdminRole, matching PRD 7.3's "Admin" role for
  /admin/reviews/. Hiding the moderation screen in React is not the control.
* Every customer-scoped lookup goes through a service that filters by
  request.user first, so another customer's review or saved item is a 404 and
  never a 403 (PRD 10.2).
"""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.catalog.services import catalogue
from apps.common.permissions import IsAdminRole

from .filters import parse_moderation_status, parse_review_query
from .serializers import (
    AdminReviewSerializer,
    ModerationSerializer,
    ReviewInputSerializer,
    ReviewSerializer,
    ReviewUpdateSerializer,
    WishlistAddSerializer,
    WishlistItemSerializer,
)
from .services import reviews as review_services
from .services import wishlist as wishlist_services


def _user_or_none(request):
    return request.user if request.user.is_authenticated else None


# ---------------------------------------------------------------------------
# Storefront -- reviews
# ---------------------------------------------------------------------------
class ProductReviewsView(GenericAPIView):
    """
    GET  /api/v1/products/{slug}/reviews/ -- approved reviews, paginated.
    POST /api/v1/products/{slug}/reviews/ -- submit one (purchase verified
    server-side).

    The product is resolved through the storefront visibility predicate, so a
    hidden product's reviews are a 404 rather than a leak of what is in the
    catalogue but not for sale.
    """

    def get_permissions(self):
        return [IsAuthenticated()] if self.request.method == "POST" else [AllowAny()]

    def get_serializer_class(self):
        return ReviewInputSerializer if self.request.method == "POST" else ReviewSerializer

    def product(self):
        return get_object_or_404(catalogue.storefront_products(), slug=self.kwargs["slug"])

    def get(self, request, slug):
        product = self.product()
        query = parse_review_query(request.query_params)
        page = self.paginate_queryset(
            review_services.approved_reviews(
                product, rating=query.rating, sort=query.sort
            )
        )
        response = self.get_paginated_response(
            ReviewSerializer(page, many=True).data
        )
        # Counted over every approved review, not the page -- the same reason
        # the product list carries facets beside its results.
        response.data["summary"] = review_services.rating_summary(product)
        # Answered by the same eligibility function that gates the write, so
        # the form is never offered where the POST would be refused.
        response.data["can_review"] = review_services.can_review(
            _user_or_none(request), product
        )
        return response

    def post(self, request, slug):
        product = self.product()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review = review_services.create_review(
            user=request.user, product=product, **serializer.validated_data
        )
        return Response(
            ReviewSerializer(review).data, status=status.HTTP_201_CREATED
        )


class ReviewDetailView(GenericAPIView):
    """
    PATCH  /api/v1/reviews/{id}/ -- the author edits, within 30 days
    (FR-REV-3). The review returns to `pending` (FR-REV-4).
    DELETE /api/v1/reviews/{id}/ -- the author withdraws it, which is the
    "removal" limb of FR-REV-5.

    Another customer's review is a 404, decided in the service by scoping to
    request.user before matching the id.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ReviewUpdateSerializer

    def patch(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review = review_services.update_review(
            user=request.user, review_id=pk, **serializer.validated_data
        )
        return Response(ReviewSerializer(review).data)

    def delete(self, request, pk):
        review_services.delete_review(user=request.user, review_id=pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Storefront -- wishlist
# ---------------------------------------------------------------------------
class WishlistView(GenericAPIView):
    """
    GET  /api/v1/wishlist/ -- saved products with their current price and
    stock status (FR-WSH-2). Out-of-stock items are present and labelled, not
    hidden (FR-WSH-3).
    POST /api/v1/wishlist/ -- save one. A repeat click is a no-op answered
    200; a genuine add is 201.
    """

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return WishlistAddSerializer if self.request.method == "POST" else WishlistItemSerializer

    def get(self, request):
        page = self.paginate_queryset(wishlist_services.wishlist_items(request.user))
        return self.get_paginated_response(
            WishlistItemSerializer(page, many=True).data
        )

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        item, created = wishlist_services.add_to_wishlist(
            user=request.user, product_id=serializer.validated_data["product_id"]
        )
        # Re-read through the annotated queryset so the response carries the
        # same price and stock the list would show.
        item = wishlist_services.wishlist_items(request.user).get(pk=item.pk)
        return Response(
            WishlistItemSerializer(item).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class WishlistItemView(GenericAPIView):
    """DELETE /api/v1/wishlist/{product_id}/ -- remove one saved product."""

    permission_classes = [IsAuthenticated]
    serializer_class = WishlistItemSerializer

    def delete(self, request, product_id):
        wishlist_services.remove_from_wishlist(
            user=request.user, product_id=product_id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin (PRD 7.3)
# ---------------------------------------------------------------------------
class AdminReviewListView(ListAPIView):
    """
    GET /api/v1/admin/reviews/?status=pending -- the moderation queue.

    Defaults to pending, takes any ReviewStatus, or `all`.
    """

    permission_classes = [IsAdminRole]
    serializer_class = AdminReviewSerializer
    filter_backends = []

    def get_queryset(self):
        return review_services.moderation_queue(
            status=parse_moderation_status(self.request.query_params)
        )


class AdminReviewModerateView(GenericAPIView):
    """
    POST /api/v1/admin/reviews/{id}/moderate/ -- approve or reject.

    Calls the same moderate_review the service layer exposes to everything
    else, which is what recomputes Product.rating_avg / rating_count. A view
    that flipped `status` itself would leave the aggregate stale.
    """

    permission_classes = [IsAdminRole]
    serializer_class = ModerationSerializer

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review = review_services.moderate_review(
            review=review_services.get_review(pk),
            decision=serializer.validated_data["decision"],
            actor=request.user,
        )
        return Response(AdminReviewSerializer(review).data)
