# 003 — Money is DECIMAL, never a float

**Status:** accepted

## Context

Floats cannot hold most decimal fractions exactly. In Python, `0.1 + 0.2` is
`0.30000000000000004`. Run that through a cart with a few lines, a percentage
discount and VAT, and totals drift by a paisa — sometimes in the customer's
favour, sometimes not. Either way the books do not balance.

## Decision

Every money column is `DECIMAL(12,2)`, through a shared `MoneyField` in
`apps/common/fields.py`. Rounding goes through `quantize_money()`, which uses
`ROUND_HALF_UP`.

Over the API, money is serialised as a **string**, not a number. DRF's
`COERCE_DECIMAL_TO_STRING` is on. JSON numbers are IEEE floats, so sending
`46500.00` as a number hands the browser a float and undoes the whole point.

MySQL runs with `STRICT_TRANS_TABLES` so an out-of-range value is an error
rather than a silent truncation.

## Consequences

- Totals are exact and reproducible.
- The frontend must treat prices as strings and never do arithmetic on them.
  It does: `lib/money.js` formats for display only, and every total shown to a
  shopper is computed server-side.
- A payload built as a plain dict rather than through a serializer bypasses
  `COERCE_DECIMAL_TO_STRING`. That happened once in the PC builder and shipped
  a float price; `builds/services/builds._money()` exists to prevent it.

## Where it lives

`apps/common/fields.py`, `config/settings/base.py`, `frontend/src/lib/money.js`.
