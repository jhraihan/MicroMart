"""
Auth and account endpoints (PRD §7.2).

Views do three things only: validate the payload, call a service, shape the
response. Every rule they appear to enforce is actually enforced in services/.
"""
from django.db import transaction
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from config.exceptions import DomainError

from .cookies import (
    clear_refresh_cookie,
    issue_tokens,
    read_refresh_cookie,
    set_refresh_cookie,
)
from .models import Address
from .serializers import (
    AddressSerializer,
    ChangePasswordSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)
from .services import addresses as address_services
from .services import auth as auth_services


def _auth_response(user, *, http_status=status.HTTP_200_OK):
    refresh_token, access_token = issue_tokens(user)
    response = Response(
        {"access": access_token, "user": UserSerializer(user).data}, status=http_status
    )
    return set_refresh_cookie(response, refresh_token)


class RegisterView(GenericAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = auth_services.register_user(**serializer.validated_data)
        return _auth_response(user, http_status=status.HTTP_201_CREATED)


class LoginView(GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = auth_services.login_user(**serializer.validated_data)
        return _auth_response(user)


@extend_schema(
    tags=["auth"],
    request=None,
    responses={200: None},
    summary="Swap the refresh cookie for a new access token",
)
class RefreshView(APIView):
    """Rotates the refresh token and blacklists the one just used."""

    permission_classes = [AllowAny]
    # Its own scope, not `auth`: the SPA refreshes on every page load, so
    # sharing the login budget would lock out ordinary browsing.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "refresh"

    def post(self, request):
        raw = read_refresh_cookie(request) or request.data.get("refresh")
        if not raw:
            raise DomainError(
                "No refresh token supplied.",
                code="NO_REFRESH_TOKEN",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            token = RefreshToken(raw)
            token.blacklist()
            new_token = RefreshToken.for_user(
                _user_from_token(token)
            )
        except TokenError:
            response = Response(
                {
                    "error": {
                        "code": "INVALID_REFRESH_TOKEN",
                        "message": "Session expired. Please sign in again.",
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_refresh_cookie(response)

        response = Response({"access": str(new_token.access_token)})
        return set_refresh_cookie(response, str(new_token))


def _user_from_token(token):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.get(pk=token["user_id"])


@extend_schema(
    tags=["auth"],
    request=None,
    responses={205: None},
    summary="Sign out and clear the refresh cookie",
)
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw = read_refresh_cookie(request) or request.data.get("refresh")
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass  # Already expired or blacklisted -- logout is idempotent.
        return clear_refresh_cookie(Response(status=status.HTTP_204_NO_CONTENT))


class VerifyEmailView(GenericAPIView):
    serializer_class = VerifyEmailSerializer
    permission_classes = [AllowAny]
    # A verification link is clicked once or twice. The token itself is 32
    # random bytes and is not guessable, so this is about database load rather
    # than about brute force.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = auth_services.verify_email(raw_token=serializer.validated_data["token"])
        return Response(UserSerializer(user).data)


class PasswordResetView(GenericAPIView):
    serializer_class = PasswordResetRequestSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_services.request_password_reset(**serializer.validated_data)
        # Always 204, whether or not the address is registered.
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetConfirmView(GenericAPIView):
    serializer_class = PasswordResetConfirmSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_services.confirm_password_reset(**serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(GenericAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_services.change_password(user=request.user, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(GenericAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(self.get_serializer(request.user).data)

    def patch(self, request):
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(
    tags=["auth"],
    parameters=[
        OpenApiParameter(
            "id",
            OpenApiTypes.INT,
            OpenApiParameter.PATH,
            description="Address id. Only the signed-in customer's own ids resolve.",
        )
    ],
)
class AddressViewSet(ModelViewSet):
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        # Scoping the queryset to request.user is what makes another
        # customer's address 404 rather than 403 (PRD §10.2).
        return Address.objects.filter(user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.instance = address_services.create_address(
            user=self.request.user, **serializer.validated_data
        )

    @transaction.atomic
    def perform_update(self, serializer):
        serializer.instance = address_services.update_address(
            address=serializer.instance, **serializer.validated_data
        )

    def perform_destroy(self, instance):
        address_services.delete_address(address=instance)
