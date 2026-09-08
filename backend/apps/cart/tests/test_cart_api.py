"""
The HTTP surface of apps/cart/urls.py.

The cart is an authenticated-only resource (FR-CRT-1) -- guests keep theirs in
localStorage and hand it over at POST /cart/merge/ on login -- so every route
must challenge an anonymous caller rather than quietly serving an empty cart.

Two contract details are asserted here and nowhere else: money crosses the wire
as decimal **strings**, and every mutation returns the whole cart so the
mini-cart, the line list and the subtotal cannot disagree.
"""
import pytest
from django.urls import reverse

from apps.cart.models import CartItem
from apps.cart.services import cart as cart_services
from apps.catalog.models import InventoryLog, ProductVariant
from apps.catalog.services import inventory as inventory_services

pytestmark = pytest.mark.django_db


ANONYMOUS_CALLS = [
    ("get", "cart:detail", {}, None),
    ("post", "cart:item-list", {}, {"variant_id": 1, "quantity": 1}),
    ("patch", "cart:item-detail", {"pk": 1}, {"quantity": 2}),
    ("delete", "cart:item-detail", {"pk": 1}, None),
    ("post", "cart:merge", {}, {"items": []}),
]


@pytest.fixture
def shopper(api, customer):
    """An authenticated client for `customer`."""
    api.force_authenticate(user=customer)
    return api


@pytest.mark.parametrize("method,route,kwargs,payload", ANONYMOUS_CALLS)
def test_an_anonymous_caller_is_refused_with_401_on_every_cart_route(
    api, method, route, kwargs, payload
):
    url = reverse(route, kwargs=kwargs)

    call = getattr(api, method)
    response = call(url) if payload is None else call(url, payload, format="json")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


# ---------------------------------------------------------------------------
# GET /api/v1/cart/
# ---------------------------------------------------------------------------
def test_a_first_time_customer_gets_an_empty_cart_rather_than_a_404(
    shopper, cart_url
):
    response = shopper.get(cart_url)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "items", "item_count", "subtotal", "notices"}
    assert body["items"] == []
    assert body["item_count"] == 0
    assert body["subtotal"] == "0.00"
    assert body["notices"] == []


def test_a_cart_line_carries_everything_needed_to_render_it(
    shopper, cart_url, cart, variant
):
    """
    The flat line shape frozen in docs/api-contract-cart-checkout-orders.md.

    Every key here is read by name in the storefront
    (frontend/src/features/cart/useCart.js `fromServerItem`), so this is a
    contract test, not a snapshot. It was nested under a `variant` object until
    2026-08-22 and the signed-in cart rendered with no name, no image and no
    link -- and `variant_id`, which the checkout quote request is built from,
    was missing entirely, so the quote came back 400 and the totals vanished
    with it. If a key is renamed here, rename it in the contract doc and in
    `fromServerItem` in the same commit.
    """
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)

    body = shopper.get(cart_url).json()

    (line,) = body["items"]
    assert set(line) == {
        "id",
        "variant_id",
        "product_id",
        "product_name",
        "product_slug",
        "variant_label",
        "sku",
        "image",
        "unit_price",
        "compare_at_price",
        "quantity",
        "effective_quantity",
        "line_total",
        "stock",
        "in_stock",
        "is_available",
        "issue",
    }
    assert line["variant_id"] == variant.pk
    assert line["product_id"] == variant.product_id
    assert line["product_name"] == "Asus Vivobook Go 15"
    assert line["product_slug"] == "asus-vivobook-go-15"
    assert line["sku"] == "VIVO-8-512"
    assert line["variant_label"] == variant.label
    # A URL string or null -- never an object. It goes straight into an
    # <img src>, and a quote line already answers in that shape.
    assert line["image"] is None or isinstance(line["image"], str)
    assert line["quantity"] == 2
    assert line["effective_quantity"] == 2
    assert line["stock"] == 10
    assert line["in_stock"] is True
    assert line["is_available"] is True
    assert line["issue"] is None


def test_a_cart_line_and_a_quote_line_describe_the_same_variant_with_the_same_words(
    shopper, cart_url, quote_url, cart, variant
):
    """
    One line vocabulary across the two surfaces that price the same basket.

    The cart page renders a row from the cart payload and its money from the
    quote payload, side by side. When the two disagreed about what a line is
    called, the join silently produced undefined on every render -- so the
    overlap is asserted rather than assumed.
    """
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)

    cart_line = shopper.get(cart_url).json()["items"][0]
    quote_line = shopper.post(
        quote_url,
        {"items": [{"variant_id": variant.pk, "quantity": 2}]},
        format="json",
    ).json()["lines"][0]

    shared = (
        "variant_id",
        "product_id",
        "product_name",
        "product_slug",
        "variant_label",
        "sku",
        "image",
        "unit_price",
        "quantity",
        "line_total",
        "is_available",
        "issue",
    )
    for key in shared:
        assert key in cart_line, key
        assert key in quote_line, key
        assert cart_line[key] == quote_line[key], key


def test_money_crosses_the_wire_as_decimal_strings_and_never_as_floats(
    shopper, cart_url, cart, variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)

    body = shopper.get(cart_url).json()

    (line,) = body["items"]
    for value in (
        body["subtotal"],
        line["unit_price"],
        line["line_total"],
    ):
        assert isinstance(value, str), value
    assert body["subtotal"] == "2000.00"
    assert line["unit_price"] == "1000.00"
    assert line["line_total"] == "2000.00"


def test_a_customer_never_sees_another_customers_cart_lines(
    shopper, cart_url, other_cart, variant
):
    cart_services.add_item(cart=other_cart, variant_id=variant.pk, quantity=3)

    body = shopper.get(cart_url).json()

    assert body["items"] == []
    assert body["item_count"] == 0


def test_the_read_re_checks_availability_and_reports_it_in_notices(
    shopper, cart_url, cart, variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    variant.stock = 0
    variant.save(update_fields=["stock"])

    body = shopper.get(cart_url).json()

    (line,) = body["items"]
    assert line["is_available"] is False
    assert line["issue"] == inventory_services.ISSUE_OUT_OF_STOCK
    assert body["subtotal"] == "0.00"
    assert [notice["code"] for notice in body["notices"]] == [
        cart_services.NOTICE_ITEM_OUT_OF_STOCK
    ]


# ---------------------------------------------------------------------------
# POST /api/v1/cart/items/
# ---------------------------------------------------------------------------
def test_adding_an_item_returns_201_with_the_whole_cart(
    shopper, items_url, variant
):
    response = shopper.post(
        items_url, {"variant_id": variant.pk, "quantity": 2}, format="json"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["item_count"] == 2
    assert body["subtotal"] == "2000.00"
    assert len(body["items"]) == 1


def test_posting_the_same_variant_twice_returns_one_accumulated_line(
    shopper, items_url, variant
):
    shopper.post(items_url, {"variant_id": variant.pk, "quantity": 2}, format="json")
    body = shopper.post(
        items_url, {"variant_id": variant.pk, "quantity": 1}, format="json"
    ).json()

    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 3
    assert body["item_count"] == 3


def test_a_clamped_add_still_succeeds_and_reports_the_clamp_in_notices(
    shopper, items_url, build_variant
):
    scarce = build_variant(price="500.00", stock=2, name="Scarce", slug="scarce")

    response = shopper.post(
        items_url, {"variant_id": scarce.pk, "quantity": 9}, format="json"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["items"][0]["quantity"] == 2
    assert body["notices"][0]["code"] == cart_services.NOTICE_QUANTITY_CLAMPED
    assert body["notices"][0]["variant_id"] == scarce.pk


def test_adding_an_unknown_variant_is_a_404_in_the_error_envelope(
    shopper, items_url
):
    response = shopper.post(
        items_url, {"variant_id": 987654321, "quantity": 1}, format="json"
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "VARIANT_NOT_FOUND",
            "message": "That product is not available.",
            "field": "variant_id",
        }
    }


def test_adding_a_sold_out_variant_is_a_422_carrying_the_out_of_stock_code(
    shopper, items_url, build_variant
):
    sold_out = build_variant(stock=0, name="Sold out", slug="sold-out")

    response = shopper.post(
        items_url, {"variant_id": sold_out.pk, "quantity": 1}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OUT_OF_STOCK"


def test_posting_a_quantity_of_zero_is_a_400_validation_error_on_the_quantity_field(
    shopper, items_url, variant
):
    response = shopper.post(
        items_url, {"variant_id": variant.pk, "quantity": 0}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "quantity"


def test_posting_without_a_variant_id_is_a_400_validation_error(shopper, items_url):
    response = shopper.post(items_url, {"quantity": 1}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "variant_id"


def test_posting_above_the_line_maximum_is_a_422_carrying_a_stable_code(
    shopper, items_url, build_variant
):
    plentiful = build_variant(stock=500, name="Cable", slug="cable")

    response = shopper.post(
        items_url, {"variant_id": plentiful.pk, "quantity": 100}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "QUANTITY_TOO_LARGE"


def test_adding_over_http_moves_no_stock_and_writes_no_inventory_log_row(
    shopper, items_url, variant
):
    shopper.post(items_url, {"variant_id": variant.pk, "quantity": 4}, format="json")

    assert ProductVariant.objects.get(pk=variant.pk).stock == 10
    assert InventoryLog.objects.filter(variant=variant).count() == 0


# ---------------------------------------------------------------------------
# PATCH / DELETE /api/v1/cart/items/{id}/
# ---------------------------------------------------------------------------
@pytest.fixture
def line_id(cart, variant):
    view = cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)
    return view.lines[0].item.pk


@pytest.fixture
def other_customers_line_id(other_cart, variant):
    view = cart_services.add_item(cart=other_cart, variant_id=variant.pk, quantity=7)
    return view.lines[0].item.pk


def test_patching_a_line_returns_200_with_the_recalculated_cart(
    shopper, item_url, line_id
):
    response = shopper.patch(item_url(line_id), {"quantity": 5}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["quantity"] == 5
    assert body["subtotal"] == "5000.00"


def test_patching_a_line_to_zero_is_a_400_because_removal_is_a_delete(
    shopper, item_url, line_id
):
    response = shopper.patch(item_url(line_id), {"quantity": 0}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "quantity"
    assert CartItem.objects.get(pk=line_id).quantity == 2


def test_patching_another_customers_line_is_a_404_and_never_a_403(
    shopper, item_url, other_customers_line_id
):
    response = shopper.patch(
        item_url(other_customers_line_id), {"quantity": 1}, format="json"
    )

    assert response.status_code == 404
    assert response.status_code != 403
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert CartItem.objects.get(pk=other_customers_line_id).quantity == 7


def test_patching_an_unknown_line_looks_exactly_like_patching_someone_elses(
    shopper, item_url, other_customers_line_id
):
    mine = shopper.patch(item_url(987654321), {"quantity": 1}, format="json")
    theirs = shopper.patch(
        item_url(other_customers_line_id), {"quantity": 1}, format="json"
    )

    assert mine.status_code == theirs.status_code == 404
    assert mine.json() == theirs.json()


def test_deleting_a_line_returns_200_with_the_whole_cart_rather_than_an_empty_204(
    shopper, item_url, line_id
):
    response = shopper.delete(item_url(line_id))

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["subtotal"] == "0.00"
    assert not CartItem.objects.filter(pk=line_id).exists()


def test_deleting_another_customers_line_is_a_404_and_leaves_the_line_in_place(
    shopper, item_url, other_customers_line_id
):
    response = shopper.delete(item_url(other_customers_line_id))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert CartItem.objects.filter(pk=other_customers_line_id).exists()


# ---------------------------------------------------------------------------
# POST /api/v1/cart/merge/
# ---------------------------------------------------------------------------
def test_merging_a_guest_cart_returns_200_with_the_combined_cart(
    shopper, merge_url, cart, variant, other_variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)

    response = shopper.post(
        merge_url,
        {
            "items": [
                {"variant_id": variant.pk, "quantity": 2},
                {"variant_id": other_variant.pk, "quantity": 1},
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["item_count"] == 4
    assert body["subtotal"] == "3250.50"
    assert len(body["items"]) == 2


def test_merging_an_empty_guest_cart_is_accepted_and_changes_nothing(
    shopper, merge_url, cart, variant
):
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)

    response = shopper.post(merge_url, {"items": []}, format="json")

    assert response.status_code == 200
    assert response.json()["item_count"] == 1


def test_a_merge_reports_a_dropped_guest_line_in_notices_instead_of_failing(
    shopper, merge_url, variant
):
    response = shopper.post(
        merge_url,
        {
            "items": [
                {"variant_id": 987654321, "quantity": 1},
                {"variant_id": variant.pk, "quantity": 1},
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert [notice["code"] for notice in body["notices"]] == ["VARIANT_NOT_FOUND"]
    assert body["item_count"] == 1


def test_a_merge_payload_without_an_items_key_is_a_400_validation_error(
    shopper, merge_url
):
    response = shopper.post(merge_url, {}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "items"


def test_merging_over_http_moves_no_stock_and_writes_no_inventory_log_row(
    shopper, merge_url, variant
):
    shopper.post(
        merge_url,
        {"items": [{"variant_id": variant.pk, "quantity": 99}]},
        format="json",
    )

    assert ProductVariant.objects.get(pk=variant.pk).stock == 10
    assert InventoryLog.objects.filter(variant=variant).count() == 0
