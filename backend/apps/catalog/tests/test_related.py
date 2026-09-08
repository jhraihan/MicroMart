"""
FR-CAT-6: up to eight related products from the same category, excluding
out-of-stock items and the product itself.
"""
import pytest

from .factories import make_brand, make_category, make_product, result_slugs

pytestmark = pytest.mark.django_db


@pytest.fixture
def related_fixture():
    gaming = make_category("Gaming Laptops", "gaming-laptops")
    office = make_category("Office Laptops", "office-laptops")
    brand = make_brand("Asus", "asus")

    subject = make_product(
        gaming, brand=brand, name="Asus TUF F15", slug="asus-tuf-f15", price="142000.00"
    )
    siblings = [
        make_product(
            gaming,
            brand=brand,
            name="Sibling {0}".format(index),
            slug="sibling-{0}".format(index),
            price="{0}000.00".format(100 + index),
            stock=3,
        )
        for index in range(10)
    ]
    sold_out = make_product(
        gaming, brand=brand, name="Sold Out", slug="sold-out", price="99000.00", stock=0
    )
    hidden = make_product(
        gaming,
        brand=brand,
        name="Hidden Sibling",
        slug="hidden-sibling",
        price="97000.00",
        stock=5,
        is_active=False,
    )
    other = make_product(
        office,
        brand=brand,
        name="Office Laptop",
        slug="office-laptop",
        price="70000.00",
    )
    return {
        "subject": subject,
        "siblings": siblings,
        "sold_out": sold_out,
        "hidden": hidden,
        "other": other,
    }


def test_related_returns_at_most_eight_products(api, related_url, related_fixture):
    rows = api.get(related_url(related_fixture["subject"].slug)).json()

    assert isinstance(rows, list)  # bare array, no pagination envelope
    assert len(rows) == 8


def test_related_excludes_the_product_itself(api, related_url, related_fixture):
    subject = related_fixture["subject"]

    rows = api.get(related_url(subject.slug)).json()

    assert subject.slug not in result_slugs(rows)


def test_related_excludes_out_of_stock_and_inactive_products(
    api, related_url, related_fixture
):
    # Only five siblings stay in stock, so the sold-out and inactive rows have
    # room to appear if they are not being filtered out.
    for sibling in related_fixture["siblings"][5:]:
        sibling.variants.update(stock=0)

    slugs = result_slugs(api.get(related_url(related_fixture["subject"].slug)).json())

    assert len(slugs) == 5
    assert related_fixture["sold_out"].slug not in slugs
    assert related_fixture["hidden"].slug not in slugs


def test_related_stays_inside_the_same_category(api, related_url, related_fixture):
    slugs = result_slugs(api.get(related_url(related_fixture["subject"].slug)).json())

    assert related_fixture["other"].slug not in slugs
    assert all(slug.startswith("sibling-") for slug in slugs)


def test_related_for_an_inactive_or_unknown_product_is_404(
    api, related_url, related_fixture
):
    subject = related_fixture["subject"]
    subject.is_active = False
    subject.save(update_fields=["is_active"])

    assert api.get(related_url(subject.slug)).status_code == 404
    assert api.get(related_url("no-such-product")).status_code == 404


def test_related_rows_carry_the_full_card_shape(api, related_url, related_fixture):
    rows = api.get(related_url(related_fixture["subject"].slug)).json()

    assert set(rows[0]) == {
        "id",
        "name",
        "slug",
        "brand",
        "category",
        "primary_image",
        "price_min",
        "price_max",
        "compare_at_price",
        "discount_percent",
        "in_stock",
        "total_stock",
        "rating_avg",
        "rating_count",
        "variant_count",
    }
