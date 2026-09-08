from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from apps.catalog import seo_views
from apps.common import health

# Django Admin stays enabled as the operational safety net described in
# PRD §12.2 -- the React dashboard is the product, this is the fallback.
urlpatterns = [
    path("django-admin/", admin.site.urls),
    # Infrastructure, not API surface, so these sit at the root rather than
    # under /api/v1/ -- they are not versioned and nothing client-facing
    # consumes them.
    path("healthz/", health.liveness, name="liveness"),
    path("readyz/", health.readiness, name="readiness"),
    path("api/v1/", include("config.api_urls")),
    # Generated from the serializers and views themselves, so it cannot drift
    # from the code the way a hand-written contract does.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # Crawler-facing files. They sit at the domain root because that is the
    # only place a crawler looks for them, and they are served by Django
    # rather than shipped as static files so the sitemap reflects the
    # catalogue as it is now (see apps/catalog/seo_views.py).
    path("robots.txt", seo_views.robots_txt, name="robots"),
    path("sitemap.xml", seo_views.sitemap_xml, name="sitemap"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.MEDIA_STORAGE_BACKEND != "s3":
    # Product imagery lives on the app server's own disk, and the reverse
    # proxy in front of Gunicorn is a plain proxy that knows nothing about the
    # release layout -- so Django serves it. Django's static serve view is not
    # built for volume; set MEDIA_STORAGE_BACKEND=s3, or give the proxy an
    # alias for this path, if media traffic ever becomes real traffic.
    from django.urls import re_path
    from django.views.static import serve

    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})
    ]
