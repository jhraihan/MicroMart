"""
Admin catalogue and inventory endpoints (PRD 7.3, US-A2/US-A4/US-A8).

These views read the request, call a service, shape the response. Nothing they
appear to enforce is enforced here -- one-level category nesting, SKU
uniqueness, "a product keeps at least one variant", "delete means deactivate"
and "stock is not a writable column" all live in
services/administration.py, beside the storefront rules in services/catalogue.py
and the stock ledger in services/inventory.py. A rule implemented in a view is
a rule the next surface will not have.

**Role gating (US-A8).** Every class below is `IsAdminRole`, not
`IsAdminOrStaff`. PRD 7.3 gives staff exactly two things -- viewing orders and
advancing their status -- and everything on this module is one of the "every
other admin endpoint rejects staff with 403" cases. An anonymous caller gets
401 from JWTAuthentication; an authenticated staff user gets 403. Hiding the
catalogue screens in React is a convenience on top of this, never the control.
"""
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole

from .admin_serializers import (
    AdminBrandPatchSerializer,
    AdminBrandSerializer,
    AdminBrandWriteSerializer,
    AdminCategoryPatchSerializer,
    AdminCategorySerializer,
    AdminCategoryWriteSerializer,
    AdminProductCreateSerializer,
    AdminProductDetailSerializer,
    AdminProductImageSerializer,
    AdminProductListSerializer,
    AdminProductUpdateSerializer,
    AdminVariantCreateSerializer,
    AdminVariantSerializer,
    AdminVariantUpdateSerializer,
    InventoryAdjustSerializer,
    InventoryLogSerializer,
    InventoryRowSerializer,
    ProductImageReorderSerializer,
    ProductImageUploadSerializer,
)
from .filters import parse_admin_product_query, parse_inventory_query
from .models import Brand, Category, Product, ProductVariant
from .services import administration


class AdminCatalogueView(GenericAPIView):
    """Shared gate. Subclasses add verbs; none of them re-open the door."""

    permission_classes = [IsAdminRole]
    filter_backends = []


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
class AdminProductListView(AdminCatalogueView):
    """
    GET  /api/v1/admin/products/ -- every product, active or not.
    POST /api/v1/admin/products/ -- create one, with its specs and its opening
    variants in the same payload (US-A2).
    """

    def get_serializer_class(self):
        return (
            AdminProductCreateSerializer
            if self.request.method == "POST"
            else AdminProductListSerializer
        )

    def get(self, request):
        query = parse_admin_product_query(request.query_params)
        page = self.paginate_queryset(administration.admin_products(query))
        return self.get_paginated_response(
            AdminProductListSerializer(page, many=True).data
        )

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = administration.create_product(
            actor=request.user, **serializer.validated_data
        )
        return Response(
            AdminProductDetailSerializer(_reload_product(product.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class AdminProductDetailView(AdminCatalogueView):
    """
    GET    /api/v1/admin/products/{id}/
    PATCH  /api/v1/admin/products/{id}/  -- product fields and the spec table.
    DELETE /api/v1/admin/products/{id}/  -- **deactivate**, never destroy.

    The 200 on DELETE carries the deactivated product rather than a bare 204,
    because "deleted" here means `is_active=False` and the response is the only
    honest place to say so: the row is still there, the orders that reference
    it still read correctly, and the admin can put it back.
    """

    serializer_class = AdminProductUpdateSerializer

    def product(self):
        return get_object_or_404(Product, pk=self.kwargs["pk"])

    def get(self, request, pk):
        return Response(AdminProductDetailSerializer(_reload_product(pk)).data)

    def patch(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        administration.update_product(
            self.product(), actor=request.user, **serializer.validated_data
        )
        return Response(AdminProductDetailSerializer(_reload_product(pk)).data)

    def delete(self, request, pk):
        administration.deactivate_product(self.product(), actor=request.user)
        return Response(AdminProductDetailSerializer(_reload_product(pk)).data)


def _reload_product(pk):
    """Re-read through the annotated queryset so counts and prices are fresh."""
    return get_object_or_404(administration.admin_product_detail_queryset(), pk=pk)


# ---------------------------------------------------------------------------
# Product images
# ---------------------------------------------------------------------------
class AdminProductImagesView(AdminCatalogueView):
    """
    POST   /api/v1/admin/products/{id}/images/ -- upload one (multipart).
    PATCH  /api/v1/admin/products/{id}/images/ -- reorder, and optionally move
           the primary flag.
    GET    /api/v1/admin/products/{id}/images/ -- the current gallery.

    PRD 7.3 lists this path once, as "upload and reorder"; POST does the first
    and PATCH the second rather than overloading one verb with a mode flag.
    """

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        return (
            ProductImageUploadSerializer
            if self.request.method == "POST"
            else ProductImageReorderSerializer
        )

    def product(self):
        return get_object_or_404(Product, pk=self.kwargs["pk"])

    def get(self, request, pk):
        return Response(_gallery(self.product()))

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = self.product()
        image = administration.add_product_image(
            product, actor=request.user, **serializer.validated_data
        )
        return Response(
            {
                "image": AdminProductImageSerializer(image).data,
                "images": _gallery(product),
            },
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = self.product()
        administration.reorder_product_images(
            product, actor=request.user, **serializer.validated_data
        )
        return Response({"images": _gallery(product)})


class AdminProductImageDetailView(AdminCatalogueView):
    """DELETE /api/v1/admin/products/{id}/images/{image_id}/ -- remove one."""

    serializer_class = AdminProductImageSerializer

    def delete(self, request, pk, image_id):
        product = get_object_or_404(Product, pk=pk)
        administration.delete_product_image(product, image_id, actor=request.user)
        return Response({"images": _gallery(product)})


def _gallery(product):
    return AdminProductImageSerializer(
        administration.product_images(product), many=True
    ).data


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------
class AdminVariantListView(AdminCatalogueView):
    """
    GET  /api/v1/admin/variants/ -- price, SKU and stock across the catalogue.
    POST /api/v1/admin/variants/ -- add one to an existing product.
    """

    def get_serializer_class(self):
        return (
            AdminVariantCreateSerializer
            if self.request.method == "POST"
            else AdminVariantSerializer
        )

    def get(self, request):
        query = parse_inventory_query(request.query_params)
        page = self.paginate_queryset(administration.admin_variants(query))
        return self.get_paginated_response(
            AdminVariantSerializer(page, many=True).data
        )

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = dict(serializer.validated_data)
        product = get_object_or_404(Product, pk=payload.pop("product_id"))
        variant = administration.create_variant(
            product=product, actor=request.user, **payload
        )
        return Response(
            AdminVariantSerializer(_reload_variant(variant.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class AdminVariantDetailView(AdminCatalogueView):
    """
    GET    /api/v1/admin/variants/{id}/
    PATCH  /api/v1/admin/variants/{id}/ -- price, SKU, label, threshold.
           A payload carrying `stock` is refused with 422 STOCK_NOT_WRITABLE.
    DELETE /api/v1/admin/variants/{id}/ -- deactivate, unless it is the
           product's last active one.
    """

    serializer_class = AdminVariantUpdateSerializer

    def variant(self):
        return get_object_or_404(
            ProductVariant.objects.select_related("product"), pk=self.kwargs["pk"]
        )

    def get(self, request, pk):
        return Response(AdminVariantSerializer(_reload_variant(pk)).data)

    def patch(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        administration.update_variant(
            self.variant(), actor=request.user, **serializer.validated_data
        )
        return Response(AdminVariantSerializer(_reload_variant(pk)).data)

    def delete(self, request, pk):
        administration.deactivate_variant(self.variant(), actor=request.user)
        return Response(AdminVariantSerializer(_reload_variant(pk)).data)


def _reload_variant(pk):
    return get_object_or_404(
        ProductVariant.objects.select_related("product", "product__brand"), pk=pk
    )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
class AdminCategoryListView(AdminCatalogueView):
    """GET / POST /api/v1/admin/categories/ -- taxonomy, one level deep."""

    pagination_class = None
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        return (
            AdminCategoryWriteSerializer
            if self.request.method == "POST"
            else AdminCategorySerializer
        )

    def get(self, request):
        return Response(
            AdminCategorySerializer(administration.admin_categories(), many=True).data
        )

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        category = administration.create_category(
            actor=request.user, **serializer.validated_data
        )
        return Response(
            AdminCategorySerializer(_reload_category(category.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class AdminCategoryDetailView(AdminCatalogueView):
    """
    GET / PATCH / DELETE /api/v1/admin/categories/{id}/.

    DELETE deactivates. Product.category is `on_delete=PROTECT`, so a real
    delete would 500 on the first category anyone had used -- and deactivating
    is what the storefront already treats as "gone", since an inactive category
    withdraws everything beneath it.
    """

    serializer_class = AdminCategoryPatchSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def category(self):
        return get_object_or_404(Category, pk=self.kwargs["pk"])

    def get(self, request, pk):
        return Response(AdminCategorySerializer(_reload_category(pk)).data)

    def patch(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        administration.update_category(
            self.category(), actor=request.user, **serializer.validated_data
        )
        return Response(AdminCategorySerializer(_reload_category(pk)).data)

    def delete(self, request, pk):
        administration.deactivate_category(self.category(), actor=request.user)
        return Response(AdminCategorySerializer(_reload_category(pk)).data)


def _reload_category(pk):
    return get_object_or_404(administration.admin_categories(), pk=pk)


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------
class AdminBrandListView(AdminCatalogueView):
    """GET / POST /api/v1/admin/brands/."""

    pagination_class = None
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        return (
            AdminBrandWriteSerializer
            if self.request.method == "POST"
            else AdminBrandSerializer
        )

    def get(self, request):
        return Response(
            AdminBrandSerializer(administration.admin_brands(), many=True).data
        )

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        brand = administration.create_brand(
            actor=request.user, **serializer.validated_data
        )
        return Response(
            AdminBrandSerializer(_reload_brand(brand.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class AdminBrandDetailView(AdminCatalogueView):
    """
    GET / PATCH / DELETE /api/v1/admin/brands/{id}/.

    DELETE deactivates here too, but note the asymmetry with categories, and
    that it is deliberate: an inactive brand leaves the brand facet while its
    products stay listed and buyable. A brand is a label on stock; a category
    is a place in the navigation.
    """

    serializer_class = AdminBrandPatchSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def brand(self):
        return get_object_or_404(Brand, pk=self.kwargs["pk"])

    def get(self, request, pk):
        return Response(AdminBrandSerializer(_reload_brand(pk)).data)

    def patch(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        administration.update_brand(
            self.brand(), actor=request.user, **serializer.validated_data
        )
        return Response(AdminBrandSerializer(_reload_brand(pk)).data)

    def delete(self, request, pk):
        administration.deactivate_brand(self.brand(), actor=request.user)
        return Response(AdminBrandSerializer(_reload_brand(pk)).data)


def _reload_brand(pk):
    return get_object_or_404(administration.admin_brands(), pk=pk)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
class AdminInventoryView(ListAPIView):
    """
    GET /api/v1/admin/inventory/ -- stock across variants, `?low_stock=true`
    for the reorder list (US-A4).

    The page carries a `summary` counted over the whole catalogue rather than
    the page, for the same reason the product list carries facets beside its
    results: "3 low-stock items on this page" is not the number anyone needs.
    """

    permission_classes = [IsAdminRole]
    serializer_class = InventoryRowSerializer
    filter_backends = []

    def get_queryset(self):
        return administration.inventory_rows(
            parse_inventory_query(self.request.query_params)
        )

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data["summary"] = administration.inventory_summary()
        return response


class AdminInventoryAdjustView(AdminCatalogueView):
    """
    POST /api/v1/admin/inventory/adjust/ -- one manual movement, with a
    mandatory reason (FR-INV-8).

    Calls services/inventory.adjust_stock through the admin policy wrapper, so
    the row lock is taken and the append-only InventoryLog row is written in the
    same transaction as the change. This is the *only* way stock moves outside
    the order state machine, which is what keeps `sum(InventoryLog.delta)`
    reconciled to `ProductVariant.stock`.
    """

    serializer_class = InventoryAdjustSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        variant, log = administration.apply_manual_adjustment(
            actor=request.user, **serializer.validated_data
        )
        return Response(
            {
                "variant": InventoryRowSerializer(_reload_variant(variant.pk)).data,
                "log": InventoryLogSerializer(log).data,
                "logged_stock": _logged_stock(variant),
            }
        )


def _logged_stock(variant):
    """The ledger's own answer, returned beside the column so drift is visible."""
    total = variant.inventory_logs.aggregate(total=Sum("delta"))["total"]
    return total or 0


class AdminVariantLedgerView(AdminCatalogueView):
    """
    GET /api/v1/admin/inventory/{variant_id}/logs/ -- the movement history
    behind one variant's number.

    Not in PRD 7.3's table, but the ledger is the entire justification for
    refusing a direct stock write: an admin told "use the adjustment endpoint"
    has to be able to see what the adjustments were.
    """

    serializer_class = InventoryLogSerializer

    def get(self, request, variant_id):
        variant = get_object_or_404(ProductVariant, pk=variant_id)
        return Response(
            {
                "variant_id": variant.pk,
                "stock": variant.stock,
                "logged_stock": _logged_stock(variant),
                "logs": InventoryLogSerializer(
                    administration.variant_ledger(variant), many=True
                ).data,
            }
        )
