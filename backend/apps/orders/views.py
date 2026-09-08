"""
Checkout and order endpoints (PRD 7.2).

Views read the request, call a service, shape the response. Every rule they
appear to enforce -- server-side totals, stock, idempotency, who may cancel
what -- is enforced in services/, so the admin API in week 5 gets the same
behaviour by calling the same functions.

Two access notes:

* `POST /orders/` and `POST /checkout/quote/` are public, because guest
  checkout is permitted (FR-CHK-5). Everything a guest sends is re-derived
  server-side; the request supplies variant ids, quantities and an address,
  never a price.
* Every order read is scoped to an owner in the service layer -- to
  `request.user` for a signed-in customer, and to the email that placed the
  order for the guest read on `GET /orders/{reference}/?email=` -- so
  another customer's reference returns 404 rather than 403 (PRD 10.2).
"""
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .serializers import (
    CancelOrderSerializer,
    CheckoutQuoteSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    PlaceOrderSerializer,
    QuoteSerializer,
)
from .services import checkout as checkout_services
from .services import history as history_services
from .services import placement as placement_services


def _user_or_none(request):
    """A guest is None, not AnonymousUser -- services take an owner or nobody."""
    return request.user if request.user.is_authenticated else None


class CheckoutQuoteView(GenericAPIView):
    """
    POST /api/v1/checkout/quote/ -- server-computed totals for a basket, a
    district and a coupon.

    Public: the checkout page prices an order before asking anyone to sign in.

    Throttled on its own scope because it is the only public endpoint that
    reveals whether a coupon code exists -- it answers COUPON_NOT_FOUND for a
    made-up code and COUPON_EXPIRED for a real one. The codes stay
    distinguishable because the checkout page needs them; the rate limit is
    what stops anyone walking the whole code space.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "checkout"

    serializer_class = CheckoutQuoteSerializer
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        quote = checkout_services.quote(
            user=_user_or_none(request),
            items=data.get("items"),
            district=data.get("district") or None,
            coupon_code=data.get("coupon_code") or None,
        )
        return Response(QuoteSerializer(quote).data)


class OrderListCreateView(GenericAPIView):
    """
    POST /api/v1/orders/ -- place an order (public, guest checkout allowed).
    GET  /api/v1/orders/ -- this customer's order history.
    """

    # Placement is public for guest checkout, so it carries its own ceiling.
    # Reading your own history is authenticated and falls under the default
    # `user` rate instead.
    throttle_scope = "place_order"

    def get_throttles(self):
        if self.request.method == "POST":
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_permissions(self):
        if self.request.method == "POST":
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        return PlaceOrderSerializer if self.request.method == "POST" else OrderListSerializer

    def get(self, request):
        queryset = history_services.customer_orders(request.user)
        page = self.paginate_queryset(queryset)
        serializer = OrderListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order, created = placement_services.place_order(
            user=_user_or_none(request),
            idempotency_key=data["idempotency_key"],
            payment_method=data["payment_method"],
            shipping_address=data.get("shipping_address"),
            address_id=data.get("address_id"),
            save_address=data.get("save_address", False),
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            items=data.get("items"),
            coupon_code=data.get("coupon_code") or None,
            note=data.get("note", ""),
        )
        # A replayed idempotency key is answered with 200 and the original
        # order; only a genuinely new order is a 201 (FR-CHK-7).
        order = history_services.detail_for_response(order)
        return Response(
            OrderDetailSerializer(order).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class OrderDetailView(GenericAPIView):
    """
    GET /api/v1/orders/{reference}/ -- detail plus the status timeline.

    Two readers, one route, as the frozen contract describes it:

    * A **signed-in customer** reads their own orders. `?email=` is ignored on
      this path -- being logged in never widens what an account may see, so a
      customer who quotes a guest's address still gets 404.
    * A **guest** reads one order with `?email=<the address that placed it>`.
      This is the return path from the payment gateway: a full navigation from
      another origin, no session, no query cache, and until now no way for a
      guest to see the order they had just paid for. The reference alone is
      never enough -- the capability is the pair -- and every miss is the same
      404, so the endpoint cannot be used to discover which references exist.

    An anonymous caller who presents no email is answered 401 rather than 404,
    because "sign in to see this order" is the honest answer to a customer who
    is simply signed out, and no order is being described either way.
    """

    serializer_class = OrderDetailSerializer
    permission_classes = [AllowAny]
    lookup_field = "reference"
    # The guest path is unauthenticated and keyed on a reference, so it is
    # rate limited per IP. See `get_throttles`.
    throttle_scope = "order_lookup"

    def get_throttles(self):
        """
        Throttle the guest path only.

        A signed-in customer is already bounded by their own order list and by
        the default user rate; the anonymous reader is the one who could sit
        and walk the reference space, so that is where the per-IP budget goes.
        """
        if self.request.user and self.request.user.is_authenticated:
            return super().get_throttles()
        return [ScopedRateThrottle()]

    def get(self, request, reference):
        if request.user.is_authenticated:
            order = history_services.get_customer_order(request.user, reference)
        else:
            email = request.query_params.get("email") or ""
            if not email.strip():
                raise NotAuthenticated()
            order = history_services.get_guest_order(reference, email)
        return Response(OrderDetailSerializer(order).data)


class OrderCancelView(GenericAPIView):
    """
    POST /api/v1/orders/{reference}/cancel/ -- customer cancellation
    (FR-ORD-4).

    Legality is the transition table's decision, not this view's: a customer
    reaching for a shipped order is refused by TRANSITIONS.
    """

    serializer_class = CancelOrderSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, reference):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = history_services.get_customer_order(request.user, reference)
        placement_services.cancel_order(
            order,
            actor=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        fresh = history_services.get_customer_order(request.user, reference)
        return Response(OrderDetailSerializer(fresh).data)
