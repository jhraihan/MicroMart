# Cart, checkout & orders API contract (week 3)

Frozen shape for the cart, checkout and order endpoints in PRD §7.2, written
in the same style as `api-contract-catalogue.md` so backend and frontend are
built against one document and cannot drift.

Conventions carried over: money is always a decimal string (`DECIMAL(12,2)`),
never a float; errors use the `{"error": {"code", "message", "field"}}`
envelope from PRD §7.1; list responses use the page-number pagination
envelope; object-level authorisation misses return **404, never 403**.

Two rules govern everything below:

- **Totals are server-side.** The client never adds, multiplies or discounts.
  Every figure a shopper sees comes from `POST /checkout/quote/` or from a
  stored order (FR-CRT-4, FR-CHK-6).
- **Nothing here reserves stock.** `stock` is reported so the UI can cap a
  quantity input. The decrement happens on order confirmation only
  (FR-INV-2).

---

## Cart

The server cart exists only for authenticated users (FR-CRT-1). Guests keep
their cart in `localStorage` and hand it over at `POST /cart/merge/` on login.

Mutations return the **whole cart**, not the touched line. A phone on a slow
connection should not pay for a second round trip to learn its new subtotal,
and returning the whole document removes any temptation to patch the total
client-side.

### GET /cart/ — Customer

```json
{
  "items": [
    {
      "id": 11,
      "variant_id": 4,
      "product_id": 2,
      "product_name": "Asus TUF Gaming F15 FX507",
      "product_slug": "asus-tuf-gaming-f15-fx507",
      "variant_label": "16GB / 512GB",
      "sku": "TUF-F15-16-512",
      "image": "/media/products/tuf-1.webp",
      "unit_price": "142000.00",
      "compare_at_price": "155000.00",
      "quantity": 2,
      "line_total": "284000.00",
      "stock": 12,
      "in_stock": true,
      "is_available": true,
      "issue": null
    }
  ],
  "item_count": 2,
  "subtotal": "284000.00",
  "notices": []
}
```

`issue` is `null` or one of `out_of_stock`, `insufficient_stock`,
`unavailable` (variant or product deactivated). `is_available` is the single
flag the UI blocks on, so the client never re-derives availability from
`stock` and `quantity`.

`notices[]` is `{"code", "message", "variant_id"?}` — the surface FR-CRT-5
requires for "changes since the item was added", and where a merge reports a
clamped line.

### POST /cart/items/ — Customer

```json
{ "variant_id": 4, "quantity": 1 }
```

Returns **200** with the full cart. Adding a variant already in the cart sums
the quantities. Quantity above available stock is clamped, and the clamp is
reported in `notices` rather than rejected — a 422 here would lose the add.

### PATCH /cart/items/{id}/ — Customer

```json
{ "quantity": 3 }
```

Returns 200 with the full cart. `quantity: 0` is a validation error; removal
is a DELETE. Another user's cart item is **404**.

### DELETE /cart/items/{id}/ — Customer

Returns 200 with the full cart (not 204 — same round-trip argument).

### POST /cart/merge/ — Customer

```json
{ "items": [{ "variant_id": 4, "quantity": 2 }] }
```

Quantities sum with any existing server line, then each line is clamped to
available stock and every clamp is reported in `notices` (FR-CRT-2). Returns
200 with the full cart. Already wired: `LoginPage` posts this immediately
after sign-in and then drops the local copy.

---

## POST /checkout/quote/ — Public

**The only place totals come from.** Called on the cart page, and again on
every checkout change to the district, the coupon, or a quantity.

Request — everything except `items` is optional:

```json
{
  "items": [{ "variant_id": 4, "quantity": 2 }],
  "district": "Dhaka",
  "coupon_code": "WELCOME10",
  "payment_method": "cod"
}
```

`items` is explicit in both the guest and the authenticated flow so there is
one code path. Prices, stock and eligibility are read server-side regardless
of what the client believes; the client's copy of a price is a display
snapshot with no authority.

Response (200):

```json
{
  "lines": [
    {
      "variant_id": 4,
      "product_id": 2,
      "product_name": "Asus TUF Gaming F15 FX507",
      "product_slug": "asus-tuf-gaming-f15-fx507",
      "variant_label": "16GB / 512GB",
      "sku": "TUF-F15-16-512",
      "image": "/media/products/tuf-1.webp",
      "unit_price": "142000.00",
      "quantity": 2,
      "line_total": "284000.00",
      "available_stock": 12,
      "is_available": true,
      "issue": null
    }
  ],
  "subtotal": "284000.00",
  "discount_total": "0.00",
  "shipping_total": "60.00",
  "tax_total": "0.00",
  "tax_rate_applied": "0.00",
  "grand_total": "284060.00",
  "currency": "BDT",
  "prices_include_tax": false,
  "zone": {
    "id": 1, "name": "Inside Dhaka", "flat_rate": "60.00",
    "cod_allowed": true, "free_shipping_threshold": null
  },
  "coupon": null,
  "coupon_error": null,
  "payment_methods": [
    { "code": "cod", "label": "Cash on Delivery", "available": true, "unavailable_reason": null },
    { "code": "online", "label": "Card / bKash / Nagad / Rocket", "available": true, "unavailable_reason": null }
  ],
  "notices": [],
  "can_place_order": true
}
```

**Before a district is known** — the cart page, and checkout before the
address is filled — `zone`, `shipping_total`, `tax_total` and `grand_total`
are **null** and `can_place_order` is false. Null, not `"0.00"`: a zero grand
total renders as a free order. The client shows "Calculated at checkout" and
blocks placement.

**A district in no zone** returns `zone: null`, null totals, and a
`{"code": "NO_SHIPPING_ZONE"}` notice. Only 13 districts are seeded, so this
is a live path, not a theoretical one.

**An invalid coupon never fails the quote.** It comes back as `coupon: null`
plus `coupon_error: {"code", "message"}` using the same codes as the validate
endpoint (`COUPON_EXPIRED`, `COUPON_MIN_NOT_MET`, `COUPON_USAGE_EXCEEDED`,
`COUPON_NOT_APPLICABLE`, `COUPON_INVALID` — FR-CPN-7). A coupon that goes
stale mid-checkout, or a typo, must not blank out the totals a shopper is
reading.

`can_place_order` is the server's own verdict — every line available, a zone
resolved, a payment method available. The client blocks on this flag instead
of re-deriving the rule, so cart and checkout cannot disagree with placement.

`payment_methods[].available` carries the COD cap and the zone's
`cod_allowed` (FR-PAY-1, FR-SHP-5) with a human reason. The UI disables the
option and prints the reason; it never decides COD eligibility itself.

### POST /checkout/coupon/validate/ — Public

`{"items": [...], "code": "WELCOME10"}` → 200 with the coupon and its computed
discount, or 422 with the envelope. Kept for parity with PRD §7.2; **this
client does not call it** — applying a coupon re-quotes instead, so there is
exactly one place totals are computed and one round trip per apply.

---

## Orders

### POST /orders/ — Public (guest checkout allowed, FR-CHK-5)

```json
{
  "idempotency_key": "3f1c9c8e-…",
  "items": [{ "variant_id": 4, "quantity": 2 }],
  "email": "shopper@example.com",
  "phone": "01712345678",
  "shipping_address": {
    "recipient_name": "Rafiq Hasan",
    "phone": "01712345678",
    "division": "Dhaka",
    "district": "Dhaka",
    "upazila": "Dhanmondi",
    "area": "Road 7",
    "street": "House 42, Road 7, Dhanmondi",
    "postcode": "1205"
  },
  "address_id": null,
  "save_address": false,
  "coupon_code": null,
  "payment_method": "cod",
  "note": ""
}
```

- `idempotency_key` is required (FR-CHK-7). A repeat with a key already on an
  order returns **200** with that order and creates nothing. The client keeps
  one key for the whole attempt including retries, and only mints a new one
  for a genuinely new attempt.
- `address_id` (authenticated only) selects a saved address instead of
  `shipping_address`. Either way the address is **copied onto the order**,
  never FK'd (FR-ORD-2).
- `save_address` (authenticated only) also writes it to the address book.
- Totals are **not** accepted from the client. They are recomputed here, a
  third time, and stored.
- On success the authenticated user's server cart is emptied.

**201** with the order detail shape below. Errors:

| status | code | field | when |
|---|---|---|---|
| 422 | `OUT_OF_STOCK` | `items` | a line went out of stock during checkout. The message **names the product and variant** (FR-CHK acceptance). |
| 422 | `CART_EMPTY` | `items` | no sellable line |
| 422 | `NO_SHIPPING_ZONE` | `shipping_address.district` | district in no zone |
| 422 | `COD_NOT_AVAILABLE` | `payment_method` | over the cap, or the zone forbids COD |
| 422 | `COUPON_*` | `coupon_code` | coupon invalid at placement (revalidated here) |
| 403 | `EMAIL_NOT_VERIFIED` | `email` | unverified account placing an order (FR-AUT-3) |
| 400 | `VALIDATION_ERROR` | the field | per-field validation |

On `OUT_OF_STOCK` the client re-quotes, which marks the offending lines with
their own `issue` — the naming appears both in the banner message and on the
line itself.

### GET /orders/ — Customer

Paginated (`page`, `page_size`), newest first:

```json
{
  "count": 3, "next": null, "previous": null,
  "results": [{
    "reference": "ORD-2026-000148",
    "status": "pending",
    "placed_at": "2026-08-19T09:12:44Z",
    "item_count": 3,
    "grand_total": "284060.00",
    "payment_method": "cod",
    "payment_status": "unpaid",
    "can_cancel": true,
    "items_preview": [
      { "product_name": "Asus TUF Gaming F15 FX507", "variant_label": "16GB / 512GB",
        "image": "/media/products/tuf-1.webp", "quantity": 2 }
    ]
  }]
}
```

`items_preview` is capped at 3 lines so the history list is scannable without
a second request per row.

### GET /orders/{reference}/ — Customer, or guest with `?email=`

```json
{
  "reference": "ORD-2026-000148",
  "status": "pending",
  "placed_at": "2026-08-19T09:12:44Z",
  "email": "shopper@example.com",
  "phone": "01712345678",
  "payment_method": "cod",
  "payment_status": "unpaid",
  "shipping_address": { "recipient_name": "…", "phone": "…", "division": "…",
                        "district": "…", "upazila": "…", "area": "…",
                        "street": "…", "postcode": "…" },
  "items": [{ "id": 1, "product_name": "…", "product_slug": "…",
              "variant_label": "16GB / 512GB", "sku": "…", "image": "…",
              "unit_price": "142000.00", "quantity": 2, "line_total": "284000.00" }],
  "subtotal": "284000.00",
  "discount_total": "0.00",
  "shipping_total": "60.00",
  "tax_total": "0.00",
  "tax_rate_applied": "0.00",
  "grand_total": "284060.00",
  "coupon_code": null,
  "zone_name": "Inside Dhaka",
  "note": "",
  "shipment": null,
  "status_logs": [{ "from_status": "", "to_status": "pending",
                    "actor_role": "customer", "note": "",
                    "created_at": "2026-08-19T09:12:44Z" }],
  "can_cancel": true
}
```

`items[].product_slug` is null once the product is gone — the snapshot still
renders, it just stops linking (FR-ORD-2). `shipment` is
`{"courier_name", "tracking_number", "shipped_at", "delivered_at"}` when one
exists (FR-ORD-7).

**Guest access.** A guest order (`user` null) is readable with
`?email=<the email that placed it>`; a mismatch is **404**, like every other
authorisation miss. Email is already the ownership key for a guest order —
FR-CHK-5 makes it the basis for claiming one later. An order that belongs to
a user account is never readable this way.

### POST /orders/{reference}/cancel/ — Customer

`{"reason": "Ordered the wrong variant"}` → 200 with the order detail. Legal
only from `pending` or `confirmed` (FR-ORD-4); anything else is 422
`ILLEGAL_TRANSITION` and is **not** logged. Cancelling from `confirmed`
restores stock and releases the coupon redemption (FR-INV-3, FR-CPN-8).

### POST /payments/initiate/ — Public

`{"order_reference": "ORD-2026-000148"}` →
`{"redirect_url": "https://sandbox.sslcommerz.com/…", "gateway": "sslcommerz", "session_key": "…"}`.

The client assigns `redirect_url` to `window.location`. The browser's return
to `/payments/callback/{result}/` is **display only** — order state changes on
the validated IPN alone (FR-PAY-3, FR-PAY-4). The confirmation page therefore
always reads `payment_status` from the order, never from the redirect it just
came back through, and offers a retry while an online order is still
`pending` and unpaid (FR-PAY-7).

---

## GET /shipping/zones/ — Public

```json
[{ "id": 1, "name": "Inside Dhaka", "flat_rate": "60.00", "per_kg_rate": "20.00",
   "base_weight_grams": 1000, "free_shipping_threshold": null,
   "cod_allowed": true, "districts": ["Dhaka", "Gazipur", "Narayanganj"] }]
```

Display only, so checkout can show what delivery will cost before an address
exists. The charge that gets billed is the one in the quote.
