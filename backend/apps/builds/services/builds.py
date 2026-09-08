"""
Saved-build persistence and the catalogue side of the PC builder.

The compatibility rules themselves live in `compatibility.py` and touch no
database. This module is the layer that turns variant ids into the selection
that module expects, and back again.

One rule runs through all of it: **a build stores variant ids, never prices.**
Totals are recomputed from the live variant on every read, so a build opened
six months later quotes today's price and today's stock, exactly as a cart
does. Storing a total would mean a share link that lies.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch

from apps.catalog.models import (
    ComponentProfile,
    ComponentSlot,
    ProductImage,
    ProductVariant,
)
from config.exceptions import DomainError

from ..models import PCBuild, PCBuildItem
from . import compatibility

MAX_BUILDS_PER_USER = 25
MAX_QUANTITY_PER_SLOT = 4

VALID_SLOTS = frozenset(ComponentSlot.values)


def _money(value):
    """
    Render a money column the way the rest of the API does.

    The payloads in this module are plain dicts rather than serializer output,
    so nothing applies DRF's COERCE_DECIMAL_TO_STRING for them. Without this
    a Decimal reaches the JSON encoder and lands in the client as a float --
    the one representation a price must never have.
    """
    return None if value is None else f"{value:.2f}"


# --------------------------------------------------------------------------
# Reading the catalogue for a slot
# --------------------------------------------------------------------------


def component_queryset(slot):
    """
    Buyable products that can fill `slot`, cheapest variant first.

    Only active products with an active, in-stock variant appear: offering a
    part the builder cannot then add to a cart is the single most annoying
    thing a configurator does.
    """
    if slot not in VALID_SLOTS:
        raise DomainError(
            f"Unknown component slot '{slot}'.", code="INVALID_SLOT", field="slot"
        )

    active_variants = ProductVariant.objects.filter(is_active=True).order_by("price", "id")

    return (
        ComponentProfile.objects.filter(
            slot=slot,
            product__is_active=True,
            product__category__is_active=True,
            product__variants__is_active=True,
        )
        .select_related("product", "product__brand", "product__category")
        .prefetch_related(
            Prefetch("product__variants", queryset=active_variants),
            Prefetch(
                "product__images",
                queryset=ProductImage.objects.order_by("-is_primary", "sort_order", "id"),
            ),
        )
        .distinct()
    )


def filter_by_compatibility(queryset, slot, selection_profiles):
    """
    Narrow a slot's options to those that fit what is already chosen.

    This is a *convenience*, not the check: it only applies the rules that are
    unambiguous and cheap in SQL (socket, memory type, board form factor).
    Everything else is left to `compatibility.evaluate`, which sees the whole
    build. The distinction matters -- a filter that guessed would hide parts
    that are actually fine, and a shopper cannot debug an absence.
    """
    cpu = selection_profiles.get(ComponentSlot.CPU)
    board = selection_profiles.get(ComponentSlot.MOTHERBOARD)
    case = selection_profiles.get(ComponentSlot.CASE)

    if slot == ComponentSlot.MOTHERBOARD:
        if cpu and cpu.socket:
            queryset = queryset.filter(socket__iexact=cpu.socket)
        if case and case.supported_form_factors:
            queryset = queryset.filter(form_factor__in=case.supported_form_factors)

    elif slot == ComponentSlot.CPU:
        if board and board.socket:
            queryset = queryset.filter(socket__iexact=board.socket)

    elif slot == ComponentSlot.RAM:
        if board and board.ram_type:
            queryset = queryset.filter(ram_type__iexact=board.ram_type)

    elif slot == ComponentSlot.CASE:
        if board and board.form_factor:
            queryset = queryset.filter(supported_form_factors__contains=board.form_factor)

    return queryset


# --------------------------------------------------------------------------
# Turning a client payload into something the rules can read
# --------------------------------------------------------------------------


def _clean_items(raw_items):
    """
    Validate the wire shape: a list of {slot, variant_id, quantity}.

    Raises rather than skipping bad rows. A configurator that silently drops a
    part the shopper picked is worse than one that refuses the request.
    """
    if not isinstance(raw_items, list):
        raise DomainError(
            "Expected a list of build items.", code="INVALID_ITEMS", field="items"
        )

    cleaned = {}
    for row in raw_items:
        if not isinstance(row, dict):
            raise DomainError(
                "Each build item must be an object.", code="INVALID_ITEMS", field="items"
            )

        slot = row.get("slot")
        if slot not in VALID_SLOTS:
            raise DomainError(
                f"Unknown component slot '{slot}'.", code="INVALID_SLOT", field="slot"
            )
        if slot in cleaned:
            raise DomainError(
                f"A build holds one part per slot, and '{slot}' was given twice.",
                code="DUPLICATE_SLOT",
                field="slot",
            )

        try:
            variant_id = int(row.get("variant_id"))
        except (TypeError, ValueError):
            raise DomainError(
                "Each build item needs a numeric variant_id.",
                code="INVALID_VARIANT",
                field="variant_id",
            ) from None

        try:
            quantity = int(row.get("quantity", 1))
        except (TypeError, ValueError):
            quantity = 1
        if not 1 <= quantity <= MAX_QUANTITY_PER_SLOT:
            raise DomainError(
                f"Quantity must be between 1 and {MAX_QUANTITY_PER_SLOT}.",
                code="INVALID_QUANTITY",
                field="quantity",
            )

        cleaned[slot] = {"variant_id": variant_id, "quantity": quantity}

    return cleaned


def load_selection(raw_items):
    """
    Resolve a payload into `(selection, lines)`.

    `selection` is what `compatibility.evaluate` consumes. `lines` is what the
    UI renders -- price, stock and image included -- and is where the honesty
    about a stale build lives: a variant that has since been deactivated or
    deleted comes back as an `unavailable` line rather than vanishing.
    """
    cleaned = _clean_items(raw_items)
    if not cleaned:
        return {}, []

    variant_ids = [row["variant_id"] for row in cleaned.values()]
    variants = {
        v.id: v
        for v in ProductVariant.objects.filter(id__in=variant_ids)
        .select_related("product", "product__brand", "product__category", "product__component")
        .prefetch_related("product__images")
    }

    selection, lines = {}, []

    for slot, row in cleaned.items():
        variant = variants.get(row["variant_id"])
        quantity = row["quantity"]

        if variant is None:
            lines.append(
                {
                    "slot": slot,
                    "variant_id": row["variant_id"],
                    "quantity": quantity,
                    "issue": "unavailable",
                    "product": None,
                }
            )
            continue

        product = variant.product
        profile = getattr(product, "component", None)

        # A part filed under a different slot than the client claims is a
        # client bug, and silently honouring it would let a GPU be checked as
        # a PSU. Report it and keep the part out of the rules.
        if profile is not None and profile.slot != slot:
            profile = None

        issue = None
        if not variant.is_active or not product.is_active:
            issue = "unavailable"
        elif variant.stock <= 0:
            issue = "out_of_stock"

        if issue != "unavailable":
            selection[slot] = {
                "profile": profile,
                "name": product.name,
                "quantity": quantity,
            }

        image = next(
            (
                img
                for img in sorted(
                    product.images.all(),
                    key=lambda i: (not i.is_primary, i.sort_order, i.id),
                )
            ),
            None,
        )

        lines.append(
            {
                "slot": slot,
                "variant_id": variant.id,
                "quantity": quantity,
                "issue": issue,
                "product": {
                    "id": product.id,
                    "name": product.name,
                    "slug": product.slug,
                    "brand": product.brand.name if product.brand else None,
                    "variant_label": variant.option_label,
                    "sku": variant.sku,
                    # Money leaves as a decimal string, never a float. These
                    # dicts bypass a serializer, so DRF's JSON encoder would
                    # otherwise render a Decimal as 46500.0 and hand the
                    # client a binary float to do arithmetic on.
                    "price": _money(variant.price),
                    "compare_at_price": _money(variant.compare_at_price),
                    "stock": variant.stock,
                    "image": image.image.url if image else None,
                },
            }
        )

    lines.sort(key=lambda line: compatibility.SLOT_ORDER.index(line["slot"]))
    return selection, lines


def price_lines(lines):
    """
    Subtotal across the buyable lines. Unavailable parts contribute zero.

    Prices on a line are already decimal *strings* (see `_money`), so they are
    parsed back to Decimal here rather than summed as text or as floats. The
    round trip is exact: the string came from a DECIMAL(12,2) column formatted
    to two places, so no precision exists to lose.
    """
    total = Decimal("0.00")
    for line in lines:
        product = line["product"]
        if product is None or line["issue"] == "unavailable":
            continue
        total += Decimal(product["price"]) * line["quantity"]
    return total


def evaluate_payload(raw_items):
    """The whole stateless check, as the validate endpoint returns it."""
    selection, lines = load_selection(raw_items)
    report = compatibility.evaluate(selection)
    return {
        "lines": lines,
        "subtotal": _money(price_lines(lines)),
        **report.as_dict(),
    }


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


@transaction.atomic
def save_build(*, user, name, raw_items, build=None):
    """
    Create or replace a saved build.

    Items are replaced wholesale rather than diffed: a build is small, and a
    diff would be more code for an operation that is already atomic.
    """
    selection, lines = load_selection(raw_items)
    if not lines:
        raise DomainError(
            "A build needs at least one component before it can be saved.",
            code="EMPTY_BUILD",
            field="items",
        )

    report = compatibility.evaluate(selection)
    clean_name = (name or "").strip()[:120] or "My build"

    if build is None:
        if user is not None and user.is_authenticated:
            existing = PCBuild.objects.filter(user=user).count()
            if existing >= MAX_BUILDS_PER_USER:
                raise DomainError(
                    f"You can keep up to {MAX_BUILDS_PER_USER} saved builds. "
                    "Delete one to save another.",
                    code="BUILD_LIMIT_REACHED",
                )
        build = PCBuild(user=user if (user and user.is_authenticated) else None)

    build.name = clean_name
    build.is_compatible = report.is_compatible
    build.estimated_watts = report.estimated_watts
    build.save()

    build.items.all().delete()
    PCBuildItem.objects.bulk_create(
        [
            PCBuildItem(
                build=build,
                slot=line["slot"],
                variant_id=line["variant_id"],
                quantity=line["quantity"],
            )
            for line in lines
            # A variant that no longer exists cannot be stored -- the FK would
            # refuse it. Dropping it here keeps the saved build loadable.
            if line["product"] is not None
        ]
    )
    return build


def build_payload(build):
    """
    Render a saved build, re-checked against the catalogue as it is now.

    The stored `is_compatible` is not trusted here. A build saved when a part
    was in stock and compatible must still report the truth today, and the
    only way to do that is to run the rules again.
    """
    raw_items = [
        {"slot": item.slot, "variant_id": item.variant_id, "quantity": item.quantity}
        for item in build.items.all()
    ]
    result = evaluate_payload(raw_items)
    return {
        "id": build.id,
        "name": build.name,
        "share_token": build.share_token,
        "created_at": build.created_at,
        "updated_at": build.updated_at,
        **result,
    }


def user_builds(user):
    return (
        PCBuild.objects.filter(user=user)
        .prefetch_related("items")
        .order_by("-updated_at", "-id")
    )


def get_build_for_share(token):
    """
    Resolve a share token.

    Missing returns 404 through DomainError's status override rather than
    None, so every caller reports it the same way.
    """
    build = (
        PCBuild.objects.filter(share_token=token).prefetch_related("items").first()
    )
    if build is None:
        raise DomainError(
            "That build link is not valid.", code="BUILD_NOT_FOUND", status_code=404
        )
    return build
