# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

**Resuming after a break? Read [docs/HANDOFF.md](docs/HANDOFF.md) first.** It records
build state, contested ports, credentials locations, decisions taken, open issues, and the
PRD contradiction in §15.1 — none of which is recoverable from the code or git history.


Weeks 1 and 2 of the 6-week plan (PRD §12.1) are built and reviewed:

- **Week 1** — Django project, all nine apps, full data model + migrations, custom user model with JWT auth (refresh token in an HttpOnly cookie), Vite + React + Tailwind shell, shared UI primitives, seed command.
- **Week 2** — catalogue API (list, detail, related, search, facets, sort, pagination) and the storefront browse/search/detail pages. Contract frozen in `docs/api-contract-catalogue.md`.

- **Week 3** — cart, checkout quote, order placement/cancel, COD. Contract in `docs/api-contract-cart-checkout-orders.md`.
- **Week 5** — admin dashboard, coupons, reviews, wishlist. Contract in `docs/api-contract-admin-catalogue.md`.
- **Discovery + PC Builder** (2026-08-23) — 117-product seeded catalogue with
  real licensed imagery, mega-menu, type-ahead search, comparison, PC Builder,
  account area, offers/brands pages, SEO. See `docs/HANDOFF.md` §0 and
  `docs/api-contract-pc-builder.md`.

**Still not started: SSLCommerz + IPN** (blocked on the owner, PRD §14 Q1).
`payments/` has routes but no live gateway. **Verify what actually landed
rather than assuming** — `docs/HANDOFF.md` §1 has a route-count command that
answers this in one shot.

## Commands

Backend — run from `backend/`, with the venv at `backend/.venv`. Paths below are
macOS/Linux (`.venv/bin/python`); on Windows the same commands use
`.venv/Scripts/python.exe`.

```bash
.venv/bin/python manage.py runserver        # dev server on :8000
.venv/bin/python manage.py migrate
.venv/bin/python manage.py makemigrations
.venv/bin/python manage.py seed_demo        # logins, shipping zones, coupons, 7 products
.venv/bin/python manage.py seed_catalog     # the full 117-product demo catalogue (offline)
.venv/bin/python manage.py fetch_media      # real openly-licensed imagery (network)
.venv/bin/python scripts/scrape_startech.py # scrape a large dev catalogue (writes scripts/data/, gitignored)
.venv/bin/python manage.py import_startech  # load that scrape; idempotent, never resets stock
.venv/bin/python manage.py check
.venv/bin/python -m pytest                  # pytest-django; -q for quiet
.venv/bin/python -m pytest apps/orders      # single app
```

Frontend — run from `frontend/`:

```bash
npm run dev       # Vite on :5173, proxies /api and /media to :8000
npm run build     # production build; verifies the admin chunk still splits
npm run preview
npm run lint      # oxlint
```

First-time database setup (MySQL 8 on port 3307): edit and run `backend/scripts/create_database.sql`, then set `DATABASE_URL` in `backend/.env` (copy from `.env.example`).

Install backend deps with `.venv/bin/python -m pip install -r requirements/dev.txt`
(`requirements/` holds `base.txt`, `dev.txt`, `prod.txt` — there is no top-level
`requirements.txt`).

## Layout

```
backend/
  config/            settings/{base,dev,prod}.py, api_urls.py, exceptions.py, pagination.py
  apps/
    common/          MoneyField, TimeStampedModel, permission classes — shared, not a feature app
    accounts/ catalog/ cart/ orders/ payments/ promotions/ reviews/ shipping/ dashboard/
    builds/          PC Builder: compatibility rules + saved builds
      services/      business logic lives here, called by both storefront and admin views
    catalog/seed_data/  demo catalogue data, generated artwork, Wikimedia fetchers
frontend/
  src/
    lib/api.js       axios instance; access token in memory, refresh via HttpOnly cookie
    stores/          Zustand: authStore (not persisted), cartStore (persisted guest cart)
    components/ui/   Button, Input, Modal, Table, Badge, Spinner
    features/        route-group features: auth, catalog, cart, checkout, orders,
                     reviews, wishlist, account, compare, builder
    routes/          router + guards; admin group is lazy-loaded
    admin/           admin route group — code-split out of the shopper bundle
```

## Conventions established in the scaffold

- Services raise `config.exceptions.DomainError(message, code=..., field=...)`; the DRF exception handler turns it into the `{"error": {...}}` envelope from PRD §7.1. Views never build that envelope themselves.
- Money columns use `apps.common.fields.MoneyField` (`DECIMAL(12,2)`), and DRF is configured with `COERCE_DECIMAL_TO_STRING`.
- `Order.status` is read-only in Django Admin and must change through the order service, so the transition is validated, stock moves, and `OrderStatusLog` is written.
- `ProductVariant.stock` is read-only in Django Admin for the same reason — every movement writes an `InventoryLog` row.
- Tailwind tokens live in `frontend/src/index.css` under `@theme`, not in a JS config (Tailwind v4).

## What this is

A single-vendor electronics e-commerce web app for a store in Bangladesh (BDT ৳). One developer, 6-week MVP timeline. Full requirements are in `docs/PRD.html`; read it before implementing any feature area, since acceptance criteria live there, not in code comments.

**Locked decisions** (do not relitigate without the user):
- Single vendor only — no marketplace/seller onboarding, ever.
- Backend: Django + Django REST Framework, MySQL 8 (InnoDB, `utf8mb4`).
- Frontend: Vite + React SPA, Tailwind CSS. Admin dashboard is a role-gated route group in the *same* React app (code-split), not Django Admin.
- Payments: Cash on Delivery + SSLCommerz hosted checkout (cards/bKash/Nagad/Rocket). No other gateway.
- No Celery/Redis/background job queue in v1 — deliberately deferred. Low-stock digest runs as a cron-invoked Django management command; emails send inline.
- English UI only in v1; Bengali is v2.

## Architecture (target, per PRD §8)

```
Browser (mobile-first) → Nginx (TLS, static, reverse proxy)
                             ├── React SPA (Vite build)
                             └── Django + DRF (Gunicorn)
                                    ├── MySQL 8
                                    ├── Media storage (local dev / S3 via django-storages in prod)
                                    └── SMTP (transactional email)
SSLCommerz ──IPN (server-to-server)──► /api/v1/payments/ipn/
Customer ──redirect──► SSLCommerz ──redirect──► /payments/callback/
```

**Backend layering — this is the load-bearing rule**: `models → services → serializers → views`. All business logic (order placement, stock movement, coupon validation, payment confirmation) lives in `services/`, never in views or serializers. Both the storefront API and the admin API must call the *same* service functions so rules can't drift between the two surfaces.

Planned Django apps: `accounts`, `catalog`, `cart`, `orders`, `payments`, `promotions`, `reviews`, `shipping`, `dashboard`.

Frontend: React 18 + React Router, storefront and admin as route groups in one build. TanStack Query for server state, Zustand (+ persist middleware) for cart/UI state, React Hook Form + Zod for forms mirroring API schemas, Recharts for admin charts.

API base path is versioned from the start: `/api/v1/`. Admin endpoints live under `/api/v1/admin/` gated by an `IsAdminOrStaff` permission class with per-view role checks — hiding a button in React is never the access-control mechanism.

## Domain invariants (the parts that are easy to get wrong)

These come directly from the PRD and are the rules most likely to be violated by a naive implementation:

- **Price/stock live on `ProductVariant`, never on `Product`.** Every product has ≥1 variant (a default one if it has no real options), so pricing/stock logic never branches on "does this product have variants."
- **Stock only decrements on order confirmation** (COD placement or validated online payment) — never on add-to-cart. Cart-add never reserves stock.
- **Oversell prevention**: order confirmation runs inside a DB transaction using `SELECT ... FOR UPDATE` on the affected variant rows. Also backed by a DB-level `CHECK (stock >= 0)`.
- **Order totals are always computed server-side**, at cart view, at checkout, and again at placement. Client-side totals are display-only and never trusted — this applies to price, discount, shipping, and tax alike.
- **Payment confirmation requires server-side validation against SSLCommerz's validation API.** The browser success/fail/cancel redirect is UI-only and is never treated as proof of payment. The IPN handler re-validates the transaction and checks the paid amount against the stored order total before changing order state; it must be idempotent (a repeated IPN for an already-confirmed order is a no-op).
- **Order data is snapshotted, not referenced.** `OrderItem` copies product name, variant label, SKU, and unit price at purchase time; shipping address is copied onto the order, not FK'd to the address book; the tax rate applied is snapshotted too. Later catalogue/address/tax-rate edits must never rewrite historical orders.
- **Order status follows a strict state machine** (PRD §15.1): `pending → confirmed → packed → shipped → delivered`, with `cancelled`/`refunded` as terminal branches. Any transition not explicitly listed is rejected server-side with 422 and is not logged as a state change. Every transition writes an append-only `OrderStatusLog` row (actor, from/to status, timestamp).
- **Every stock movement writes an append-only `InventoryLog` row** (variant, delta, reason, actor, timestamp). Summing deltas should reconcile to current stock.
- **Object-level authorization**: a user can only read their own orders/addresses/cart/wishlist. Accessing another customer's order by ID must return 404, not 403 (403 confirms the record exists).
- **Reviews require a `delivered` order containing the product** — enforced server-side, not just hidden in the UI. One review per (product, user), editable within 30 days, enters a `pending` moderation queue; only `approved` reviews count toward the denormalized `rating_avg`/`rating_count` on `Product`.
- **Coupons**: one per order (no stacking), validated server-side on every recalculation and again at placement, scoped to all/category/product. Redemption is per-user logged and released if the order is cancelled pre-shipment.
- **Idempotent order placement**: a client-generated idempotency key prevents duplicate orders from double-submit or retry.
- **Money is always `DECIMAL(12,2)`**, serialized as decimal strings over the API — never floats. A payload built as a plain dict rather than through a serializer bypasses DRF's `COERCE_DECIMAL_TO_STRING` and will ship a float unless it formats the value itself.
- **Externally-licensed images carry their credit.** CC BY / CC BY-SA make displaying the author and licence a *condition of use*, so `ProductImage.source_url/license_name/attribution` travel with the file and the gallery renders them. An image whose licence cannot be confirmed as open is skipped, never guessed at.
- **PC-builder compatibility is advisory and must be labelled so.** The rules compare the specs this store holds; they are not a manufacturer guarantee, and every verdict response carries an `advisory` string that clients must surface.

## Non-functional bars (PRD §9–§10)

- Mobile-first, must be fully usable one-handed at 360px width; WCAG 2.1 AA contrast; keyboard-operable with visible focus rings.
- Product list API p95 < 500ms, product detail p95 < 400ms — avoid N+1s, use `select_related`/`prefetch_related`.
- No card data ever touches this application (SSLCommerz hosted checkout keeps PCI scope minimal).
- `DEBUG=False` and strict `ALLOWED_HOSTS` in production; secrets only from environment variables (full list in PRD §15.3), nothing sensitive committed.
- Refresh tokens in `HttpOnly`/`Secure`/`SameSite=Lax` cookies; access token in memory only — neither in `localStorage`.

## Design system

`docs/design-system.md` is a reverse-engineered reference palette/component spec (from a StarTech-style OpenCart theme), not a mandate — treat its tokens (colors, spacing scale, radii, component CSS) as a starting point for Tailwind config and shared primitives (Button, Input, Modal, Table, Badge), and prefer its accessibility fixes (§8 of that doc) over the source site's actual behavior, e.g. use `--s-primary-dark` (#d51e0b) for text instead of `--s-primary` (#ef4a23), which fails AA contrast on white.

## Non-goals (do not build without an explicit ask)

No marketplace/multi-vendor, no POS/accounting system, no warehouse/bin-location tracking, no native mobile app, no returns/RMA workflow, no loyalty/referrals, no live chat, no multi-currency/multi-language, no recommendation engine beyond same-category related products, no courier API integration (tracking numbers are manual in v1), no gift cards, no abandoned-cart recovery emails, no gateway-initiated refunds (refunds are admin-recorded manually).
