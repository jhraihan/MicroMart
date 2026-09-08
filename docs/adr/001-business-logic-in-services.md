# 001 — Business logic lives in a services layer

**Status:** accepted

## Context

There are two ways into most of this application: the storefront API that
shoppers use, and the admin API that staff use. Both cancel orders, both move
stock, both read prices.

If each one carried its own copy of the rules, the two would drift. Someone
fixes a coupon bug in the shopper path and forgets the admin path, and now the
same coupon behaves differently depending on who applies it.

## Decision

All business rules live in `apps/<app>/services/`. Views only translate HTTP:
read the request, call a service, return the response. Serializers only shape
data. Neither decides anything.

The order is `models → services → serializers → views`.

Services raise `DomainError` rather than HTTP exceptions, so the same function
works from a view, a management command, or a test.

## Consequences

- A rule has one definition, so the storefront and the admin cannot disagree.
- Business logic is testable without HTTP.
- It is more indirection than putting the logic in the view, which is the usual
  Django tutorial shape. The payoff only shows up once there is a second caller
  — which there is here.

## Example

Cancelling an order goes through `orders/services/placement.transition_order`
whether a customer clicks Cancel or an admin does it from the dashboard. That
function is the only place allowed to write `Order.status`.
