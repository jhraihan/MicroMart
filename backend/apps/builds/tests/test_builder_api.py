"""
The PC-builder endpoints.

These cover the parts `test_compatibility.py` cannot: the database side
(which parts a slot offers, how a selection resolves to lines), the
authorisation rules on saved builds, and the money contract.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.builds.models import PCBuild
from apps.catalog.models import (
    Brand,
    Category,
    ComponentProfile,
    ComponentSlot,
    Product,
    ProductVariant,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def taxonomy():
    category = Category.objects.create(name="Component", slug="component")
    brand = Brand.objects.create(name="TestBrand", slug="testbrand")
    return category, brand


def make_part(taxonomy, *, slot, name, price="1000.00", stock=5, active=True, **profile):
    category, brand = taxonomy
    product = Product.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        category=category,
        brand=brand,
        is_active=active,
    )
    variant = ProductVariant.objects.create(
        product=product,
        sku=f"SKU-{product.slug}",
        price=price,
        stock=stock,
        is_active=active,
    )
    ComponentProfile.objects.create(product=product, slot=slot, **profile)
    return product, variant


@pytest.fixture
def customer():
    user = User.objects.create_user(
        email="builder@example.com", password="Str0ngPass!2026", role=Role.CUSTOMER
    )
    return user


# ---------------------------------------------------------------------------
# Component listing
# ---------------------------------------------------------------------------
def test_a_slot_lists_only_parts_filed_under_it(api, taxonomy):
    make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU", socket="AM4")
    make_part(taxonomy, slot=ComponentSlot.GPU, name="A GPU", power_watts=200)

    response = api.get(reverse("builds:components"), {"slot": "cpu"})

    assert response.status_code == 200
    assert [row["name"] for row in response.json()["results"]] == ["A CPU"]


def test_an_unknown_slot_is_refused_rather_than_returning_everything(api):
    response = api.get(reverse("builds:components"), {"slot": "flux-capacitor"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SLOT"


def test_an_inactive_product_is_never_offered(api, taxonomy):
    make_part(taxonomy, slot=ComponentSlot.CPU, name="Retired CPU", active=False)
    response = api.get(reverse("builds:components"), {"slot": "cpu"})
    assert response.json()["count"] == 0


def test_choosing_a_cpu_narrows_the_board_list_to_its_socket(api, taxonomy):
    _, cpu_variant = make_part(taxonomy, slot=ComponentSlot.CPU, name="AM4 CPU", socket="AM4")
    make_part(
        taxonomy, slot=ComponentSlot.MOTHERBOARD, name="AM4 Board",
        socket="AM4", form_factor="ATX", ram_type="DDR4",
    )
    make_part(
        taxonomy, slot=ComponentSlot.MOTHERBOARD, name="AM5 Board",
        socket="AM5", form_factor="ATX", ram_type="DDR5",
    )

    response = api.get(
        reverse("builds:components"),
        {"slot": "motherboard", "selected": f"cpu:{cpu_variant.id}"},
    )

    assert [row["name"] for row in response.json()["results"]] == ["AM4 Board"]


def test_the_narrowing_can_be_turned_off(api, taxonomy):
    """
    A filter that silently hides a part the shopper knows exists is impossible
    for them to debug, so "show everything" is always available.
    """
    _, cpu_variant = make_part(taxonomy, slot=ComponentSlot.CPU, name="AM4 CPU", socket="AM4")
    make_part(taxonomy, slot=ComponentSlot.MOTHERBOARD, name="AM5 Board", socket="AM5")

    response = api.get(
        reverse("builds:components"),
        {
            "slot": "motherboard",
            "selected": f"cpu:{cpu_variant.id}",
            "compatible_only": "false",
        },
    )

    assert response.json()["count"] == 1


def test_prices_leave_as_decimal_strings(api, taxonomy):
    make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU", price="16500.00")
    row = api.get(reverse("builds:components"), {"slot": "cpu"}).json()["results"][0]
    assert row["price"] == "16500.00"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_validate_returns_lines_a_subtotal_and_a_verdict(api, taxonomy):
    _, cpu = make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU", price="16500.00", socket="AM4")
    _, board = make_part(
        taxonomy, slot=ComponentSlot.MOTHERBOARD, name="A Board",
        price="13500.00", socket="AM4",
    )

    response = api.post(
        reverse("builds:validate"),
        {
            "items": [
                {"slot": "cpu", "variant_id": cpu.id, "quantity": 1},
                {"slot": "motherboard", "variant_id": board.id, "quantity": 1},
            ]
        },
        format="json",
    )

    payload = response.json()
    assert response.status_code == 200
    assert len(payload["lines"]) == 2
    # Money as a decimal string, never a float.
    assert payload["subtotal"] == "30000.00"
    assert payload["is_compatible"] is True


def test_validate_writes_nothing(api, taxonomy):
    """It is called on every change; persisting would accumulate rows."""
    _, cpu = make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU")
    api.post(
        reverse("builds:validate"),
        {"items": [{"slot": "cpu", "variant_id": cpu.id, "quantity": 1}]},
        format="json",
    )
    assert PCBuild.objects.count() == 0


def test_an_out_of_stock_part_is_flagged_but_still_checked(api, taxonomy):
    """
    Being unbuyable today does not make a part incompatible. The line reports
    the stock problem and the rules still run over it.
    """
    _, cpu = make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU", stock=0, socket="AM4")
    payload = api.post(
        reverse("builds:validate"),
        {"items": [{"slot": "cpu", "variant_id": cpu.id, "quantity": 1}]},
        format="json",
    ).json()

    assert payload["lines"][0]["issue"] == "out_of_stock"
    assert payload["is_compatible"] is True


def test_a_deleted_variant_comes_back_as_unavailable_rather_than_vanishing(api, taxonomy):
    payload = api.post(
        reverse("builds:validate"),
        {"items": [{"slot": "cpu", "variant_id": 999999, "quantity": 1}]},
        format="json",
    ).json()

    assert payload["lines"][0]["issue"] == "unavailable"
    assert payload["lines"][0]["product"] is None


def test_the_same_slot_twice_is_refused(api, taxonomy):
    _, a = make_part(taxonomy, slot=ComponentSlot.CPU, name="CPU A")
    _, b = make_part(taxonomy, slot=ComponentSlot.CPU, name="CPU B")

    response = api.post(
        reverse("builds:validate"),
        {
            "items": [
                {"slot": "cpu", "variant_id": a.id, "quantity": 1},
                {"slot": "cpu", "variant_id": b.id, "quantity": 1},
            ]
        },
        format="json",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DUPLICATE_SLOT"


# ---------------------------------------------------------------------------
# Saving and sharing
# ---------------------------------------------------------------------------
def test_saving_requires_an_account(api, taxonomy):
    _, cpu = make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU")
    response = api.post(
        reverse("builds:build-list"),
        {"name": "Mine", "items": [{"slot": "cpu", "variant_id": cpu.id, "quantity": 1}]},
        format="json",
    )
    assert response.status_code == 401


def test_a_saved_build_can_be_read_by_anyone_holding_its_link(api, taxonomy, customer):
    """
    The token *is* the read capability -- a link you send someone has to work
    when they open it, and they are by definition not signed in as you.
    """
    _, cpu = make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU")
    api.force_authenticate(customer)
    created = api.post(
        reverse("builds:build-list"),
        {"name": "Mine", "items": [{"slot": "cpu", "variant_id": cpu.id, "quantity": 1}]},
        format="json",
    ).json()

    anonymous = APIClient()
    response = anonymous.get(
        reverse("builds:build-detail", args=[created["share_token"]])
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Mine"
    assert response.json()["is_owner"] is False


def test_another_customer_cannot_edit_a_build_and_gets_404_not_403(api, taxonomy, customer):
    """
    404, not 403, exactly as the rest of this API does it: a 403 would confirm
    the build exists to anyone probing tokens.
    """
    _, cpu = make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU")
    api.force_authenticate(customer)
    created = api.post(
        reverse("builds:build-list"),
        {"name": "Mine", "items": [{"slot": "cpu", "variant_id": cpu.id, "quantity": 1}]},
        format="json",
    ).json()

    intruder = User.objects.create_user(
        email="other@example.com", password="Str0ngPass!2026", role=Role.CUSTOMER
    )
    other = APIClient()
    other.force_authenticate(intruder)

    response = other.delete(
        reverse("builds:build-detail", args=[created["share_token"]])
    )
    assert response.status_code == 404
    assert PCBuild.objects.count() == 1


def test_an_empty_build_cannot_be_saved(api, customer):
    api.force_authenticate(customer)
    response = api.post(
        reverse("builds:build-list"), {"name": "Empty", "items": []}, format="json"
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_BUILD"


def test_a_saved_build_is_repriced_on_every_read(api, taxonomy, customer):
    """
    A build stores variant ids, never prices. A link shared in March must
    quote today's price, or it lies.
    """
    _, cpu = make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU", price="16500.00")
    api.force_authenticate(customer)
    created = api.post(
        reverse("builds:build-list"),
        {"name": "Mine", "items": [{"slot": "cpu", "variant_id": cpu.id, "quantity": 1}]},
        format="json",
    ).json()
    assert created["subtotal"] == "16500.00"

    ProductVariant.objects.filter(pk=cpu.pk).update(price="19000.00")

    reread = api.get(reverse("builds:build-detail", args=[created["share_token"]])).json()
    assert reread["subtotal"] == "19000.00"


def test_saving_the_same_build_twice_replaces_its_items(api, taxonomy, customer):
    _, cpu = make_part(taxonomy, slot=ComponentSlot.CPU, name="A CPU")
    _, gpu = make_part(taxonomy, slot=ComponentSlot.GPU, name="A GPU")

    api.force_authenticate(customer)
    created = api.post(
        reverse("builds:build-list"),
        {"name": "Mine", "items": [{"slot": "cpu", "variant_id": cpu.id, "quantity": 1}]},
        format="json",
    ).json()

    api.put(
        reverse("builds:build-detail", args=[created["share_token"]]),
        {
            "name": "Mine",
            "items": [
                {"slot": "cpu", "variant_id": cpu.id, "quantity": 1},
                {"slot": "gpu", "variant_id": gpu.id, "quantity": 1},
            ],
        },
        format="json",
    )

    build = PCBuild.objects.get(share_token=created["share_token"])
    assert build.items.count() == 2


def test_an_unknown_share_token_is_404(api):
    response = api.get(reverse("builds:build-detail", args=["nope"]))
    assert response.status_code == 404
