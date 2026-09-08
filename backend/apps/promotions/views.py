"""
Coupon endpoints for the admin surface (PRD 7.3, US-A5).

Views read the request, call a service, shape the response. Nothing they
appear to enforce is enforced here: the discount bounds, the validity window,
the scope, the code's uniqueness and normalisation, the immutability of a
redeemed coupon's code and the refusal to destroy redemption history all live
in services/coupons.py -- beside the validator checkout runs, so the admin
surface and the storefront cannot end up with two ideas of what a legal coupon
is.

Access: IsAdminRole, not IsAdminOrStaff. PRD 7.3 lists CRUD /admin/coupons/
under the Admin role, and US-A8/US-T2 are explicit that staff may view orders
and update order status only -- an attempt by staff to edit a coupon is
refused server-side with 403. Hiding the screen in React is not the control.
"""
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole

from .filters import parse_coupon_query
from .serializers import (
    CouponCreateSerializer,
    CouponSerializer,
    CouponUpdateSerializer,
)
from .services import coupons as coupon_services


class AdminCouponListCreateView(GenericAPIView):
    """
    GET  /api/v1/admin/coupons/ -- the coupon register, newest first,
    filterable by ?status= and searchable by ?search= on the code. Every row
    carries its redemption count, counted from CouponRedemption.
    POST /api/v1/admin/coupons/ -- create one.
    """

    permission_classes = [IsAdminRole]
    filter_backends = []

    def get_serializer_class(self):
        return (
            CouponCreateSerializer
            if self.request.method == "POST"
            else CouponSerializer
        )

    def get(self, request):
        query = parse_coupon_query(request.query_params)
        page = self.paginate_queryset(
            coupon_services.admin_coupons(status=query.status, search=query.search)
        )
        return self.get_paginated_response(CouponSerializer(page, many=True).data)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        coupon = coupon_services.create_coupon(**serializer.validated_data)
        # Re-read through the annotated queryset so the created row answers
        # with the same redemption count the list would show it with.
        return Response(
            CouponSerializer(coupon_services.get_admin_coupon(coupon.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class AdminCouponDetailView(GenericAPIView):
    """
    GET    /api/v1/admin/coupons/{id}/ -- one coupon and its redemption count.
    PATCH  /api/v1/admin/coupons/{id}/ -- edit it.
    DELETE /api/v1/admin/coupons/{id}/ -- retire it.

    DELETE deactivates rather than destroys, and answers 200 with the retired
    coupon rather than 204. The reason is in `deactivate_coupon`: redemptions
    cascade and placed orders reference the coupon, so a real delete would
    rewrite the record of a promotion that actually ran. The response body is
    the coupon so the client can see the state it is now in.
    """

    permission_classes = [IsAdminRole]
    filter_backends = []
    serializer_class = CouponUpdateSerializer

    def get_serializer_class(self):
        return CouponUpdateSerializer if self.request.method == "PATCH" else CouponSerializer

    def get(self, request, pk):
        return Response(CouponSerializer(coupon_services.get_admin_coupon(pk)).data)

    def patch(self, request, pk):
        serializer = CouponUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        coupon = coupon_services.update_coupon(
            coupon_services.get_admin_coupon(pk), **serializer.validated_data
        )
        return Response(
            CouponSerializer(coupon_services.get_admin_coupon(coupon.pk)).data
        )

    def delete(self, request, pk):
        coupon = coupon_services.deactivate_coupon(coupon_services.get_admin_coupon(pk))
        return Response(
            CouponSerializer(coupon_services.get_admin_coupon(coupon.pk)).data
        )
