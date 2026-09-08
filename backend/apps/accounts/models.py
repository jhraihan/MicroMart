"""
User and Address (PRD §6.2).

The custom user model with email as USERNAME_FIELD lands in the very first
migration -- swapping it later is painful.
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class Role(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    STAFF = "staff", "Staff"
    ADMIN = "admin", "Admin"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("role", Role.CUSTOMER)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("role", Role.ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_email_verified", True)
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("Superuser must have is_staff and is_superuser set.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, max_length=254)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.CUSTOMER)
    is_email_verified = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False, help_text="Access to Django Admin. Distinct from the staff role."
    )
    date_joined = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"
        indexes = [models.Index(fields=["role"])]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower().strip()
        super().save(*args, **kwargs)

    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_admin_or_staff(self):
        return self.role in (Role.ADMIN, Role.STAFF)

    def get_full_name(self):
        return self.full_name or self.email

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.email


class Address(TimeStampedModel):
    """
    Bangladesh address shape. Copied verbatim onto an order at placement --
    editing a saved address must never rewrite a past order (PRD §6.3).
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    recipient_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    division = models.CharField(max_length=64)
    district = models.CharField(max_length=64)
    upazila = models.CharField(max_length=64, blank=True)
    area = models.CharField(max_length=128, blank=True)
    street = models.CharField(max_length=255)
    postcode = models.CharField(max_length=12, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_address"
        ordering = ["-is_default", "-created_at"]
        indexes = [models.Index(fields=["user", "is_default"])]
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.recipient_name}, {self.district}"


class EmailVerificationToken(TimeStampedModel):
    """Single-use, time-limited token for registration verification (FR-AUT-3)."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="verification_tokens"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_email_verification_token"

    @property
    def is_usable(self):
        return self.used_at is None and self.expires_at > timezone.now()
