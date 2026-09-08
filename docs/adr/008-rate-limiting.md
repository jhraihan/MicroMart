# 008 — Every endpoint is rate limited, and the counters are shared

**Status:** accepted

## Context

The project had `DEFAULT_THROTTLE_RATES` written out and tuned — 120 requests a
minute for anonymous callers, 300 for signed-in ones, 10 for the auth
endpoints. It also had a passing test proving the login limit worked.

None of it applied. Django REST Framework needs `DEFAULT_THROTTLE_CLASSES` to
decide *which* throttle to run; rates on their own are read by nothing. Only the
handful of views that named a scope explicitly were limited. Everything else —
the catalogue, search, the cart, the checkout quote, order placement, the whole
admin API — had no limit at all.

That is worse than having no configuration, because the settings file reads like
a working control and the passing test reinforces it.

## Decision

**1. Turn the defaults on.**

```python
"DEFAULT_THROTTLE_CLASSES": (
    "rest_framework.throttling.AnonRateThrottle",
    "rest_framework.throttling.UserRateThrottle",
),
```

**2. Give the endpoints that need their own budget a scope of their own.**

| Scope | Rate | Why |
|---|---|---|
| `refresh` | 60/min | Called on every page load. Sharing `auth` would mean ordinary browsing used up the budget that stops password guessing. |
| `checkout` | 30/min | The quote endpoint is the only public one that reveals whether a coupon code exists. Chattier than a page view, so it cannot use `anon`. |
| `place_order` | 10/min | Placement is public for guest checkout, so anyone can post to it. A shopper places one order. |
| `auth` | 10/min | Login, registration, password reset, email verification. |

**3. Use a shared cache.** Throttle counters live in Django's cache. The default
local-memory cache is per-process, so under Gunicorn with N workers a 10/min
limit quietly becomes 10×N/min — and the test still passes, because pytest runs
in one process. `CACHE_URL` therefore points at a shared backend in production.

**4. Do not flatten the coupon error codes.** `COUPON_EXPIRED` and
`COUPON_MIN_ORDER_NOT_MET` are genuinely useful to a shopper and the checkout
page branches on them. Making them vague would degrade a working feature to
mitigate an enumeration risk that a rate limit handles better.

## Consequences

- Every endpoint now has a ceiling.
- The suite makes hundreds of catalogue requests from one address, so
  `config/settings/dev.py` relaxes the rates for development and tests. This is
  the existing pattern for `auth`, extended to the rest. Production reads
  `base.py` and is untouched.
- Because the rates are relaxed in tests, `apps/common/tests/test_throttling.py`
  re-arms them with `monkeypatch` and proves the limits fire. Those tests fail
  against the old configuration, which is what makes them worth having.

## Where it lives

`config/settings/base.py` (classes, rates, cache), `config/settings/dev.py`
(relaxed rates), `apps/accounts/views.py` and `apps/orders/views.py` (scopes),
`apps/common/tests/test_throttling.py` (proof).
