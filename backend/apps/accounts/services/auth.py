"""
Authentication services (PRD §5.7).

All of the behaviour lives here rather than in views so that the storefront
API, the admin API, a management command and a test all exercise the same
rules. Views translate HTTP; this module owns the domain.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from config.exceptions import DomainError

from ..models import EmailVerificationToken, User

VERIFICATION_TOKEN_TTL = timedelta(hours=48)

password_reset_token_generator = PasswordResetTokenGenerator()


@transaction.atomic
def register_user(*, email, password, full_name="", phone=""):
    """Create a customer account and send the verification email."""
    email = email.strip().lower()
    try:
        user = User.objects.create_user(
            email=email, password=password, full_name=full_name.strip(), phone=phone.strip()
        )
    except IntegrityError:
        # Deliberately the same wording the serializer uses, so a race and a
        # plain duplicate look identical to the client.
        raise DomainError(
            "An account with this email already exists.",
            code="EMAIL_TAKEN",
            field="email",
            status_code=400,
        )

    token = issue_verification_token(user)
    transaction.on_commit(lambda: send_verification_email(user, token))
    return user


def issue_verification_token(user):
    token = EmailVerificationToken.objects.create(
        user=user,
        token=secrets.token_urlsafe(32),
        expires_at=timezone.now() + VERIFICATION_TOKEN_TTL,
    )
    return token


def send_verification_email(user, token):
    link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={token.token}"
    send_mail(
        subject="Verify your email address",
        message=(
            f"Hello {user.get_short_name()},\n\n"
            f"Confirm your email address to finish setting up your account:\n{link}\n\n"
            f"This link expires in 48 hours."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )


@transaction.atomic
def verify_email(*, raw_token):
    try:
        token = EmailVerificationToken.objects.select_for_update().get(token=raw_token)
    except EmailVerificationToken.DoesNotExist:
        raise DomainError(
            "This verification link is not valid.", code="INVALID_TOKEN", field="token"
        )

    if not token.is_usable:
        raise DomainError(
            "This verification link has expired or has already been used.",
            code="TOKEN_EXPIRED",
            field="token",
        )

    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])

    user = token.user
    if not user.is_email_verified:
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])
    return user


def login_user(*, email, password):
    """
    One refusal for every cause -- no such account, wrong password, or
    deactivated. Naming which one would answer "does this email exist?" for
    anyone who asks.

    There is deliberately no is_active branch: ModelBackend already returns
    None for an inactive user, and checking it first would reopen that oracle.
    """
    user = authenticate(username=email.strip().lower(), password=password)
    if user is None:
        # One message for "no such account", "wrong password" and "account
        # deactivated" alike -- naming which one it was hands an attacker a
        # user-enumeration oracle.
        raise DomainError(
            "Email or password is incorrect.",
            code="INVALID_CREDENTIALS",
            status_code=401,
        )
    return user


def request_password_reset(*, email):
    """
    Always succeeds from the caller's point of view. Whether an account exists
    is never revealed.
    """
    user = User.objects.filter(email=email.strip().lower(), is_active=True).first()
    if user is None:
        return None

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = password_reset_token_generator.make_token(user)
    link = f"{settings.FRONTEND_BASE_URL}/reset-password?uid={uid}&token={token}"
    send_mail(
        subject="Reset your password",
        message=(
            f"Hello {user.get_short_name()},\n\n"
            f"Use this single-use link to choose a new password:\n{link}\n\n"
            f"If you did not request this, you can ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )
    return user


def confirm_password_reset(*, uid, token, new_password):
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=pk, is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        raise DomainError(
            "This reset link is not valid.", code="INVALID_TOKEN", field="token"
        )

    if not password_reset_token_generator.check_token(user, token):
        raise DomainError(
            "This reset link has expired or has already been used.",
            code="TOKEN_EXPIRED",
            field="token",
        )

    user.set_password(new_password)
    user.save(update_fields=["password"])
    # A reset is the "somebody else is in my account" path -- typically the
    # customer cannot even sign in, because the other party changed something.
    # Leaving their sessions alive would defeat the entire act.
    revoke_all_sessions(user)
    return user


def revoke_all_sessions(user):
    """
    Blacklist every refresh token this user still holds, so sessions opened
    with the old password die with it.

    Per token rather than a flag on the user, so a token issued after this
    call is untouched -- which lets the caller hand out a fresh session in the
    same request. Returns how many were newly blacklisted.
    """
    revoked = 0
    for outstanding in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
        if created:
            revoked += 1
    return revoked


def change_password(*, user, current_password, new_password):
    if not user.check_password(current_password):
        raise DomainError(
            "Your current password is incorrect.",
            code="INVALID_PASSWORD",
            field="current_password",
            status_code=400,
        )
    user.set_password(new_password)
    user.save(update_fields=["password"])
    # Sessions opened with the old password must not outlive it.
    revoke_all_sessions(user)
    return user
