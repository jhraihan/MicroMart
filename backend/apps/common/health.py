"""
Health checks for whatever runs this in production -- a load balancer, a
container orchestrator, an uptime monitor.

Two endpoints rather than one, because they answer different questions:

* /healthz/ asks "is this process alive?" It must never fail for a reason
  outside this process. If it checked the database, a brief database blip
  would make an orchestrator restart a perfectly healthy app and turn a small
  problem into an outage.

* /readyz/ asks "can this process serve a request right now?" That does depend
  on the database and the cache, so it checks both and answers 503 when either
  is unreachable. A load balancer takes the instance out of rotation until it
  recovers.
"""
from django.core.cache import cache
from django.db import connections
from django.http import JsonResponse
from django.views.decorators.http import require_GET

CACHE_PROBE_KEY = "healthcheck"


@require_GET
def liveness(request):
    return JsonResponse({"status": "ok"})


@require_GET
def readiness(request):
    checks = {}

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    try:
        cache.set(CACHE_PROBE_KEY, "1", 5)
        checks["cache"] = "ok" if cache.get(CACHE_PROBE_KEY) == "1" else "error"
    except Exception:
        checks["cache"] = "error"

    healthy = all(value == "ok" for value in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=200 if healthy else 503,
    )
