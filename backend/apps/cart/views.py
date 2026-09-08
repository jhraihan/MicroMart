"""
Cart endpoints (PRD 7.2).

Views read the request, call a service, shape the response -- nothing else.
Every one of them is scoped to request.user's own cart, which is what makes
another customer's line a 404 rather than a 403.

All four mutating endpoints return the whole cart, so the header mini-cart,
the line list and any clamp notice can never disagree with each other.
"""
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .serializers import (
    CartItemAddSerializer,
    CartItemUpdateSerializer,
    CartMergeSerializer,
    CartSerializer,
)
from .services import cart as cart_services


class CartBaseView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = None
    filter_backends = []

    def cart(self):
        return cart_services.get_cart(self.request.user)

    def rendered(self, view, http_status=status.HTTP_200_OK):
        return Response(CartSerializer(view).data, status=http_status)


class CartView(CartBaseView):
    """GET /api/v1/cart/ -- stock and availability re-checked on every read."""

    serializer_class = CartSerializer

    def get(self, request):
        return self.rendered(cart_services.read_cart(self.cart()))


class CartItemsView(CartBaseView):
    """POST /api/v1/cart/items/ -- add a variant. Reserves no stock."""

    serializer_class = CartItemAddSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        view = cart_services.add_item(cart=self.cart(), **serializer.validated_data)
        return self.rendered(view, http_status=status.HTTP_201_CREATED)


class CartItemDetailView(CartBaseView):
    """PATCH / DELETE /api/v1/cart/items/{id}/"""

    serializer_class = CartItemUpdateSerializer

    def patch(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        view = cart_services.update_item(
            cart=self.cart(), item_id=pk, quantity=serializer.validated_data["quantity"]
        )
        return self.rendered(view)

    def delete(self, request, pk):
        return self.rendered(cart_services.remove_item(cart=self.cart(), item_id=pk))


class CartMergeView(CartBaseView):
    """
    POST /api/v1/cart/merge/ -- fold the guest cart in at login (FR-CRT-2).

    Quantities sum with anything already on the server, each line is clamped to
    available stock, and every clamp or drop comes back as a notice so the UI
    can say what changed.
    """

    serializer_class = CartMergeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        view = cart_services.merge_guest_cart(
            cart=self.cart(), items=serializer.validated_data["items"]
        )
        return self.rendered(view)
