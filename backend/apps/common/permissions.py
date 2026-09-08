"""
API-level authorisation (PRD §10.2).

Hiding a button in React is never the access-control mechanism -- every admin
route carries one of these classes.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAdminOrStaff(BasePermission):
    """Gate for everything under /api/v1/admin/."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_admin_or_staff)


class IsAdminRole(BasePermission):
    """Stricter gate: full admin only, staff excluded."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_admin)


class IsOwner(BasePermission):
    """
    Object-level ownership. Views pair this with a queryset already filtered to
    request.user so a miss surfaces as 404 rather than 403.
    """

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "user", None)
        return owner is not None and owner == request.user


class ReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS
