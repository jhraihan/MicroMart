"""
The checkout quote -- `apps/orders/services/checkout.py`.

`POST /checkout/quote/` is the only place a shopper's totals come from, and the
same `resolve_basket` + `compute_totals` pair prices order placement, so a bug
here is charged to a real card. The suite pins four things:

1. **`resolve_basket` handles all three input shapes** -- an explicit items
   payload (guest checkout, and buy-now from a product page), a signed-in
   customer's server cart, and a cart object handed straight in by placement.
2. **Payment-method availability is the server's answer**, not React's: the
   store switch, the zone's policy and the Cash-on-Delivery ceiling each refuse
   with their own stable code.
3. **The client's arithmetic has no authority.** A request may name a variant
   and a quantity. Everything else it sends about money is ignored.
4. Money crosses the wire as decimal strings.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.cart.services import cart as cart_services
from apps.orders.models import PaymentMethod
from apps.orders.services import checkout as checkout_services
from apps.orders.services import totals as totals_services
from apps.promotions.models import DiscountType
from apps.shipping.services import rates as shipping_services
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


def totals_for(variant, quantity=1, *, district=None, coupon_code=None):
    """Price one variant the way the quote would, so the gates get real totals."""
    return totals_services.compute_totals(
        lines=totals_services.build_lines([(variant, quantity)]),
        district=district,
        coupon_code=coupon_code,
    )


# ---------------------------------------------------------------------------
# resolve_basket -- the three input shapes
# ---------------------------------------------------------------------------
def test_resolve_basket_prices_an_explicit_items_payload_and_reports_no_server_cart(
    store_settings, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="1000.00", name="Guest buy")

    lines, cart = checkout_services.resolve_basket(
        items=[{"variant_id": variant.pk, "quantity": 2}]
    )

    assert cart is None
    assert len(lines) == 1
    assert lines[0].product_name == "Guest buy"
    assert lines[0].quantity == 2
    assert_money(lines[0].line_total, "2000.00", "line_total")


def test_resolve_basket_prices_the_signed_in_customers_server_cart_when_no_items_are_sent(
    store_settings, customer, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="1000.00")
    cart = cart_services.get_cart(customer)
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=3)

    lines, resolved_cart = checkout_services.resolve_basket(user=customer)

    assert resolved_cart.pk == cart.pk
    assert len(lines) == 1
    assert_money(lines[0].line_total, "3000.00", "line_total")


def test_resolve_basket_uses_a_cart_object_it_is_handed_rather_than_looking_one_up(
    store_settings, customer, make_sellable_variant
):
    # Placement passes the cart it means to empty, so the basket priced and the
    # cart cleared afterwards are guaranteed to be the same row.
    variant = make_sellable_variant(price="1000.00")
    cart = cart_services.get_cart(customer)
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=1)

    lines, resolved_cart = checkout_services.resolve_basket(user=customer, cart=cart)

    assert resolved_cart is cart
    assert len(lines) == 1


def test_an_explicit_items_payload_wins_over_the_signed_in_customers_server_cart(
    store_settings, customer, make_sellable_variant, assert_money
):
    in_cart = make_sellable_variant(price="1000.00", name="Already in the cart")
    buy_now = make_sellable_variant(price="7000.00", name="Buy now")
    cart = cart_services.get_cart(customer)
    cart_services.add_item(cart=cart, variant_id=in_cart.pk, quantity=4)

    lines, resolved_cart = checkout_services.resolve_basket(
        user=customer, items=[{"variant_id": buy_now.pk, "quantity": 1}]
    )

    # Buying straight from a product page must not disturb the cart, so the
    # cart is not even consulted -- and not returned to be emptied.
    assert resolved_cart is None
    assert [built.product_name for built in lines] == ["Buy now"]
    assert_money(totals_services.subtotal_of(lines), "7000.00", "subtotal")


def test_resolve_basket_refuses_a_guest_who_sends_no_items(store_settings):
    with pytest.raises(DomainError) as excinfo:
        checkout_services.resolve_basket()

    assert excinfo.value.code == "ITEMS_REQUIRED"
    assert excinfo.value.field == "items"


def test_resolve_basket_refuses_a_signed_in_customer_whose_cart_is_empty(
    store_settings, customer
):
    cart_services.get_cart(customer)

    with pytest.raises(DomainError) as excinfo:
        checkout_services.resolve_basket(user=customer)

    assert excinfo.value.code == "CART_EMPTY"
    assert excinfo.value.field == "items"


def test_resolve_basket_leaves_an_unavailable_cart_line_out_of_the_priced_basket(
    store_settings, customer, make_sellable_variant, assert_money
):
    keep = make_sellable_variant(price="1000.00", name="Still sold")
    withdrawn = make_sellable_variant(price="9000.00", name="Withdrawn")
    cart = cart_services.get_cart(customer)
    cart_services.add_item(cart=cart, variant_id=keep.pk, quantity=1)
    cart_services.add_item(cart=cart, variant_id=withdrawn.pk, quantity=1)

    withdrawn.is_active = False
    withdrawn.save(update_fields=["is_active"])

    lines, _cart = checkout_services.resolve_basket(user=customer)

    assert [built.product_name for built in lines] == ["Still sold"]
    assert_money(totals_services.subtotal_of(lines), "1000.00", "subtotal")


def test_an_items_payload_naming_the_same_variant_twice_is_priced_as_one_line(
    store_settings, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="1000.00")

    lines, _cart = checkout_services.resolve_basket(
        items=[
            {"variant_id": variant.pk, "quantity": 2},
            {"variant_id": variant.pk, "quantity": 3},
        ]
    )

    assert len(lines) == 1
    assert lines[0].quantity == 5
    assert_money(lines[0].line_total, "5000.00", "line_total")


def test_resolve_basket_refuses_an_items_payload_naming_a_variant_that_is_not_sold(
    store_settings, make_sellable_variant
):
    variant = make_sellable_variant(price="1000.00")
    variant.is_active = False
    variant.save(update_fields=["is_active"])

    with pytest.raises(DomainError) as excinfo:
        checkout_services.resolve_basket(items=[{"variant_id": variant.pk, "quantity": 1}])

    assert excinfo.value.code == "VARIANT_NOT_FOUND"
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# quote()
# ---------------------------------------------------------------------------
def test_quote_returns_server_computed_totals_for_a_basket_a_district_and_a_coupon(
    store_settings, dhaka_zone, make_sellable_variant, make_coupon, assert_money
):
    store_settings.tax_rate = Decimal("15.00")
    store_settings.save()
    variant = make_sellable_variant(price="1000.00")
    make_coupon("SAVE10", discount_type=DiscountType.PERCENT, value="10.00")

    result = checkout_services.quote(
        items=[{"variant_id": variant.pk, "quantity": 2}],
        district="Dhaka",
        coupon_code="SAVE10",
    )
    totals, payment_options = result.totals, result.payment_options

    assert_money(totals.subtotal, "2000.00", "subtotal")
    assert_money(totals.discount_total, "200.00", "discount_total")
    assert_money(totals.shipping_total, "60.00", "shipping_total")
    assert_money(totals.tax_total, "270.00", "tax_total")
    assert_money(totals.grand_total, "2130.00", "grand_total")
    assert totals.zone == dhaka_zone
    assert [option["method"] for option in payment_options] == [
        PaymentMethod.COD.value,
        PaymentMethod.ONLINE.value,
    ]


def test_quote_without_a_district_reports_shipping_as_not_yet_known(
    store_settings, dhaka_zone, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="1000.00")

    result = checkout_services.quote(
        items=[{"variant_id": variant.pk, "quantity": 1}]
    )
    totals = result.totals

    assert totals.shipping_known is False
    assert totals.zone is None
    assert_money(totals.grand_total, "1000.00", "grand_total")


def test_quote_prices_the_signed_in_customers_cart_when_the_request_carries_no_items(
    store_settings, dhaka_zone, customer, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="1000.00")
    cart = cart_services.get_cart(customer)
    cart_services.add_item(cart=cart, variant_id=variant.pk, quantity=2)

    result = checkout_services.quote(user=customer, district="Dhaka")
    totals = result.totals

    assert_money(totals.subtotal, "2000.00", "subtotal")
    assert_money(totals.grand_total, "2060.00", "grand_total")


# ---------------------------------------------------------------------------
# Cash on Delivery availability
# ---------------------------------------------------------------------------
def test_cash_on_delivery_is_available_by_default_in_a_zone_that_allows_it(
    store_settings, dhaka_zone, make_sellable_variant
):
    variant = make_sellable_variant(price="1000.00")

    available, code, message = checkout_services.cod_availability(
        totals_for(variant, district="Dhaka")
    )

    assert available is True
    assert code is None
    assert message is None


def test_cash_on_delivery_is_refused_when_the_store_has_switched_it_off(
    store_settings, dhaka_zone, make_sellable_variant
):
    store_settings.cod_enabled = False
    store_settings.save()
    variant = make_sellable_variant(price="1000.00")

    available, code, _message = checkout_services.cod_availability(
        totals_for(variant, district="Dhaka")
    )

    assert available is False
    assert code == "COD_DISABLED"


def test_cash_on_delivery_is_refused_in_a_zone_that_does_not_allow_it(
    store_settings, make_zone, make_sellable_variant
):
    make_zone(name="Chattogram Hill Tracts", cod_allowed=False, districts=["Bandarban"])
    variant = make_sellable_variant(price="1000.00")

    available, code, message = checkout_services.cod_availability(
        totals_for(variant, district="Bandarban")
    )

    assert available is False
    assert code == "COD_NOT_ALLOWED_IN_ZONE"
    assert "Chattogram Hill Tracts" in message


def test_cash_on_delivery_is_refused_once_the_grand_total_passes_the_stores_ceiling(
    store_settings, make_sellable_variant
):
    store_settings.cod_max_order_value = Decimal("50000.00")
    store_settings.save()
    variant = make_sellable_variant(price="60000.00")

    available, code, _message = checkout_services.cod_availability(totals_for(variant))

    assert available is False
    assert code == "COD_LIMIT_EXCEEDED"


def test_an_order_landing_exactly_on_the_cash_on_delivery_ceiling_is_still_allowed(
    store_settings, make_sellable_variant, assert_money
):
    store_settings.cod_max_order_value = Decimal("50000.00")
    store_settings.save()
    variant = make_sellable_variant(price="50000.00")
    totals = totals_for(variant)

    assert_money(totals.grand_total, "50000.00", "grand_total")
    # The ceiling is a maximum, not an exclusive bound: an order *at* the cap
    # is payable in cash.
    assert checkout_services.cod_availability(totals)[0] is True


def test_a_null_cash_on_delivery_ceiling_places_no_limit_on_the_order_value(
    store_settings, make_sellable_variant
):
    assert store_settings.cod_max_order_value is None
    variant = make_sellable_variant(price="9000000.00")

    assert checkout_services.cod_availability(totals_for(variant))[0] is True


def test_the_shipping_added_to_a_basket_can_be_what_pushes_it_over_the_cod_ceiling(
    store_settings, make_zone, make_sellable_variant
):
    make_zone(flat_rate="60.00")
    store_settings.cod_max_order_value = Decimal("50000.00")
    store_settings.save()
    variant = make_sellable_variant(price="50000.00")

    # 50000 alone is payable in cash; 50060 delivered is not. The ceiling is
    # tested against the grand total, which is what the courier collects.
    assert checkout_services.cod_availability(totals_for(variant))[0] is True
    assert (
        checkout_services.cod_availability(totals_for(variant, district="Dhaka"))[1]
        == "COD_LIMIT_EXCEEDED"
    )


def test_the_store_switch_is_reported_ahead_of_the_zone_and_the_ceiling(
    store_settings, make_zone, make_sellable_variant
):
    store_settings.cod_enabled = False
    store_settings.cod_max_order_value = Decimal("100.00")
    store_settings.save()
    make_zone(cod_allowed=False)
    variant = make_sellable_variant(price="60000.00")

    assert (
        checkout_services.cod_availability(totals_for(variant, district="Dhaka"))[1]
        == "COD_DISABLED"
    )


def test_the_zone_policy_is_reported_ahead_of_the_order_value_ceiling(
    store_settings, make_zone, make_sellable_variant
):
    store_settings.cod_max_order_value = Decimal("100.00")
    store_settings.save()
    make_zone(cod_allowed=False)
    variant = make_sellable_variant(price="60000.00")

    assert (
        checkout_services.cod_availability(totals_for(variant, district="Dhaka"))[1]
        == "COD_NOT_ALLOWED_IN_ZONE"
    )


# ---------------------------------------------------------------------------
# assert_payment_method_allowed
# ---------------------------------------------------------------------------
def test_assert_payment_method_allowed_lets_a_payable_cash_order_through(
    store_settings, dhaka_zone, make_sellable_variant
):
    variant = make_sellable_variant(price="1000.00")

    assert (
        checkout_services.assert_payment_method_allowed(
            totals_for(variant, district="Dhaka"), PaymentMethod.COD
        )
        is None
    )


def test_assert_payment_method_allowed_refuses_cash_on_delivery_over_the_ceiling(
    store_settings, make_sellable_variant
):
    store_settings.cod_max_order_value = Decimal("50000.00")
    store_settings.save()
    variant = make_sellable_variant(price="60000.00")

    with pytest.raises(DomainError) as excinfo:
        checkout_services.assert_payment_method_allowed(
            totals_for(variant), PaymentMethod.COD
        )

    assert excinfo.value.code == "COD_LIMIT_EXCEEDED"
    assert excinfo.value.field == "payment_method"


def test_assert_payment_method_allowed_refuses_cash_on_delivery_in_a_zone_that_forbids_it(
    store_settings, make_zone, make_sellable_variant
):
    make_zone(cod_allowed=False)
    variant = make_sellable_variant(price="1000.00")

    with pytest.raises(DomainError) as excinfo:
        checkout_services.assert_payment_method_allowed(
            totals_for(variant, district="Dhaka"), PaymentMethod.COD
        )

    assert excinfo.value.code == "COD_NOT_ALLOWED_IN_ZONE"
    assert excinfo.value.field == "payment_method"


def test_assert_payment_method_allowed_lets_an_online_payment_through_a_basket_that_cannot_be_paid_in_cash(
    store_settings, make_zone, make_sellable_variant
):
    store_settings.cod_enabled = False
    store_settings.cod_max_order_value = Decimal("100.00")
    store_settings.save()
    make_zone(cod_allowed=False)
    variant = make_sellable_variant(price="60000.00")

    assert (
        checkout_services.assert_payment_method_allowed(
            totals_for(variant, district="Dhaka"), PaymentMethod.ONLINE
        )
        is None
    )


@pytest.mark.parametrize("method", ["bkash", "cheque", "", None, "COD"])
def test_assert_payment_method_allowed_refuses_a_method_the_store_does_not_offer(
    store_settings, make_sellable_variant, method
):
    variant = make_sellable_variant(price="1000.00")

    with pytest.raises(DomainError) as excinfo:
        checkout_services.assert_payment_method_allowed(totals_for(variant), method)

    assert excinfo.value.code == "INVALID_PAYMENT_METHOD"
    assert excinfo.value.field == "payment_method"


# ---------------------------------------------------------------------------
# payment_options and the zone's own COD guard
# ---------------------------------------------------------------------------
def test_payment_options_offer_both_methods_in_display_order_when_both_are_payable(
    store_settings, dhaka_zone, make_sellable_variant
):
    variant = make_sellable_variant(price="1000.00")

    options = checkout_services.payment_options(totals_for(variant, district="Dhaka"))

    assert [option["method"] for option in options] == ["cod", "online"]
    assert all(option["available"] for option in options)
    assert all(option["unavailable_code"] is None for option in options)


def test_payment_options_carry_the_reason_cash_on_delivery_is_unavailable(
    store_settings, make_sellable_variant
):
    store_settings.cod_max_order_value = Decimal("50000.00")
    store_settings.save()
    variant = make_sellable_variant(price="60000.00")

    cod, online = checkout_services.payment_options(totals_for(variant))

    assert cod["available"] is False
    assert cod["unavailable_code"] == "COD_LIMIT_EXCEEDED"
    assert cod["unavailable_reason"]
    # Online is the way out of a refused cash order, so it stays offered.
    assert online["available"] is True


def test_assert_zone_allows_cod_refuses_a_zone_that_forbids_cash_on_delivery(make_zone):
    zone = make_zone(name="Chattogram Hill Tracts", cod_allowed=False)

    with pytest.raises(DomainError) as excinfo:
        shipping_services.assert_zone_allows_cod(zone)

    assert excinfo.value.code == "COD_NOT_ALLOWED_IN_ZONE"
    assert excinfo.value.field == "payment_method"


def test_assert_zone_allows_cod_passes_an_allowing_zone_and_an_unresolved_one(make_zone):
    assert shipping_services.assert_zone_allows_cod(make_zone()) is None
    assert shipping_services.assert_zone_allows_cod(None) is None


# ---------------------------------------------------------------------------
# The client's arithmetic has no authority
# ---------------------------------------------------------------------------
def test_a_client_supplied_unit_price_in_the_items_payload_is_ignored(
    store_settings, dhaka_zone, make_sellable_variant, assert_money
):
    variant = make_sellable_variant(price="142000.00")

    result = checkout_services.quote(
        items=[
            {
                "variant_id": variant.pk,
                "quantity": 2,
                "unit_price": "1.00",
                "price": "1.00",
                "line_total": "2.00",
            }
        ],
        district="Dhaka",
    )
    totals = result.totals

    assert_money(totals.lines[0].unit_price, "142000.00", "unit_price")
    assert_money(totals.lines[0].line_total, "284000.00", "line_total")
    assert_money(totals.subtotal, "284000.00", "subtotal")
    assert_money(totals.grand_total, "284060.00", "grand_total")


def test_a_poisoned_payload_prices_identically_to_an_honest_one(
    store_settings, dhaka_zone, make_sellable_variant, make_coupon
):
    store_settings.tax_rate = Decimal("15.00")
    store_settings.save()
    variant = make_sellable_variant(price="142000.00")
    make_coupon("SAVE10", discount_type=DiscountType.PERCENT, value="10.00")

    result = checkout_services.quote(
        items=[{"variant_id": variant.pk, "quantity": 2}],
        district="Dhaka",
        coupon_code="SAVE10",
    )
    honest = result.totals
    result = checkout_services.quote(
        items=[
            {
                "variant_id": variant.pk,
                "quantity": 2,
                "unit_price": "0.01",
                "line_total": "0.02",
                "discount_total": "1000000.00",
                "shipping_total": "0.00",
                "tax_total": "0.00",
                "grand_total": "0.02",
            }
        ],
        district="Dhaka",
        coupon_code="SAVE10",
    )
    poisoned = result.totals

    for field in (
        "subtotal",
        "discount_total",
        "shipping_total",
        "tax_total",
        "tax_rate",
        "grand_total",
    ):
        assert getattr(poisoned, field) == getattr(honest, field), field


# ---------------------------------------------------------------------------
# POST /api/v1/checkout/quote/
# ---------------------------------------------------------------------------
def test_the_quote_endpoint_prices_a_guest_basket_and_returns_money_as_decimal_strings(
    api, quote_url, store_settings, dhaka_zone, make_sellable_variant
):
    variant = make_sellable_variant(price="142000.00")

    response = api.post(
        quote_url,
        {"items": [{"variant_id": variant.pk, "quantity": 2}], "district": "Dhaka"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subtotal"] == "284000.00"
    assert body["shipping_total"] == "60.00"
    assert body["grand_total"] == "284060.00"
    assert body["currency"] == "BDT"
    assert body["item_count"] == 2
    # Decimal strings, never JSON numbers -- a float here is a rounding bug
    # waiting for a big enough order.
    for field in ("subtotal", "discount_total", "shipping_total", "tax_total", "grand_total"):
        assert isinstance(body[field], str), field


def test_the_quote_endpoint_recomputes_every_figure_and_ignores_the_totals_the_client_sent(
    api, quote_url, store_settings, dhaka_zone, make_sellable_variant
):
    variant = make_sellable_variant(price="142000.00")

    response = api.post(
        quote_url,
        {
            "items": [
                {
                    "variant_id": variant.pk,
                    "quantity": 2,
                    "unit_price": "1.00",
                    "line_total": "2.00",
                }
            ],
            "district": "Dhaka",
            "subtotal": "2.00",
            "discount_total": "999999.00",
            "shipping_total": "0.00",
            "tax_total": "0.00",
            "grand_total": "2.00",
            "tax_rate": "0.00",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subtotal"] == "284000.00"
    assert body["discount_total"] == "0.00"
    assert body["shipping_total"] == "60.00"
    assert body["grand_total"] == "284060.00"
    assert body["lines"][0]["unit_price"] == "142000.00"
    assert body["lines"][0]["line_total"] == "284000.00"


def test_the_quote_endpoint_refuses_a_signed_out_caller_who_sends_no_items(
    api, quote_url, store_settings
):
    response = api.post(quote_url, {"district": "Dhaka"}, format="json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ITEMS_REQUIRED"


def test_the_quote_endpoint_reports_the_payment_options_it_computed(
    api, quote_url, store_settings, make_zone, make_sellable_variant
):
    make_zone(cod_allowed=False)
    variant = make_sellable_variant(price="1000.00")

    response = api.post(
        quote_url,
        {"items": [{"variant_id": variant.pk, "quantity": 1}], "district": "Dhaka"},
        format="json",
    )

    assert response.status_code == 200
    # On the wire the key is `payment_methods` and the identifier is `code`
    # (docs/api-contract-cart-checkout-orders.md); `payment_options` /
    # `method` is the service-side vocabulary.
    cod = response.json()["payment_methods"][0]
    assert cod["code"] == "cod"
    assert cod["available"] is False
    assert cod["unavailable_code"] == "COD_NOT_ALLOWED_IN_ZONE"


def test_an_invalid_coupon_is_reported_without_blanking_the_rest_of_the_quote(
    api, quote_url, store_settings, dhaka_zone, make_sellable_variant, make_coupon
):
    """
    FR-CPN-7 / the frozen contract: "An invalid coupon never fails the quote."

    A coupon that goes stale mid-checkout, or a plain typo, must not take the
    totals off the screen a shopper is reading. The basket stays priced, the
    coupon comes back null, and the reason travels in `coupon_error`.
    """
    now = timezone.now()
    variant = make_sellable_variant(price="1000.00")
    make_coupon(
        "LASTMONTH",
        valid_from=now - timedelta(days=30),
        valid_until=now - timedelta(days=1),
    )

    response = api.post(
        quote_url,
        {
            "items": [{"variant_id": variant.pk, "quantity": 1}],
            "district": "Dhaka",
            "coupon_code": "LASTMONTH",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["coupon"] is None
    assert body["coupon_error"]["code"] == "COUPON_EXPIRED"
    assert body["coupon_error"]["message"]
    # The whole point: the figures survived the bad coupon.
    assert body["subtotal"] == "1000.00"
    assert body["discount_total"] == "0.00"
    assert body["grand_total"] == "1060.00"
    assert body["can_place_order"] is True


def test_a_valid_coupon_reports_no_coupon_error(
    api, quote_url, store_settings, dhaka_zone, make_sellable_variant, make_coupon
):
    variant = make_sellable_variant(price="1000.00")
    make_coupon("SAVE10", discount_type=DiscountType.PERCENT, value="10.00")

    response = api.post(
        quote_url,
        {
            "items": [{"variant_id": variant.pk, "quantity": 1}],
            "district": "Dhaka",
            "coupon_code": "SAVE10",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["coupon_error"] is None
    assert body["coupon"]["code"] == "SAVE10"
    assert body["discount_total"] == "100.00"


def test_a_district_we_do_not_deliver_to_is_a_notice_not_a_failed_quote(
    api, quote_url, store_settings, dhaka_zone, make_sellable_variant
):
    """
    The frozen contract: a district in no zone returns `zone: null`, null
    totals and a NO_SHIPPING_ZONE notice -- the basket stays on screen so the
    shopper can pick a district we do reach.
    """
    variant = make_sellable_variant(price="1000.00")

    response = api.post(
        quote_url,
        {"items": [{"variant_id": variant.pk, "quantity": 1}], "district": "Atlantis"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["zone"] is None
    assert body["subtotal"] == "1000.00"
    assert [notice["code"] for notice in body["notices"]] == ["NO_SHIPPING_ZONE"]
    # Null, never "0.00": a zero grand total renders as a free order.
    assert body["shipping_total"] is None
    assert body["tax_total"] is None
    assert body["grand_total"] is None
    assert body["can_place_order"] is False


def test_a_quote_without_a_district_nulls_the_unknown_figures_and_blocks_placement(
    api, quote_url, store_settings, dhaka_zone, make_sellable_variant
):
    variant = make_sellable_variant(price="1000.00")

    response = api.post(
        quote_url,
        {"items": [{"variant_id": variant.pk, "quantity": 1}]},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subtotal"] == "1000.00"
    assert body["zone"] is None
    assert body["shipping_total"] is None
    assert body["grand_total"] is None
    assert body["can_place_order"] is False


def test_a_quote_line_carries_the_flat_shape_the_cart_and_checkout_render(
    api, quote_url, store_settings, dhaka_zone, make_sellable_variant
):
    """
    The line is flat and self-sufficient: name, slug, label, sku, price and
    availability all sit on the line itself, because the cart page and the
    checkout review list both render it without a second lookup.
    """
    variant = make_sellable_variant(price="1000.00", stock=7)

    response = api.post(
        quote_url,
        {"items": [{"variant_id": variant.pk, "quantity": 2}], "district": "Dhaka"},
        format="json",
    )

    assert response.status_code == 200
    line = response.json()["lines"][0]
    assert line["variant_id"] == variant.pk
    assert line["product_id"] == variant.product_id
    assert line["product_name"] == variant.product.name
    assert line["product_slug"] == variant.product.slug
    assert line["variant_label"] == variant.label
    assert line["sku"] == variant.sku
    assert line["quantity"] == 2
    assert line["unit_price"] == "1000.00"
    assert line["line_total"] == "2000.00"
    assert line["available_stock"] == 7
    assert line["is_available"] is True
    assert line["issue"] is None
    assert "image" in line


def test_a_line_short_of_stock_is_reported_as_unbuyable_and_blocks_placement(
    api, quote_url, store_settings, dhaka_zone, make_sellable_variant
):
    """
    Reported, never reserved: the quote says the line cannot be bought at that
    quantity, and `can_place_order` goes false, but no stock moves (FR-CRT-3).
    """
    variant = make_sellable_variant(price="1000.00", stock=1)

    response = api.post(
        quote_url,
        {"items": [{"variant_id": variant.pk, "quantity": 5}], "district": "Dhaka"},
        format="json",
    )

    assert response.status_code == 200
    line = response.json()["lines"][0]
    assert line["is_available"] is False
    assert line["issue"] == "insufficient_stock"
    assert line["available_stock"] == 1
    assert response.json()["can_place_order"] is False

    variant.refresh_from_db()
    assert variant.stock == 1
