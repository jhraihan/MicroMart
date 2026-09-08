"""
Proof that the default throttles are switched on.

Until 2026-09-07 `DEFAULT_THROTTLE_RATES` was configured but
`DEFAULT_THROTTLE_CLASSES` was not, so DRF applied no throttle at all to any
view that did not name a scope of its own. The settings *looked* like a rate
limit and were read by nothing: the catalogue, search, the checkout quote and
order placement were all unlimited.

These tests fail against that old configuration and pass now. They re-arm the
real rates with monkeypatch because config/settings/dev.py relaxes them for the
suite -- without that relaxation a few hundred catalogue reads from one address
would fail unrelated tests with a 429.
"""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    """
    Throttle counters live in the cache and are keyed by client address, so
    one test's requests would otherwise count against the next.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_anonymous_catalogue_requests_are_rate_limited(api, monkeypatch):
    """
    The product list names no scope of its own, so it is covered by the `anon`
    default -- exactly the case that used to be unprotected.
    """
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "5/min")

    for _ in range(5):
        assert api.get("/api/v1/products/").status_code == 200

    assert api.get("/api/v1/products/").status_code == 429


@pytest.mark.django_db
def test_the_checkout_quote_has_its_own_budget(api, monkeypatch):
    """
    The quote endpoint reports whether a coupon code exists, so it is limited
    separately from ordinary browsing: tight enough that walking the code space
    is impractical, loose enough that editing a basket never trips it.
    """
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "checkout", "3/min")
    payload = {"items": [], "coupon_code": "GUESS"}

    for _ in range(3):
        response = api.post("/api/v1/checkout/quote/", payload, format="json")
        assert response.status_code != 429

    assert api.post("/api/v1/checkout/quote/", payload, format="json").status_code == 429


@pytest.mark.django_db
def test_refresh_does_not_draw_on_the_login_budget(api, monkeypatch):
    """
    The SPA refreshes on every page load. If that drew from the `auth` scope,
    ordinary browsing would use up the budget that stops password guessing.
    """
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth", "1/min")
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "refresh", "10/min")

    # No cookie, so each call is a 401. The point is which counter it lands on.
    for _ in range(5):
        assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code != 429


@pytest.mark.django_db
def test_order_placement_is_capped(api, monkeypatch):
    """
    Placement is public so guests can check out, which also means anyone can
    post to it. One shopper places one order.
    """
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "place_order", "2/min")
    payload = {"items": []}

    for _ in range(2):
        assert api.post("/api/v1/orders/", payload, format="json").status_code != 429

    assert api.post("/api/v1/orders/", payload, format="json").status_code == 429
