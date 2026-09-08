"""
The SSLCommerz HTTP client (PRD 5.5, FR-PAY-2, FR-PAY-4).

Everything in this module is *transport*. It knows the gateway's two endpoints,
the shape of their payloads, and how to turn a network failure into a
DomainError -- and nothing at all about orders, stock or payment state. The
domain rules live next door in payments.py, so the one rule that must never
drift (what counts as proof of payment) is stated in exactly one place.

Two endpoints, one host that depends on SSLCOMMERZ_SANDBOX:

    session     POST {host}/gwprocess/v4/api.php
    validation  GET  {host}/validator/api/validationserverAPI.php

Sandbox and live are separate merchant accounts with separate credentials, so
pointing sandbox credentials at the live host fails at the gateway rather than
quietly charging anybody.

**The validation call is the only source of truth in the whole payment flow.**
The IPN body and the browser redirect are both attacker-reachable -- anyone can
POST whatever they like at /payments/ipn/ and anyone can open a callback URL by
hand. This GET, made from our server to theirs and authenticated with our store
password, is not. Nothing else in this codebase is permitted to conclude that
money arrived.

Every network call goes through `_request`, which is the single seam the test
suite replaces. No test in apps/payments/tests/ opens a socket.
"""
import logging

import requests
from django.conf import settings

from config.exceptions import DomainError

logger = logging.getLogger(__name__)

SANDBOX_HOST = "https://sandbox.sslcommerz.com"
LIVE_HOST = "https://securepay.sslcommerz.com"

SESSION_PATH = "/gwprocess/v4/api.php"
VALIDATION_PATH = "/validator/api/validationserverAPI.php"

# A customer is sitting in front of a spinner while the session call runs, and
# the IPN validation runs while the gateway waits for our 200. Neither is
# allowed to hang a worker indefinitely.
TIMEOUT_SECONDS = 20

SESSION_SUCCESS = "SUCCESS"

# The gateway's own vocabulary for "this transaction is real and settled".
# VALID comes back the first time a transaction is validated; VALIDATED on
# every subsequent validation of the same one -- which is exactly what a
# replayed IPN produces, so both must be accepted or FR-PAY-5 is unreachable.
VALIDATION_SUCCESS_STATUSES = frozenset({"VALID", "VALIDATED"})


def host():
    """Sandbox or live. There is no third option and no per-call override."""
    return SANDBOX_HOST if getattr(settings, "SSLCOMMERZ_SANDBOX", True) else LIVE_HOST


def is_configured():
    return bool(settings.SSLCOMMERZ_STORE_ID and settings.SSLCOMMERZ_STORE_PASSWORD)


def credentials():
    """
    (store_id, store_password), or a clean refusal.

    An unconfigured store is a deployment problem, not a customer problem, so
    it is 503 rather than 422 -- the shopper's basket is fine and Cash on
    Delivery still works.
    """
    if not is_configured():
        raise DomainError(
            "Online payment is not available right now. Please choose Cash on Delivery.",
            code="GATEWAY_NOT_CONFIGURED",
            field="payment_method",
            status_code=503,
        )
    return settings.SSLCOMMERZ_STORE_ID, settings.SSLCOMMERZ_STORE_PASSWORD


def _request(method, url, *, data=None, params=None):
    """
    The one place this application talks to SSLCommerz.

    Kept as a single function on purpose: it is the seam the tests replace, and
    a second call site that bypassed it would be a call site nobody could stub.
    """
    try:
        response = requests.request(
            method, url, data=data, params=params, timeout=TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # 502, not 500: the failure is upstream, and the distinction matters to
        # the gateway, which retries an IPN we could not answer.
        raise DomainError(
            "The payment gateway could not be reached. Please try again.",
            code="GATEWAY_UNREACHABLE",
            status_code=502,
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise DomainError(
            "The payment gateway returned an unreadable response.",
            code="GATEWAY_BAD_RESPONSE",
            status_code=502,
        ) from exc

    if not isinstance(payload, dict):
        raise DomainError(
            "The payment gateway returned an unreadable response.",
            code="GATEWAY_BAD_RESPONSE",
            status_code=502,
        )
    return payload


def create_session(payload):
    """
    Open a hosted-checkout session (FR-PAY-2). Returns the gateway's own dict,
    which carries `GatewayPageURL` and `sessionkey`.

    The caller builds the order-shaped half of the payload; credentials are
    added here so a store password can never be assembled by domain code and
    can never be logged by it either.
    """
    store_id, store_passwd = credentials()
    body = dict(payload)
    body["store_id"] = store_id
    body["store_passwd"] = store_passwd

    response = _request("POST", host() + SESSION_PATH, data=body)

    if str(response.get("status") or "").upper() != SESSION_SUCCESS:
        # `failedreason` is the gateway's own wording -- usually a rejected
        # field, occasionally a suspended store. It is safe to surface.
        raise DomainError(
            response.get("failedreason")
            or "The payment gateway refused to open a checkout session.",
            code="GATEWAY_SESSION_FAILED",
            field="payment_method",
            status_code=502,
        )

    if not response.get("GatewayPageURL"):
        raise DomainError(
            "The payment gateway did not return a checkout URL.",
            code="GATEWAY_SESSION_FAILED",
            field="payment_method",
            status_code=502,
        )
    return response


def validate_transaction(val_id):
    """
    Ask SSLCommerz what really happened to `val_id` (FR-PAY-4).

    This is a *fresh* request to the gateway, not a re-reading of anything the
    caller was handed. That is the entire security property: the only thing
    taken from the untrusted notification is the val_id, and the only thing
    that decides the outcome is what comes back from here.
    """
    store_id, store_passwd = credentials()
    val_id = str(val_id or "").strip()
    if not val_id:
        raise DomainError(
            "A payment notification without a val_id cannot be validated.",
            code="MISSING_VAL_ID",
            field="val_id",
            status_code=400,
        )

    return _request(
        "GET",
        host() + VALIDATION_PATH,
        params={
            "val_id": val_id,
            "store_id": store_id,
            "store_passwd": store_passwd,
            "v": 1,
            "format": "json",
        },
    )
