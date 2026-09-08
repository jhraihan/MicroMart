"""
Store settings (PRD 7.3 GET/PATCH /admin/settings/, 14 Q2/Q3/Q4).

Two properties are load-bearing.

**There is one store.** `StoreSettings.save()` pins pk=1 and `delete()`
raises, so "create or return" and "update" are the same row by construction.
The tests here assert the row count after every path, because a second row
would mean checkout and the admin screen could read different tax rates.

**Changing a setting never reaches a placed order.** `tax_rate` and
`cod_max_order_value` feed checkout, and checkout snapshots what it used onto
the order. Raising VAT tomorrow must not re-price yesterday's sale -- that is
FR-ORD-2 and FR-SHP-7, and `test_raising_the_tax_rate_does_not_reprice_an_order_already_placed`
is the line that holds it.
"""
from decimal import Decimal

import pytest
from rest_framework import status

from apps.dashboard.models import StoreSettings
from apps.dashboard.services import store as store_services
from apps.orders.services import placement as placement_services
from apps.shipping.models import ShippingZone

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# The singleton
# ---------------------------------------------------------------------------
def test_reading_the_settings_creates_the_one_row_if_it_has_never_existed(
    admin_client, settings_url
):
    StoreSettings.objects.all().delete()

    response = admin_client.get(settings_url)

    assert response.status_code == status.HTTP_200_OK
    assert StoreSettings.objects.count() == 1
    assert response.data["store_name"] == "MicroMart"


def test_reading_the_settings_twice_does_not_produce_a_second_row(
    admin_client, settings_url
):
    admin_client.get(settings_url)
    admin_client.get(settings_url)

    assert StoreSettings.objects.count() == 1


def test_patching_updates_the_one_row_rather_than_inserting_another(
    admin_client, settings_url, store_settings
):
    response = admin_client.patch(
        settings_url, {"store_name": "MicroMart BD"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert StoreSettings.objects.count() == 1
    assert StoreSettings.load().store_name == "MicroMart BD"


def test_repeated_patches_keep_editing_the_same_row(
    admin_client, settings_url, store_settings
):
    for name in ("One", "Two", "Three"):
        admin_client.patch(settings_url, {"store_name": name}, format="json")

    assert StoreSettings.objects.count() == 1
    assert StoreSettings.objects.get().store_name == "Three"


def test_a_patch_is_partial_and_leaves_untouched_settings_alone(
    admin_client, settings_url, store_settings
):
    store_settings.tax_rate = Decimal("7.50")
    store_settings.support_email = "help@micromart.example"
    store_settings.save()

    admin_client.patch(settings_url, {"store_name": "MicroMart BD"}, format="json")

    settings = StoreSettings.load()
    assert settings.tax_rate == Decimal("7.50")
    assert settings.support_email == "help@micromart.example"


def test_the_settings_row_cannot_be_deleted(store_settings):
    """Deleting the store's configuration would silently reset VAT to zero."""
    with pytest.raises(RuntimeError):
        store_settings.delete()


# ---------------------------------------------------------------------------
# The snapshot rule
# ---------------------------------------------------------------------------
@pytest.fixture
def dhaka_zone(db):
    return ShippingZone.objects.create(
        name="Inside Dhaka",
        flat_rate=Decimal("60.00"),
        per_kg_rate=Decimal("0.00"),
        base_weight_grams=1000,
        cod_allowed=True,
        districts=["Dhaka"],
        is_active=True,
    )


@pytest.fixture
def place_cod_order(make_variant, dhaka_zone):
    """A real order through the real placement service, so the tax is snapshotted."""
    counter = {"n": 0}

    def _place(variant=None):
        counter["n"] += 1
        variant = variant or make_variant(price="1000.00", stock=10)
        order, _created = placement_services.place_order(
            idempotency_key="settings-test-{0}".format(counter["n"]),
            payment_method="cod",
            shipping_address={
                "recipient_name": "Buyer Rahman",
                "phone": "01712345678",
                "division": "Dhaka",
                "district": "Dhaka",
                "street": "1 Test Road",
            },
            email="buyer@example.com",
            items=[{"variant_id": variant.pk, "quantity": 1}],
        )
        return order

    return _place


def test_raising_the_tax_rate_does_not_reprice_an_order_already_placed(
    admin_client, settings_url, store_settings, place_cod_order
):
    """
    The whole reason `Order.tax_rate_applied` is a column and not a lookup.
    An accountant changing the VAT rate must not rewrite the receipts already
    issued -- and if this ever fails, every historical total silently moved.
    """
    store_settings.tax_rate = Decimal("5.00")
    store_settings.save()
    order = place_cod_order()
    original = (order.tax_rate_applied, order.tax_total, order.grand_total)

    response = admin_client.patch(settings_url, {"tax_rate": "15.00"}, format="json")

    order.refresh_from_db()
    assert response.status_code == status.HTTP_200_OK
    assert order.tax_rate_applied == Decimal("5.00")
    assert (order.tax_rate_applied, order.tax_total, order.grand_total) == original


def test_the_new_tax_rate_does_apply_to_the_next_order(
    admin_client, settings_url, store_settings, place_cod_order
):
    """
    The other half of the previous test, and the reason it means something: if
    the setting had no effect at all, "the old order did not change" would
    pass trivially.
    """
    store_settings.tax_rate = Decimal("5.00")
    store_settings.save()
    before = place_cod_order()

    admin_client.patch(settings_url, {"tax_rate": "15.00"}, format="json")
    after = place_cod_order()

    assert before.tax_rate_applied == Decimal("5.00")
    assert after.tax_rate_applied == Decimal("15.00")


def test_lowering_the_cod_ceiling_does_not_invalidate_an_order_already_placed(
    admin_client, settings_url, store_settings, place_cod_order
):
    store_settings.cod_max_order_value = None
    store_settings.save()
    order = place_cod_order()

    admin_client.patch(settings_url, {"cod_max_order_value": "10.00"}, format="json")

    order.refresh_from_db()
    assert order.payment_method == "cod"
    assert order.grand_total > Decimal("10.00")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rate", ["-1.00", "101.00"])
def test_an_impossible_vat_rate_is_refused(admin_client, settings_url, store_settings, rate):
    """
    Refused in the service, not the serializer, so a management command or a
    shell session setting the rate is held to the same range.
    """
    response = admin_client.patch(settings_url, {"tax_rate": rate}, format="json")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.data["error"]["code"] == "INVALID_TAX_RATE"
    assert StoreSettings.load().tax_rate == Decimal("0.00")


def test_a_negative_cod_ceiling_is_refused(admin_client, settings_url, store_settings):
    response = admin_client.patch(
        settings_url, {"cod_max_order_value": "-5.00"}, format="json"
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.data["error"]["code"] == "INVALID_COD_CEILING"


def test_clearing_the_cod_ceiling_disables_the_cap(
    admin_client, settings_url, store_settings
):
    store_settings.cod_max_order_value = Decimal("20000.00")
    store_settings.save()

    response = admin_client.patch(
        settings_url, {"cod_max_order_value": None}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert StoreSettings.load().cod_max_order_value is None


def test_a_digest_recipient_that_is_not_an_email_address_is_refused(
    admin_client, settings_url, store_settings
):
    """
    The digest sends inline with fail_silently on (FR-INV-7), so a malformed
    address would fail quietly every morning and nobody would learn of it.
    """
    response = admin_client.patch(
        settings_url,
        {"low_stock_digest_recipients": ["ops@micromart.example", "not-an-address"]},
        format="json",
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.data["error"]["code"] == "INVALID_RECIPIENTS"
    assert StoreSettings.load().low_stock_digest_recipients == []


def test_valid_digest_recipients_are_stored(admin_client, settings_url, store_settings):
    response = admin_client.patch(
        settings_url,
        {"low_stock_digest_recipients": ["ops@micromart.example", " owner@micromart.example "]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert StoreSettings.load().low_stock_digest_recipients == [
        "ops@micromart.example",
        "owner@micromart.example",
    ]


def test_an_unknown_setting_is_refused_rather_than_silently_dropped(store_settings):
    """
    Ignoring a misspelled key reports success for a change that did not happen,
    and the admin walks away believing VAT is now 15%.
    """
    from config.exceptions import DomainError

    with pytest.raises(DomainError) as raised:
        store_services.update_store_settings(vat_rate=Decimal("15.00"))

    assert raised.value.code == "UNKNOWN_SETTING"


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------
def test_money_and_rates_cross_the_wire_as_decimal_strings(
    admin_client, settings_url, store_settings
):
    store_settings.tax_rate = Decimal("15.00")
    store_settings.cod_max_order_value = Decimal("20000.00")
    store_settings.save()

    response = admin_client.get(settings_url)

    assert response.data["tax_rate"] == "15.00"
    assert response.data["cod_max_order_value"] == "20000.00"


def test_the_settings_payload_does_not_advertise_a_primary_key(
    admin_client, settings_url, store_settings
):
    """Exposing an id invites a client to believe there could be a second store."""
    response = admin_client.get(settings_url)

    assert "id" not in response.data
