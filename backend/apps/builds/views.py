"""
PC-builder endpoints (§14 of the build brief).

Three surfaces, and the split between them is the point:

  * `/pc-builder/components/` is catalogue browsing, scoped to one slot.
  * `/pc-builder/validate/` is stateless. The client posts what is selected
    and gets a verdict; nothing is written, so the panel can revalidate on
    every change without accumulating rows.
  * `/builds/` persists, and is the only one that needs an account -- except
    for reading a share link, which is public by design.
"""
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.catalog.models import ComponentSlot
from config.exceptions import DomainError

from .serializers import (
    BuildSaveInputSerializer,
    BuildValidateInputSerializer,
    ComponentOptionSerializer,
)
from .services import builds as build_services
from .services import compatibility

# Which profile fields are worth surfacing on a picker row, per slot. Keeping
# this here rather than in the model means adding a column to the UI never
# means a migration.
_ROW_ATTRIBUTES = {
    ComponentSlot.CPU: ("socket", "tdp_watts"),
    ComponentSlot.COOLER: ("cooler_max_tdp_watts", "height_mm"),
    ComponentSlot.MOTHERBOARD: ("socket", "form_factor", "ram_type", "ram_slots"),
    ComponentSlot.RAM: ("ram_type", "capacity_gb", "module_count"),
    ComponentSlot.GPU: ("power_watts", "length_mm"),
    ComponentSlot.SSD: ("capacity_gb",),
    ComponentSlot.HDD: ("capacity_gb",),
    ComponentSlot.PSU: ("wattage", "efficiency_rating"),
    ComponentSlot.CASE: ("supported_form_factors", "max_gpu_length_mm"),
}

_ATTRIBUTE_LABELS = {
    "socket": "Socket",
    "tdp_watts": "TDP",
    "cooler_max_tdp_watts": "Cools up to",
    "height_mm": "Height",
    "form_factor": "Form factor",
    "ram_type": "Memory",
    "ram_slots": "Slots",
    "capacity_gb": "Capacity",
    "module_count": "Modules",
    "power_watts": "Draw",
    "length_mm": "Length",
    "wattage": "Output",
    "efficiency_rating": "Efficiency",
    "supported_form_factors": "Fits",
    "max_gpu_length_mm": "Max GPU",
}

_ATTRIBUTE_UNITS = {
    "tdp_watts": "W",
    "cooler_max_tdp_watts": "W",
    "power_watts": "W",
    "wattage": "W",
    "height_mm": "mm",
    "length_mm": "mm",
    "max_gpu_length_mm": "mm",
    "capacity_gb": "GB",
}


def _row_attributes(profile):
    """Format a profile's headline fields as display strings."""
    out = {}
    for field_name in _ROW_ATTRIBUTES.get(profile.slot, ()):
        value = getattr(profile, field_name, None)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        else:
            value = f"{value}{_ATTRIBUTE_UNITS.get(field_name, '')}"
        out[_ATTRIBUTE_LABELS.get(field_name, field_name)] = value
    return out


def _selected_profiles(request):
    """
    Read the already-chosen parts from the query string.

    Sent as `?selected=cpu:12,motherboard:34` -- a compact form that survives
    being a bookmarkable URL, which matters because the picker is a page the
    shopper navigates back to.
    """
    raw = request.query_params.get("selected", "").strip()
    if not raw:
        return {}

    items = []
    for chunk in raw.split(","):
        slot, _, variant_id = chunk.partition(":")
        slot, variant_id = slot.strip(), variant_id.strip()
        if not slot or not variant_id.isdigit():
            continue
        items.append({"slot": slot, "variant_id": int(variant_id)})

    selection, _ = build_services.load_selection(items)
    return {slot: entry["profile"] for slot, entry in selection.items() if entry["profile"]}


class ComponentListView(GenericAPIView):
    """
    GET /api/v1/pc-builder/components/?slot=cpu[&selected=...][&q=][&brand=]

    Public: choosing parts is browsing, and requiring an account to browse is
    how a configurator loses the visit.
    """

    permission_classes = [AllowAny]
    serializer_class = ComponentOptionSerializer

    def get(self, request):
        slot = request.query_params.get("slot", "").strip()
        if not slot:
            raise DomainError(
                "A component slot is required.", code="INVALID_SLOT", field="slot"
            )

        queryset = build_services.component_queryset(slot)

        compatible_only = request.query_params.get("compatible_only", "true").lower() not in (
            "false",
            "0",
            "no",
        )
        if compatible_only:
            queryset = build_services.filter_by_compatibility(
                queryset, slot, _selected_profiles(request)
            )

        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(product__name__icontains=keyword)

        brand = request.query_params.get("brand", "").strip()
        if brand:
            queryset = queryset.filter(product__brand__slug=brand)

        rows = []
        for profile in queryset[:200]:
            product = profile.product
            variant = next(iter(product.variants.all()), None)
            if variant is None:
                continue
            image = next(iter(product.images.all()), None)
            rows.append(
                {
                    "product_id": product.id,
                    "name": product.name,
                    "slug": product.slug,
                    "brand": product.brand.name if product.brand else None,
                    "category": product.category.name if product.category else None,
                    "image": image.image.url if image else None,
                    "variant_id": variant.id,
                    "sku": variant.sku,
                    "variant_label": variant.option_label,
                    "price": variant.price,
                    "compare_at_price": variant.compare_at_price,
                    "stock": variant.stock,
                    "in_stock": variant.stock > 0,
                    "rating_avg": product.rating_avg,
                    "rating_count": product.rating_count,
                    "attributes": _row_attributes(profile),
                }
            )

        rows.sort(key=lambda row: row["price"])
        return Response(
            {
                "slot": slot,
                "count": len(rows),
                "results": ComponentOptionSerializer(rows, many=True).data,
            }
        )


@extend_schema(
    tags=["builds"],
    responses={200: None},
    summary="The component slots a PC build is made of",
)
class SlotListView(APIView):
    """
    GET /api/v1/pc-builder/slots/ -- the builder's own vocabulary.

    Served rather than hardcoded in the client so the two cannot drift on
    which slots are required or what order they appear in.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "slots": [
                    {
                        "slot": slot,
                        "label": ComponentSlot(slot).label,
                        "required": slot in compatibility.REQUIRED_SLOTS,
                        "peripheral": slot in compatibility.PERIPHERAL_SLOTS,
                    }
                    for slot in compatibility.SLOT_ORDER
                ]
            }
        )


class BuildValidateView(GenericAPIView):
    """POST /api/v1/pc-builder/validate/ -- stateless compatibility check."""

    permission_classes = [AllowAny]
    serializer_class = BuildValidateInputSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(build_services.evaluate_payload(serializer.validated_data["items"]))


class BuildListCreateView(GenericAPIView):
    """
    GET  /api/v1/builds/ -- this account's saved builds.
    POST /api/v1/builds/ -- save one.

    Saving needs an account. A guest can still build and share: the share
    token is minted on save, and an anonymous save is refused here only
    because there would be no way to list it back.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BuildSaveInputSerializer

    def get(self, request):
        builds = build_services.user_builds(request.user)
        return Response(
            {"results": [build_services.build_payload(b) for b in builds]}
        )

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        build = build_services.save_build(
            user=request.user,
            name=serializer.validated_data.get("name"),
            raw_items=serializer.validated_data["items"],
        )
        return Response(
            build_services.build_payload(build), status=status.HTTP_201_CREATED
        )


class BuildDetailView(GenericAPIView):
    """
    GET    /api/v1/builds/{token}/ -- public, the share link.
    PUT    /api/v1/builds/{token}/ -- owner only.
    DELETE /api/v1/builds/{token}/ -- owner only.

    The token *is* the read capability, so GET is deliberately open: a link
    you send someone has to work when they open it. Writes check ownership,
    and a non-owner's write returns 404 rather than 403 -- the same rule the
    rest of this API follows, so a probe cannot confirm a build exists.
    """

    permission_classes = [AllowAny]
    serializer_class = BuildSaveInputSerializer

    def get(self, request, token):
        build = build_services.get_build_for_share(token)
        payload = build_services.build_payload(build)
        payload["is_owner"] = bool(
            request.user.is_authenticated and build.user_id == request.user.id
        )
        return Response(payload)

    def _owned(self, request, token):
        build = build_services.get_build_for_share(token)
        if not request.user.is_authenticated or build.user_id != request.user.id:
            raise DomainError(
                "That build link is not valid.",
                code="BUILD_NOT_FOUND",
                status_code=404,
            )
        return build

    def put(self, request, token):
        build = self._owned(request, token)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        build = build_services.save_build(
            user=request.user,
            name=serializer.validated_data.get("name"),
            raw_items=serializer.validated_data["items"],
            build=build,
        )
        return Response(build_services.build_payload(build))

    def delete(self, request, token):
        self._owned(request, token).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
