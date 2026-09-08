"""
Admin order pipeline and dashboard endpoints (PRD 7.3).

Views read the request, call a service, shape the response. Every rule they
appear to enforce lives in `services/`, and the order rules live in
apps/orders/services/ specifically -- the admin surface advances an order with
the same `transition_order` a customer's cancellation goes through, so the
state machine cannot be legal on one surface and not the other.

**Role gating is per view, not per prefix** (PRD 4.3 US-A8, FR-ADM-10). Staff
may read orders and move their status; that is the whole of their authority.
Everything else here -- the dashboard, the customer directory, store settings
-- is `IsAdminRole` and answers staff with 403. `IsAdminOrStaff` on the whole
module would have been one line shorter and wrong.
"""
from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.response import Response

from apps.common.permissions import IsAdminOrStaff, IsAdminRole
from apps.orders.models import Actor
from apps.orders.services import history as history_services
from apps.orders.services import placement as placement_services
from config.exceptions import DomainError

from .serializers import (
    AdminCustomerSerializer,
    AdminOrderDetailSerializer,
    AdminOrderListSerializer,
    DashboardSerializer,
    OrderStatusUpdateSerializer,
    ShipmentInputSerializer,
    StoreSettingsSerializer,
    StoreSettingsUpdateSerializer,
)
from .services import customers as customer_services
from .services import metrics as metric_services
from .services import store as store_services


def _parse_date_bound(params, key, *, end_of_day=False):
    """
    `?placed_from=2026-08-01` / `?placed_to=2026-08-22`, inclusive of both
    named days, resolved to aware datetimes.

    Resolved here rather than handed to the ORM as a date, because MySQL on
    this deployment has no timezone tables: a `placed_at__date__gte` lookup
    would compare against CONVERT_TZ(...) = NULL and quietly match nothing.
    """
    raw = (params.get(key) or "").strip()
    if not raw:
        return None
    try:
        day = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise DomainError(
            "Use YYYY-MM-DD, e.g. 2026-08-22.",
            code="INVALID_FILTER",
            field=key,
        )
    start = timezone.make_aware(
        datetime.combine(day, datetime.min.time()), timezone.get_current_timezone()
    )
    return start + timedelta(days=1) if end_of_day else start


class AdminDashboardView(GenericAPIView):
    """
    GET /api/v1/admin/dashboard/ -- revenue, order counts, trend series, alerts
    (US-A1). Admin only: staff get 403 (US-A8).
    """

    permission_classes = [IsAdminRole]
    serializer_class = DashboardSerializer

    def get(self, request):
        days = metric_services.parse_trend_days(request.query_params.get("days"))
        snapshot = metric_services.dashboard_snapshot(days=days)
        return Response(DashboardSerializer(snapshot).data)


class AdminOrderListView(ListAPIView):
    """
    GET /api/v1/admin/orders/ -- filter and search (US-A3, US-T1).

    Filters: `status` (repeatable or comma-separated), `payment_method`,
    `placed_from`, `placed_to`. Search: `q` against reference, email, phone or
    customer name.
    """

    permission_classes = [IsAdminOrStaff]
    serializer_class = AdminOrderListSerializer
    filter_backends = []

    def get_queryset(self):
        params = self.request.query_params
        statuses = params.getlist("status") or None
        return history_services.admin_orders(
            statuses=statuses,
            payment_method=params.get("payment_method"),
            placed_from=_parse_date_bound(params, "placed_from"),
            placed_to=_parse_date_bound(params, "placed_to", end_of_day=True),
            search=params.get("q") or params.get("search"),
        )


class AdminOrderDetailView(GenericAPIView):
    """GET /api/v1/admin/orders/{reference}/ -- full detail (US-A3)."""

    permission_classes = [IsAdminOrStaff]
    serializer_class = AdminOrderDetailSerializer

    def get(self, request, reference):
        order = history_services.get_admin_order(reference)
        return Response(AdminOrderDetailSerializer(order).data)


class AdminOrderStatusView(GenericAPIView):
    """
    POST /api/v1/admin/orders/{reference}/status/ -- advance the order.

    The view decides nothing. `transition_order` consults TRANSITIONS
    (PRD 15.1), refuses anything absent from it with 422 *without logging it*,
    moves stock where the rule says to, and writes the OrderStatusLog row with
    this admin as the actor. A view that set `order.status` itself would skip
    all four.
    """

    permission_classes = [IsAdminOrStaff]
    serializer_class = OrderStatusUpdateSerializer

    def post(self, request, reference):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = history_services.get_admin_order(reference)
        placement_services.transition_order(
            order=order,
            to_status=serializer.validated_data["status"],
            actor=request.user,
            actor_role=Actor.ADMIN,
            note=serializer.validated_data.get("note", ""),
        )
        fresh = history_services.get_admin_order(reference)
        return Response(AdminOrderDetailSerializer(fresh).data)


class AdminOrderShipmentView(GenericAPIView):
    """
    POST /api/v1/admin/orders/{reference}/shipment/ -- attach courier and
    tracking number (FR-ORD-7).

    Separate from the status endpoint on purpose: `packed -> shipped` is
    marked `requires_shipment` in TRANSITIONS, so this is the step that makes
    that transition legal rather than a field smuggled into it.
    """

    permission_classes = [IsAdminOrStaff]
    serializer_class = ShipmentInputSerializer

    def post(self, request, reference):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = history_services.get_admin_order(reference)
        placement_services.record_shipment(
            order=order,
            courier_name=serializer.validated_data["courier_name"],
            tracking_number=serializer.validated_data["tracking_number"],
        )
        fresh = history_services.get_admin_order(reference)
        return Response(AdminOrderDetailSerializer(fresh).data)


class AdminCustomerListView(ListAPIView):
    """
    GET /api/v1/admin/customers/ -- order count and lifetime value.
    Admin only: staff get 403 (US-A8).
    """

    permission_classes = [IsAdminRole]
    serializer_class = AdminCustomerSerializer
    filter_backends = []

    def get_queryset(self):
        params = self.request.query_params
        return customer_services.customer_directory(
            search=params.get("q") or params.get("search")
        )


class AdminStoreSettingsView(GenericAPIView):
    """
    GET / PATCH /api/v1/admin/settings/ -- the store singleton.
    Admin only: staff get 403 (US-A8).

    GET creates the row if it has never been read; PATCH updates it. Neither
    can produce a second row -- `StoreSettings.save()` pins pk=1.
    """

    permission_classes = [IsAdminRole]
    serializer_class = StoreSettingsUpdateSerializer

    def get(self, request):
        settings = store_services.get_store_settings()
        return Response(StoreSettingsSerializer(settings).data)

    def patch(self, request):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        settings = store_services.update_store_settings(**serializer.validated_data)
        return Response(StoreSettingsSerializer(settings).data)
