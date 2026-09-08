"""
Shipping endpoints (PRD 7.2).

Public and read-only: the checkout page needs the rate table before a customer
has an account, let alone an address.
"""
from rest_framework.generics import ListAPIView

from .serializers import ShippingZoneSerializer
from .services import rates as shipping_services


class ShippingZoneListView(ListAPIView):
    """GET /api/v1/shipping/zones/ -- active zones and their rates."""

    serializer_class = ShippingZoneSerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return shipping_services.active_zones()
