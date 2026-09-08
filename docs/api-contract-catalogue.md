# Catalogue API contract (week 2)

Frozen shape for the endpoints in PRD §7.2. Backend and frontend are built
against this document so the two cannot drift. Money is always a decimal
string. All list responses use the pagination envelope from PRD §7.1.

## GET /api/v1/categories/

Full tree, one level of nesting. Inactive categories omitted.

```json
[{ "id": 1, "name": "Laptops", "slug": "laptops", "image": null,
   "product_count": 12,
   "children": [{ "id": 2, "name": "Gaming Laptops", "slug": "gaming-laptops",
                  "image": null, "product_count": 5, "children": [] }] }]
```

`product_count` counts active products, including those in child categories.

## GET /api/v1/brands/

```json
[{ "id": 1, "name": "Asus", "slug": "asus", "logo": null }]
```

## GET /api/v1/products/

Query parameters (FR-SRC-1..5). All are optional and independently combinable.

| param | type | notes |
|---|---|---|
| `q` | string | Keyword. FULLTEXT when >= 4 chars, LIKE fallback below that (FR-SRC-1). |
| `category` | slug, repeatable | Includes child-category products. Multiple values OR together. Inactive categories match nothing. |
| `brand` | slug, repeatable | Multiple values OR together, then AND with everything else. |
| `min_price` / `max_price` | decimal | Compared against the variant price range. |
| `in_stock` | bool | `true` keeps products with any variant stock > 0. |
| `min_rating` | 1-5 | Compared against `rating_avg`. |
| `has_discount` | bool | `true` keeps products whose cheapest sellable variant has a compare-at above its price -- the same test the badge uses. |
| `featured` | bool | `true` keeps editorially featured products. Drives the homepage rows. |
| `sort` | enum | `relevance` (search only), `price_asc`, `price_desc`, `newest`, `rating`, `best_selling`. Default `relevance` with `q`, else `newest`. |
| `page` / `page_size` | int | Default page_size 24, max 100. |

Response:

```json
{
  "count": 37,
  "next": "http://.../products/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Asus TUF Gaming F15 FX507",
      "slug": "asus-tuf-gaming-f15-fx507",
      "brand": { "id": 1, "name": "Asus", "slug": "asus" },
      "category": { "id": 2, "name": "Gaming Laptops", "slug": "gaming-laptops" },
      "primary_image": { "url": "/media/...", "alt_text": "..." },
      "price_min": "142000.00",
      "price_max": "178000.00",
      "compare_at_price": "155000.00",
      "discount_percent": 8,
      "in_stock": true,
      "total_stock": 22,
      "rating_avg": "0.00",
      "rating_count": 0,
      "variant_count": 3
    }
  ],
  "facets": {
    "brands":     [{ "slug": "asus", "name": "Asus", "count": 1 }],
    "categories": [{ "slug": "gaming-laptops", "name": "Gaming Laptops", "count": 1 }],
    "price":      { "min": "13500.00", "max": "178000.00" },
    "in_stock":   { "true": 6, "false": 1 },
    "ratings":    [{ "value": 4, "count": 0 }]
  }
}
```

**Facets reflect the current result set (FR-SRC-2)**, with one carve-out that
makes multi-select usable: a facet's own dimension is excluded from its own
count. Picking Asus must still show how many Lenovo products the *other*
filters would allow, otherwise every unselected brand reads zero and the
filter cannot be widened.

`compare_at_price` and `discount_percent` come from the cheapest active
variant, and are null / 0 unless that variant's compare-at exceeds its price
(FR-CAT-8).

**Visibility.** A product is listed only while its own `is_active` is set
*and* its category is active (and, for a child category, its parent too) —
the same rule `/categories/` applies, so the two endpoints never disagree
about what exists. A product in a deactivated category is absent from the
list, from every facet and from its detail route, and `?category=<that slug>`
matches nothing.

Brand is deliberately **not** part of that rule. A brand is a label on
sellable stock rather than a place in the navigation, so deactivating one
removes it from `/brands/` and from `facets.brands` but leaves its products
listed, searchable and buyable.

## GET /api/v1/products/{slug}/

Inactive products return **404** (FR-CAT-7). Adds to the list shape:

```json
{
  "description": "...",
  "model_number": "FX507ZC4-HN109W",
  "highlights": ["144Hz display", "RTX 3050 graphics"],
  "warranty_months": 24,
  "images": [{ "id": 1, "url": "...", "alt_text": "...", "variant_id": null,
               "sort_order": 0, "is_primary": true }],
  "specs": [{ "key": "Processor", "value": "Intel Core i7-12700H",
              "group": "Performance" }],
  "spec_groups": [{ "group": "Performance",
                    "rows": [{ "key": "Processor", "value": "Intel Core i7-12700H" }] }],
  "component": { "slot": "cpu", "label": "Processor" },
  "variants": [
    { "id": 1, "sku": "...-16-512", "option_label": "16GB / 512GB",
      "price": "142000.00", "compare_at_price": "155000.00",
      "discount_percent": 8, "stock": 12, "in_stock": true,
      "is_low_stock": false, "weight_grams": 2200,
      "images": [] }
  ]
}
```

`stock` is exposed as an integer so the UI can cap the quantity selector.
This is not a reservation — stock moves only on order confirmation.

**On detail only, `price_min`, `price_max` and `compare_at_price` are
nullable.** FR-CAT-7 gates the detail page on the product's own `is_active`
flag, so a product whose variants have all been deactivated still resolves
here — with `variants: []`, `in_stock: false`, `total_stock: 0`,
`variant_count: 0` and no price. Null is reported rather than `"0.00"`, which
would render as a free product. Clients must handle it; the list endpoint
never returns it, because a product with no active variant is not listable.

## GET /api/v1/products/{slug}/related/

Up to 8 active products from the same category, **excluding out-of-stock
items** and the product itself (FR-CAT-6). Returns a bare array of the list
shape above. No pagination.

## Errors

Standard envelope. A missing or inactive product is
`{"error": {"code": "NOT_FOUND", "message": "Not found."}}` with status 404.

## Out of scope for week 2

`FR-SRC-6` (search-as-you-type) is P2 and first on the PRD §12.3 cut list.
Deferred deliberately, not forgotten.


## Additions after the week-2 freeze

The shapes above are unchanged; everything below is **additive**, so a client
written against the frozen contract keeps working.

* `GET /products/{slug}/` gained `model_number`, `highlights` (a list of
  strings, often empty), `spec_groups` and `component`.
  * `spec_groups` is `specs` banded under headings, in the order the groups
    should render. It is served *alongside* the flat `specs` array rather than
    replacing it, because regrouping a flat array client-side loses the group
    order. A spec with no group lands under `"Specifications"`.
  * `component` is `null` for anything that is not a PC-builder part, and
    `{ "slot": "...", "label": "..." }` for one that is.
* `specs[]` rows gained `group` (a string, possibly empty).

### GET /api/v1/search/suggest/?q=

Type-ahead for the header box (FR-SRC-6). Below two characters every list is
empty. This is a prefix/substring lookup over names, model numbers, brands and
SKUs -- deliberately **not** the ranked full-text search, which needs whole
tokens a shopper part-way through a word has not typed yet.

```json
{
  "query": "ryz",
  "products": [ /* product card shape, at most 6 */ ],
  "categories": [ /* category shape, at most 4 */ ],
  "brands": [ /* brand shape, at most 4 */ ],
  "popular": ["gaming laptop", "ryzen processor"]
}
```

`popular` is a static list, not derived from traffic -- there is no analytics
store in v1, and deriving it from order counts would make it a bestseller list
wearing the wrong label.

### GET /api/v1/products/compare/?slugs=a,b,c

At most four products (`max` in the response states the cap). Returns them in
the order asked for, because the compare table's columns are the order the
shopper added them in.

```json
{
  "count": 2,
  "max": 4,
  "products": [ /* full detail shape */ ],
  "spec_matrix": [
    { "group": "General",
      "rows": [{ "key": "Socket", "values": ["AM4", "LGA1700"], "differs": true }] }
  ]
}
```

`spec_matrix` is the union of every spec key across the set. A product missing
a key gets `null` in its slot -- absence is information in a comparison, so it
is never collapsed with a blank value. `differs` is false when every product
reports the same value, which is what lets the UI offer "differences only".

### GET /api/v1/products/{slug}/bought-together/

A bare array (at most 3) of products that have actually shared a confirmed
order with this one. Real co-purchase data, so **an empty array is a normal
answer** on a young catalogue -- the detail page hides the section rather than
padding it with related products wearing a stronger claim than they can
support.
