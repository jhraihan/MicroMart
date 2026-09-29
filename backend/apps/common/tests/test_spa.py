"""
The storefront entry point served by Django in single-service deployments
(config/settings/prod.py, "The storefront, served by this process").
"""
import re

import pytest
from django.test import RequestFactory, override_settings

from apps.common import spa

INDEX_HTML = b'<!doctype html><div id="root"></div>'


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_bytes(INDEX_HTML)
    return tmp_path


@pytest.mark.parametrize(
    "path",
    ["", "p/samsung-t7-1tb-portable-ssd", "admin/orders", "cart", "order/ORD-2026-000001"],
)
def test_client_side_routes_are_claimed_by_the_storefront(path):
    assert re.match(spa.ROUTE, path)


@pytest.mark.parametrize(
    "path",
    [
        "api/v1/products/",
        "api/v1/does-not-exist/",
        "django-admin/login/",
        "media/products/x.png",
        "static/admin/css/base.css",
        "healthz/",
        "readyz/",
    ],
)
def test_server_paths_keep_their_own_404s_instead_of_the_storefront_html(path):
    # "/admin/..." is the React dashboard; "/django-admin/..." is Django's.
    assert re.match(spa.ROUTE, path) is None


def test_every_client_route_receives_index_html_with_no_cache(dist):
    with override_settings(FRONTEND_DIST_DIR=dist):
        response = spa.index(RequestFactory().get("/p/anything"))

    assert response.status_code == 200
    assert response.content == INDEX_HTML
    assert response["Content-Type"] == "text/html; charset=utf-8"
    # A cached index.html would keep loading last release's bundles.
    assert response["Cache-Control"] == "no-cache"


def test_the_entry_point_refuses_writes(dist):
    with override_settings(FRONTEND_DIST_DIR=dist):
        response = spa.index(RequestFactory().post("/cart"))

    assert response.status_code == 405
