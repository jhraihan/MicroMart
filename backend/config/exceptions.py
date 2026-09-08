"""
A single error envelope for the whole API (PRD §7.1):

    {"error": {"code": "COUPON_EXPIRED", "message": "...", "field": "coupon_code"}}

Codes are stable and safe to branch on in the client; messages are not.
"""
import logging

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("micromart.api")


class DomainError(Exception):
    """
    Raised by service functions when a business rule is violated.

    Services raise this instead of a DRF exception so the same function can be
    called from a view, a management command, or a test without dragging HTTP
    concepts into the domain layer.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "DOMAIN_ERROR"

    def __init__(self, message, code=None, field=None, status_code=None):
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.field = field
        if status_code is not None:
            self.status_code = status_code


def _envelope(code, message, field=None):
    payload = {"code": code, "message": message}
    if field:
        payload["field"] = field
    return {"error": payload}


# Keys DRF uses for errors that belong to the request as a whole. They are not
# form fields, so they must not be reported as one -- a client that trusted
# them would try to attach the message to an input that does not exist.
_NON_FIELD_KEYS = {"non_field_errors", "detail"}


def _flatten_drf_detail(detail):
    """Reduce a DRF error body to a single (message, field) pair."""
    if isinstance(detail, dict):
        for field, value in detail.items():
            message, _ = _flatten_drf_detail(value)
            return message, (None if field in _NON_FIELD_KEYS else field)
    if isinstance(detail, list) and detail:
        return _flatten_drf_detail(detail[0])[0], None
    return str(detail), None


def api_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response(
            _envelope(exc.code, exc.message, exc.field), status=exc.status_code
        )

    # Object-level authorisation returns 404, never 403 -- a 403 confirms the
    # record exists and leaks the ID space (PRD §10.2).
    if isinstance(exc, (Http404, PermissionDenied)):
        return Response(
            _envelope("NOT_FOUND", "Not found."), status=status.HTTP_404_NOT_FOUND
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        # Nothing above matched and DRF could not turn this into an HTTP
        # error, so it is a genuine 500. This is the only branch that logs:
        # 404s and DomainErrors are ordinary traffic here, and logging those
        # would bury the real failures.
        request = context.get("request")
        view = context.get("view")
        logger.exception(
            "Unhandled exception in %s %s (view=%s)",
            getattr(request, "method", "?"),
            getattr(request, "path", "?"),
            view.__class__.__name__ if view is not None else "?",
        )
        return None

    message, field = _flatten_drf_detail(response.data)
    code = getattr(exc, "default_code", "ERROR")
    if isinstance(response.data, dict):
        detail = response.data.get("detail")
        code = getattr(detail, "code", code)
    response.data = _envelope(str(code).upper(), message, field)
    return response
