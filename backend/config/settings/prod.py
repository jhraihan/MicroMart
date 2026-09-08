"""Production settings. DEBUG is False here without exception (PRD §10.4)."""
from .base import *  # noqa: F401,F403
from .base import MIDDLEWARE, REFRESH_COOKIE_SAMESITE, env

DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

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
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
X_FRAME_OPTIONS = "DENY"
REFRESH_COOKIE_SECURE = True

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
