"""
Payment endpoints (PRD 7.2, FR-PAY-2..7).

Views read the request, call a service, shape the response. Every rule these
appear to enforce -- what may be paid for, what counts as proof, what an
already-confirmed order does with a second notification -- lives in
services/payments.py, so the admin surface in week 5 gets the same answers by
calling the same functions.

The three surfaces have three different threat models, and the class
attributes below say so explicitly rather than inheriting whatever
REST_FRAMEWORK happens to default to:

* **initiate** is public because guest checkout is (FR-CHK-5). It takes an
  order reference and nothing else; ownership is checked in the service, where
  a miss is 404 rather than 403 (PRD 10.2).
* **ipn** is called by SSLCommerz's servers, never by a browser. No session, no
  JWT, no CSRF token, no throttle -- and correspondingly nothing in the request
  is trusted, including the claim that a payment succeeded.
* **callback** is a browser redirect anybody can type. It is read-only by
  construction: the service it calls touches no rows at all.
"""
from django.conf import settings
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .serializers import (
    IPNResultSerializer,
    PaymentCallbackSerializer,
    PaymentInitiateSerializer,
    PaymentSessionSerializer,
)
from .services import payments as payment_services


def _payload(request):
    """
    The request body as a plain dict.

    SSLCommerz posts form-encoded, so DRF hands over a QueryDict; `.dict()`
    collapses it. This is evidence, not instruction -- see handle_ipn.
    """
    data = getattr(request, "data", None)
    if data is None:
        return {}
    if hasattr(data, "dict"):
        return data.dict()
    if isinstance(data, dict):
        return dict(data)
    return {}


def _client_ip(request):
    """Best-effort, for the gateway's own risk scoring. Never used to authorise."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "")[:45]


class PaymentInitiateView(GenericAPIView):
    """
    POST /api/v1/payments/initiate/ -- open an SSLCommerz session (FR-PAY-2).

    Returns 200 with a redirect URL. Not 201: what the client receives is an
    instruction to go somewhere, not a resource it may later fetch. The Payment
    row this writes says INITIATED, which means "a customer was sent to the
    gateway" and never "a customer paid".
    """

    serializer_class = PaymentInitiateSerializer
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = payment_services.initiate_payment(
            order_reference=serializer.validated_data["order_reference"],
            user=request.user if request.user.is_authenticated else None,
            # The public origin of this API, so the gateway's four callbacks
            # point back here rather than at a hard-coded host.
            base_url=request.build_absolute_uri("/"),
            customer_ip=_client_ip(request),
        )
        return Response(PaymentSessionSerializer(session).data)


@method_decorator(csrf_exempt, name="dispatch")
@extend_schema(
    tags=["payments"],
    request=None,
    responses={200: None},
    summary="Gateway notification (server-to-server only)",
    description=(
        "SSLCommerz posts here. The body is never trusted: the handler calls "
        "the gateway back to validate, and takes the order reference from "
        "that response rather than from this request."
    ),
)
class PaymentIPNView(APIView):
    """
    POST /api/v1/payments/ipn/ -- the gateway's server-to-server notification
    (FR-PAY-4, FR-PAY-5).

    This is the only endpoint in the application that can mark an order paid,
    and it does so on the strength of its own outbound validation call, never
    on the body it was handed.

    Everything is switched off here on purpose. There is no authentication to
    apply (SSLCommerz does not carry our JWTs), no CSRF token to check (no
    browser session is involved), and no throttle (a throttled IPN is a
    retried IPN, and the endpoint is idempotent anyway). Safety comes from
    distrusting the request, not from gating it.

    It answers 200 for every notification it understood, including the ones it
    refused to act on -- a non-2xx makes the gateway retry, and retrying an
    amount mismatch would never produce a different answer.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        result = payment_services.handle_ipn(_payload(request))
        return Response(IPNResultSerializer(result).data)


@method_decorator(csrf_exempt, name="dispatch")
@extend_schema(
    tags=["payments"],
    request=None,
    responses={200: None},
    summary="Where the browser lands after paying (display only)",
    description=(
        "Reads nothing and writes nothing. Anyone can open this URL, so it "
        "never reports whether a payment succeeded."
    ),
)
class PaymentCallbackView(APIView):
    """
    GET /api/v1/payments/callback/{result}/ -- the browser coming back from
    SSLCommerz (FR-PAY-3).

    **Display only, and read-only.** This endpoint changes no order status, no
    payment status and no stock, and it does not so much as SELECT the order:
    a redirect URL is user-controllable, so anything decided here would be
    decided by whoever typed it. Confirmation happens in the IPN handler or it
    does not happen.

    POST is accepted because SSLCommerz posts its redirect rather than getting
    it, and it does exactly the same nothing.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, result):
        return self._respond(request, result)

    def post(self, request, result):
        return self._respond(request, result)

    def _respond(self, request, result):
        body = _payload(request)
        reference = (
            request.query_params.get("tran_id")
            or request.query_params.get("reference")
            or body.get("tran_id")
            or body.get("value_a")
            or ""
        )
        payload = payment_services.callback(
            result,
            reference=reference,
            frontend_base_url=settings.FRONTEND_BASE_URL,
        )
        # A browser is on the other end of this, not an API client: SSLCommerz
        # sends the customer here, so answering JSON at them would leave raw
        # JSON on screen. 302 hands them to the SPA return page.
        #
        # This does not weaken the read-only guarantee one bit -- a redirect
        # reads no rows and writes none, and the page it lands on decides
        # nothing either: it reads the order back over the authenticated API.
        response = redirect(payload["redirect_url"])
        response["Cache-Control"] = "no-store"
        return response
