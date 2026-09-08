# PC Builder API contract

The endpoints behind the PC Builder and saved builds. Money is a decimal
string throughout, as everywhere else in this API.

**The compatibility verdict is advisory and every response says so.** These
rules are this application's own comparison of the specifications it holds —
socket, memory generation, board form factor, card length, cooler height and
power draw. They are not a manufacturer compatibility list, and they say
nothing about BIOS revisions, memory QVLs, chipset lane budgets or radiator
clearance. No client may present a passing verdict as a certification; the
`advisory` string is returned on every verdict response so there is always
something honest to render.

---

## Slots

`ComponentSlot` is a closed set, because the rules are written against it:

    cpu  cooler  motherboard  ram  gpu  ssd  hdd  psu  case  monitor  keyboard  mouse

A slot is **not** a category. Categories are navigation and may be renamed,
nested or merged by whoever runs the shop; a slot is the key the compatibility
code switches on.

### GET /api/v1/pc-builder/slots/

Served rather than duplicated in the client, so the two cannot drift on which
slots are required or what order they render in.

```json
{ "slots": [
  { "slot": "cpu", "label": "Processor", "required": true, "peripheral": false },
  { "slot": "monitor", "label": "Monitor", "required": false, "peripheral": true }
] }
```

`required` marks what a machine needs to POST. Storage is the carve-out:
neither `ssd` nor `hdd` is individually required, but a build with neither
reports `ssd` in `missing_slots`.

---

## GET /api/v1/pc-builder/components/

| param | notes |
|---|---|
| `slot` | **required**. Unknown slots return 422 `INVALID_SLOT`. |
| `selected` | Compact form: `cpu:12,motherboard:34`. What is already chosen. |
| `compatible_only` | Default `true`. `false` shows every part in the slot. |
| `q` | Substring match on the product name. |
| `brand` | Brand slug. |

Only active, in-stock products of that slot are returned — offering a part the
builder cannot then add to a cart is the most annoying thing a configurator
does.

**Narrowing is a convenience, not the check.** `compatible_only` applies only
the rules that are unambiguous and cheap in SQL (socket, memory type, board
form factor); everything else is left to `/validate/`, which sees the whole
build. A filter that guessed would hide parts that are actually fine, and a
shopper cannot debug an absence — which is why the filter can always be turned
off.

```json
{
  "slot": "motherboard",
  "count": 2,
  "results": [{
    "product_id": 12, "name": "MSI PRO B550M-A WiFi", "slug": "msi-pro-b550m-a-wifi",
    "brand": "MSI", "category": "Motherboard", "image": "/media/...",
    "variant_id": 34, "sku": "TT-...", "variant_label": "",
    "price": "13500.00", "compare_at_price": "15200.00",
    "stock": 15, "in_stock": true,
    "rating_avg": "4.50", "rating_count": 2,
    "attributes": { "Socket": "AM4", "Form factor": "Micro-ATX", "Memory": "DDR4", "Slots": "4" }
  }]
}
```

`attributes` is display-only, formatted per slot — enough to tell two boards
apart in a picker without opening both.

---

## POST /api/v1/pc-builder/validate/

Stateless. Nothing is written, so the panel may revalidate on every change.

```json
{ "items": [{ "slot": "cpu", "variant_id": 12, "quantity": 1 }] }
```

One part per slot: a repeated slot is 422 `DUPLICATE_SLOT`. Quantity is 1–4.

```json
{
  "lines": [{
    "slot": "cpu", "variant_id": 12, "quantity": 1,
    "issue": null,
    "product": { "id": 3, "name": "...", "slug": "...", "brand": "AMD",
                 "variant_label": "", "sku": "TT-...",
                 "price": "16500.00", "compare_at_price": "18900.00",
                 "stock": 26, "image": "/media/..." }
  }],
  "subtotal": "16500.00",
  "is_compatible": true,
  "is_complete": false,
  "estimated_watts": 140,
  "recommended_psu_watts": 350,
  "power_is_estimated": false,
  "missing_slots": ["motherboard", "ram", "psu", "case", "ssd"],
  "findings": [{ "level": "info", "code": "NO_DISCRETE_GPU",
                 "message": "...", "slots": ["gpu"] }],
  "advisory": "Compatibility checks are this store's own guidance..."
}
```

`issue` is `null`, `out_of_stock` or `unavailable`. A variant that no longer
exists comes back as an `unavailable` line with `product: null` rather than
vanishing — a configurator that silently drops a part the shopper picked is
worse than one that explains.

### Finding levels

Three, and the distinction is load-bearing: merging them either cries wolf
over a gap in our own data or buries a genuine conflict.

| level | meaning |
|---|---|
| `error` | Two **known** values conflict. `is_compatible` is false. |
| `warning` | A real risk — thin PSU headroom, an undersized cooler. Still compatible. |
| `info` | A check could not run because a value is missing, or a prompt. |

Codes: `SOCKET_MISMATCH`, `SOCKET_UNKNOWN`, `COOLER_SOCKET_MISMATCH`,
`COOLER_UNDERSIZED`, `COOLER_RECOMMENDED`, `COOLER_TOO_TALL`,
`RAM_TYPE_MISMATCH`, `RAM_TYPE_UNKNOWN`, `RAM_SLOTS_EXCEEDED`,
`RAM_CAPACITY_EXCEEDED`, `FORM_FACTOR_MISMATCH`, `FORM_FACTOR_UNKNOWN`,
`GPU_TOO_LONG`, `NO_DISCRETE_GPU`, `PSU_INSUFFICIENT`, `PSU_TIGHT`,
`PSU_WATTAGE_UNKNOWN`, `POWER_PARTIALLY_ESTIMATED`.

### Power model

Steady-state draw only: `BASE_SYSTEM_WATTS` (75W for board, fans and USB) plus
each non-peripheral part's `power_watts` (or a CPU's `tdp_watts`), times its
quantity. Peripherals are excluded — a monitor is plugged into the wall.

It is deliberately **not** a peak-power model. Transient spikes on a modern
GPU can briefly double its rated draw, which is a PSU-quality question this
store holds no data to answer; the 1.3× headroom factor stands in for it.

Where a part carries no figure at all, a typical value is used **and
`power_is_estimated` is set**, with a `POWER_PARTIALLY_ESTIMATED` finding. A
silent default is how a wattage estimate becomes confidently wrong.

---

## Saved builds

### GET / POST `/api/v1/builds/` — authenticated

`GET` lists this account's builds; `POST` saves one and mints a share token.
Saving needs an account only because there would otherwise be no way to list
it back — a guest can build and validate freely. Limit: 25 per account
(`BUILD_LIMIT_REACHED`). An empty build is 422 `EMPTY_BUILD`.

### GET `/api/v1/builds/{token}/` — **public**

The token *is* the read capability: 132 bits of URL-safe randomness, and a
link you send someone has to work when they open it — they are, by definition,
not signed in as you. It grants nothing but reading that build.

Returns the `/validate/` shape plus `id`, `name`, `share_token`, `created_at`,
`updated_at` and `is_owner`.

**A build stores variant ids, never prices.** Totals and the compatibility
verdict are recomputed on every read, so a link shared in March quotes March's
price and re-checks against the catalogue as it is then. The stored
`is_compatible` is advisory bookkeeping and is never trusted on read.

### PUT / DELETE `/api/v1/builds/{token}/` — owner only

A non-owner gets **404, not 403** — the same rule as the rest of this API, so
a probe cannot confirm a build exists. `PUT` replaces the items wholesale.
