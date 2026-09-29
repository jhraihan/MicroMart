"""
Base settings shared by every environment.

Environment-specific overrides live in dev.py / prod.py. Every secret is read
from the environment (PRD §15.3) -- nothing sensitive is ever committed.
"""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.catalog",
    "apps.cart",
    "apps.orders",
    "apps.payments",
    "apps.promotions",
    "apps.reviews",
    "apps.shipping",
    "apps.dashboard",
    "apps.builds",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database -- MySQL 8, InnoDB, utf8mb4 (PRD §6.5)
# --------------------------------------------------------------------------
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"].setdefault("OPTIONS", {})
DATABASES["default"]["OPTIONS"].update(
    {
        "charset": "utf8mb4",
        # STRICT_TRANS_TABLES turns silent truncation into an error -- essential
        # when money columns are DECIMAL(12,2).
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    }
)
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

# Managed MySQL providers accept only TLS connections. DB_SSL_CA is the path to
# the provider's CA certificate -- on Render, upload it as a Secret File and it
# is mounted under /etc/secrets/. Unset, the connection is plain, which is
# right for a database on the same host or private network.
DB_SSL_CA = env("DB_SSL_CA", default="")
if DB_SSL_CA:
    DATABASES["default"]["OPTIONS"]["ssl"] = {"ca": DB_SSL_CA}

# Providers hand out URLs ending in ?ssl-mode=REQUIRED. django-environ passes
# that through as an OPTIONS key, and mysqlclient rejects "ssl-mode" as an
# unknown argument -- so the URL exactly as copied would never connect. TLS is
# governed by DB_SSL_CA above; the parameter only tells us it is expected.
_ssl_mode = str(DATABASES["default"]["OPTIONS"].pop("ssl-mode", "")).upper()
if _ssl_mode and _ssl_mode != "DISABLED" and not DB_SSL_CA:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        f"DATABASE_URL asks for ssl-mode={_ssl_mode}, but DB_SSL_CA is not set. "
        "Download the provider's CA certificate and point DB_SSL_CA at it."
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# Cache
#
# Throttle counters live here. The default local-memory cache is per-process,
# so under Gunicorn with N workers every rate below would quietly become N
# times itself, and the login test would still pass because pytest runs in one
# process. A shared backend is what makes the numbers real.
#
# Set CACHE_URL to something shared (redis://127.0.0.1:6379/1) in production.
# --------------------------------------------------------------------------
CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://")}

# --------------------------------------------------------------------------
# DRF + JWT (PRD §7.1, §10.1)
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": "config.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "COERCE_DECIMAL_TO_STRING": True,  # money as decimal strings, never floats
    # Without these classes the rates below are read by nothing. They were
    # configured but inert until 2026-09-07, so every endpoint that did not
    # name a scope of its own was unlimited.
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("ANON_THROTTLE_RATE", default="120/min"),
        "user": env("USER_THROTTLE_RATE", default="300/min"),
        "auth": env("AUTH_THROTTLE_RATE", default="10/min"),
        # The unauthenticated guest order read,
        # GET /orders/{reference}/?email=. Generous for the one or two
        # refreshes a shopper makes on the confirmation screen, mean enough
        # that walking the reference space from one address is pointless.
        "order_lookup": "20/min",
        # Called on every page load, so it cannot share the `auth` budget with
        # login -- normal browsing would exhaust it. It is unauthenticated and
        # writes a row per call (the rotated token is blacklisted), so it still
        # needs a ceiling of its own.
        "refresh": "60/min",
        # The checkout quote is the only public endpoint that will say whether
        # a coupon code exists. Loose enough for a shopper editing their
        # basket, tight enough that walking the code space is impractical.
        "checkout": "30/min",
        # A shopper places one order. Anything placing them in bulk is not a
        # shopper.
        "place_order": "10/min",
    },
}

# --------------------------------------------------------------------------
# API documentation -- browsable schema at /api/docs/
# --------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "MicroMart API",
    "DESCRIPTION": (
        "Storefront and admin API for MicroMart, a single-vendor electronics "
        "shop in Bangladesh. "
        "Money is returned as decimal strings, never floats. Errors all use "
        "one envelope with a stable `code`, a human `message` and an optional "
        "`field`; branch on the code, not the message. "
        "Anything under /admin/ needs a staff or admin account."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# The refresh token travels in an HttpOnly cookie; the access token stays in
# browser memory only. Neither ever touches localStorage (PRD §10.1).
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth/"

# Lax is right whenever the SPA and the API share a registrable domain, which
# is the case in development (Vite proxies /api, so the browser is
# same-origin) and in the PRD's single-host architecture (§8).
#
# It is configurable because a deployment that puts the SPA and the API on
# *different* registrable domains makes every API call cross-site, and a Lax
# cookie is not sent cross-site -- the refresh endpoint would simply never
# receive the token, and users would appear to be logged out at random. Such a
# deployment must set this to "None", which browsers only honour on a Secure
# cookie; prod.py refuses to start if that pairing is broken.
REFRESH_COOKIE_SAMESITE = env("REFRESH_COOKIE_SAMESITE", default="Lax")
REFRESH_COOKIE_SECURE = env.bool("REFRESH_COOKIE_SECURE", default=not DEBUG)

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

# --------------------------------------------------------------------------
# I18N / TZ -- English UI only in v1, BDT throughout
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

CURRENCY_CODE = "BDT"
CURRENCY_SYMBOL = "৳"

# --------------------------------------------------------------------------
# Static & media
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

MEDIA_STORAGE_BACKEND = env("MEDIA_STORAGE_BACKEND", default="local")

# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@localhost")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
# Unset, smtplib inherits the OS socket default, which can hold a worker for
# minutes on an unreachable relay. A password reset that takes ten seconds has
# already failed as far as the customer is concerned.
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)

# --------------------------------------------------------------------------
# Storefront / gateway
# --------------------------------------------------------------------------
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:5173")

SSLCOMMERZ_STORE_ID = env("SSLCOMMERZ_STORE_ID", default="")
SSLCOMMERZ_STORE_PASSWORD = env("SSLCOMMERZ_STORE_PASSWORD", default="")
SSLCOMMERZ_SANDBOX = env.bool("SSLCOMMERZ_SANDBOX", default=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
