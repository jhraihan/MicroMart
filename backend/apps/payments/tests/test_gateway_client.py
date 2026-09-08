"""
The SSLCommerz transport layer (apps/payments/services/sslcommerz.py).

Nothing here touches the database and nothing opens a socket: `_request` is the
module's single network seam and it is replaced wholesale. What is under test
is the small set of decisions the client makes on its own -- which host, what
gets sent with a request, and which gateway answers count as failures.

The credential assertions matter more than they look. The store password is
added by this module and never by the domain layer, which is what keeps it out
of session payloads assembled elsewhere and out of anything those payloads are
logged into.
"""
import pytest
import requests

from apps.payments.services import sslcommerz
from config.exceptions import DomainError


@pytest.fixture
def configured(settings):
    settings.SSLCOMMERZ_STORE_ID = "micromart_test"
    settings.SSLCOMMERZ_STORE_PASSWORD = "micromart_test@ssl"
    settings.SSLCOMMERZ_SANDBOX = True
    return settings


@pytest.fixture
def transport(monkeypatch):
    """Record every request and answer with whatever the test staged."""

    calls = []
    staged = {"response": {"status": "SUCCESS"}, "error": None}

    def _request(method, url, *, data=None, params=None):
        calls.append({"method": method, "url": url, "data": data, "params": params})
        if staged["error"] is not None:
            raise staged["error"]
        return dict(staged["response"])

    monkeypatch.setattr(sslcommerz, "_request", _request)
    return {"calls": calls, "staged": staged}


# ---------------------------------------------------------------------------
# Hosts and credentials
# ---------------------------------------------------------------------------
def test_the_sandbox_flag_picks_the_sandbox_host(configured):
    configured.SSLCOMMERZ_SANDBOX = True
    assert sslcommerz.host() == "https://sandbox.sslcommerz.com"


def test_turning_the_sandbox_flag_off_picks_the_live_host(configured):
    configured.SSLCOMMERZ_SANDBOX = False
    assert sslcommerz.host() == "https://securepay.sslcommerz.com"


def test_a_store_with_no_credentials_is_refused_before_any_request_is_made(
    settings, transport
):
    settings.SSLCOMMERZ_STORE_ID = ""
    settings.SSLCOMMERZ_STORE_PASSWORD = ""

    with pytest.raises(DomainError) as exc:
        sslcommerz.create_session({"tran_id": "ORD-2026-000001"})

    assert exc.value.code == "GATEWAY_NOT_CONFIGURED"
    assert exc.value.status_code == 503
    assert transport["calls"] == []


def test_the_client_adds_the_store_credentials_so_the_domain_layer_never_holds_them(
    configured, transport
):
    transport["staged"]["response"] = {
        "status": "SUCCESS",
        "sessionkey": "K",
        "GatewayPageURL": "https://sandbox.sslcommerz.com/x",
    }

    sslcommerz.create_session({"tran_id": "ORD-2026-000001", "total_amount": "10.00"})

    sent = transport["calls"][0]
    assert sent["method"] == "POST"
    assert sent["url"] == "https://sandbox.sslcommerz.com/gwprocess/v4/api.php"
    assert sent["data"]["store_id"] == "micromart_test"
    assert sent["data"]["store_passwd"] == "micromart_test@ssl"
    assert sent["data"]["tran_id"] == "ORD-2026-000001"


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------
def test_a_session_the_gateway_refuses_raises_with_the_gateways_own_reason(
    configured, transport
):
    transport["staged"]["response"] = {
        "status": "FAILED",
        "failedreason": "Store Credential Error",
    }

    with pytest.raises(DomainError) as exc:
        sslcommerz.create_session({"tran_id": "ORD-2026-000001"})

    assert exc.value.code == "GATEWAY_SESSION_FAILED"
    assert exc.value.status_code == 502


def test_a_success_with_no_checkout_url_is_still_a_failure(configured, transport):
    transport["staged"]["response"] = {"status": "SUCCESS", "sessionkey": "K"}

    with pytest.raises(DomainError) as exc:
        sslcommerz.create_session({"tran_id": "ORD-2026-000001"})

    assert exc.value.code == "GATEWAY_SESSION_FAILED"


def test_an_unreachable_gateway_is_reported_as_a_bad_gateway_not_a_crash(
    configured, monkeypatch
):
    def _boom(*args, **kwargs):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "request", _boom)

    with pytest.raises(DomainError) as exc:
        sslcommerz.create_session({"tran_id": "ORD-2026-000001"})

    assert exc.value.code == "GATEWAY_UNREACHABLE"
    assert exc.value.status_code == 502


def test_a_gateway_response_that_is_not_json_is_reported_rather_than_parsed(
    configured, monkeypatch
):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(requests, "request", lambda *a, **k: _Response())

    with pytest.raises(DomainError) as exc:
        sslcommerz.create_session({"tran_id": "ORD-2026-000001"})

    assert exc.value.code == "GATEWAY_BAD_RESPONSE"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_validation_is_a_get_to_the_validation_endpoint_carrying_the_val_id(
    configured, transport
):
    transport["staged"]["response"] = {"status": "VALID"}

    sslcommerz.validate_transaction("VAL-123")

    sent = transport["calls"][0]
    assert sent["method"] == "GET"
    assert sent["url"] == (
        "https://sandbox.sslcommerz.com/validator/api/validationserverAPI.php"
    )
    assert sent["params"]["val_id"] == "VAL-123"
    assert sent["params"]["store_id"] == "micromart_test"
    assert sent["params"]["store_passwd"] == "micromart_test@ssl"
    assert sent["params"]["format"] == "json"


def test_validating_an_empty_val_id_is_refused_without_a_request(configured, transport):
    with pytest.raises(DomainError) as exc:
        sslcommerz.validate_transaction("   ")

    assert exc.value.code == "MISSING_VAL_ID"
    assert transport["calls"] == []


def test_both_valid_and_validated_count_as_success_and_nothing_else_does():
    """
    VALID is the first validation of a transaction; VALIDATED is every one
    after it -- which is exactly what a replayed IPN produces, so excluding it
    would make FR-PAY-5's replay path unreachable.
    """
    assert "VALID" in sslcommerz.VALIDATION_SUCCESS_STATUSES
    assert "VALIDATED" in sslcommerz.VALIDATION_SUCCESS_STATUSES
    for rejected in ("FAILED", "PENDING", "INVALID_TRANSACTION", "UNATTEMPTED", ""):
        assert rejected not in sslcommerz.VALIDATION_SUCCESS_STATUSES
