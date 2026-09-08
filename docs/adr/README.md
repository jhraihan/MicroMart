# Architecture Decision Records

Short notes on the decisions that shaped MicroMart, and why the alternative was
rejected. Each one is a page.

| # | Decision |
|---|---|
| [001](001-business-logic-in-services.md) | Business logic lives in a services layer |
| [002](002-404-not-403.md) | Someone else's record returns 404, not 403 |
| [003](003-money-as-decimal.md) | Money is DECIMAL, never a float |
| [004](004-jwt-in-httponly-cookie.md) | Refresh token in an HttpOnly cookie, access token in memory |
| [005](005-uniform-login-failure.md) | One login failure message for every cause |
| [006](006-stock-locking.md) | Stock is locked with SELECT FOR UPDATE at checkout |
| [007](007-payment-verified-server-side.md) | A payment counts only when the gateway confirms it to our server |
| [008](008-rate-limiting.md) | Every endpoint is rate limited, and the counters are shared |
