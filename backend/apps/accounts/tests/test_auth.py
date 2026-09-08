"""
The authentication surface (PRD 5.7, 10.1, 10.2; FR-AUT-1..6).

This suite is as much a security test as a functional one. Four invariants
matter more than anything else here, and each is asserted directly rather
than inferred from a happy path:

1. **The refresh token is only ever in an HttpOnly cookie**, and the access
   token is only ever in the response body. Neither goes to localStorage, and
   no JavaScript may read the refresh token (PRD 10.1). The cookie flags
   themselves are asserted -- HttpOnly, SameSite=Lax, and the narrow
   /api/v1/auth/ path.
2. **A failed login is a user-enumeration oracle if it says too much.** The
   answer to "wrong password" and to "no such account" must be byte-for-byte
   identical.
3. **Refresh rotates and blacklists.** A refresh token cannot be replayed.
4. **An authorisation miss is 404, never 403** -- a 403 confirms the record
   exists and leaks the ID space (PRD 10.2).

Assertions are on stable error codes and HTTP status, never on wording. The
one deliberate exception is the enumeration test, where the *equality of two
messages* is the property under test.
"""
import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.models import Address, Role, User
from apps.accounts.services import auth as auth_services
from config.exceptions import DomainError

PASSWORD = "Str0ngPass!2026"
NEW_PASSWORD = "An0ther$trongPass2026"
REFRESH_COOKIE = settings.REFRESH_COOKIE_NAME


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _relax_auth_throttle(monkeypatch):
    """
    The auth endpoints are throttled at 10/min per IP, which is a real control
    with its own test at the bottom of this file. Every *other* test here
    would otherwise start failing on the eleventh request in a run for a
    reason that has nothing to do with what it is asserting.

    The rate is patched on the throttle class rather than through the
    `settings` fixture because DRF binds `SimpleRateThrottle.THROTTLE_RATES`
    to the settings dict once, at import time -- overriding REST_FRAMEWORK
    afterwards does not reach it.
    """
    cache.clear()
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth", None)
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="shopper@example.com", password=PASSWORD, full_name="Rafiq Hasan"
    )


@pytest.fixture
def other_customer(db):
    return User.objects.create_user(email="someone.else@example.com", password=PASSWORD)


@pytest.fixture
def register_url():
    return reverse("accounts:register")


@pytest.fixture
def login_url():
    return reverse("accounts:login")


@pytest.fixture
def refresh_url():
    return reverse("accounts:refresh")


@pytest.fixture
def logout_url():
    return reverse("accounts:logout")


@pytest.fixture
def me_url():
    return reverse("accounts:me")


@pytest.fixture
def change_password_url():
    return reverse("accounts:change-password")


@pytest.fixture
def addresses_url():
    return reverse("addresses:address-list")


@pytest.fixture
def address_detail_url():
    return lambda pk: reverse("addresses:address-detail", kwargs={"pk": pk})


def sign_in(api, url, email=None, password=PASSWORD, user=None):
    """Log in and leave the client holding both the access header and cookie."""
    response = api.post(
        url, {"email": email or user.email, "password": password}, format="json"
    )
    assert response.status_code == 200, response.json()
    access = response.json()["access"]
    api.credentials(HTTP_AUTHORIZATION="Bearer " + access)
    return response, access


def make_address(user, recipient_name="Rafiq Hasan", district="Dhaka"):
    return Address.objects.create(
        user=user,
        recipient_name=recipient_name,
        phone="01712345678",
        division="Dhaka",
        district=district,
        upazila="Dhanmondi",
        area="Road 7",
        street="House 42, Road 7, Dhanmondi",
        postcode="1205",
    )


# ---------------------------------------------------------------------------
# Registration (FR-AUT-1)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_registering_with_a_new_email_creates_a_customer_and_returns_an_access_token(
    api, register_url
):
    response = api.post(
        register_url,
        {"email": "New.Shopper@Example.com", "password": PASSWORD, "full_name": "New Shopper"},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["access"]
    assert body["user"]["email"] == "new.shopper@example.com"
    assert body["user"]["role"] == Role.CUSTOMER
    # A brand new account is unverified until the emailed link is used.
    assert body["user"]["is_email_verified"] is False
    assert User.objects.filter(email="new.shopper@example.com").exists()


@pytest.mark.django_db
def test_registering_never_echoes_the_password_back_in_the_response(api, register_url):
    body = api.post(
        register_url, {"email": "new@example.com", "password": PASSWORD}, format="json"
    ).json()

    assert "password" not in body
    assert "password" not in body["user"]


@pytest.mark.django_db
def test_registering_with_an_email_that_already_exists_is_refused(
    api, register_url, customer
):
    response = api.post(
        register_url, {"email": customer.email, "password": PASSWORD}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "email"
    assert User.objects.filter(email=customer.email).count() == 1


@pytest.mark.django_db
def test_a_duplicate_email_is_detected_regardless_of_the_case_it_is_typed_in(
    api, register_url, customer
):
    response = api.post(
        register_url,
        {"email": customer.email.upper(), "password": PASSWORD},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "email"
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_registering_with_a_password_on_the_common_password_list_is_refused(
    api, register_url
):
    response = api.post(
        register_url, {"email": "weak@example.com", "password": "password"}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "password"
    assert not User.objects.filter(email="weak@example.com").exists()


@pytest.mark.django_db
def test_registering_with_a_short_or_numeric_password_is_refused(api, register_url):
    for weak in ("Ab1!", "84759302847"):
        response = api.post(
            register_url,
            {"email": "weak-{0}@example.com".format(len(weak)), "password": weak},
            format="json",
        )
        assert response.status_code == 400, weak
        assert response.json()["error"]["field"] == "password", weak

    assert User.objects.count() == 0


@pytest.mark.django_db
def test_registering_sets_the_refresh_token_in_an_httponly_cookie_like_login_does(
    api, register_url
):
    response = api.post(
        register_url, {"email": "new@example.com", "password": PASSWORD}, format="json"
    )

    cookie = response.cookies[REFRESH_COOKIE]
    assert cookie.value
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"


# ---------------------------------------------------------------------------
# Login and the refresh cookie (FR-AUT-2, PRD 10.1)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_logging_in_with_correct_credentials_returns_an_access_token_and_the_user(
    api, login_url, customer
):
    response = api.post(
        login_url, {"email": customer.email, "password": PASSWORD}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access"]
    assert body["user"]["id"] == customer.pk
    assert body["user"]["email"] == customer.email


@pytest.mark.django_db
def test_logging_in_puts_the_refresh_token_in_a_cookie_that_javascript_cannot_read(
    api, login_url, customer
):
    # PRD 10.1. HttpOnly is the whole defence against an XSS payload walking
    # off with a seven-day session, so it is asserted on the flag itself.
    response = api.post(
        login_url, {"email": customer.email, "password": PASSWORD}, format="json"
    )

    cookie = response.cookies[REFRESH_COOKIE]
    assert cookie.value
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/api/v1/auth/"
    assert cookie["max-age"] == int(
        settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()
    )


@pytest.mark.django_db
def test_the_refresh_token_is_never_in_the_response_body_where_a_script_could_keep_it(
    api, login_url, customer
):
    body = api.post(
        login_url, {"email": customer.email, "password": PASSWORD}, format="json"
    ).json()

    assert set(body) == {"access", "user"}
    assert "refresh" not in body


@pytest.mark.django_db
def test_the_access_token_is_never_placed_in_a_cookie_on_any_auth_response(
    api, register_url, login_url, refresh_url, customer
):
    # The access token lives in browser memory only. A cookie would survive a
    # reload, which is exactly the persistence PRD 10.1 forbids it.
    registered = api.post(
        register_url, {"email": "new@example.com", "password": PASSWORD}, format="json"
    )
    logged_in = api.post(
        login_url, {"email": customer.email, "password": PASSWORD}, format="json"
    )
    refreshed = api.post(refresh_url, {}, format="json")

    for response in (registered, logged_in, refreshed):
        access = response.json()["access"]
        assert access
        cookie_values = [morsel.value for morsel in response.cookies.values()]
        assert access not in cookie_values
        assert set(response.cookies) <= {REFRESH_COOKIE}


@pytest.mark.django_db
def test_logging_in_with_a_wrong_password_fails_without_revealing_that_the_email_exists(
    api, login_url, customer
):
    # The equality of these two answers *is* the security property: any
    # difference in status, code, message or field is an enumeration oracle.
    wrong_password = api.post(
        login_url, {"email": customer.email, "password": "NotThePassword!1"}, format="json"
    )
    no_such_account = api.post(
        login_url,
        {"email": "nobody-here@example.com", "password": "NotThePassword!1"},
        format="json",
    )

    assert wrong_password.status_code == no_such_account.status_code == 401
    assert wrong_password.json() == no_such_account.json()
    assert wrong_password.json()["error"]["code"] == "INVALID_CREDENTIALS"
    # No `field`, either -- "field: email" would point straight at the answer.
    assert "field" not in wrong_password.json()["error"]


@pytest.mark.django_db
def test_a_failed_login_sets_no_refresh_cookie_at_all(api, login_url, customer):
    response = api.post(
        login_url, {"email": customer.email, "password": "NotThePassword!1"}, format="json"
    )

    assert REFRESH_COOKIE not in response.cookies


@pytest.mark.django_db
def test_logging_in_matches_the_email_case_insensitively(api, login_url, customer):
    response = api.post(
        login_url, {"email": "SHOPPER@EXAMPLE.COM", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["user"]["id"] == customer.pk


@pytest.mark.django_db
def test_logging_in_to_a_deactivated_account_is_refused_exactly_like_an_unknown_email(
    api, login_url, customer
):
    """
    A deactivated account gets the same 401 INVALID_CREDENTIALS as an email
    that was never registered -- byte for byte, cookie included.

    This is the chosen behaviour, not an accident of Django's default
    `ModelBackend` refusing inactive users before `login_user` sees them.
    Distinguishing the two would mean checking `is_active` before
    authenticating, which answers "does this email exist?" for an unauthorised
    caller. If a future change makes deactivation observable here, this test is
    the one that should stop it.
    """
    customer.is_active = False
    customer.save(update_fields=["is_active"])

    response = api.post(
        login_url, {"email": customer.email, "password": PASSWORD}, format="json"
    )
    unknown_account = api.post(
        login_url, {"email": "nobody-here@example.com", "password": PASSWORD}, format="json"
    )

    assert response.status_code == unknown_account.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.json() == unknown_account.json()
    # No `field` either -- "field: email" would point straight at the answer.
    assert "field" not in response.json()["error"]
    assert REFRESH_COOKIE not in response.cookies


# ---------------------------------------------------------------------------
# The same rules at the service layer -- the admin surface and any management
# command reach these functions without going through a view, so the codes are
# asserted on DomainError directly and not only on the HTTP translation.
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_login_service_gives_the_identical_refusal_for_a_bad_password_and_an_unknown_email(
    customer,
):
    failures = []
    for email, password in (
        (customer.email, "NotThePassword!1"),
        ("nobody-here@example.com", PASSWORD),
    ):
        with pytest.raises(DomainError) as excinfo:
            auth_services.login_user(email=email, password=password)
        failures.append(excinfo.value)

    for failure in failures:
        assert failure.code == "INVALID_CREDENTIALS"
        assert failure.status_code == 401
        # No field: naming `email` would point at which half was wrong.
        assert failure.field is None
    assert failures[0].message == failures[1].message


@pytest.mark.django_db
def test_the_login_service_refuses_a_deactivated_account_as_bad_credentials_not_as_a_disabled_one(
    customer,
):
    """
    The service surface gives no clue that the account exists but is switched
    off: same code, same 401, same message as any other failed login. There is
    no ACCOUNT_DISABLED code to assert -- refusing to have one is the point.
    """
    customer.is_active = False
    customer.save(update_fields=["is_active"])

    with pytest.raises(DomainError) as deactivated:
        auth_services.login_user(email=customer.email, password=PASSWORD)
    with pytest.raises(DomainError) as unknown:
        auth_services.login_user(email="nobody-here@example.com", password=PASSWORD)

    assert deactivated.value.code == unknown.value.code == "INVALID_CREDENTIALS"
    assert deactivated.value.status_code == unknown.value.status_code == 401
    assert deactivated.value.field is None
    assert deactivated.value.message == unknown.value.message


@pytest.mark.django_db
def test_the_registration_service_refuses_a_duplicate_email_even_when_the_serializer_is_bypassed(
    customer,
):
    # The serializer catches the ordinary duplicate; this is the racing pair
    # that reaches the unique index, and it must look identical to the client.
    with pytest.raises(DomainError) as excinfo:
        auth_services.register_user(email=customer.email.upper(), password=PASSWORD)

    assert excinfo.value.code == "EMAIL_TAKEN"
    assert excinfo.value.field == "email"
    assert excinfo.value.status_code == 400
    assert User.objects.filter(email=customer.email).count() == 1


@pytest.mark.django_db
def test_the_change_password_service_refuses_a_wrong_current_password(customer):
    with pytest.raises(DomainError) as excinfo:
        auth_services.change_password(
            user=customer, current_password="NotThePassword!1", new_password=NEW_PASSWORD
        )

    assert excinfo.value.code == "INVALID_PASSWORD"
    assert excinfo.value.field == "current_password"
    assert excinfo.value.status_code == 400
    customer.refresh_from_db()
    assert customer.check_password(PASSWORD)


# ---------------------------------------------------------------------------
# Refresh rotation (PRD 10.1)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_refreshing_with_the_cookie_returns_a_new_access_token_and_rotates_the_cookie(
    api, login_url, refresh_url, customer
):
    login = api.post(
        login_url, {"email": customer.email, "password": PASSWORD}, format="json"
    )
    original_refresh = login.cookies[REFRESH_COOKIE].value

    response = api.post(refresh_url, {}, format="json")

    assert response.status_code == 200
    assert response.json()["access"]
    rotated = response.cookies[REFRESH_COOKIE]
    assert rotated.value
    assert rotated.value != original_refresh
    assert rotated["httponly"] is True
    assert rotated["samesite"] == "Lax"


@pytest.mark.django_db
def test_a_refresh_token_that_has_been_rotated_away_cannot_be_used_a_second_time(
    api, login_url, refresh_url, customer
):
    login = api.post(
        login_url, {"email": customer.email, "password": PASSWORD}, format="json"
    )
    spent = login.cookies[REFRESH_COOKIE].value
    assert api.post(refresh_url, {}, format="json").status_code == 200

    # Replay the token the rotation blacklisted -- a stolen copy must be inert.
    api.cookies[REFRESH_COOKIE] = spent
    response = api.post(refresh_url, {}, format="json")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


@pytest.mark.django_db
def test_a_rejected_refresh_clears_the_cookie_so_the_browser_stops_replaying_it(
    api, login_url, refresh_url, customer
):
    login = api.post(
        login_url, {"email": customer.email, "password": PASSWORD}, format="json"
    )
    spent = login.cookies[REFRESH_COOKIE].value
    api.post(refresh_url, {}, format="json")
    api.cookies[REFRESH_COOKIE] = spent

    response = api.post(refresh_url, {}, format="json")

    assert response.cookies[REFRESH_COOKIE].value == ""


@pytest.mark.django_db
def test_refreshing_with_no_cookie_and_no_body_token_is_rejected(api, refresh_url):
    response = api.post(refresh_url, {}, format="json")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NO_REFRESH_TOKEN"


@pytest.mark.django_db
def test_refreshing_with_a_garbage_token_is_rejected_as_an_invalid_refresh_token(
    api, refresh_url
):
    api.cookies[REFRESH_COOKIE] = "not.a.jwt"

    response = api.post(refresh_url, {}, format="json")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


@pytest.mark.django_db
def test_the_refreshed_access_token_actually_authenticates_the_same_customer(
    api, login_url, refresh_url, me_url, customer
):
    api.post(login_url, {"email": customer.email, "password": PASSWORD}, format="json")
    refreshed = api.post(refresh_url, {}, format="json").json()["access"]

    api.credentials(HTTP_AUTHORIZATION="Bearer " + refreshed)
    response = api.get(me_url)

    assert response.status_code == 200
    assert response.json()["id"] == customer.pk


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_logging_out_clears_the_refresh_cookie(api, login_url, logout_url, customer):
    sign_in(api, login_url, user=customer)

    response = api.post(logout_url, {}, format="json")

    assert response.status_code == 204
    cleared = response.cookies[REFRESH_COOKIE]
    assert cleared.value == ""
    assert cleared["max-age"] == 0


@pytest.mark.django_db
def test_logging_out_blacklists_the_refresh_token_so_a_stolen_copy_is_dead(
    api, login_url, logout_url, refresh_url, customer
):
    login, _access = sign_in(api, login_url, user=customer)
    stolen = login.cookies[REFRESH_COOKIE].value

    api.post(logout_url, {}, format="json")

    api.cookies[REFRESH_COOKIE] = stolen
    response = api.post(refresh_url, {}, format="json")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


@pytest.mark.django_db
def test_logging_out_twice_is_not_an_error_because_logout_is_idempotent(
    api, login_url, logout_url, customer
):
    login, _access = sign_in(api, login_url, user=customer)
    spent = login.cookies[REFRESH_COOKIE].value

    assert api.post(logout_url, {}, format="json").status_code == 204
    api.cookies[REFRESH_COOKIE] = spent
    assert api.post(logout_url, {}, format="json").status_code == 204


@pytest.mark.django_db
def test_logging_out_requires_authentication(api, logout_url):
    response = api.post(logout_url, {}, format="json")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


# ---------------------------------------------------------------------------
# /auth/me/
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_reading_the_current_user_requires_authentication(api, me_url):
    response = api.get(me_url)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.django_db
def test_reading_the_current_user_returns_the_authenticated_account_and_no_secrets(
    api, login_url, me_url, customer
):
    sign_in(api, login_url, user=customer)

    response = api.get(me_url)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == customer.pk
    assert body["email"] == customer.email
    assert body["full_name"] == "Rafiq Hasan"
    assert body["role"] == Role.CUSTOMER
    assert "password" not in body


@pytest.mark.django_db
def test_the_current_user_can_edit_their_own_name_and_phone(
    api, login_url, me_url, customer
):
    sign_in(api, login_url, user=customer)

    response = api.patch(
        me_url, {"full_name": "Rafiqul Hasan", "phone": "01812345678"}, format="json"
    )

    assert response.status_code == 200
    customer.refresh_from_db()
    assert customer.full_name == "Rafiqul Hasan"
    assert customer.phone == "01812345678"


@pytest.mark.django_db
def test_the_current_user_cannot_promote_themselves_or_change_their_email(
    api, login_url, me_url, customer
):
    # role and email are read-only on the serializer. Privilege escalation by
    # PATCH is the classic way a role-gated admin route stops being gated.
    sign_in(api, login_url, user=customer)

    response = api.patch(
        me_url,
        {"role": Role.ADMIN, "email": "hijack@example.com", "is_email_verified": True},
        format="json",
    )

    assert response.status_code == 200
    customer.refresh_from_db()
    assert customer.role == Role.CUSTOMER
    assert customer.email == "shopper@example.com"
    assert customer.is_email_verified is False


# ---------------------------------------------------------------------------
# change-password (FR-AUT-5)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_changing_the_password_requires_authentication(api, change_password_url):
    response = api.post(
        change_password_url,
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.django_db
def test_changing_the_password_requires_the_current_password_to_be_correct(
    api, login_url, change_password_url, customer
):
    sign_in(api, login_url, user=customer)

    response = api.post(
        change_password_url,
        {"current_password": "NotThePassword!1", "new_password": NEW_PASSWORD},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PASSWORD"
    assert response.json()["error"]["field"] == "current_password"
    customer.refresh_from_db()
    assert customer.check_password(PASSWORD)


@pytest.mark.django_db
def test_changing_the_password_rejects_a_weak_replacement(
    api, login_url, change_password_url, customer
):
    sign_in(api, login_url, user=customer)

    response = api.post(
        change_password_url,
        {"current_password": PASSWORD, "new_password": "password"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "new_password"
    customer.refresh_from_db()
    assert customer.check_password(PASSWORD)


@pytest.mark.django_db
def test_changing_the_password_replaces_it_so_the_old_one_no_longer_signs_in(
    api, login_url, change_password_url, customer
):
    sign_in(api, login_url, user=customer)

    response = api.post(
        change_password_url,
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.status_code == 204

    fresh = APIClient()
    assert fresh.post(
        login_url, {"email": customer.email, "password": PASSWORD}, format="json"
    ).status_code == 401
    assert fresh.post(
        login_url, {"email": customer.email, "password": NEW_PASSWORD}, format="json"
    ).status_code == 200


@pytest.mark.django_db
def test_changing_the_password_invalidates_every_existing_refresh_token(
    api, login_url, change_password_url, refresh_url, customer
):
    """
    Someone changes a password because they think it has leaked. If a session
    opened with the *old* password keeps refreshing afterwards, the change has
    evicted nobody and the account is still open to whoever had it.

    Enforced in `auth_services.change_password` via revoke_all_sessions(), not
    in the view, so the same eviction happens on every surface that can change
    a password.
    """
    login, _access = sign_in(api, login_url, user=customer)
    session_opened_with_the_old_password = login.cookies[REFRESH_COOKIE].value

    assert api.post(
        change_password_url,
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    ).status_code == 204

    replay = APIClient()
    replay.cookies[REFRESH_COOKIE] = session_opened_with_the_old_password
    response = replay.post(refresh_url, {}, format="json")

    assert response.status_code == 401, (
        "a refresh token minted before the password change must be dead"
    )


@pytest.mark.django_db
def test_resetting_the_password_also_invalidates_every_existing_refresh_token(
    api, login_url, refresh_url, customer
):
    """
    The reset link is the harder case: the customer typically cannot sign in
    at all, because somebody else is already in the account. Revoking on reset
    is what actually removes them.
    """
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    from apps.accounts.services import auth as auth_services

    login, _access = sign_in(api, login_url, user=customer)
    attackers_session = login.cookies[REFRESH_COOKIE].value

    auth_services.confirm_password_reset(
        uid=urlsafe_base64_encode(force_bytes(customer.pk)),
        token=auth_services.password_reset_token_generator.make_token(customer),
        new_password=NEW_PASSWORD,
    )

    replay = APIClient()
    replay.cookies[REFRESH_COOKIE] = attackers_session

    assert replay.post(refresh_url, {}, format="json").status_code == 401


# ---------------------------------------------------------------------------
# Address book -- object-level authorisation (PRD 10.2, FR-AUT-6)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_address_book_requires_authentication(api, addresses_url):
    response = api.get(addresses_url)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.django_db
def test_the_address_list_contains_only_the_requesting_customers_addresses(
    api, login_url, addresses_url, customer, other_customer
):
    mine = make_address(customer, recipient_name="Mine")
    make_address(other_customer, recipient_name="Theirs")
    sign_in(api, login_url, user=customer)

    body = api.get(addresses_url).json()

    assert [row["id"] for row in body] == [mine.pk]


@pytest.mark.django_db
def test_reading_another_customers_address_returns_404_and_never_403(
    api, login_url, address_detail_url, customer, other_customer
):
    # 403 would confirm the row exists and hand an attacker a working oracle
    # over the whole ID space. The miss must be indistinguishable from absence.
    theirs = make_address(other_customer, recipient_name="Theirs")
    sign_in(api, login_url, user=customer)

    response = api.get(address_detail_url(theirs.pk))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.django_db
def test_another_customers_address_is_indistinguishable_from_one_that_does_not_exist(
    api, login_url, address_detail_url, customer, other_customer
):
    theirs = make_address(other_customer)
    sign_in(api, login_url, user=customer)

    existing_but_not_mine = api.get(address_detail_url(theirs.pk))
    never_existed = api.get(address_detail_url(theirs.pk + 10_000))

    assert existing_but_not_mine.status_code == never_existed.status_code == 404
    assert existing_but_not_mine.json() == never_existed.json()


@pytest.mark.django_db
def test_updating_another_customers_address_returns_404_and_changes_nothing(
    api, login_url, address_detail_url, customer, other_customer
):
    theirs = make_address(other_customer, recipient_name="Theirs")
    sign_in(api, login_url, user=customer)

    response = api.patch(
        address_detail_url(theirs.pk), {"recipient_name": "Hijacked"}, format="json"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    theirs.refresh_from_db()
    assert theirs.recipient_name == "Theirs"


@pytest.mark.django_db
def test_deleting_another_customers_address_returns_404_and_leaves_the_row_in_place(
    api, login_url, address_detail_url, customer, other_customer
):
    theirs = make_address(other_customer)
    sign_in(api, login_url, user=customer)

    response = api.delete(address_detail_url(theirs.pk))

    assert response.status_code == 404
    assert Address.objects.filter(pk=theirs.pk).exists()


@pytest.mark.django_db
def test_a_customer_can_read_and_edit_their_own_address(
    api, login_url, address_detail_url, customer
):
    mine = make_address(customer)
    sign_in(api, login_url, user=customer)

    assert api.get(address_detail_url(mine.pk)).status_code == 200
    assert api.patch(
        address_detail_url(mine.pk), {"recipient_name": "Rafiqul Hasan"}, format="json"
    ).status_code == 200
    mine.refresh_from_db()
    assert mine.recipient_name == "Rafiqul Hasan"


@pytest.mark.django_db
def test_a_new_address_is_filed_under_the_signed_in_customer_whatever_the_payload_says(
    api, login_url, addresses_url, customer, other_customer
):
    # Ownership comes from request.user in the view, never from the body.
    sign_in(api, login_url, user=customer)

    response = api.post(
        addresses_url,
        {
            "user": other_customer.pk,
            "recipient_name": "Rafiq Hasan",
            "phone": "01712345678",
            "division": "Dhaka",
            "district": "Dhaka",
            "street": "House 42, Road 7, Dhanmondi",
        },
        format="json",
    )

    assert response.status_code == 201
    created = Address.objects.get(pk=response.json()["id"])
    assert created.user_id == customer.pk
    # The first address a customer saves becomes their default (FR-CHK-4).
    assert created.is_default is True


# ---------------------------------------------------------------------------
# Brute-force protection (PRD 10.4)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_repeated_login_attempts_from_one_client_are_rate_limited(
    api, login_url, customer, monkeypatch
):
    # Re-arms the throttle the autouse fixture above switched off, so the
    # control is proved rather than assumed.
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth", "10/min")
    payload = {"email": customer.email, "password": "NotThePassword!1"}

    for _ in range(10):
        assert api.post(login_url, payload, format="json").status_code == 401

    throttled = api.post(login_url, payload, format="json")

    assert throttled.status_code == 429
