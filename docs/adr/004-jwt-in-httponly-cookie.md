# 004 — Refresh token in an HttpOnly cookie, access token in memory

**Status:** accepted

## Context

JWT tutorials usually put both tokens in `localStorage`. It is easy and it
survives a page reload.

It is also readable by any JavaScript on the page. One cross-site scripting
hole — in our code or in any npm package we depend on — and the attacker reads
the refresh token and owns the account for its full lifetime.

## Decision

- **Refresh token** goes in an `HttpOnly` cookie. JavaScript cannot read it;
  the browser attaches it automatically to the refresh endpoint.
- **Access token** is held in a plain JavaScript variable in `lib/api.js` —
  memory only. It is short-lived (15 minutes) and is gone on reload, at which
  point the app silently refreshes.
- Neither goes in `localStorage` or `sessionStorage`.

The cookie is `SameSite=Lax` and `Secure` outside development.

## Consequences

- An XSS bug can use the session while the page is open, but cannot steal a
  token to use later. That is a meaningful reduction in blast radius.
- A page reload costs one refresh call. `lib/api.js` shares a single in-flight
  refresh between callers, so six queries firing on mount do not start six
  rotations and blacklist each other.
- If the SPA and API are served from different domains, the cookie becomes
  cross-site and needs `SameSite=None`, which Safari and Firefox block by
  default. Serving both from the same domain avoids the problem — worth knowing
  before deploying.

## Where it lives

`config/settings/base.py` (cookie settings), `apps/accounts/cookies.py`,
`frontend/src/lib/api.js`.
