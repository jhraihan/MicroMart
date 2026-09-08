# Admin catalogue & inventory API contract (week 5)

Frozen shape for the catalogue half of PRD §7.3 — products, variants,
categories, brands and inventory. Backend and frontend are built against this
document so the two cannot drift, exactly as with
`api-contract-catalogue.md` (storefront) and
`api-contract-cart-checkout-orders.md`.

Money is always a decimal **string**. List responses use the pagination
envelope from PRD §7.1. Errors use the envelope from PRD §7.1:
`{"error": {"code": "...", "message": "...", "field": "..."}}` — codes are
stable and safe to branch on, messages are not.

Routes live in `backend/apps/catalog/admin_urls.py`, mounted at the `admin/`
prefix in `config/api_urls.py` alongside `apps/reviews/admin_urls.py`.

---

## Authorisation — Admin only

Every endpoint in this document is `IsAdminRole`. **A staff user gets 403 on
all of them**, per PRD §4.3 US-A8: staff may view orders and update order
status, and nothing else. An anonymous caller gets 401.

| caller | status |
|---|---|
| anonymous | 401 |
| customer | 403 |
| staff | 403 |
| admin | 200 |

Pinned by `apps/catalog/tests/test_admin_permissions.py`, which asserts the
matrix against **every** (route, method) pair rather than a sample. Hiding the
screens in React is a convenience on top of this, never the control.

---

## Four rules that shape these endpoints

1. **Stock is not a writable field.** `PATCH /admin/variants/{id}/` carrying
   `stock` is refused with `422 STOCK_NOT_WRITABLE` — not ignored. Stock moves
   only through `POST /admin/inventory/adjust/`, which writes an append-only
   `InventoryLog` row, so `sum(InventoryLog.delta)` keeps reconciling to
   `ProductVariant.stock` (PRD §6.4). The single exception is variant
   *creation*, where an opening quantity is written through the same ledger
   with reason `initial`.
2. **DELETE deactivates.** Products, variants, categories and brands all answer
   DELETE by setting `is_active = false` and returning `200` with the updated
   object. Nothing is destroyed: orders keep their `OrderItem.variant` FK,
   `Product.category` is `PROTECT`, and a deactivation can be undone with a
   `PATCH {"is_active": true}`.
3. **A product always keeps ≥ 1 active variant** (FR-CAT-4). Price and stock
   live on the variant, so a product with none has no price at all.
   `POST /admin/products/` **requires at least one variant in the payload** —
   it is refused (`PRODUCT_REQUIRES_VARIANT`), not auto-filled, because a
   server-invented SKU and price would be a placeholder that could later be
   snapshotted onto a real order line. A product with no options simply sends
   one variant with a blank `option_label`. Deactivating the last active
   variant is refused with `LAST_VARIANT`.
4. **Categories nest one level** (FR-CAT-1). A parent that already has a parent
   is refused with `CATEGORY_NESTING_TOO_DEEP`.

---

## Products

### `GET /api/v1/admin/products/`

Every product, active or not.

| param | type | notes |
|---|---|---|
| `q` | string | Matches product name, slug, or any of its variants' SKUs. |
| `category` | slug | Includes child-category products. |
| `brand` | slug | |
| `is_active` | bool | Omit for both. |
| `low_stock` | bool | Products with an active variant at or below its own threshold. |
| `sort` | enum | `newest` (default), `oldest`, `name`, `updated`. |
| `page` / `page_size` | int | Default 24, max 100. |

A bad `sort` is `422 INVALID_SORT`; a bad boolean is `422 INVALID_FILTER`.
Filters are never silently dropped.

```json
{
  "count": 37, "next": null, "previous": null,
  "results": [{
    "id": 1,
    "name": "Asus Vivobook Go 15",
    "slug": "asus-vivobook-go-15",
    "category": { "id": 2, "name": "Laptops", "slug": "laptops" },
    "brand": { "id": 1, "name": "Asus", "slug": "asus" },
    "primary_image": { "id": 9, "url": "/media/...", "alt_text": "Front" },
    "price_min": "62500.00",
    "price_max": "74900.00",
    "total_stock": 9,
    "has_low_stock": false,
    "variant_count": 2,
    "active_variant_count": 2,
    "image_count": 3,
    "is_active": true,
    "rating_avg": "4.50",
    "rating_count": 12,
    "created_at": "2026-08-22T09:00:00+06:00",
    "updated_at": "2026-08-22T09:00:00+06:00"
  }]
}
```

`price_min` / `price_max` / `total_stock` / `has_low_stock` cover **active**
variants only, and are `null` / `0` / `false` when there are none. The list
costs a constant number of queries regardless of page size — pinned by
`test_admin_query_counts.py`.

### `POST /api/v1/admin/products/` → `201`

The whole US-A2 form in one payload.

```json
{
  "name": "Asus Vivobook Go 15",
  "slug": "",
  "description": "A 15-inch everyday laptop.",
  "category_id": 2,
  "brand_id": 1,
  "warranty_months": 24,
  "is_active": true,
  "specs": [{ "key": "Processor", "value": "AMD Ryzen 5 7520U", "sort_order": 0 }],
  "variants": [{
    "sku": "VIVO-8-512",
    "option_label": "8GB / 512GB",
    "price": "62500.00",
    "compare_at_price": null,
    "stock": 7,
    "low_stock_threshold": 3,
    "weight_grams": 1630,
    "is_active": true
  }]
}
```

- `slug` is derived from `name` when blank, and de-duplicated (`-2`, `-3`, …).
- `stock` is an **opening** quantity, written through the ledger with reason
  `initial`. Omitted means 0 and no ledger row.
- Creation is atomic: a colliding SKU on the second variant leaves no product
  behind.

Responds with the detail shape below.

### `GET / PATCH / DELETE /api/v1/admin/products/{id}/`

`PATCH` accepts `name`, `slug`, `description`, `category_id`, `brand_id`,
`warranty_months`, `is_active`, `specs`. **Variants are not accepted here** —
they have their own endpoint, because each owns a price, an SKU and a stock
ledger.

`specs` is replace-the-whole-table: sending a list swaps every row, `[]`
clears them, omitting the key leaves them alone.

`DELETE` deactivates and returns `200` with the product. Repeat calls are a
no-op, not an error. A deactivated product leaves the storefront list and its
detail page 404s — and **never alters an order already placed**, which reads
from its own snapshot (PRD §6.3).

Detail shape = the list row plus:

```json
{
  "description": "...",
  "warranty_months": 24,
  "variants": [ /* variant objects, see below */ ],
  "images":   [ /* image objects, see below */ ],
  "specs":    [ { "key": "Processor", "value": "AMD Ryzen 5 7520U", "sort_order": 0 } ]
}
```

---

## Product images

### `POST /api/v1/admin/products/{id}/images/` → `201`

`multipart/form-data`.

| field | notes |
|---|---|
| `image` | Required. Verified with Pillow — a `.txt` renamed `.jpg` is `400`, field `image`. Max 5 MB (`422 IMAGE_TOO_LARGE`). |
| `alt_text` | Optional. |
| `variant_id` | Optional; must belong to this product (`422 VARIANT_NOT_FOUND`). |
| `is_primary` | Optional. Claims the primary flag from whoever holds it. |
| `sort_order` | Optional; defaults to the end of the gallery. |

```json
{ "image": { "id": 9, "url": "/media/products/2026/08/x.png", "alt_text": "Front",
             "variant_id": null, "sort_order": 0, "is_primary": true },
  "images": [ /* the whole gallery, in order */ ] }
```

While a product has any image, **exactly one** of them is primary. The first
upload becomes primary automatically.

### `PATCH /api/v1/admin/products/{id}/images/`

Reorder. `order` must list **every** one of the product's image ids
(`422 IMAGE_ORDER_INCOMPLETE`; duplicates are `IMAGE_ORDER_DUPLICATE`; a
foreign id is `IMAGE_NOT_FOUND`).

```json
{ "order": [12, 9, 10], "primary_id": 9 }
```

`sort_order` is rewritten to the given sequence. **The primary flag does not
move** unless `primary_id` names a new one — sorting and designating are two
different decisions.

### `GET /api/v1/admin/products/{id}/images/` — the gallery
### `DELETE /api/v1/admin/products/{id}/images/{image_id}/`

Removes the image for real (nothing snapshots it). If it was primary, the next
image in order inherits the flag. Both return `{"images": [...]}`.

---

## Variants

### `GET /api/v1/admin/variants/`

| param | notes |
|---|---|
| `q` | SKU or product name. |
| `category` | slug, includes children. |
| `product` | product id. |
| `low_stock` | bool. |
| `include_inactive` | bool. Default `false` — inactive variants and variants of inactive products are hidden. |

```json
{
  "id": 5,
  "product_id": 1,
  "product_name": "Asus Vivobook Go 15",
  "product_slug": "asus-vivobook-go-15",
  "product_is_active": true,
  "sku": "VIVO-8-512",
  "option_label": "8GB / 512GB",
  "price": "62500.00",
  "compare_at_price": null,
  "discount_percent": 0,
  "stock": 7,
  "low_stock_threshold": 3,
  "in_stock": true,
  "is_low_stock": false,
  "weight_grams": 1630,
  "is_active": true
}
```

### `POST /api/v1/admin/variants/` → `201`

Body is the variant object above plus `product_id`. `stock` is the opening
quantity and goes through the ledger. An unknown `product_id` is `404`.

### `GET / PATCH / DELETE /api/v1/admin/variants/{id}/`

`PATCH` accepts `sku`, `option_label`, `price`, `compare_at_price`,
`low_stock_threshold`, `weight_grams`, `is_active`.

**`stock` is refused**:

```json
{ "error": { "code": "STOCK_NOT_WRITABLE", "field": "stock",
             "message": "Stock is not editable here. Use /api/v1/admin/inventory/adjust/, which records the movement and its reason." } }
```

A payload mixing `stock` with a legal field is refused whole — nothing is
partially applied.

`DELETE` deactivates. The product's last active variant cannot be deactivated,
by DELETE or by `PATCH {"is_active": false}` — both give `422 LAST_VARIANT`.

---

## Categories

`GET / POST /api/v1/admin/categories/` — unpaginated, includes inactive.
`GET / PATCH / DELETE /api/v1/admin/categories/{id}/`.

```json
{ "id": 2, "name": "Laptops", "slug": "laptops",
  "parent_id": null, "parent_name": null, "image": null,
  "sort_order": 0, "is_active": true, "product_count": 12 }
```

Write fields: `name`, `slug` (derived from `name` when blank), `parent_id`,
`sort_order`, `is_active`, `image` (multipart).

Three refusals keep the taxonomy two levels deep:

| code | when |
|---|---|
| `CATEGORY_NESTING_TOO_DEEP` | the chosen parent already has a parent |
| `CATEGORY_HAS_CHILDREN` | this category has children, so it cannot become one |
| `CATEGORY_SELF_PARENT` | a category cannot be its own parent |

`DELETE` deactivates, which **withdraws the products inside it** from the
storefront — a category is a place in the navigation.

## Brands

`GET / POST /api/v1/admin/brands/` — unpaginated, includes inactive.
`GET / PATCH / DELETE /api/v1/admin/brands/{id}/`.

```json
{ "id": 1, "name": "Asus", "slug": "asus", "logo": null,
  "is_active": true, "product_count": 12 }
```

`DELETE` deactivates, and — deliberately asymmetric with categories, see
`docs/HANDOFF.md` §3 — the brand's products **stay listed and buyable**. Only
the public brand list and the brand facet lose it.

---

## Inventory

### `GET /api/v1/admin/inventory/`

Same parameters as `GET /admin/variants/`. `?low_stock=true` is the reorder
list, and returns exactly what the low-stock digest would send — both read
`apps/catalog/services/inventory.low_stock_variants()`. "At or below the
variant's own threshold", so zero-stock variants are included and sort first.

```json
{
  "count": 3, "next": null, "previous": null,
  "results": [{ /* variant object, plus: */
    "category_name": "Laptops",
    "brand_name": "Asus"
  }],
  "summary": { "variant_count": 42, "low_stock_count": 3, "out_of_stock_count": 1 }
}
```

`summary` is counted over the whole catalogue, not the page.

### `POST /api/v1/admin/inventory/adjust/` → `200`

```json
{ "variant_id": 5, "delta": 5, "reason": "restock", "note": "Delivery from supplier" }
```

`reason` is **mandatory** (FR-INV-8) and must be one of `restock`,
`manual_adjustment`, `damage`. The order-driven reasons (`order_confirmed`,
`order_cancelled`) and `initial` cannot be typed in by hand — those are written
by the order state machine and by variant creation. `delta` must be non-zero.

```json
{ "variant": { /* inventory row */ },
  "log": { "id": 77, "delta": 5, "reason": "restock", "note": "Delivery from supplier",
           "created_at": "...", "actor_email": "owner@example.com",
           "order_reference": null },
  "logged_stock": 12 }
```

`logged_stock` is `sum(InventoryLog.delta)` for the variant. It is returned
beside `variant.stock` so a drift between the two is visible rather than
theoretical — they must always be equal.

### `GET /api/v1/admin/inventory/{variant_id}/logs/`

The audit trail behind one number. Not in PRD §7.3's table, but the ledger is
the whole justification for refusing a direct stock write.

```json
{ "variant_id": 5, "stock": 12, "logged_stock": 12,
  "logs": [ /* most recent first, 50 max */ ] }
```

---

## Error codes

| code | status | field | meaning |
|---|---|---|---|
| `STOCK_NOT_WRITABLE` | 422 | `stock` | PATCH a variant with `stock`; use the adjust endpoint |
| `SKU_TAKEN` | 422 | `sku` | SKU already in use |
| `SKU_REQUIRED` | 422 | `sku` | blank SKU |
| `INVALID_PRICE` | 422 | `price` / `compare_at_price` | negative money |
| `INVALID_STOCK` | 422 | `stock` | negative opening stock |
| `PRODUCT_REQUIRES_VARIANT` | 422 | `variants` | product created with no variants |
| `LAST_VARIANT` | 422 | `variant_id` | would leave the product with none |
| `SLUG_TAKEN` | 422 | `slug` | product / category / brand slug in use |
| `CATEGORY_REQUIRED` | 422 | `category_id` | |
| `CATEGORY_NOT_FOUND` | 422 | `category_id` / `parent_id` | |
| `BRAND_NOT_FOUND` | 422 | `brand_id` | |
| `VARIANT_NOT_FOUND` | 422 | `variant_id` | unknown, or not on this product |
| `CATEGORY_NESTING_TOO_DEEP` | 422 | `parent_id` | FR-CAT-1 |
| `CATEGORY_HAS_CHILDREN` | 422 | `parent_id` | FR-CAT-1 |
| `CATEGORY_SELF_PARENT` | 422 | `parent_id` | |
| `IMAGE_REQUIRED` | 422 | `image` | |
| `IMAGE_TOO_LARGE` | 422 | `image` | over 5 MB |
| `IMAGE_NOT_FOUND` | 422 | `order` / `image_id` / `primary_id` | not this product's image |
| `IMAGE_ORDER_INCOMPLETE` | 422 | `order` | reorder must list every image |
| `IMAGE_ORDER_DUPLICATE` | 422 | `order` | same id twice |
| `REASON_REQUIRED` | 422 | `reason` | manual adjustment with no reason |
| `INVALID_REASON` | 422 | `reason` | order-driven reason typed by hand |
| `INVALID_DELTA` | 422 | `delta` | adjustment of zero |
| `INSUFFICIENT_STOCK` | 422 | `items` | adjustment would take stock below zero |
| `INVALID_FILTER` / `INVALID_SORT` | 422 | the parameter | nonsense query parameter |

Field-shaped payload errors (missing `name`, a non-image upload) come back as
`400` with the offending field named. Note the envelope reports one field: for
an error inside the nested `variants` list, price and stock validation is done
in the service precisely so the field name is `price` rather than `variants`.
