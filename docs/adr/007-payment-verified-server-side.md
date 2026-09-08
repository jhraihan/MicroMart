# 007 — A payment counts only when the gateway confirms it to our server

**Status:** accepted

## Context

After paying, SSLCommerz sends the customer back to a URL like
`/payments/callback/success/`.

Anyone can type that URL. If the application marks an order paid because the
browser arrived at the success address, then free merchandise is one address-bar
edit away.

The gateway also sends a separate server-to-server notification (an IPN). That
is better, but the notification is just an HTTP request — anyone who knows the
endpoint can post to it, claiming any amount for any order.

## Decision

**The browser callback reads nothing and writes nothing.** It shows a message
and redirects. It does not even look the order up: reporting "this reference is
confirmed" to whoever opens the URL would turn a display page into an oracle
over the reference space. The screen the customer lands on reads the order back
through the normal authenticated API and shows whatever status the server
actually holds.

**Only the IPN handler can confirm an order, and it trusts one thing: its own
outbound call to SSLCommerz's validation API.** From the incoming notification
it reads exactly one field — `val_id` — and treats it as a lookup key, not as a
claim.

Everything that decides the outcome comes from the validation *response*:

- **which order this is about.** The reference is taken from the validation
  response, not the notification. Otherwise a forged body could aim a real,
  validated ৳500 payment at a ৳200,000 order.
- **the status**, which must be a success status.
- **the currency**, which must be BDT.
- **the amount**, compared against the order total stored at placement.

Only then does it call the same `confirm_order` the Cash on Delivery path uses,
so stock movement and the audit log work identically however an order is paid.

Idempotency comes from locking the order row *before* reading its status, so two
notifications arriving together serialise and the second sees the first's work.
A replayed IPN is acknowledged and ignored.

## Consequences

- A payment cannot be faked by editing a URL or posting a forged notification.
- Confirmation depends on the gateway being reachable. If validation fails the
  order stays pending, which is the safe direction.
- If the money arrives but the order cannot be confirmed — for instance stock
  ran out while the customer was on the gateway's page — the payment record is
  kept and the order is left pending for a human. Refunds are manual in v1, and
  a manual refund needs evidence.

## Where it lives

`apps/payments/services/payments.py` — `handle_ipn` and `callback`.
