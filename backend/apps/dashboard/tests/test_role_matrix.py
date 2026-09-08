"""
The role matrix (PRD 4.3 US-A8, FR-ADM-10, 7.3).

"Roles are admin and staff; staff may view orders and update order status
only; every other admin endpoint rejects staff with 403."

That sentence is a grid, so it is tested as a grid. Every endpoint this app
registers appears in ENDPOINTS exactly once, with the answer each of the four
callers must get -- and `test_every_route_this_app_registers_has_a_row_in_the_matrix`
fails if a route is added without a row, because the failure mode this guards
against is a *new* endpoint quietly inheriting admin-only or staff-inclusive
access by whichever permission class was copied.

`IsAdminOrStaff` on the whole URL prefix would pass a naive reading of 7.3
("gated by an IsAdminOrStaff permission class") and be wrong: 7.3's own table
gives the dashboard, the customer directory and store settings to Admin alone.
The gate is per view.
"""
import pytest
from rest_framework import status

pytestmark = pytest.mark.django_db

ADMIN_ONLY = "admin_only"
ADMIN_AND_STAFF = "admin_and_staff"

# (url fixture name, HTTP method, body, access level)
ENDPOINTS = [
    ("dashboard_url", "get", None, ADMIN_ONLY),
    ("orders_url", "get", None, ADMIN_AND_STAFF),
    ("order_detail_url", "get", None, ADMIN_AND_STAFF),
    ("order_status_url", "post", {"status": "packed"}, ADMIN_AND_STAFF),
    (
        "order_shipment_url",
        "post",
        {"courier_name": "Pathao", "tracking_number": "PT-1001"},
        ADMIN_AND_STAFF,
    ),
    ("customers_url", "get", None, ADMIN_ONLY),
    ("settings_url", "get", None, ADMIN_ONLY),
    ("settings_url", "patch", {"store_name": "MicroMart BD"}, ADMIN_ONLY),
]

# The route each row exercises, so a new endpoint without a row is caught by
# test_every_route_this_app_registers_has_a_row_in_the_matrix.
ROUTE_NAMES = {
    "dashboard_url": "dashboard",
    "orders_url": "order-list",
    "order_detail_url": "order-detail",
    "order_status_url": "order-status",
    "order_shipment_url": "order-shipment",
    "customers_url": "customer-list",
    "settings_url": "store-settings",
}


def resolve(request_fixture, url_fixture, order):
    """A concrete URL: the reference-taking routes need an order to point at."""
    value = request_fixture.getfixturevalue(url_fixture)
    return value(order.reference) if callable(value) else value


def call(client, method, url, body):
    return getattr(client, method)(url, body, format="json") if body else getattr(client, method)(url)


@pytest.fixture
def matrix_order(make_order):
    """A confirmed order, so `packed` is a legal next step for the status POST."""
    from apps.orders.models import OrderStatus

    return make_order(status=OrderStatus.CONFIRMED)


@pytest.mark.parametrize("url_fixture,method,body,access", ENDPOINTS)
def test_an_anonymous_caller_is_refused_by_every_admin_endpoint(
    request, api, matrix_order, url_fixture, method, body, access
):
    url = resolve(request, url_fixture, matrix_order)
    response = call(api, method, url, body)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED, (
        "{0} {1} answered {2} to an anonymous caller".format(
            method.upper(), url, response.status_code
        )
    )


@pytest.mark.parametrize("url_fixture,method,body,access", ENDPOINTS)
def test_a_signed_in_customer_is_refused_by_every_admin_endpoint(
    request, as_user, customer, matrix_order, url_fixture, method, body, access
):
    client = as_user(customer)
    url = resolve(request, url_fixture, matrix_order)
    response = call(client, method, url, body)
    assert response.status_code == status.HTTP_403_FORBIDDEN, (
        "{0} {1} answered {2} to a customer".format(
            method.upper(), url, response.status_code
        )
    )


@pytest.mark.parametrize("url_fixture,method,body,access", ENDPOINTS)
def test_staff_reach_the_order_endpoints_and_nothing_else(
    request, staff_client, matrix_order, url_fixture, method, body, access
):
    url = resolve(request, url_fixture, matrix_order)
    response = call(staff_client, method, url, body)

    if access == ADMIN_AND_STAFF:
        assert response.status_code == status.HTTP_200_OK, (
            "staff must be able to {0} {1}, got {2}: {3}".format(
                method.upper(), url, response.status_code, response.data
            )
        )
    else:
        assert response.status_code == status.HTTP_403_FORBIDDEN, (
            "{0} {1} is Admin-only in PRD 7.3 but answered staff with {2}".format(
                method.upper(), url, response.status_code
            )
        )


@pytest.mark.parametrize("url_fixture,method,body,access", ENDPOINTS)
def test_an_admin_reaches_every_admin_endpoint(
    request, admin_client, matrix_order, url_fixture, method, body, access
):
    url = resolve(request, url_fixture, matrix_order)
    response = call(admin_client, method, url, body)
    assert response.status_code == status.HTTP_200_OK, (
        "admin was refused {0} {1}: {2} {3}".format(
            method.upper(), url, response.status_code, response.data
        )
    )


def test_staff_are_refused_with_403_and_not_hidden_behind_a_404(
    staff_client, dashboard_url
):
    """
    A staff member is a real, authenticated principal reaching a real endpoint
    that exists -- 403 is the honest answer and the one US-A8 names.

    The 404-not-403 rule (PRD 10.2) is about *object-level* authorisation,
    where a 403 would confirm that someone else's order id is real. Nothing is
    confirmed by telling a staff member the dashboard exists; they can see the
    navigation.
    """
    response = staff_client.get(dashboard_url)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "error" in response.data


def test_every_route_this_app_registers_has_a_row_in_the_matrix():
    """
    A new endpoint under admin/ must be given a role, not inherit one.

    This is what makes the grid above load-bearing rather than decorative:
    adding a route to apps/dashboard/urls.py without a row here fails, and the
    failure message names the route that was missed.
    """
    from apps.dashboard import urls as dashboard_urls

    registered = {pattern.name for pattern in dashboard_urls.urlpatterns}
    covered = {ROUTE_NAMES[fixture] for fixture, _, _, _ in ENDPOINTS}

    assert registered - covered == set(), (
        "these admin routes have no row in ENDPOINTS, so no test asserts who "
        "may call them: {0}".format(sorted(registered - covered))
    )
    assert covered - registered == set(), (
        "ENDPOINTS names routes that no longer exist: {0}".format(
            sorted(covered - registered)
        )
    )
