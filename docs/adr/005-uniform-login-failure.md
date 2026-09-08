# 005 — One login failure message for every cause

**Status:** accepted

## Context

Helpful login errors are a user-enumeration tool. If "no account with that
email" and "wrong password" are different messages, anyone can submit a list of
addresses and learn which ones are registered. That is a privacy leak on its
own, and it is the first step in credential stuffing.

## Decision

Every failed sign-in returns the same message and the same 401:

> Email or password is incorrect.

That covers all three cases: no such account, wrong password, and deactivated
account.

There is deliberately **no separate branch for a deactivated account**. Django's
`ModelBackend` already returns `None` for an inactive user, so it falls into the
same refusal. Adding a specific message would mean checking `is_active` *before*
authenticating — which answers "does this email exist?" for anyone who asks.

The password reset flow follows the same rule: it always reports success,
whether or not the address is registered.

## Consequences

- An attacker learns nothing from the response.
- A real user who has forgotten which email they used gets less help. Password
  reset is the intended path, and it is on the same screen.
- Deactivation still bites on every later request: SimpleJWT rejects an access
  token belonging to an inactive user.

## Where it lives

`apps/accounts/services/auth.py` — `login_user` and `request_password_reset`.
