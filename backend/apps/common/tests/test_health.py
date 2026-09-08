"""
The health endpoints a load balancer or container platform polls.

The split matters: liveness must not depend on anything outside this process,
or a brief database blip makes an orchestrator restart a healthy app and turns
a small problem into an outage. Readiness is the one allowed to say "not right
now".
"""
import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client(headers={"host": "localhost"})


def test_liveness_answers_without_touching_the_database(client):
    response = client.get("/healthz/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readiness_reports_each_dependency(client):
    response = client.get("/readyz/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["cache"] == "ok"


@pytest.mark.django_db
def test_readiness_answers_503_when_the_database_is_unreachable(client, monkeypatch):
    """
    503 rather than 500, so a load balancer takes the instance out of rotation
    instead of serving errors to shoppers.
    """
    from apps.common import health

    def explode(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(health.connections["default"], "cursor", explode)

    response = client.get("/readyz/")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "error"
