# Running MicroMart

Two servers have to be running: Django on port 8000 and the React dev server on
port 5173. MySQL must be up before Django will start.

---

## Right now

Everything is already running. Open <http://localhost:5173> and the shop is
there. Skip to [The tour](#the-tour) below.

The rest of this page is for next time, after a reboot.

---

## Starting from cold

### 1. MySQL

Django will not start without it.

```powershell
Get-Service MySQL80
```

If it says Stopped:

```powershell
Start-Service MySQL80
```

It is set to start automatically, so normally there is nothing to do here.

### 2. Backend

Open a terminal in `backend/`:

```powershell
.venv\Scripts\python.exe manage.py runserver
```

Leave it running. You should see `Starting development server at
http://127.0.0.1:8000/`.

### 3. Frontend

Open a **second** terminal in `frontend/`:

```powershell
npm run dev
```

Leave that running too. It prints a `Local: http://localhost:5173/` line.

### 4. Open the shop

<http://localhost:5173>

> Always browse through **5173**, not 8000. The React dev server proxies
> `/api` calls through to Django, which keeps the browser on one origin so the
> login cookie works. Opening 8000 directly gives you the raw API, not the shop.

---

## Logins

Both accounts are created by `manage.py seed_demo`.

| Role | Email | Password |
|---|---|---|
| Customer | `shopper@example.com` | `Str0ngPass!2026` |
| Admin | `admin@example.com` | `ChangeMe!2026` |

---

## The tour

A route through the app that shows off the parts worth showing. Roughly ten
minutes.

### As a shopper

**1. Home** — <http://localhost:5173>
Nine merchandising rows built from the live catalogue. Hover the top navigation
to open the mega-menu, which is generated from the category tree rather than
hardcoded.

**2. Browse a category** — <http://localhost:5173/c/laptop>
Filter by brand, price and availability. Watch the URL: every filter is a query
parameter, so the page is shareable and the back button works. Facet counts
update with the filters.

**3. Search** — type in the header search box
Suggestions appear as you type. It uses MySQL full-text indexes, not
`LIKE '%term%'`.

**4. A product page** —
<http://localhost:5173/p/samsung-t7-1tb-portable-ssd>
Gallery, specification table, related products, and reviews with a Verified
Purchase badge. The badge is derived from a delivered order, not a flag anyone
can set.

**5. Compare** — click Compare on two or three product cards, then
<http://localhost:5173/compare>
A specification matrix built server-side. Capped at four, because beyond that
the table stops being readable.

**6. PC Builder** — <http://localhost:5173/pc-builder>
Pick a CPU, then a motherboard. Try deliberately mismatching the socket — an
AMD CPU with an Intel board — and the compatibility panel raises an error.
Findings come in three levels: `error` for a real conflict, `warning` for a
risk, `info` when a check could not run because the shop does not hold that
spec.

**7. Cart** — add something, then <http://localhost:5173/cart>
Do this while signed out. The cart is in `localStorage`, so a refresh keeps it.
Then sign in and watch it merge into the account cart.

**8. Checkout** — <http://localhost:5173/checkout>
Change the district and watch the shipping cost change. Apply a coupon --
`WELCOME10` takes 10% off, `FLAT500` takes a flat 500 taka. Every figure comes
from the server; the browser only displays them.
Place a Cash on Delivery order and you land on a confirmation page with an order
reference.

**9. Account** — <http://localhost:5173/account>
Order history, saved addresses, profile, password.

### As an admin

Sign in with the admin account, then <http://localhost:5173/admin>.

**Overview** — revenue windows, an orders-awaiting-action tile, a low-stock
count and a revenue chart.

**Orders** — `/admin/orders`
Open the order you just placed. Move it through the status pipeline:
`pending → confirmed → packed → shipped → delivered`. Two things to notice:
you cannot skip a step, and marking it shipped is refused until you add a
courier and tracking number. Every change appends to a timeline that records
who did it and when.

**Inventory** — `/admin/inventory`
Adjust a stock level. A reason is mandatory, and every movement writes a ledger
row. Summing those rows must equal the current stock.

**Products** — `/admin/products`
Full catalogue CRUD, with variants, images and specifications.

**Coupons** — `/admin/coupons`
Create one scoped to a category and try it at checkout — it should discount only
the eligible lines.

**Reviews** — `/admin/reviews`
The moderation queue. Approving a review recomputes the product's rating.

> `/admin/products`, `/admin/inventory`, `/admin/coupons`, `/admin/reviews` and
> `/admin/settings` are admin-only. A staff account can reach orders and
> nothing else — and that is enforced by the API, not by hiding the links.

### The API

**Swagger UI** — <http://127.0.0.1:8000/api/docs/>
All 64 endpoints, generated from the code. Expand any one and use **Try it out**
to call it live.

**Health checks**
- <http://127.0.0.1:8000/healthz/> — is the process alive
- <http://127.0.0.1:8000/readyz/> — is the database and cache reachable

**Django Admin** — <http://127.0.0.1:8000/django-admin/>
The operational fallback. Order status and variant stock are read-only here on
purpose: changing them has to go through the service that validates the
transition, moves stock and writes the audit row.

---

## Things worth demonstrating

If you are showing this to someone, these land better than clicking through
pages.

**Prices are computed server-side.** Open the browser dev tools network tab at
checkout, change the district, and show the `POST /checkout/quote/` request. The
browser sends what is in the basket; the server returns every figure.

**Money is never a float.** In the same response, prices are JSON *strings*
(`"92000.00"`), not numbers. JSON numbers are floats, which is how rounding
errors get into totals.

**Authorisation is server-side.** Sign in as the customer, then type
`localhost:5173/admin` in the address bar. You are redirected — and if you call
an admin endpoint directly from Swagger with a customer token, the API refuses
it. The React guard is a convenience, not the boundary.

**Someone else's order is a 404, not a 403.** In Swagger, fetch an order
reference that is not yours. A 403 would confirm the order exists, which leaks
the reference space.

---

## Running the tests

**Backend** — from `backend/`, takes about 22 minutes:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Faster, skipping the real-thread concurrency tests:

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not slow"
```

**Frontend** — from `frontend/`, a few seconds:

```powershell
npm run test
```

**End-to-end** — needs both servers running:

```powershell
npx playwright test
```

---

## Resetting the data

If the catalogue gets into a mess:

```powershell
.venv\Scripts\python.exe manage.py seed_demo      # logins, zones, coupons
.venv\Scripts\python.exe manage.py seed_catalog   # 117 products
```

Both are safe to re-run. They update what exists rather than duplicating it.

To start completely fresh, drop and recreate the database in MySQL Workbench,
then run `migrate` followed by both seed commands.

---

## When something is wrong

**The shop loads but every product area shows an error**
Django is not running, or it is running but MySQL is not. Check the backend
terminal.

**`Can't connect to MySQL server`**
`Start-Service MySQL80`.

**`Error: That port is already in use`**
An old server is still holding it. Find and stop it:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

Same command with `5173` for the frontend.

**Changes to Python files are not showing**
If you started the server with `--noreload`, it does not pick up edits. Restart
it, or drop the flag.

**Everything 429s**
You hit a rate limit. Development limits are deliberately high, so this usually
means a script is hammering an endpoint. Wait a minute.

**Signed out at random**
The access token lasts fifteen minutes and refreshes through a cookie. If it is
not refreshing, check you are on `localhost:5173` and not `127.0.0.1:5173` —
they are different origins to the browser, and the cookie is set for one of
them.

---

## Ports

| Port | What |
|---|---|
| 5173 | React dev server — **use this one** |
| 8000 | Django API, Swagger docs, Django Admin |
| 3306 | MySQL |
