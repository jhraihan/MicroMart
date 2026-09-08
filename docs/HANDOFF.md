# Handoff — resuming work on MicroMart

---

## 0. Latest session (2026-08-23) — discovery, PC Builder, real imagery

Everything below §1 predates this session and its "week 5/6 not started" notes
are now out of date in the areas listed here. Re-read §1's route-count command
rather than trusting any prose.

### What landed

| Area | Detail |
|---|---|
| **Catalogue size** | `manage.py seed_catalog` seeds **117 products / 130 variants / 55 categories / 35 brands / ~1,018 spec rows / 208 reviews**. Product data lives in `apps/catalog/seed_data/`, never in components. |
| **Real imagery** | `manage.py fetch_media` pulls openly-licensed photography from Wikipedia/Wikimedia and **stores the licence and author with every image**. 114 of 117 products and 32 of 35 brands carry real media. |
| **PC Builder** | New `apps.builds` app: compatibility engine, component picker, saved and shareable builds. Contract in `docs/api-contract-pc-builder.md`. |
| **Comparison** | Client-side tray (`stores/compareStore`) + `GET /products/compare/` returning a server-computed spec matrix. |
| **Type-ahead search** | `GET /search/suggest/` — FR-SRC-6, previously deferred, is now built. |
| **Account area** | `/account` overview, addresses, profile, password. Plus `/forgot-password` (both halves of the reset flow). |
| **Merchandising** | `/offers`, `/brands`, `has_discount` and `featured` filters, homepage rebuilt to nine rows. |
| **Admin taxonomy** | `/admin/taxonomy` — category and brand CRUD. The endpoints already existed (`apps/catalog/admin_urls.py`); only the React screen was missing. |
| **Navigation** | Data-driven mega-menu (desktop) and drawer (mobile), both built from `/categories/`. |
| **SEO** | `lib/seo.js` (title/meta/canonical/OG + JSON-LD), plus Django-served `/robots.txt` and `/sitemap.xml` (176 URLs). |

### Verified on 2026-08-23

- `pytest -q -m "not slow"` → **1358 passed** (was 1290 before this session's tests).
- `npx playwright test` → **105 passed**; `e2e/a11y.spec.js` alone → 90 passed.
- `npm run build` → succeeds, admin **and** PC Builder split into their own chunks.
- `makemigrations --check` → no drift.
- axe (wcag2a/2aa/21a/21aa) over `/`, `/offers`, `/brands`, `/compare`,
  `/pc-builder`, `/c/component`, `/forgot-password` and a product page, at
  1280px and 360px → **zero violations**.
- No horizontal overflow at 1280 / 1024 / 768 / 390 / 360px.

### Decisions worth not re-litigating

**Product imagery is Wikipedia article lead images, not a Commons search.**
Three approaches were tried and measured before this one: free-text Commons
search returned "Cycling Amsterdam" for headphones; a model-gated search was
accurate but covered a fraction of the catalogue and still confused a MacBook
*Pro* for an *Air*; Commons category members are alphabetical and unfiltered
("Animal Shelter for Computer Mice" sits in Category:Computer mice). An
article's lead image is chosen by editors to depict that article's subject,
which is why `wikimedia.ARTICLES` is curated by hand. Entries whose obvious
article leads with the wrong thing (Asus → a headquarters building, Redmi → an
advertising portrait) were **removed**, not guessed at.

**Brand logos come from Wikidata P154, not from `pageimages`.** A company's
Wikipedia article leads with a photo of its offices; asking for "Intel"'s page
image returns an office block. P154 models the logo explicitly.

**Exact vs representative imagery is tracked and shown.** A product with its
own article gets a photo of that product; one without gets its product
*type*'s photo, prefixed `Representative image` in `alt_text`, and the gallery
labels it. Never let a stand-in pass as the actual unit.

**Attribution is a licence condition, not metadata.** CC BY and CC BY-SA
require the author and licence to be displayed wherever the image is used, so
`ProductImage.source_url/license_name/attribution` are populated on write and
rendered by `ProductGallery`. An image whose licence cannot be confirmed as
open is skipped rather than risked.

**Compatibility findings have three levels, deliberately.** `error` (two known
values conflict), `warning` (a real risk), `info` (a check could not run).
Flattening them either cries wolf over gaps in our own specs or buries a real
conflict. And no verdict is presented as authoritative — every response
carries an `advisory` string.

**`view=grid|list` is URL state that never reaches the API.** It changes how a
result set is drawn, not what is in it.

### Traps this session walked into — do not repeat

- **`select_related`, not `prefetch_related`, for `Product.component`.** It is
  a reverse OneToOne; prefetching added a query to the endpoint with the
  tightest budget (detail p95 < 400ms) and broke
  `test_product_detail_query_count_is_bounded`.
- **Money in hand-built dicts bypasses DRF's `COERCE_DECIMAL_TO_STRING`.** The
  builder payloads are plain dicts, so a `Decimal` reached the JSON encoder
  and shipped `46500.0` — a float price. `builds.services.builds._money()`
  exists for exactly this.
- **Never nest a `<Link>` inside a `<button>`.** The first mega-menu draft did,
  and axe flagged `nested-interactive` (serious) across all 18 departments.
  `aria-expanded` is a supported state on `role="link"`, so the trigger is one
  anchor.
- **`seed_demo` and `seed_catalog` must agree on category slugs.** They did
  not at first, and the storefront grew a "Laptops" tab beside a "Laptop" one.
  `seed_catalog._reconcile_legacy_taxonomy()` folds the old plural slugs in and
  is a no-op afterwards.
- **The 18-department mega-menu and the 5-icon header both overflowed.** The
  strip now scrolls inside itself (safe *only* because the panel is rendered
  outside it); Offers/Builder/Compare are desktop-only in the header and live
  in the mobile drawer instead.

### Commands added

```bash
.venv/bin/python manage.py seed_catalog              # 117 products, offline, ~17s
.venv/bin/python manage.py seed_catalog --no-images  # faster, text only
.venv/bin/python manage.py fetch_media               # real licensed imagery (network, minutes)
.venv/bin/python manage.py fetch_media --brands      # logos only
```

`seed_catalog` is offline and deterministic; `fetch_media` talks to a
third-party API and is allowed to partially fail. They are separate commands
for that reason — a flaky network must not turn "seed the catalogue" into a
broken catalogue.

### Still open

- SSLCommerz remains blocked on the owner (§14 Q1). `payments/` has routes but
  no live gateway credentials.
- 3 products and 3 brands keep generated placeholder artwork because no
  suitable openly-licensed image exists (Havit, A4Tech, and power banks —
  every battery article on Wikipedia leads with a car).
- **Running the Playwright suite leaves fixture products in the dev
  database.** That is by design (`playwright.config.js` explains why it runs
  against dev), but they are active and therefore visible in the storefront.
  `seed_e2e_fixture.py` says they are safe to delete and recreates them, so
  clear them before taking screenshots:
  `Product.objects.filter(category__slug='e2e-fixtures').delete()`.
- Changing a password now signs the account out everywhere else (§4, resolved).
  The account page says so.


Written 2026-08-19 on Windows. **Revised 2026-08-22 on macOS** — the project moved
machines, so §2 and §6 were rewritten; everything else was re-verified against a
clean run rather than trusted. Read this before touching anything; it records
state that is not recoverable from the code or git history.

---

## 1. Where the build actually is

| PRD week (§12.1) | Status |
|---|---|
| 1 — data model, auth, React shell | **Done, verified end to end** |
| 2 — catalogue API, storefront browse/search/detail | **Done, reviewed, fixes applied** |
| 3 — cart, checkout, orders, COD, email | **Landed** — commit `9e8d316`, contract in `docs/api-contract-cart-checkout-orders.md` |
| 4 — SSLCommerz, IPN, stock locking, shipping/tax | **Partly done** — stock locking under concurrency is built, tested and green; SSLCommerz/IPN not started (still blocked, §14 Q1) |
| 5 — admin dashboard, coupons, reviews, wishlist | Not started |
| 6 — QA, a11y, perf, deployment, backups | Not started |

The quickest truthful check of what exists is route count per app:

```bash
cd backend
for a in accounts catalog cart orders payments promotions reviews shipping dashboard; do
  printf "%-11s routes=%-3s services=%s\n" "$a" \
    "$(grep -c 'path(\|router.register' apps/$a/urls.py 2>/dev/null || echo NONE)" \
    "$(ls apps/$a/services/*.py 2>/dev/null | grep -v __init__ | wc -l | tr -d ' ')"
done
```

Measured 2026-09-07:

| app | routes | services |
|---|---|---|
| accounts | 9 | 2 |
| catalog | 8 | 3 |
| cart | 4 | 1 |
| orders | 4 | 5 |
| payments | 3 | 2 |
| promotions | 0 (admin only) | 1 |
| reviews | 4 | 2 |
| shipping | 1 | 1 |
| dashboard | 7 | 3 |
| builds | 5 | 2 |

Every app above is built. The earlier version of this table said payments,
promotions, reviews and dashboard had no `urls.py` at all; that was true when it
was written and is not true now.

`promotions` shows 0 storefront routes because its endpoints are admin-only and
live in `apps/promotions/admin_urls.py`. Its `urls.py` is an empty stub that is
still mounted — the natural place for a public coupon-check endpoint later.

Verified green on **2026-08-22 (second pass, after the week-3/4 test backfill)**,
macOS, from a clean checkout: `manage.py check` (no issues),
`makemigrations --check` (no drift), all migrations applied,
`pytest -q` → **554 passed, 0 failed**, `npm run build` → succeeds and the admin
chunk still splits (`AdminOverviewPage-*.js` emitted separately), `npm run lint`
→ exit 0 with five pre-existing warnings and no errors.

> The earlier figure in this file was **120 passed**. The jump is a test
> backfill, not new features: `apps/cart/tests/` (136), `apps/orders/tests/`
> for totals, the checkout quote, placement and oversell concurrency,
> `apps/promotions/tests/`, `apps/shipping/tests/` and `apps/accounts/tests/`
> all went from zero. Five of the 554 are marked `slow` (real threads, real row
> locks) and run by default — deselect with `-m "not slow"`.

**One test database, and it is shared.** The `ecom` grant covers `ecom.*` and
`test_ecom.*` only, so parallel pytest processes fight over the same schema.
`OperationalError (1049, "Unknown database 'test_ecom'")`, MySQL 1213 deadlocks
and "table doesn't exist" during a run are contention between processes, not
defects — re-run with `--create-db` when nothing else is running before
believing any of them.

The live route list, which is more trustworthy than the counts above:

```bash
cd backend && .venv/bin/python manage.py shell -c "
from django.urls import get_resolver
def walk(res, prefix=''):
    for p in res.url_patterns:
        pat = prefix + str(p.pattern)
        walk(p, pat) if hasattr(p, 'url_patterns') else print(pat)
walk(get_resolver())" | grep '^api/' | sort
```

---

## 2. Environment — the parts that will waste your time

**Current machine is macOS** (Darwin 25.5, Python 3.14.0 from Homebrew, Node 25.9).
The venv interpreter is `backend/.venv/bin/python` — the Windows
`.venv/Scripts/python.exe` in older notes no longer exists here.

Ports on macOS as measured 2026-08-22:

| Service | Port | Notes |
|---|---|---|
| Django (this project) | **8000** | free here — the Windows port conflict does not apply |
| Vite (this project) | **5173** | free here |
| MySQL 8 | **3307** | this project's database, running |
| MariaDB 10.4 | 3306 | also running, *not* used by this project |

Because 8000 and 5173 are free, **`frontend/.env.local` is not needed on this
machine** and does not exist — `vite.config.js` already defaults to
`http://127.0.0.1:8000`. Create it (from `frontend/.env.example`) only if 8000
gets taken; set `VITE_BACKEND_ORIGIN` there rather than editing `vite.config.js`.

> On the old Windows box another project held `:8000`/`:5173`, so Django ran on
> **8001** and Vite fell back to **5174**. Re-check with `lsof` before assuming
> either layout.

Start everything:

```bash
# backend  (omit --noreload, or new routes will not be picked up)
cd backend && .venv/bin/python manage.py runserver 127.0.0.1:8000

# frontend
cd frontend && npm run dev
```

First contact on a fresh checkout, in order:

```bash
cd backend
python3 -m venv .venv                                   # if .venv is absent
.venv/bin/python -m pip install -r requirements/dev.txt  # note: requirements/ is a directory
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo
cd ../frontend && npm install
```

A first `manage.py` call under a sandboxed shell can fail spuriously with
`ModuleNotFoundError: No module named 'django'` or `Set the DJANGO_SECRET_KEY
environment variable` even when the venv and `.env` are both fine. Re-run it
once before believing either — both were false alarms on 2026-08-22.

### Credentials

- **Database**: `backend/.env` holds `DATABASE_URL`. Gitignored. Real password
  lives only there and in `backend/scripts/create_database.local.sql`
  (also gitignored). The committed `create_database.sql` has a placeholder.
  Both files **are present on the macOS box** and Django connects with them —
  the `ecom` MySQL user works, so nothing needs recreating.
- **MySQL root** password is *not* recorded anywhere in the repo (deliberately —
  this file is committed). Nothing routine needs root: the `ecom` grant in
  `.env` covers migrate, seed and the pytest `test_ecom` database. Root is only
  needed to re-run `create_database.sql` from scratch.
- **Seeded logins**:
  - `admin@example.com` / `ChangeMe!2026` — created by `manage.py seed_demo`.
    Note `_seed_admin` **leaves the password alone if the user already exists**,
    so on a database that has been seeded before, the real password may differ
    from the default. Force it with
    `manage.py seed_demo --admin-password 'ChangeMe!2026'`.
  - `shopper@example.com` / `Str0ngPass!2026` — **now created by
    `manage.py seed_demo`** (2026-08-22), with a seeded default address in
    Dhaka so checkout resolves a shipping zone immediately. Same caveat as the
    admin: the password is left alone if the user already exists, so force it
    with `manage.py seed_demo --customer-password 'Str0ngPass!2026'`.
  - The login page shows these in dev only — `DemoCredentials.jsx` is behind
    `import.meta.env.DEV`, so Vite strips it from production builds. Verified:
    the strings do not appear in `dist/`.

Database contents as measured 2026-08-22 — the `seed_demo` fixtures only:
7 products, 14 variants, 7 categories, 7 brands, **2 users (the admin and the
shopper) and 1 address**.

---

## 3. Decisions taken that are not obvious from the code

These were judgment calls. Revisit them deliberately, not by accident.

**Facet counts exclude their own dimension.** PRD FR-SRC-2 says facets reflect
the current result set. Taken literally, selecting Asus makes every other brand
read zero and the filter can never be widened. So a facet dimension is dropped
when counting itself. Documented in `docs/api-contract-catalogue.md`.

**Inactive category hides its products; inactive brand does not.** A category is
a place in the navigation, so hiding it must hide what is inside it. A brand is
a label on sellable stock — deactivating it removes it from `/brands/` and from
the brand facet, but the products stay listed and buyable.

**`price_min` / `price_max` / `compare_at_price` are nullable on detail only.**
FR-CAT-7 gates detail on the product's own `is_active` flag, so a product whose
variants have all been deactivated still resolves — with no price. Null is
reported rather than `"0.00"`, which would render as free. The list endpoint
never returns null, because such a product is not listable.

**Price filter means "has a buyable variant in this band"**, not "the product's
range overlaps the band".

**React pinned to 18** to match PRD §8.3, though Vite scaffolds 19 by default.
Not in the §1.2 locked-decisions table, so it is changeable.

**Recharts on v3**; v2 is unmaintained upstream.

**Search is FULLTEXT OR LIKE, not a strict fallback.** FR-SRC-1 requires
searching brand name, which sits in no FULLTEXT index, so an OR is unavoidable.

**Malformed query params return 422** with stable codes
(`INVALID_SORT`, `INVALID_FILTER`, `INVALID_PRICE_RANGE`) rather than being
silently ignored. Empty values are treated as absent.

**FR-SRC-6 (search-as-you-type) is deliberately deferred.** P2, and first on the
PRD §12.3 cut list.

**The dev catalogue is scraped from startech.com.bd** (`scripts/scrape_startech.py`
→ `manage.py import_startech`), because real catalogue content is still blocked
on the owner (§14 Q11) and seven fixtures do not exercise faceting, pagination
or search. Three things about it are deliberate, keep them:

- `backend/scripts/data/` is **gitignored**. The payload and photos are the
  source site's IP; they are dev seed data, never production content, and never
  committed.
- `Product.description` is **synthesised from the factual "Key Features"
  bullets**, not copied from the source's marketing prose. See
  `build_description()` in the import command.
- **Brand-filter nav entries are not categories.** About a third of the source
  nav's second level is brand filters ("Monitor → MSI"). They are detected
  against the site's A-Z manufacturer index and folded into their parent, since
  brand is already a first-class field on `Product`. That is what takes the
  taxonomy from 328 noisy categories to 18 roots / 239 real children.

The source is single-SKU, so each product imports one default variant, SKU
`ST-<source product code>`. The source publishes a stock *label*, not a number,
so in-stock products get a deterministic pseudo-stock from `crc32(slug)` (4–45)
— stable across re-imports — written through an `InventoryLog` row with reason
`INITIAL`. Re-running the import refreshes name/price/specs/images but **never
rewrites stock** on an existing variant, because something may have moved it and
written a ledger row that must not be orphaned.

---

## 4. Known open issues

### ~~Seed / login-page drift~~ — RESOLVED 2026-08-22

`DemoCredentials.jsx` advertised `shopper@example.com` / `Str0ngPass!2026` and
claimed parity with `manage.py seed_demo`, which seeded only the admin. Closed
in the "add a shopper seed" direction: `seed_demo` now takes
`--customer-email` / `--customer-password`, creates the shopper as a plain
non-staff `customer`, and seeds it a default Dhaka address through
`apps.accounts.services.addresses.create_address` so checkout has a
preselected address in a real shipping zone. Idempotent — re-running never
duplicates the user or the address and never rewrites an existing password.
The comment in `DemoCredentials.jsx` was rewritten and is now true.

### Production bugs found by the 2026-08-22 test backfill — all three fixed

Writing tests for previously untested services turned up three real defects.
Each fix is in the service layer, and each is pinned by a test that fails if
the fix is reverted.

**1. Order references collided under concurrency, and the collision reached
the customer as a 500.** `placement.next_reference()` read the year's highest
reference with a plain `SELECT`. Django runs MySQL at READ COMMITTED, so that
read was *current* but not *exclusive* — N simultaneous checkouts read the
same maximum and every one computed the same successor. One `INSERT` won the
unique index and the rest raised `IntegrityError`. The hazard is **baskets
that share no variant**, so nothing else serialised them: 24 simultaneous
checkouts of 24 *different* products produced 3 orders and 21 crashes, on
every run. The read is now `select_for_update()`, taken last so lock ordering
stays consistent. Compounding it, `_reserve_reference()` raised
`REFERENCE_ALLOCATION_FAILED` when its fast path was exhausted, which bypassed
`place_order`'s own `IntegrityError` retry and turned recoverable contention
into a permanent 422; it now returns the last candidate and lets the unique
index arbitrate. **That error code no longer exists** — it was in no
contract and no client branched on it. Residual, stated honestly: allocation
is a fast path, not a proof (the first order of a fresh year has no row to
lock), and the unique index plus the retry absorb the rest. An airtight fix
needs a counter row or an advisory lock.

**2. The signed-in cart was broken end to end by a serializer/contract
mismatch.** `CartLineSerializer` nested everything under a `variant` object;
`docs/api-contract-cart-checkout-orders.md` freezes a **flat** line and
`frontend/src/features/cart/useCart.js` `fromServerItem` reads exactly the flat
keys. So for a signed-in shopper every line rendered with no name, no image and
no product link — and, because `variant_id` was among the missing keys, the
`POST /checkout/quote/` body built from those lines went out with no
`variant_id` at all and came back **400 `items: This field is required`**,
taking the whole totals panel down with it. The serializer is now flat and a
line's `issue` uses the contract's vocabulary (`out_of_stock`,
`insufficient_stock`, `unavailable`) via `inventory_services.ISSUE_*` instead
of the cart's own uppercase `NOTICE_*` codes. `notices[]` keeps the `NOTICE_*`
vocabulary on purpose — a notice says what *changed*, an issue says what a line
*is*. Pinned by `test_a_cart_line_carries_everything_needed_to_render_it` and
`test_a_cart_line_and_a_quote_line_describe_the_same_variant_with_the_same_words`.

**3. An invalid coupon blanked the entire checkout quote.** `checkout.quote()`
let `coupons.validate_coupon`'s `DomainError` escape, so a typo'd or
newly-expired code 422'd the whole endpoint — exactly what the frozen contract
forbids ("a coupon that goes stale mid-checkout, or a typo, must not blank out
the totals a shopper is reading"), and the frontend was already built against
the documented behaviour. `quote()` now absorbs `COUPON_*` into `coupon_error`
and an unresolvable district into a `NO_SHIPPING_ZONE` notice, and returns a
`Quote` carrying the server's own `can_place_order` verdict. **Placement is
deliberately not tolerant of either** — an order must never be created with an
unpriced delivery or a lapsed coupon. `QuoteSerializer` was reshaped to the
contract at the same time (`lines`, `tax_rate_applied`, `zone`,
`payment_methods[].code`, `prices_include_tax`, `notices`, `can_place_order`),
so the doc, the API and the React checkout finally agree.

### Contract drift still open — smaller, none of it user-visible yet

- `POST /cart/items/` returns **201**; the contract says **200**. Nothing
  branches on it (axios treats any 2xx as success), so it is a doc-or-code
  decision, not a break.
- `GET /orders/{reference}/` is `IsAuthenticated`. The contract documents a
  guest read via `?email=`, which is **not implemented**. This is why
  `OrderConfirmationPage` paints a guest's thank-you screen from the cache
  `usePlaceOrder` seeded and shows an explicit "not on this device" panel on
  reload rather than spinning.
- Order list rows return the full `items` array, not the documented
  `items_preview`; order detail uses `timeline`, not `status_logs`, and
  `shipping_zone` (a string), not `zone_name`. Order items carry no `image`,
  so the order screens are text-only. The order pages were built against the
  serializers, which is the running API.
- The contract itself is inconsistent about one name: a **cart** line reports
  `stock`, a **quote** line reports `available_stock`, for the same number.
  Both are implemented as written, and the storefront reads the right one on
  each surface, so this is a doc wart rather than a bug.

### ~~Catalogue sort performance~~ — FIXED 2026-08-22, without denormalising

The two week-2 findings (`sort=price_asc` p90 **877ms**, `sort=best_selling`
p50 **2214ms** at 5,000 products) were re-measured before being fixed, and the
headline numbers **did not reproduce** on this machine. Re-measured on macOS,
MySQL 9.5, Django 5.2.6, 5,000 products / 10,000 variants / 5,287 order items
in `test_ecom`, the *whole endpoint* (count + page + serialize + five facets)
was already inside the 500ms budget before any change: `price_asc` p95
**227ms**, `best_selling` p95 **265ms**. Do not record the old figures as
having been beaten — they were from a different machine and a different Django
version. What **did** reproduce is the query plan the review described, and
that was real: a 4,875-row temporary table and ~24,000 correlated subquery
executions to draw one page of 24 cards.

The cause was subtler than "price_asc sorts on a subquery". `newest` cost the
same 220ms, because the five card aggregates (`price_min`, `price_max`,
`total_stock`, `variant_count`, `cheapest_compare_at`) were annotated onto the
queryset **before** pagination sliced it, and MySQL evaluates a SELECT-list
subquery once per row reaching the sort, not once per row surviving the LIMIT.

**Applied — the cheap wins, which were enough:**

1. *Paginate bare ids, then hydrate the page.* `catalogue.product_list_ids()`
   selects nothing but `id` and annotates only what ORDER BY needs;
   `catalogue.product_list_rows()` puts the aggregates on the 24 rows that
   survived. One extra round trip (list budget 8 → **9**), constant.
2. *`_price_facet` dropped a redundant `EXISTS`.* It was built on
   `listable_products()`, then joined to the variant table — a doubled semijoin
   MySQL resolves with a duplicate-weedout temp table. It now uses
   `storefront_products()`; a product with no active variant contributes no row
   to an `is_active=True` variant aggregate either way, so the answer is
   provably identical. Measured at 20,000 products: 152ms → 90ms.

Measured after, same seed, interleaved A/B so machine drift cancels — endpoint
p95 at 5,000 products: `price_asc` **227 → 144ms**, `best_selling`
**265 → 164ms**, `newest` 225 → 133ms, deep page 150 of `best_selling`
294 → 175ms.

**Not applied, with numbers, so nobody re-tries them blind:**

- *Grouping the five facet queries by shared base* — measured, does not pay.
  Merging `in_stock` + `ratings` (their bases coincide only when neither filter
  is active) saved 6ms of 100ms at 5,000 and 20ms of 390ms at 20,000. Merging
  `brands` + `categories` into one `GROUP BY (brand, category)` was a **wash at
  5,000** (4,478 groups for 4,875 products) and its group count is the product
  of the two dimensions, so it degrades exactly where it would be needed.
- *Denormalised `price_min` / `price_max` / `units_sold` on `Product`* — **not
  warranted at 5,000, and at 20,000 it would not fix what breaks first.** The
  remaining ORDER BY subquery costs ~82ms (`price_asc`) and ~137ms
  (`best_selling`) at 20,000 products. Decomposed there (quiet machine, before
  the `_price_facet` fix): `price_asc` 551ms total = count 25 + ids 127 +
  rows/serialize 7 + **facets 390**; `newest`, which correlates nothing at all,
  was already 467ms on the same set. Zeroing both sort terms therefore leaves
  the endpoint at ~470ms, still against the 500ms budget — **the facets are the
  binding constraint above ~10,000 products, not the sorts.** Carrying
  `units_sold` would also mean maintaining it from order placement *and* every
  cancel/refund transition, which is a lot of write-path surface to buy a term
  that is not what breaches the budget.

  If a catalogue that size is actually coming, attack the facets in this
  order (measured at 20,000, post-fix): `in_stock` 97ms, `price` 86ms,
  `brands` 65ms, `ratings` 51ms, `categories` 36ms. `in_stock` is now the
  dearest, and it is an `EXISTS` evaluated per product.

Guarded by `apps/catalog/tests/test_list_query_plans.py`: the query the view
paginates must select ids and nothing else, sorts on a real column must show
**zero** correlated subqueries in the MySQL plan, and `price_asc` /
`best_selling` at most **one** — its own sort term. Verified to fail (10 tests)
when the pre-fix shape is restored. `test_query_counts.py` pins the count at 9
across sorts, catalogue sizes and page depth.

**Re-measure after the StarTech import (§3) anyway.** These numbers are from a
synthetic seed with 238 categories and 40 brands; facet cost scales with those
cardinalities, and the import produces a different shape.

### Auth findings — one decided, one still open

Both are pinned by tests that assert **today's** behaviour, with docstrings
saying which way to invert them. `ACCOUNT_DISABLED` has since been decided (see
below); the password-change one is still untouched, because it is a security
decision rather than a defect with an obvious right answer.

- **Changing a password invalidates existing sessions — RESOLVED (2026-09-07).**
  `accounts/services/auth.py::change_password` calls `revoke_all_sessions`,
  which blacklists every refresh token the user holds, so a session opened with
  the old password dies with it. Password reset does the same. Pinned by
  `test_changing_the_password_invalidates_every_existing_refresh_token`.
  The account page told users the opposite until 2026-09-07; that copy is fixed.
- **`ACCOUNT_DISABLED` — RESOLVED (2026-08-22): the dead branch was deleted.**
  Django's default `ModelBackend` calls `user_can_authenticate()`, so
  `authenticate()` returned `None` for an inactive user and the
  `INVALID_CREDENTIALS` raise above it always won; a deactivated account got
  401, never the 403, and nothing in `backend/` or `frontend/` consumed the
  code. Making it reachable would have meant checking `is_active` *before*
  `authenticate()`, which is an account-enumeration disclosure, and no PRD
  requirement asks for a deactivated user to be told why. So `login_user` now
  has one refusal, and a docstring says not to add the branch back.
  Deactivation is still enforced everywhere else: SimpleJWT's
  `CHECK_USER_IS_ACTIVE` (default on) rejects an inactive user's access token
  on every request. Pinned by
  `test_logging_in_to_a_deactivated_account_is_refused_exactly_like_an_unknown_email`
  and its service-layer counterpart
  `test_the_login_service_refuses_a_deactivated_account_as_bad_credentials_not_as_a_disabled_one`.

### Coupon behaviour worth a second look

`COUPON_RELEASING_STATUSES` excludes `shipped`, so cancelling a *shipped* order
restores stock but does **not** release the coupon redemption. That is pinned
as intended by
`test_a_coupon_consumed_on_a_shipped_order_is_not_released_when_delivery_later_fails`.
If the owner disagrees, that test is the one to change.

### Unresolved contradiction in the PRD

**§15.1 disagrees with itself.** The ASCII diagram draws an arrow from
`confirmed` to `refunded`; the transition rules table below it does not list
that pair. The table states it is authoritative ("any transition not listed is
rejected"), so `apps/orders/models.py` `TRANSITIONS` implements the table — nine
transitions, no `confirmed → refunded`. `test_state_machine.py` pins this
against a hand-transcribed copy. **Ask the owner whether refunding a
confirmed-but-undelivered order should be legal.**

### One finding I could never reproduce

A reviewer reported MySQL error 1690 (`DOUBLE value is out of range`) on
`sort=relevance`, claiming every keyword search 500s at ~5,000 products. I
seeded 3,000 with `ANALYZE` and 5,007 without, and **it did not reproduce**.
The fix was applied anyway — `MATCH` was moved out of the summed arithmetic
expression into its own `ORDER BY` term — because the risky construct was
objectively present and `sort=relevance` is the default for every search.

**Ranking is unchanged and verified** (exact SKU first, model number first), but
do not record this as "a crash was fixed". Record it as "a risky construct was
removed".

### Test coverage blind spot — important

**InnoDB does not expose uncommitted rows to `MATCH ... AGAINST`.** Rows written
inside pytest's open transaction are invisible to full-text search, so almost
every search test passes through the `LIKE` arm and **never exercises the
FULLTEXT arm at all**. Any test that must prove full-text behaviour needs
`@pytest.mark.django_db(transaction=True)`. There is exactly one such test.
Keep this in mind before trusting a green search suite.

---

## 5. How this codebase is meant to be worked on

- **`models → services → serializers → views`.** All business logic in
  `apps/<app>/services/`. The storefront API and the admin API must call the
  *same* service functions, or rules drift between the two surfaces.
- Services raise `config.exceptions.DomainError(message, code=..., field=...)`;
  the DRF handler shapes the `{"error": {...}}` envelope. Never build it by hand.
- Object-level authorisation misses return **404, not 403**.
- Money is `apps.common.fields.MoneyField` (`DECIMAL(12,2)`), serialised as
  strings.
- `Order.status` and `ProductVariant.stock` are **read-only in Django Admin** on
  purpose, so nothing can bypass the service layer and its append-only logs.
- Tailwind v4: tokens live in `frontend/src/index.css` under `@theme`, not a JS
  config. Tailwind extracts class names **statically** — never build one by
  interpolation (`text-${align}` is silently dropped).
- Accessibility rules this codebase keeps breaking: brand orange `#ef4a23` fails
  AA on white and must never be text or button fill; `text-ink-subtle` `#838383`
  is 3.79:1 and must not carry body copy; interactive targets are ≥44px.

### Commands

```bash
# backend (cwd backend/)
.venv/bin/python manage.py check
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo      # idempotent
.venv/bin/python -m pytest -q

# large scraped dev catalogue (see §3 and §7) -- scrape first, then import
.venv/bin/python scripts/scrape_startech.py --per-category 8 --max-images 3 --workers 4 --delay 0.5
.venv/bin/python manage.py import_startech

# frontend (cwd frontend/)
npm run dev
npm run build
```

---

## 6. If the MySQL root password is lost again

> **Windows-only runbook.** Kept because it was expensive to work out and stays
> valid if the project moves back to that machine. It does **not** apply to the
> current macOS box — there, use `mysqld_safe --skip-grant-tables` or, if MySQL
> came from Homebrew, `brew services stop mysql` and restart it with
> `--skip-grant-tables`, then `ALTER USER 'root'@'localhost' IDENTIFIED BY '<new>'`
> and `FLUSH PRIVILEGES`. Note the MySQL on `:3307` here was **not** installed by
> the current Homebrew prefix, so check `ps -ax | grep mysqld` for its actual
> `--basedir`/`--datadir` before assuming which install you are restarting.
> **Nothing routine needs root** — the `ecom` user in `.env` covers migrate,
> seed and pytest — so only do this if `create_database.sql` must be re-run.

Do not run `mysqld` manually as Administrator — it leaves admin-owned files in
`C:\ProgramData\MySQL\MySQL Server 8.0\Data` that the `NetworkService` account
then cannot write, which breaks the service. Use the config route instead:

1. Elevated PowerShell.
2. Write `ALTER USER 'root'@'localhost' IDENTIFIED BY '<new>';` to a file under
   `C:\ProgramData\MySQL\` (ASCII, no BOM — `mysqld` will not parse a UTF-8 BOM).
3. Add `init_file=C:/ProgramData/MySQL/<that file>` under `[mysqld]` in
   `C:\ProgramData\MySQL\MySQL Server 8.0\my.ini` (forward slashes).
4. `Restart-Service MySQL80` — the *service account* runs the statement.
5. Remove the `init_file` line, delete the file, restart again.

Back `my.ini` up first. Verify with `mysql.exe -h 127.0.0.1 -P 3307 -u root -p`.

**PowerShell gotchas that cost time last session:** `<` input redirection is
reserved (use `-e "source <file>"`); a quoted exe path needs the `&` call
operator; and `2>&1` on a native exe under `$ErrorActionPreference='Stop'` turns
a harmless stderr *warning* into a terminating error — which is how a *successful*
password reset reported itself as `FAILED`.

Also: MySQL resolves a `127.0.0.1` connection back to the hostname `localhost`,
so a user granted only on `'127.0.0.1'` gets "Access denied". Create both.

---

## 7. Picking up where this left off

**This was re-checked on 2026-08-22 and the results are in §1** — week 3 landed
(commit `9e8d316`), 120 tests pass, the frontend builds, migrations are clean.
Re-run the same checks after any break:

```bash
git log --oneline | head -20
git status --short
cd backend && .venv/bin/python -m pytest -q
cd ../frontend && npm run build
```

Then compare route counts (§1) against PRD §7.2 and §7.3 to see which endpoints
exist. `docs/PRD.txt` is a plain-text extract of the PRD — acceptance criteria
live there, not in code comments.

Endpoints live as of 2026-08-22 — auth (9), catalogue (`products/`,
`products/<slug>/`, `products/<slug>/related/`, `categories/`, `brands/`),
`addresses/` (viewset), `cart/` + `cart/items/` + `cart/merge/`,
`checkout/quote/`, `orders/` + `orders/<reference>/` + `.../cancel/`, and
`shipping/zones/`. Smoke-tested green against a running server; `cart/` returns
401 for an anonymous caller by design (the guest cart is client-side and merges
via `cart/merge/` on login).

**The next valuable step is week 4**: SSLCommerz + IPN, stock locking under
concurrency, shipping/tax. Note the gateway half is still blocked on the owner
(§14 Q1), but **the concurrency work is not** — `select_for_update` on order
confirmation and its zero-oversell test can be written today, and it is the
highest-risk item in the whole build (see below).

### The scraped dev catalogue — nothing is cached on this machine

**Status on macOS, 2026-08-22: `backend/scripts/data/` does not exist at all.**
No JSON, no cached images. The Windows box had ~830 products / 33 MB of photos
part-downloaded; none of that came across (the directory is gitignored, by
design — see §3). So the scrape must run from zero here, and the
"`download_images()` skips files already on disk" saving does not apply on a
first run.

The import command has still **never been run anywhere**, so expect to debug it
on first contact. Verification steps after importing are listed below.

Original notes follow.

### In flight when this was written: the scraped dev catalogue

`scripts/scrape_startech.py` and `apps/catalog/management/commands/import_startech.py`
were written and the scrape was **still running in the background** — about 830
products / 33 MB of photos downloaded. Rationale and design are in §3.

The scraper writes `scripts/data/startech_catalog.json` **only at the very end**,
so if that process did not finish, the JSON does not exist and the scrape must
be repeated. That is cheaper than it sounds: `download_images()` skips any file
already on disk, so a re-run re-fetches product HTML but not the photos already
downloaded.

Start here:

```bash
cd backend
ls scripts/data/startech_catalog.json   # exists -> skip straight to the import
ls scripts/data/images | wc -l          # products whose photos are already cached
```

Then re-run the scrape if needed (command in §5; do **not** pipe it through
`tail`, that buffers the whole run — watch `ls scripts/data/images | wc -l`
instead), and import.

**The import command has never been run.** `manage.py check` passes and that is
all that has been verified — expect to debug it on first contact. Afterwards,
confirm:

- every product has ≥1 variant, and `catalogue.listable_products().count()` > 0
- no category nested more than one level (`parent__parent__isnull=False` → 0)
- `sum(InventoryLog.delta) == sum(ProductVariant.stock)` — the ledger invariant
- then look at `/`, `/c/<slug>`, `/search`, `/p/<slug>` in the browser

Known gaps: `Category.image` is left blank (the nav carries no artwork), most
products will carry a compare-at price so the discount badge may become visual
noise, and long product names plus 45-row spec tables will stress the card and
detail layouts at 360px. The parsers (`parse_nav`, `parse_listing`,
`parse_product`, `parse_brands`) are regex-over-HTML against one theme and are
pure string→dict — they are the first place to look if counts come back zero,
and the obvious thing to cover with tests using saved HTML fixtures.

### Highest-risk work still ahead

1. ~~**Order confirmation under concurrency.**~~ **DONE 2026-08-22.**
   `apps/catalog/services/inventory.py` already sorted variant ids and locked
   them `FOR UPDATE`; that half needed no change. The week-4 exit criterion now
   exists as `apps/orders/tests/test_oversell_concurrency.py` — five tests with
   real threads, per-thread connections and `transaction=True` (marked `slow`).
   20 simultaneous orders against 5 units oversell zero times; 16 orders holding
   two variants in opposite line order deadlock zero times.
   **It found a separate, worse bug in reference allocation — see §4.**
2. **Payment confirmation.** The browser redirect is display-only and must never
   change order state. Only a server-validated IPN may confirm, it must compare
   paid amount *and* currency against the stored total, and it must be
   idempotent on replay.
3. **The admin dashboard** is called out in PRD §12.2 as the single largest
   schedule risk. Django Admin is already enabled as the fallback, so fulfilment
   is never blocked if it slips.

### Still blocked on the owner (PRD §14)

SSLCommerz merchant approval (§14 Q1 — can take weeks, blocks week 4), the VAT
rate, real shipping rates, the COD ceiling, the domain, the SMTP provider, and
the actual catalogue content. The rate-driven ones are configuration on
`StoreSettings` and `ShippingZone`, not code.
