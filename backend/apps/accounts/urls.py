"""Auth routes, mounted at /api/v1/auth/ (PRD §7.2)."""
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("verify-email/", views.VerifyEmailView.as_view(), name="verify-email"),
    path("password-reset/", views.PasswordResetView.as_view(), name="password-reset"),
    path(
        "password-reset/confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("me/", views.MeView.as_view(), name="me"),
]
