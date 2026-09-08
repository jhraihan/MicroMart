"""Address book services (FR-AUT-6)."""
from django.db import transaction

from ..models import Address


@transaction.atomic
def create_address(*, user, **fields):
    address = Address(user=user, **fields)
    
    if not user.addresses.exists():
        address.is_default = True
    address.save()
    if address.is_default:
        _clear_other_defaults(user, keep=address.pk)
    return address


@transaction.atomic
def update_address(*, address, **fields):
    for key, value in fields.items():
        setattr(address, key, value)
    address.save()
    if address.is_default:
        _clear_other_defaults(address.user, keep=address.pk)
    return address


@transaction.atomic
def delete_address(*, address):
    user, was_default = address.user, address.is_default
    address.delete()
    if was_default:
        replacement = user.addresses.order_by("-created_at").first()
        if replacement:
            replacement.is_default = True
            replacement.save(update_fields=["is_default"])


def _clear_other_defaults(user, *, keep):
    Address.objects.filter(user=user, is_default=True).exclude(pk=keep).update(
        is_default=False
    )
