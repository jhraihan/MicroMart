"""
The React storefront's entry point, for deployments where Django serves it.

Only wired up when settings.SERVE_SPA is on (config/settings/prod.py). The
built assets are answered by WhiteNoise before a request gets this far; what
reaches here is every client-side route -- /, /p/<slug>, /admin/orders -- and
each of them gets the same index.html, from which React Router takes over.
"""
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.http import require_safe

# Every path except the server's own. The API, Django Admin, media, static and
# health checks keep their real 404s -- an unknown API URL answered with the
# storefront's HTML would hand a JSON client a 200 it cannot parse.
ROUTE = r"^(?!api/|django-admin/|media/|static/|healthz/|readyz/).*$"


@require_safe
def index(request):
    html = (settings.FRONTEND_DIST_DIR / "index.html").read_bytes()
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    # index.html names the fingerprinted bundles, so a stale copy would load
    # last release's JavaScript. It must be revalidated on every visit; the
    # bundles themselves are cached forever.
    response["Cache-Control"] = "no-cache"
    return response
