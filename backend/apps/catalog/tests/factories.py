"""
Deterministic catalogue fixtures.

Every test builds the rows it asserts on. Nothing here reads the seed data --
a suite that depends on whatever happens to be in the dev database asserts on
a moving target, and the acceptance criteria in PRD 5.1/5.2 are exact.

Kept as plain ORM helpers rather than model_bakery recipes because price,
stock and compare-at are the values under test: they must be stated in the
test that depends on them, never filled in by a fixture library.
"""
from __future__ import annotations

import itertools
from decimal import Decimal

from apps.catalog.models import (
    Brand,
    Category,
    Product,
    ProductImage,
    ProductSpec,
    ProductVariant,
)
from apps.orders.models import Order, OrderItem, OrderStatus, PaymentMethod

_seq = itertools.count(1)


def _next(prefix):
    return "{0}-{1}".format(prefix, next(_seq))


def money(value):
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
def make_category(name="Laptops", slug=None, *, parent=None, is_active=True, sort_order=0):
    return Category.objects.create(
        name=name,
        slug=slug or _next("category"),
        parent=parent,
        is_active=is_active,
        sort_order=sort_order,
    )


def make_brand(name="Asus", slug=None, *, is_active=True):
    return Brand.objects.create(
        name=name, slug=slug or _next("brand"), is_active=is_active
    )


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
def make_variant(
    product,
    *,
    sku=None,
    price="1000.00",
    stock=10,
    compare_at_price=None,
    option_label="",
    is_active=True,
    low_stock_threshold=5,
    weight_grams=0,
):
    return ProductVariant.objects.create(
        product=product,
        sku=sku or _next("SKU"),
        option_label=option_label,
        price=money(price),
        compare_at_price=None if compare_at_price is None else money(compare_at_price),
        stock=stock,
        low_stock_threshold=low_stock_threshold,
        weight_grams=weight_grams,
        is_active=is_active,
    )


def make_product(
    category,
    *,
    brand=None,
    name="Test Product",
    slug=None,
    is_active=True,
    description="",
    rating_avg="0.00",
    rating_count=0,
    warranty_months=0,
    model_number="",
    is_featured=False,
    price="1000.00",
    stock=10,
    compare_at_price=None,
    sku=None,
    variants=None,
):
    """
    A product with at least one variant, because price and stock live on
    ProductVariant and never on Product.

    Pass `variants=[{...}]` for the multi-variant case, or `variants=[]` for
    the deliberate no-variant edge case.
    """
    product = Product.objects.create(
        category=category,
        brand=brand,
        name=name,
        slug=slug or _next("product"),
        description=description,
        warranty_months=warranty_months,
        model_number=model_number,
        is_featured=is_featured,
        is_active=is_active,
        rating_avg=Decimal(str(rating_avg)),
        rating_count=rating_count,
    )
    if variants is None:
        make_variant(
            product,
            sku=sku,
            price=price,
            stock=stock,
            compare_at_price=compare_at_price,
        )
    else:
        for spec in variants:
            make_variant(product, **spec)
    return product


def make_image(product, *, variant=None, is_primary=False, sort_order=0, alt_text=""):
    return ProductImage.objects.create(
        product=product,
        variant=variant,
        image="products/2026/01/{0}.jpg".format(_next("img")),
        alt_text=alt_text,
        sort_order=sort_order,
        is_primary=is_primary,
    )


def make_spec(
    product,
    key="Processor",
    value="Intel Core i7",
    sort_order=0,
    *,
    group="",
    group_order=0,
):
    """
    One spec row. `group` bands it on the detail page and in the compare
    matrix; an empty group is legal and renders under a single default band.
    """
    return ProductSpec.objects.create(
        product=product,
        key=key,
        value=value,
        group=group,
        group_order=group_order,
        sort_order=sort_order,
    )


# ---------------------------------------------------------------------------
# Orders -- only needed to give sort=best_selling something to rank
# ---------------------------------------------------------------------------
def place_order(items, *, status=OrderStatus.DELIVERED):
    """`items` is a list of (variant, quantity). Totals are irrelevant here."""
    order = Order.objects.create(
        reference=_next("ORD"),
        email="buyer@example.com",
        phone="01700000000",
        ship_recipient_name="Buyer",
        ship_phone="01700000000",
        ship_division="Dhaka",
        ship_district="Dhaka",
        ship_street="1 Test Road",
        payment_method=PaymentMethod.COD,
        status=status,
        idempotency_key=_next("idem"),
    )
    for variant, quantity in items:
        OrderItem.objects.create(
            order=order,
            variant=variant,
            product_name=variant.product.name,
            variant_label=variant.label,
            sku=variant.sku,
            unit_price=variant.price,
            quantity=quantity,
            line_total=variant.price * quantity,
        )
    return order


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
def result_slugs(payload):
    """Slugs in response order. Accepts a paginated body or a bare array."""
    rows = payload["results"] if isinstance(payload, dict) else payload
    return [row["slug"] for row in rows]
