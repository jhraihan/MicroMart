"""Production settings. DEBUG is False here without exception (PRD §10.4)."""
import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, MIDDLEWARE, REFRESH_COOKIE_SAMESITE, env

DEBUG = False

# Render sets RENDER_EXTERNAL_HOSTNAME to the service's public host
# (micromart.onrender.com), so a fresh service needs no host configured by
# hand. A custom domain is added through DJANGO_ALLOWED_HOSTS as usual.
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "Set DJANGO_ALLOWED_HOSTS -- with DEBUG off, an empty list refuses every request."
    )

# Emails, sitemap and payment redirects link to the storefront. On Render the
# SPA is served by this same service, so its own public URL is the default.
FRONTEND_BASE_URL = env(
    "FRONTEND_BASE_URL",
    default=f"https://{RENDER_EXTERNAL_HOSTNAME}" if RENDER_EXTERNAL_HOSTNAME else "",
)

# Throttle counters must be shared across Gunicorn workers (see base.py). The
# database cache is shared by construction and needs no extra service; point
# CACHE_URL at Redis instead if the request rate ever makes that worth it.
# `manage.py createcachetable` creates the table -- scripts/start.sh runs it.
CACHES = {"default": env.cache("CACHE_URL", default="dbcache://django_cache")}

EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)

# Only Django's own static lives here -- the admin and the DRF browsable API.
# WhiteNoise serves it from inside the app process, so the reverse proxy needs
# no knowledge of the release layout.
#
# It must sit directly after SecurityMiddleware so a static hit returns before
# any session, auth or CORS work happens.
MIDDLEWARE = MIDDLEWARE.copy()
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# Image URLs are built as MEDIA_URL + filename, so a relative "/media/" makes
# the API emit "/media/products/x.png". A browser on the storefront's own
# domain resolves that against *itself*, not against this API, and every
# product image 404s -- which is invisible in development, where the Vite
# proxy makes the two origins one.
#
# Setting the API's public origin here fixes it for every endpoint at once,
# because they all serialize through the same helper.
MEDIA_URL = env("MEDIA_URL", default=MEDIA_URL)  # noqa: F405

# If the SPA is on a different domain than the API, every request is
# cross-site: the refresh cookie needs SameSite=None (which requires Secure),
# CORS must allow that exact origin with credentials, and CSRF must trust it.
#
# Safari and Firefox block third-party cookies by default, and a cross-site
# refresh cookie is one. Serving the SPA from a subdomain of this API's domain
# avoids the problem entirely.
if REFRESH_COOKIE_SAMESITE == "None" and not CORS_ALLOWED_ORIGINS:  # noqa: F405
    raise RuntimeError(
        "REFRESH_COOKIE_SAMESITE=None means the SPA is on another origin, but "
        "CORS_ALLOWED_ORIGINS is empty -- the browser would block every API "
        "call before the cookie ever mattered. Set it to the SPA's origin."
    )

SECURE_SSL_REDIRECT = True
# A platform health check may call the container over plain HTTP from inside
# the network; answering it with a redirect would read as a failure.
SECURE_REDIRECT_EXEMPT = [r"^healthz/$", r"^readyz/$"]
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if RENDER_EXTERNAL_HOSTNAME:
    # Django Admin's login form is the one CSRF-protected form in the app.
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")
X_FRAME_OPTIONS = "DENY"
REFRESH_COOKIE_SECURE = True

# ---------------------------------------------------------------------------
# The storefront, served by this process
# ---------------------------------------------------------------------------
# The PRD's architecture puts Nginx in front and serves the React build from
# there. On a platform without that proxy the SPA is served from here instead,
# which keeps the browser on one origin -- and that is not just convenience.
# A separate static site on *.onrender.com would be a different *site* from
# the API (onrender.com is on the Public Suffix List), so the Lax refresh
# cookie would never be sent and Safari/Firefox would block a SameSite=None
# one as third-party. One origin is the same arrangement the Vite dev proxy
# gives in development.
#
# The Dockerfile copies `npm run build` output here. Absent (a plain Gunicorn
# deployment behind Nginx), nothing below switches on.
FRONTEND_DIST_DIR = Path(env("FRONTEND_DIST_DIR", default=str(BASE_DIR / "frontend_dist")))
SERVE_SPA = (FRONTEND_DIST_DIR / "index.html").is_file()

if SERVE_SPA:
    # /assets/*, the favicon and anything else in the build are answered by
    # WhiteNoise at the site root before Django is reached. index.html itself
    # is not -- deep links such as /p/<slug> need it too, so a catch-all view
    # in config/urls.py serves it with no-cache.
    WHITENOISE_ROOT = FRONTEND_DIST_DIR

    _VITE_HASHED_ASSET = re.compile(r"^/assets/.+-[A-Za-z0-9_-]{8}\.[a-z0-9]+$")

    def WHITENOISE_IMMUTABLE_FILE_TEST(path, url):
        # Vite fingerprints every file under /assets/, so a changed file is a
        # new URL and the old one can be cached forever.
        return bool(_VITE_HASHED_ASSET.match(url))

if env("MEDIA_STORAGE_BACKEND", default="local") == "s3":
    # Only `default` (uploaded media) moves to S3. Static files stay with
    # WhiteNoise, which is already in the middleware chain above -- there is
    # nothing to gain from an S3 round trip for a hashed asset the image
    # already ships.
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="ap-south-1")
    AWS_QUERYSTRING_AUTH = False
    # S3-compatible stores other than AWS (Cloudflare R2, Backblaze B2) are
    # reached through their own endpoint. R2 wants region "auto".
    AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default=None)
    # The public host images are served from -- R2's pub-<id>.r2.dev address
    # or a custom domain. Without it, URLs point at the API endpoint, which
    # R2 does not serve publicly.
    AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN", default=None)
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
