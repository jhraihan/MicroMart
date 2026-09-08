"""Local development settings."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# Emails print to the console until an SMTP provider is chosen (PRD §14 Q9).
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)

REFRESH_COOKIE_SECURE = False

# ---------------------------------------------------------------------------
# Throttling in development and tests
# ---------------------------------------------------------------------------
# The real limits are in base.py. They are unusable for an automated run from
# one machine -- the test suite makes hundreds of catalogue requests from a
# single address, and every one would 429.
#
# Each rate stays overridable, so the genuine control can be exercised here:
#
#     ANON_THROTTLE_RATE=120/min .venv/Scripts/python.exe manage.py runserver
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],  # noqa: F405
    "anon": env("ANON_THROTTLE_RATE", default="20000/min"),
    "user": env("USER_THROTTLE_RATE", default="20000/min"),
    "auth": env("AUTH_THROTTLE_RATE", default="2000/min"),
    "refresh": env("REFRESH_THROTTLE_RATE", default="2000/min"),
    "checkout": env("CHECKOUT_THROTTLE_RATE", default="2000/min"),
    "place_order": env("PLACE_ORDER_THROTTLE_RATE", default="2000/min"),
    "order_lookup": env("ORDER_LOOKUP_THROTTLE_RATE", default="2000/min"),
}
