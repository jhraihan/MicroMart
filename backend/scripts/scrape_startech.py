"""
Scrape a development catalogue (categories, products, images) from
startech.com.bd into a JSON file plus a local image folder, ready to be loaded
by `manage.py import_startech`.

This is a *development seeding* tool. It collects factual catalogue data --
the category tree, product name, brand, price, stock status, specification
key/values and product photos -- so the storefront can be exercised against a
realistic BDT catalogue instead of a handful of fixtures. Product descriptions
are composed from the factual key-feature bullets rather than copied from the
source site's marketing copy. Do not ship this output as production content.

    python scripts/scrape_startech.py --per-category 12
    python scripts/scrape_startech.py --per-category 24 --workers 8

Output:
    scripts/data/startech_catalog.json
    scripts/data/images/<product-slug>/<n>.webp
"""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

BASE = "https://www.startech.com.bd/"
BRANDS_URL = urljoin(BASE, "index.php?route=product/manufacturer")
DATA_DIR = Path(__file__).resolve().parent / "data"
IMAGE_DIR = DATA_DIR / "images"
OUT_FILE = DATA_DIR / "startech_catalog.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Nav entries that are campaigns, tools or informational pages rather than
# catalogue categories.
SKIP_SLUGS = {"special-pc", "offers", "campaign", "used-product", "pc_builder"}
SKIP_PATH_PREFIXES = ("tool/", "information/", "index.php", "blog")
ALLOWED_HOSTS = ("www.startech.com.bd", "startech.com.bd")

_print_lock = threading.Lock()


def log(*parts):
    with _print_lock:
        print(*parts, flush=True)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Fetcher:
    """Session-backed GET with retries and a politeness delay per request."""

    def __init__(self, delay: float = 0.25, retries: int = 3):
        self.delay = delay
        self.retries = retries
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(HEADERS)
            self._local.session = session
        return session

    def get(self, url: str, *, binary: bool = False):
        last_error = None
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, timeout=30)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                time.sleep(self.delay)
                return response.content if binary else response.text
            except requests.RequestException as exc:  # transient network / 5xx
                last_error = exc
                time.sleep(self.delay * (attempt + 2))
        log(f"  ! giving up on {url}: {last_error}")
        return None


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def text_of(fragment: str) -> str:
    """Strip tags and collapse whitespace, turning <br> into a space."""
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub("", fragment))).strip()


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1] if path else ""


def parse_money(raw: str):
    """'3,750' -> '3750.00'. None when the string holds no number."""
    digits = re.sub(r"[^\d.]", "", raw.replace(",", ""))
    if not digits:
        return None
    try:
        return f"{float(digits):.2f}"
    except ValueError:
        return None


def is_catalogue_url(url: str) -> bool:
    parts = urlparse(url)
    if parts.netloc not in ALLOWED_HOSTS:
        return False
    path = parts.path.strip("/")
    if not path or path.startswith(SKIP_PATH_PREFIXES):
        return False
    return slug_from_url(url) not in SKIP_SLUGS


# ---------------------------------------------------------------------------
# Navigation -> category tree
# ---------------------------------------------------------------------------
# Three token kinds: a <ul> opening, a </ul> closing, and a nav anchor. Depth is
# just the running <ul> balance, so the parser does not care how many dropdown
# levels the source theme uses.
NAV_TOKEN_RE = re.compile(
    r'(?P<open><ul\b[^>]*>)'
    r'|(?P<close></ul>)'
    r'|<li class="nav-item[^"]*">\s*<a class="nav-link" href="(?P<href>[^"]+)"[^>]*>(?P<label>.*?)</a>',
    re.S,
)


BRAND_LINK_RE = re.compile(
    r'<div class="col-sm-3">\s*<a href="(?P<href>[^"]+)"[^>]*>(?P<name>[^<]+)</a>\s*</div>'
)


def parse_brands(manufacturer_html: str):
    """The site's A-Z manufacturer index -> [{name, slug}]."""
    brands, seen = [], set()
    for match in BRAND_LINK_RE.finditer(manufacturer_html):
        url = urljoin(BASE, html.unescape(match.group("href")))
        name = text_of(match.group("name"))
        slug = slug_from_url(url)
        if not name or not slug or slug in seen:
            continue
        seen.add(slug)
        brands.append({"name": name, "slug": slug, "url": url})
    return brands


def parse_nav(home_html: str, brand_names: set[str] | None = None):
    """
    Flatten the source site's three-level nav into the two levels the Category
    model allows: a top-level entry becomes a root category, a first-level
    dropdown entry becomes its child, and third-level entries are folded away --
    their listing URLs are kept as extra product sources for the child they sat
    under.

    Many first-level entries are brand filters rather than categories ("Monitor
    > MSI"). Those are folded into their parent too: the brand is already a
    first-class field on the product, so it has no business in the taxonomy.

    Returns [{name, slug, url, parent_slug, sort_order, extra_urls}].
    """
    brand_names = brand_names or set()
    start = home_html.find('<ul class="navbar-nav">')
    end = home_html.find("</nav>", start)
    if start == -1 or end == -1:
        raise SystemExit("navbar not found -- the source markup changed")
    nav = home_html[start:end]

    categories: dict[str, dict] = {}
    trail: list[str] = []  # slug most recently seen at each depth
    depth = -1  # incremented to 0 by the opening <ul class="navbar-nav">
    order = 0

    for token in NAV_TOKEN_RE.finditer(nav):
        if token.group("open"):
            depth += 1
            continue
        if token.group("close"):
            depth -= 1
            continue

        url = urljoin(BASE, html.unescape(token.group("href")))
        label = text_of(token.group("label"))
        slug = slug_from_url(url)
        if not label or not slug or not is_catalogue_url(url):
            continue

        del trail[depth:]
        trail.append(slug)

        is_brand_filter = depth >= 1 and (
            label.lower() in brand_names or slug in brand_names
        )
        if depth >= 2 or is_brand_filter:
            # Grandchild or brand filter: no category of its own, but its
            # listing still feeds products into the nearest real category.
            parent = next(
                (s for s in reversed(trail[:depth]) if s in categories), None
            )
            if parent:
                categories[parent]["extra_urls"].append(url)
            continue

        if slug in categories:
            continue
        order += 1
        categories[slug] = {
            "name": label,
            "slug": slug,
            "url": url,
            "parent_slug": trail[depth - 1] if depth == 1 else None,
            "sort_order": order,
            "extra_urls": [],
        }

    # A child whose parent was filtered out is promoted to a root.
    for entry in categories.values():
        if entry["parent_slug"] and entry["parent_slug"] not in categories:
            entry["parent_slug"] = None
    return list(categories.values())


# ---------------------------------------------------------------------------
# Category listing -> product URLs
# ---------------------------------------------------------------------------
CARD_RE = re.compile(
    r'<h4 class="p-item-name">\s*<a href="(?P<href>[^"]+)"[^>]*>(?P<name>.*?)</a>', re.S
)


def parse_listing(listing_html: str):
    urls, seen = [], set()
    for match in CARD_RE.finditer(listing_html):
        url = urljoin(BASE, html.unescape(match.group("href")))
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# Product detail
# ---------------------------------------------------------------------------
NAME_RE = re.compile(r'<h1 itemprop="name" class="product-name">(.*?)</h1>', re.S)
INFO_CELL_RE = re.compile(r'<td class="product-info-data ([a-z-]+)"[^>]*>(.*?)</td>', re.S)
PRICE_META_RE = re.compile(r'<meta itemprop="price" content="([\d.]+)"')
MAIN_IMG_RE = re.compile(r'<div class="product-img-holder">\s*<a class="thumbnail" href="([^"]+)"', re.S)
THUMB_LIST_RE = re.compile(r'<ul class="thumbnails">(.*?)</ul>', re.S)
THUMB_HREF_RE = re.compile(r'<a class="thumbnail" href="([^"]+)"')
FEATURE_BLOCK_RE = re.compile(r'<div class="short-description".*?<ul>(.*?)</ul>', re.S)
FEATURE_LI_RE = re.compile(r"<li(?![^>]*view-more)[^>]*>(.*?)</li>", re.S)
SPEC_SECTION_RE = re.compile(
    r'<section class="specification-tab[^"]*" id="specification">(.*?)</section>', re.S
)
SPEC_ROW_RE = re.compile(r'<td\s+class="name">(.*?)</td>\s*<td class="value">(.*?)</td>', re.S)
BREADCRUMB_RE = re.compile(
    r'<li\s+itemprop="itemListElement".*?href="([^"]+)"><span itemprop="name">(.*?)</span>', re.S
)


def _warranty_months(value: str):
    value = value.lower()
    if "lifetime" in value:
        return 120
    years = re.search(r"(\d+(?:\.\d+)?)\s*year", value)
    if years:
        return int(round(float(years.group(1)) * 12))
    months = re.search(r"(\d+)\s*month", value)
    if months:
        return int(months.group(1))
    days = re.search(r"(\d+)\s*day", value)
    if days:
        return max(1, int(days.group(1)) // 30)
    return None


def _weight_grams(value: str):
    value = value.lower().replace(",", "")
    kilos = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|kilogram)", value)
    if kilos:
        return int(round(float(kilos.group(1)) * 1000))
    grams = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gram|gm)\b", value)
    if grams:
        return int(round(float(grams.group(1))))
    return None


def _prices(info: dict, page: str):
    """(price, compare_at). compare_at is dropped unless it beats the price."""
    price = compare_at = None
    numbers = re.findall(r"[\d,]+(?=৳)", info.get("product-price", ""))
    if numbers:
        price = parse_money(numbers[0])
        if len(numbers) > 1:
            compare_at = parse_money(numbers[1])
    if price is None:
        meta = PRICE_META_RE.search(page)
        price = parse_money(meta.group(1)) if meta else None
    if price is None:
        return None, None

    regular = parse_money(info.get("product-regular-price", ""))
    for candidate in (compare_at, regular):
        if candidate and float(candidate) > float(price):
            return price, candidate
    return price, None


def parse_product(page: str, url: str, max_images: int = 3):
    name_match = NAME_RE.search(page)
    if not name_match:
        return None

    info = {key: text_of(value) for key, value in INFO_CELL_RE.findall(page)}
    price, compare_at = _prices(info, page)

    images = []
    main = MAIN_IMG_RE.search(page)
    if main:
        images.append(urljoin(BASE, html.unescape(main.group(1))))
    thumbs = THUMB_LIST_RE.search(page)
    if thumbs:
        images.extend(
            urljoin(BASE, html.unescape(href)) for href in THUMB_HREF_RE.findall(thumbs.group(1))
        )
    images = [i for i in dict.fromkeys(images) if "/image/cache/catalog/" in i]

    features = []
    feature_block = FEATURE_BLOCK_RE.search(page)
    if feature_block:
        for item in FEATURE_LI_RE.findall(feature_block.group(1)):
            cleaned = text_of(item)
            if cleaned and cleaned.lower() != "view more info":
                features.append(cleaned)

    specs = []
    spec_section = SPEC_SECTION_RE.search(page)
    if spec_section:
        for key, value in SPEC_ROW_RE.findall(spec_section.group(1)):
            key_text, value_text = text_of(key), text_of(value)
            if key_text and value_text:
                specs.append({"key": key_text[:120], "value": value_text[:500]})

    warranty_months = weight_grams = None
    for spec in specs:
        lowered = spec["key"].lower()
        if warranty_months is None and "warranty" in lowered:
            warranty_months = _warranty_months(spec["value"])
        if weight_grams is None and "weight" in lowered:
            weight_grams = _weight_grams(spec["value"])

    breadcrumbs = [
        {"slug": slug_from_url(urljoin(BASE, html.unescape(href))), "name": text_of(label)}
        for href, label in BREADCRUMB_RE.findall(page)
    ]

    return {
        "name": text_of(name_match.group(1)),
        "slug": slug_from_url(url),
        "source_url": url,
        "code": info.get("product-code", ""),
        "brand": info.get("product-brand", ""),
        "price": price,
        "compare_at_price": compare_at,
        "status": info.get("product-status", ""),
        "features": features[:12],
        "specs": specs[:60],
        "warranty_months": warranty_months,
        "weight_grams": weight_grams,
        "image_urls": images[:max_images],
        "breadcrumbs": breadcrumbs[:-1],  # the last crumb is the product itself
        "images": [],
    }


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
def download_images(fetcher: Fetcher, product: dict):
    target = IMAGE_DIR / product["slug"]
    saved = []
    for index, url in enumerate(product["image_urls"]):
        suffix = Path(urlparse(url).path).suffix or ".webp"
        path = target / f"{index:02d}{suffix}"
        if path.exists() and path.stat().st_size > 0:
            saved.append(path.relative_to(DATA_DIR).as_posix())
            continue
        blob = fetcher.get(url, binary=True)
        if not blob:
            continue
        target.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        saved.append(path.relative_to(DATA_DIR).as_posix())
    product["images"] = saved
    return saved


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def scrape(per_category: int, delay: float, workers: int, limit, no_images: bool, max_images: int):
    fetcher = Fetcher(delay=delay)

    log("Fetching home page ...")
    home = fetcher.get(BASE)
    if not home:
        raise SystemExit("could not fetch the home page")

    log("Fetching brand index ...")
    brands = parse_brands(fetcher.get(BRANDS_URL) or "")
    brand_names = {b["name"].lower() for b in brands} | {b["slug"] for b in brands}
    log(f"Brands: {len(brands)}")

    categories = parse_nav(home, brand_names)
    roots = sum(1 for c in categories if not c["parent_slug"])
    log(f"Nav parsed: {len(categories)} categories ({roots} root, {len(categories) - roots} child)")

    # Home page module products keep category_slug None; the breadcrumb pass
    # below assigns them.
    product_urls: dict[str, str | None] = {url: None for url in parse_listing(home)}
    log(f"Home page modules: {len(product_urls)} products")

    def collect(category):
        urls = []
        for listing_url in [category["url"], *category["extra_urls"]]:
            page = fetcher.get(listing_url)
            if page:
                urls.extend(parse_listing(page))
            if len(urls) >= per_category:
                break
        return category["slug"], urls[:per_category]

    log(f"Collecting up to {per_category} products per category ...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for slug, urls in pool.map(collect, categories):
            for url in urls:
                if product_urls.get(url) is None:
                    product_urls[url] = slug
            log(f"  {slug}: {len(urls)}")

    ordered = list(product_urls.items())
    if limit:
        ordered = ordered[:limit]
    log(f"Fetching {len(ordered)} product pages ...")

    def fetch_product(item):
        url, category_slug = item
        page = fetcher.get(url)
        if not page:
            return None
        parsed = parse_product(page, url, max_images)
        if not parsed or not parsed["price"]:
            return None
        parsed["category_slug"] = category_slug
        if not no_images:
            download_images(fetcher, parsed)
        return parsed

    products, done = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(fetch_product, ordered):
            done += 1
            if done % 50 == 0:
                log(f"  {done}/{len(ordered)} ...")
            if result:
                products.append(result)

    # Products picked up from the home page (or from a filtered-out category)
    # fall back to the deepest breadcrumb that matches a category we kept.
    known = {c["slug"] for c in categories}
    for product in products:
        if product["category_slug"] in known:
            continue
        product["category_slug"] = next(
            (c["slug"] for c in reversed(product["breadcrumbs"]) if c["slug"] in known), None
        )

    payload = {
        "source": BASE,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "categories": [{k: v for k, v in c.items() if k != "extra_urls"} for c in categories],
        "brands": brands,
        "products": products,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    log(f"\nWrote {OUT_FILE}")
    log(f"  categories: {len(categories)}")
    log(f"  products:   {len(products)} ({sum(1 for p in products if p['images'])} with images)")
    log(f"  no category: {sum(1 for p in products if not p['category_slug'])}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scrape a dev catalogue from startech.com.bd")
    parser.add_argument("--per-category", type=int, default=8)
    parser.add_argument("--max-images", type=int, default=3, help="photos kept per product")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests, per worker")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None, help="cap total products (debugging)")
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args(argv)
    scrape(
        args.per_category, args.delay, args.workers, args.limit, args.no_images, args.max_images
    )


if __name__ == "__main__":
    sys.exit(main())
