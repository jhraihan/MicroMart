"""
Fetch real, openly-licensed product photography from Wikipedia and Wikimedia
Commons.

**Why this source.** Photographs on a retailer's site belong to whoever shot
them; re-hosting those is infringement however the resulting site is
described. Wikipedia's images live on Commons under licences that explicitly
permit reuse -- CC0, CC BY, CC BY-SA, and public domain -- as long as the
licence's conditions are met. CC BY and CC BY-SA require the author and
licence to be shown wherever the image appears, which is exactly why
`ProductImage.source_url`, `.license_name` and `.attribution` exist: the
credit travels with the file into the database and back out onto the page.

**Why the article lead image, not a search.** Three approaches were tried
against this catalogue before this one:

  * *Free-text Commons search* returned "Cycling Amsterdam" for headphones and
    an Amiga 500 for a mouse.
  * *Model-gated Commons search* was accurate when it hit but covered a small
    fraction of the catalogue, and still confused a MacBook **Pro** for a
    MacBook **Air** because "m2" matched both.
  * *Commons category members* are alphabetical and unfiltered -- "Animal
    Shelter for Computer Mice" sits in Category:Computer mice.

A Wikipedia article's lead image is different in kind: it is chosen by editors
to depict that article's subject. Ask for the lead image of "Samsung Galaxy
S24" and you get a Samsung Galaxy S24. So this module resolves an *article*
per product and takes its lead image, which is why `ARTICLES` below is
curated rather than guessed.

**Exact versus representative.** Not every product in a shop has its own
encyclopedia article -- nothing on Wikipedia depicts a "Havit KB487L". Those
fall back to the article for their product *type* ("Mechanical keyboard"),
which yields a real photograph of the right kind of thing. Those images are
marked `is_representative` so the storefront can label them honestly instead
of implying the photo is of that exact unit.
"""
import time
from urllib.parse import quote

import requests

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Wikimedia asks automated clients to identify themselves.
USER_AGENT = (
    "MicroMartDemoSeed/1.0 (educational demo storefront; contact: dev@micromart.example)"
)

# Serial politeness delay. The earlier probe that fired requests back-to-back
# started getting non-JSON error bodies back -- that was us being rude, not a
# broken API.
REQUEST_DELAY_SECONDS = 0.6
MAX_RETRIES = 3
BACKOFF_SECONDS = 2.0

THUMB_WIDTH = 1000

# Licences that permit reuse. Anything not matching is skipped rather than
# risked -- "fair use" files exist on Wikipedia and must never be pulled in.
OPEN_LICENCE_PATTERNS = ("cc0", "cc by", "cc-by", "public domain", "pd-", "attribution")

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


class RemoteImage:
    """A fetched image plus everything its licence requires us to display."""

    def __init__(
        self, *, url, file_title, license_name, attribution, source_url,
        is_representative,
    ):
        self.url = url
        self.file_title = file_title
        self.license_name = license_name
        self.attribution = attribution
        self.source_url = source_url
        self.is_representative = is_representative

    def __repr__(self):  # pragma: no cover -- debugging aid
        return f"<RemoteImage {self.file_title!r} {self.license_name}>"


def _get(api, params):
    """
    One JSON API call, with backoff.

    Wikimedia answers an over-eager client with an HTML error page, which
    fails to parse as JSON -- so a ValueError here means "slow down", not
    "malformed API".
    """
    for attempt in range(MAX_RETRIES):
        try:
            response = _session.get(api, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            time.sleep(REQUEST_DELAY_SECONDS)
            return payload
        except (requests.RequestException, ValueError):
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
    return None


def _is_open(license_name):
    lowered = (license_name or "").lower()
    return bool(lowered) and any(p in lowered for p in OPEN_LICENCE_PATTERNS)


def _strip_html(value):
    """Commons returns the author as an HTML fragment; a credit line is text."""
    import re

    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip()[:200]


def lead_image_file(article):
    """
    The Commons file title of an article's lead image, or None.

    `redirects=1` matters: half the curated titles below are redirects to the
    canonical article, and without it those resolve to nothing.
    """
    payload = _get(
        WIKIPEDIA_API,
        {
            "action": "query",
            "format": "json",
            "titles": article,
            "prop": "pageimages",
            "piprop": "name",
            "redirects": 1,
        },
    )
    if not payload:
        return None

    for page in (payload.get("query", {}).get("pages", {}) or {}).values():
        if "missing" in page:
            continue
        name = page.get("pageimage")
        if name:
            return f"File:{name}"
    return None


def file_details(file_title):
    """URL, licence and author for a Commons file, or None if unusable."""
    payload = _get(
        COMMONS_API,
        {
            "action": "query",
            "format": "json",
            "titles": file_title,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": THUMB_WIDTH,
        },
    )
    if not payload:
        return None

    for page in (payload.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info:
            continue

        # Some articles lead with a video or an audio clip -- Wikipedia's
        # "Computer keyboard" leads with an .ogv of someone typing. A still is
        # the only thing a product gallery can use.
        mime = info.get("mime", "")
        if not mime.startswith("image/"):
            return None

        # Rasterised thumbnails are served for SVG too, so an SVG lead image
        # (the iPhone 15 article uses one) is still usable -- Commons hands
        # back a PNG at `thumburl`. A vector with no thumbnail is not.
        url = info.get("thumburl")
        if not url and mime != "image/svg+xml":
            url = info.get("url")
        if not url:
            continue

        meta = info.get("extmetadata", {})
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        if not _is_open(license_name):
            return None

        return {
            "url": url,
            "license_name": license_name,
            "attribution": _strip_html(meta.get("Artist", {}).get("value", "")),
            "source_url": info.get("descriptionurl")
            or f"https://commons.wikimedia.org/wiki/{quote(file_title.replace(' ', '_'))}",
        }
    return None


def resolve(article, *, is_representative):
    """Article title -> RemoteImage, or None when nothing usable is found."""
    file_title = lead_image_file(article)
    if not file_title:
        return None

    details = file_details(file_title)
    if not details:
        return None

    return RemoteImage(
        url=details["url"],
        file_title=file_title,
        license_name=details["license_name"],
        attribution=details["attribution"] or "Wikimedia Commons contributor",
        source_url=details["source_url"],
        is_representative=is_representative,
    )


def download(image):
    """Image bytes, or None if the fetch fails."""
    for attempt in range(MAX_RETRIES):
        try:
            response = _session.get(image.url, timeout=45)
            response.raise_for_status()
            time.sleep(REQUEST_DELAY_SECONDS)
            return response.content
        except requests.RequestException:
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
    return None


# ---------------------------------------------------------------------------
# Curated article map
#
# Keyed by product name. A value here means Wikipedia has an article whose
# lead image depicts this exact product or its immediate family, so the photo
# is a true product shot.
# ---------------------------------------------------------------------------
# Entries are removed rather than guessed when the obvious article has no
# usable lead image: Wikipedia's "Asus Vivobook" leads with a photo of the
# company's headquarters, and "Redmi" with an advertising portrait. Both
# would be worse than the category fallback they now get.
ARTICLES = {
    # Processors
    "AMD Ryzen 5 5600X Desktop Processor": "Ryzen",
    "AMD Ryzen 7 5800X Desktop Processor": "Ryzen",
    "AMD Ryzen 5 7600 Desktop Processor": "Ryzen",
    "AMD Ryzen 7 7800X3D Desktop Processor": "Ryzen",
    "Intel Core i5-12400F Desktop Processor": "Alder Lake",
    "Intel Core i5-13400 Desktop Processor": "Raptor Lake",
    "Intel Core i7-13700K Desktop Processor": "Raptor Lake",
    # Graphics
    "NVIDIA GeForce RTX 4060 8GB Graphics Card": "GeForce RTX 40 series",
    "NVIDIA GeForce RTX 4070 Super 12GB Graphics Card": "GeForce RTX 40 series",
    "MSI GeForce RTX 4060 Ti Ventus 2X 8GB": "GeForce RTX 40 series",
    "Gigabyte GeForce RTX 4090 Gaming OC 24GB": "GeForce RTX 40 series",
    "Asus Dual Radeon RX 7600 8GB OC Edition": "Radeon RX 7000 series",
    # Laptops and desktops
    "Apple MacBook Air 13 M2": "MacBook Air",
    "Lenovo ThinkPad E14 Gen 5": "ThinkPad E series",
    "Dell Latitude 3540 Business Laptop": "Dell Latitude",
    "Asus TUF Gaming F15 FX507ZC4": "Gaming computer",
    "Acer Nitro V 15 ANV15-51": "Gaming computer",
    "Lenovo IdeaPad Slim 3 15IAU7": "IdeaPad",
    "HP All-in-One 24-cb1004in": "All-in-one computer",
    # Phones and tablets
    "Samsung Galaxy S24 5G": "Samsung Galaxy S24",
    "Samsung Galaxy A15 4G": "Samsung Galaxy A15",
    "Apple iPhone 15": "IPhone 15",
    "Apple iPad 10th Generation 10.9\"": "IPad (10th generation)",
    "Samsung Galaxy Tab A9+ 11\"": "Samsung Galaxy Tab A series",
    "Xiaomi Pad 6": "Xiaomi Pad 6",
    # Peripherals with their own article
    "Samsung Galaxy Buds2 Pro": "Samsung Galaxy Buds",
    "Sony PlayStation 5 Slim Digital Edition": "PlayStation 5",
    "Xbox Wireless Controller": "Xbox Wireless Controller",
    "Samsung Galaxy Watch6 44mm Bluetooth": "Samsung Galaxy Watch 6",
    "Xiaomi Smart Band 8": "Xiaomi Smart Band 8",
    # Software
    "Microsoft Office Home & Student 2021": "Microsoft 365",
    # Storage
    "Samsung 990 PRO 1TB NVMe M.2 SSD": "M.2",
    "Samsung 980 500GB NVMe M.2 SSD": "M.2",
    "Samsung T7 1TB Portable SSD": "Solid-state drive",
    "Synology DS223j 2-Bay NAS Enclosure": "Network-attached storage",
}

# Fallback per category: a real photograph of the right *kind* of product,
# used when nothing depicts the exact model. Marked representative.
CATEGORY_ARTICLES = {
    "processor": "Central processing unit",
    "cpu-cooler": "Computer fan",
    "motherboard": "Motherboard",
    "ram": "DIMM",
    "graphics-card": "Graphics card",
    "ssd": "Solid-state drive",
    "hard-disk-drive": "Hard disk drive",
    "power-supply": "Power supply unit (computer)",
    "pc-case": "Computer case",
    "gaming-pc": "Gaming computer",
    "office-desktop": "Desktop computer",
    "all-in-one-pc": "All-in-one computer",
    "gaming-laptop": "Gaming computer",
    "ultrabook": "Laptop",
    "business-laptop": "Laptop",
    "gaming-monitor": "Computer monitor",
    "office-monitor": "Computer monitor",
    "ups": "Uninterruptible power supply",
    "tablet": "Tablet computer",
    "mobile-phone": "Smartphone",
    "action-camera": "Action camera",
    "mirrorless-camera": "Mirrorless camera",
    "router": "Wireless router",
    "network-switch": "Ethernet hub",
    "network-adapter": "Wireless network interface controller",
    "keyboard": "Model M keyboard",
    "mouse": "Computer mouse",
    "headphone": "Headphones",
    "speaker": "Computer speakers",
    "microphone": "Microphone",
    "webcam": "Webcam",
    "inkjet-printer": "Inkjet printing",
    "laser-printer": "Laser printing",
    "projector": "Video projector",
    "tv": "Smart TV",
    "air-conditioner": "Air conditioning",
    "smart-watch": "Smartwatch",
    # Deliberately absent: every battery-related article on Wikipedia
    # leads with a car or an EV pack, so a power bank keeps the generated
    # placeholder rather than showing a shopper the wrong object.
    "gaming-chair": "Office chair",
    "gaming-console": "Video game console",
    "controller": "Game controller",
    # "Computer software" leads with a screenshot of JavaScript source,
    # which tells a shopper nothing about a boxed licence. A certificate
    # of authenticity is what they actually receive.
    "software": "Product key",
    "nas-storage": "Network-attached storage",
    "external-storage": "External hard disk drive",
}

# Brand logos. Wikipedia's article for a company carries its logo as the lead
# image. A trademark is not a copyright: showing a maker's mark to identify
# whose goods are for sale is nominative use, and it is never presented as
# this store's own mark.
BRAND_ARTICLES = {
    "AMD": "Advanced Micro Devices",
    "Intel": "Intel",
    "NVIDIA": "Nvidia",
    "Asus": "Asus",
    "MSI": "Micro-Star International",
    "Gigabyte": "Gigabyte Technology",
    "Lenovo": "Lenovo",
    "HP": "Hewlett-Packard",
    "Dell": "Dell",
    "Acer": "Acer Inc.",
    "Apple": "Apple Inc.",
    "Samsung": "Samsung Electronics",
    "Xiaomi": "Xiaomi",
    "Realme": "Realme",
    "Corsair": "Corsair Gaming",
    "Logitech": "Logitech",
    "Razer": "Razer Inc.",
    "Kingston": "Kingston Technology",
    "Western Digital": "Western Digital",
    "Seagate": "Seagate Technology",
    "TP-Link": "TP-Link",
    "Cooler Master": "Cooler Master",
    "Thermaltake": "Thermaltake",
    "BenQ": "BenQ",
    "LG": "LG Electronics",
    "Sony": "Sony",
    "Canon": "Canon Inc.",
    "Epson": "Seiko Epson",
    "Brother": "Brother Industries",
    "Microsoft": "Microsoft",
    "Synology": "Synology",
    "Anker": "Anker Innovations",
    "Walton": "Walton (company)",
    "Havit": None,   # no encyclopedia article -- keeps the generated wordmark
    "A4Tech": None,
}


def article_for_product(name, category_slug):
    """
    (article, is_representative) for a product.

    An exact article means the photo depicts this product; a category article
    means it depicts the right kind of thing and must be labelled as such.
    """
    exact = ARTICLES.get(name)
    if exact:
        return exact, False
    fallback = CATEGORY_ARTICLES.get(category_slug)
    if fallback:
        return fallback, True
    return None, True


# ---------------------------------------------------------------------------
# Brand logos, via Wikidata
#
# A company's Wikipedia article leads with a photograph of its headquarters,
# not its mark -- asking `pageimages` for "Intel" returns an office block.
# Wikidata models the logo explicitly as property P154, so that is what gets
# asked, and the answer is a Commons filename rather than a guess.
# ---------------------------------------------------------------------------

WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# P154 = "logo image".
LOGO_PROPERTY = "P154"


def wikidata_id(article):
    """The Wikidata QID behind an English Wikipedia article, or None."""
    payload = _get(
        WIKIPEDIA_API,
        {
            "action": "query",
            "format": "json",
            "titles": article,
            "prop": "pageprops",
            "ppprop": "wikibase_item",
            "redirects": 1,
        },
    )
    if not payload:
        return None
    for page in (payload.get("query", {}).get("pages", {}) or {}).values():
        qid = (page.get("pageprops") or {}).get("wikibase_item")
        if qid:
            return qid
    return None


def logo_file(article):
    """The Commons file title of a company's logo, or None."""
    qid = wikidata_id(article)
    if not qid:
        return None

    payload = _get(
        WIKIDATA_API,
        {
            "action": "wbgetclaims",
            "format": "json",
            "entity": qid,
            "property": LOGO_PROPERTY,
        },
    )
    if not payload:
        return None

    claims = (payload.get("claims") or {}).get(LOGO_PROPERTY) or []
    for claim in claims:
        # A company can list several logos over time; `preferred` marks the
        # current one, so it wins when present.
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if not value:
            continue
        if claim.get("rank") == "preferred":
            return f"File:{value}"
    for claim in claims:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if value:
            return f"File:{value}"
    return None


def resolve_logo(article):
    """Company article -> RemoteImage of its logo, or None."""
    file_title = logo_file(article)
    if not file_title:
        return None
    details = file_details(file_title)
    if not details:
        return None
    return RemoteImage(
        url=details["url"],
        file_title=file_title,
        license_name=details["license_name"],
        attribution=details["attribution"] or "Wikimedia Commons",
        source_url=details["source_url"],
        is_representative=False,
    )
