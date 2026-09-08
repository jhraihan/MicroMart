# 006 — Stock is locked with SELECT FOR UPDATE at checkout

**Status:** accepted

## Context

One unit left. Two customers press Place Order at the same moment.

The naive version reads stock, sees `1`, and writes `0`. Both requests read
before either writes, so both see `1`, both sell it, and the shop owes a unit it
does not have. The window is milliseconds wide, which is why it survives casual
testing and shows up on the first busy day.

Checking stock in the cart does not help. A cart is a wish, not a reservation.

## Decision

Two rules.

**1. Stock moves only on order confirmation** — never on add-to-cart. Cash on
Delivery confirms at placement; an online order stays pending until the payment
is verified. An abandoned checkout leaves stock untouched.

**2. Confirmation runs inside one transaction that locks the rows it is about
to change:**

```python
ProductVariant.objects.select_for_update().filter(pk__in=ids).order_by("pk")
```

`SELECT ... FOR UPDATE` makes the second transaction wait until the first
finishes, so it re-reads stock as `0` and is refused. Stock is re-checked
*inside* the lock, and prices are read from the locked rows, so the price
charged is the price at the instant of sale.

**Locks are always taken in primary-key order.** Two checkouts holding
overlapping baskets in different orders would deadlock, and MySQL resolves a
deadlock by killing one transaction at random. Sorting the ids removes the
possibility.

There is also a database-level `CHECK (stock >= 0)` as a backstop, and every
movement writes an `InventoryLog` row — summing the deltas must reconcile to
the current stock.

## Consequences

- Overselling is prevented by the database, not by hopeful application code.
- Simultaneous checkouts serialise briefly. That is the intended trade: a short
  wait beats selling stock twice.
- It is MySQL-specific behaviour. SQLite ignores row-level locking, which is one
  reason the test suite requires MySQL.

## Where it lives

`apps/catalog/services/inventory.py` (`lock_variants`, `decrement_for_order`)
and `apps/orders/services/placement.py`. Tested under real threads in
`apps/orders/tests/test_oversell_concurrency.py`.
