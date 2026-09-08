"""
One guard over the whole /api/v1/admin/ prefix (PRD 4.3 US-A8, 7.3, 10.2).

Every app that owns admin endpoints already asserts its own role matrix --
apps/dashboard/tests/test_role_matrix.py, apps/catalog/tests/test_admin_permissions.py,
apps/promotions/tests/test_admin_coupons.py, apps/reviews/tests/. Each of those
enumerates the routes *its own module* registers, so a new admin route in a
new app is gated by nobody: it is simply absent from every matrix, and every
one of them still passes.

That gap has teeth here, because `DEFAULT_PERMISSION_CLASSES` in
config/settings/base.py is `AllowAny` (the storefront is mostly public, and
that is the right default for it). A view under admin/ that forgets
`permission_classes` is therefore not merely under-gated -- it is world
readable, to an anonymous caller, with no test anywhere going red.

So this module walks the live URL resolver instead of a hand-written list. It
fails on a route that does not exist yet, which is the entire point.
"""
import pytest
from django.urls import get_resolver
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.common.permissions import IsAdminOrStaff, IsAdminRole

pytestmark = pytest.mark.django_db

ADMIN_PREFIX = "api/v1/admin/"
PASSWORD = "Str0ngPass!2026"

# PRD 7.3, and nothing else: staff may view orders and move their status, plus
# attach the courier and tracking number that `packed -> shipped` requires.
# Every other admin route answers staff with 403 (US-A8, US-T2).
STAFF_ROUTES = {
    "api/v1/admin/orders/",
    "api/v1/admin/orders/<str:reference>/",
    "api/v1/admin/orders/<str:reference>/status/",
    "api/v1/admin/orders/<str:reference>/shipment/",
}

# Placeholders for captured segments. The rows they address do not exist, and
# they do not need to: authorisation is decided before the lookup, so an
# ungated route answers 200/400/404 where a gated one answers 401/403.
SAMPLE_ARGS = {
    "pk": "1",
    "id": "1",
    "image_id": "1",
    "variant_id": "1",
    "reference": "ORD-2026-000001",
}

METHODS = ("get", "post", "patch", "delete")


def _admin_routes():
    """(pattern, url, view class, [methods]) for every route under admin/."""
    flat = []

    def walk(resolver, prefix=""):
        for entry in resolver.url_patterns:
            pattern = prefix + str(entry.pattern)
            if hasattr(entry, "url_patterns"):
                walk(entry, pattern)
            else:
                flat.append((pattern, entry.callback))

    walk(get_resolver())

    routes = []
    for pattern, callback in sorted(flat):
        if not pattern.startswith(ADMIN_PREFIX):
            continue
        url = "/" + pattern
        for name, value in SAMPLE_ARGS.items():
            url = url.replace("<int:{0}>".format(name), value)
            url = url.replace("<str:{0}>".format(name), value)
        view = getattr(callback, "cls", getattr(callback, "view_class", None))
        methods = [m for m in METHODS if hasattr(view, m)]
        routes.append((pattern, url, view, methods))
    return routes


ADMIN_ROUTES = _admin_routes()
ROUTE_METHODS = [
    (pattern, url, method)
    for pattern, url, _view, methods in ADMIN_ROUTES
    for method in methods
]
ROUTE_IDS = ["{0} {1}".format(m.upper(), p) for p, _u, m in ROUTE_METHODS]


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="gate-admin@example.com", password=PASSWORD, role=Role.ADMIN
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        email="gate-staff@example.com", password=PASSWORD, role=Role.STAFF
    )


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        email="gate-customer@example.com", password=PASSWORD, role=Role.CUSTOMER
    )


def _call(method, url, user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return getattr(client, method)(url, {}, format="json").status_code


def test_the_admin_prefix_actually_has_routes_so_an_empty_walk_cannot_pass_this_module():
    """
    Every other test here iterates ADMIN_ROUTES. If the walk ever returned
    nothing -- a renamed prefix, a resolver change -- they would all pass
    vacuously and this file would be decoration.
    """
    assert len(ADMIN_ROUTES) >= 20, ADMIN_ROUTES


def test_every_route_under_the_admin_prefix_declares_one_of_the_two_admin_permission_classes():
    """
    The default is AllowAny, so a missing `permission_classes` is an open door
    rather than a locked one. Naming the class is checked separately from the
    behaviour below because the two fail differently: this one names the file
    to edit, the behavioural ones name the hole.
    """
    ungated = []
    for pattern, _url, view, _methods in ADMIN_ROUTES:
        declared = list(getattr(view, "permission_classes", []) or [])
        if not any(cls in (IsAdminRole, IsAdminOrStaff) for cls in declared):
            ungated.append((pattern, view.__name__, [c.__name__ for c in declared]))
    assert not ungated, (
        "these admin routes carry no admin permission class, so DRF's AllowAny "
        "default applies and they are open to anonymous callers: {0}".format(ungated)
    )


def test_only_the_four_order_routes_are_declared_reachable_by_staff():
    """
    PRD 7.3 grants staff exactly four rows. A new route that widens the staff
    surface has to change this set, which is a decision someone makes on
    purpose rather than a permission class copied from the view above it.
    """
    staff_reachable = {
        pattern
        for pattern, _url, view, _methods in ADMIN_ROUTES
        if IsAdminOrStaff in (getattr(view, "permission_classes", []) or [])
    }
    assert staff_reachable == STAFF_ROUTES


@pytest.mark.parametrize("pattern,url,method", ROUTE_METHODS, ids=ROUTE_IDS)
def test_an_anonymous_caller_is_refused_by_every_admin_route(pattern, url, method):
    assert _call(method, url) in (401, 403)


@pytest.mark.parametrize("pattern,url,method", ROUTE_METHODS, ids=ROUTE_IDS)
def test_a_signed_in_customer_is_refused_by_every_admin_route_with_403(
    pattern, url, method, customer_user
):
    assert _call(method, url, customer_user) == 403


@pytest.mark.parametrize("pattern,url,method", ROUTE_METHODS, ids=ROUTE_IDS)
def test_staff_reach_the_order_routes_and_are_refused_everywhere_else_with_403(
    pattern, url, method, staff_user
):
    """
    403 rather than 404 on the refusals, deliberately. The 404-not-403 rule is
    about *object-level* authorisation, where a 403 would confirm that someone
    else's order reference is real. Nothing is disclosed by telling a staff
    member that the coupon screen exists; hiding it would only make a
    misconfigured role look like a broken URL.
    """
    status = _call(method, url, staff_user)
    if pattern in STAFF_ROUTES:
        assert status != 403
    else:
        assert status == 403
