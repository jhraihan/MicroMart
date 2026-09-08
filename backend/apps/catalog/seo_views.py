"""
robots.txt and sitemap.xml.

Served by Django rather than dropped into the SPA's `public/` directory,
because both need to know what is actually in the catalogue: a static sitemap
goes stale the moment a product is added, and a stale sitemap is worse than
none -- it sends crawlers to 404s and teaches them to trust the file less.

Django ships a `sitemaps` framework, and it is deliberately not used here. It
builds URLs from `get_absolute_url()` on the model, but these URLs belong to
the **React router**, not to Django: a product lives at `/p/<slug>`, which no
Django view serves. Hard-coding the SPA's routes into model methods to satisfy
the framework would put frontend routing knowledge in the ORM layer. A plain
view that knows the three URL shapes is smaller and honest about where they
come from.
"""
from django.http import HttpResponse
from django.utils.http import http_date
from django.views.decorators.http import require_GET

from .services import catalogue

# The storefront's own routes, mirrored from frontend/src/routes/index.jsx.
# Changing a route there means changing it here -- there is no way around the
# duplication without the backend importing the frontend's router.
PRODUCT_PATH = "/p/{slug}"
CATEGORY_PATH = "/c/{slug}"

# Static routes worth indexing. Everything behind a login, plus /cart,
# /checkout, /compare and /search, is deliberately absent: those pages are
# either per-user or infinitely variable, and both are noindex client-side too.
STATIC_PATHS = [
    ("/", "daily", "1.0"),
    ("/offers", "daily", "0.9"),
    ("/brands", "weekly", "0.6"),
    ("/pc-builder", "weekly", "0.7"),
]

# A crawler fetching 117 product URLs is fine; one fetching every facet
# combination is not, which is what the Disallow lines below are for.
ROBOTS = """User-agent: *
Allow: /

# Per-customer or transactional. Nothing here is useful in an index, and
# crawling it wastes budget that should go to product pages.
Disallow: /cart
Disallow: /checkout
Disallow: /account
Disallow: /orders
Disallow: /order/
Disallow: /wishlist
Disallow: /compare
Disallow: /builds/
Disallow: /payments/

# Search results are effectively unlimited near-duplicate pages. Category
# pages carry the same products with stable, linkable URLs.
Disallow: /search

# Faceted listings multiply into combinatorially many URLs for the same
# products. The unfiltered category page is the canonical one.
Disallow: /*?brand=
Disallow: /*?min_price=
Disallow: /*?max_price=
Disallow: /*?sort=
Disallow: /*?page=

Sitemap: {base}/sitemap.xml
"""


def _base_url(request):
    """Absolute origin, taken from the request rather than a setting."""
    return f"{request.scheme}://{request.get_host()}"


def _url_entry(loc, changefreq, priority, lastmod=None):
    parts = [f"    <loc>{loc}</loc>"]
    if lastmod:
        parts.append(f"    <lastmod>{lastmod:%Y-%m-%d}</lastmod>")
    parts.append(f"    <changefreq>{changefreq}</changefreq>")
    parts.append(f"    <priority>{priority}</priority>")
    body = "\n".join(parts)
    return f"  <url>\n{body}\n  </url>"


@require_GET
def robots_txt(request):
    return HttpResponse(
        ROBOTS.replace("{base}", _base_url(request)),
        content_type="text/plain; charset=utf-8",
    )


@require_GET
def sitemap_xml(request):
    """
    Every indexable URL: static pages, active categories, listable products.

    `listable_products()` rather than every row -- a product with no sellable
    variant cannot be bought, and its detail page is not somewhere a crawler
    should be sent. Categories come from the same tree the nav renders, so the
    sitemap can never advertise a category the site does not show.
    """
    base = _base_url(request)
    entries = [_url_entry(f"{base}{path}", freq, priority) for path, freq, priority in STATIC_PATHS]

    for category in catalogue.category_tree():
        entries.append(
            _url_entry(
                base + CATEGORY_PATH.format(slug=category.slug), "weekly", "0.8"
            )
        )
        for child in category.children.all():
            if child.is_active:
                entries.append(
                    _url_entry(
                        base + CATEGORY_PATH.format(slug=child.slug), "weekly", "0.7"
                    )
                )

    products = (
        catalogue.listable_products()
        .only("slug", "updated_at")
        .order_by("-updated_at")
    )
    for product in products.iterator(chunk_size=500):
        entries.append(
            _url_entry(
                base + PRODUCT_PATH.format(slug=product.slug),
                "weekly",
                "0.9",
                lastmod=product.updated_at,
            )
        )

    body = "\n".join(entries)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )

    response = HttpResponse(xml, content_type="application/xml; charset=utf-8")
    # Crawlers re-fetch a sitemap often; an hour of caching costs nothing and
    # keeps a large catalogue from re-querying on every hit.
    response["Cache-Control"] = "public, max-age=3600"
    response["Last-Modified"] = http_date()
    return response
