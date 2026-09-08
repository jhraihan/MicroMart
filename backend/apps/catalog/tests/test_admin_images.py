"""
Product images: upload, ordering, and the primary flag
(PRD 4.3 US-A2, 7.3 POST /admin/products/{id}/images/).

US-A2 asks for "images (multiple, reorderable)". Three things about that are
easy to get subtly wrong, and each has a test here:

* **The file must actually be an image.** A .txt renamed to .jpg has to be
  refused at the door, not discovered later by a broken product card. The
  serializer's ImageField opens it with Pillow, so the refusal is real rather
  than a filename check.
* **A reorder must not lose the primary flag.** Promoting whatever landed
  first would make "primary" mean "top-left in the last drag", which is not
  what it means on a product card.
* **A product with images always has exactly one primary.** Uploading,
  reordering and deleting all pass back through the same settling function, so
  the invariant cannot depend on which door was used.

Every test here redirects MEDIA_ROOT into a temp directory: uploads must never
land in the repo's media/.
"""
import pytest

from apps.catalog.models import ProductImage
from apps.catalog.tests import factories

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]


def upload(admin_api, url, product_id, png, **extra):
    payload = {"image": png}
    payload.update(extra)
    return admin_api.post(url(product_id), payload, format="multipart")


def gallery(admin_api, url, product_id):
    return admin_api.get(url(product_id)).json()


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def test_uploading_an_image_attaches_it_to_the_product(
    admin_api, admin_product_images_url, product, png_upload
):
    response = upload(
        admin_api,
        admin_product_images_url,
        product.pk,
        png_upload(),
        alt_text="Front view",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["image"]["alt_text"] == "Front view"
    assert body["image"]["url"].startswith("/media/products/")
    assert product.images.count() == 1


def test_a_product_takes_several_images_in_upload_order(
    admin_api, admin_product_images_url, product, png_upload
):
    for index in range(3):
        upload(
            admin_api,
            admin_product_images_url,
            product.pk,
            png_upload(name="shot{0}.png".format(index)),
        )

    rows = gallery(admin_api, admin_product_images_url, product.pk)

    assert [row["sort_order"] for row in rows] == [0, 1, 2]


def test_a_file_that_is_not_an_image_is_refused_against_the_image_field(
    admin_api, admin_product_images_url, product
):
    from django.core.files.uploadedfile import SimpleUploadedFile

    fake = SimpleUploadedFile("sneaky.jpg", b"this is not a JPEG", content_type="image/jpeg")

    response = admin_api.post(
        admin_product_images_url(product.pk), {"image": fake}, format="multipart"
    )

    assert response.status_code == 400
    assert response.json()["error"]["field"] == "image"
    assert product.images.count() == 0


def test_an_oversized_image_is_refused_against_the_image_field(
    admin_api, admin_product_images_url, product, png_upload, monkeypatch
):
    """
    The cap is catalogue policy, so it lives in the service. Patched rather
    than met with a real 5 MB upload, because generating five megabytes to
    prove a comparison is a slow way to test an integer.
    """
    from apps.catalog.services import administration

    monkeypatch.setattr(administration, "MAX_IMAGE_BYTES", 10)

    response = upload(admin_api, admin_product_images_url, product.pk, png_upload())

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "IMAGE_TOO_LARGE"
    assert error["field"] == "image"


def test_an_image_can_be_pinned_to_one_variant(
    admin_api, admin_product_images_url, product, variant, png_upload
):
    response = upload(
        admin_api,
        admin_product_images_url,
        product.pk,
        png_upload(),
        variant_id=variant.pk,
    )

    assert response.json()["image"]["variant_id"] == variant.pk


def test_an_image_cannot_be_pinned_to_another_products_variant(
    admin_api, admin_product_images_url, product, category, png_upload
):
    stranger = factories.make_product(category, slug="stranger", sku="STRANGER-1")

    response = upload(
        admin_api,
        admin_product_images_url,
        product.pk,
        png_upload(),
        variant_id=stranger.variants.get().pk,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VARIANT_NOT_FOUND"


def test_uploading_to_an_unknown_product_is_a_404(
    admin_api, admin_product_images_url, png_upload
):
    assert upload(
        admin_api, admin_product_images_url, 999_999, png_upload()
    ).status_code == 404


# ---------------------------------------------------------------------------
# The primary flag
# ---------------------------------------------------------------------------
def test_the_first_image_becomes_the_primary_without_being_asked(
    admin_api, admin_product_images_url, product, png_upload
):
    """A product with images and no primary would render a card with no photo."""
    upload(admin_api, admin_product_images_url, product.pk, png_upload())

    assert gallery(admin_api, admin_product_images_url, product.pk)[0]["is_primary"] is True


def test_a_later_upload_can_claim_the_primary_flag_from_the_first(
    admin_api, admin_product_images_url, product, png_upload
):
    upload(admin_api, admin_product_images_url, product.pk, png_upload(name="a.png"))
    upload(
        admin_api,
        admin_product_images_url,
        product.pk,
        png_upload(name="b.png"),
        is_primary=True,
    )

    rows = gallery(admin_api, admin_product_images_url, product.pk)

    assert [row["is_primary"] for row in rows] == [False, True]


def test_exactly_one_image_is_primary_however_many_are_uploaded(
    admin_api, admin_product_images_url, product, png_upload
):
    for index in range(4):
        upload(
            admin_api,
            admin_product_images_url,
            product.pk,
            png_upload(name="shot{0}.png".format(index)),
            is_primary=True,
        )

    rows = gallery(admin_api, admin_product_images_url, product.pk)

    assert sum(1 for row in rows if row["is_primary"]) == 1


# ---------------------------------------------------------------------------
# Reordering
# ---------------------------------------------------------------------------
def test_reordering_rewrites_sort_order_in_the_sequence_given(
    admin_api, admin_product_images_url, product, png_upload
):
    for index in range(3):
        upload(
            admin_api,
            admin_product_images_url,
            product.pk,
            png_upload(name="shot{0}.png".format(index)),
        )
    ids = [row["id"] for row in gallery(admin_api, admin_product_images_url, product.pk)]

    response = admin_api.patch(
        admin_product_images_url(product.pk),
        {"order": [ids[2], ids[0], ids[1]]},
        format="json",
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["images"]] == [ids[2], ids[0], ids[1]]
    assert [row["sort_order"] for row in response.json()["images"]] == [0, 1, 2]


def test_reordering_does_not_move_the_primary_flag(
    admin_api, admin_product_images_url, product, png_upload
):
    """
    The claim this whole endpoint most easily breaks. Sorting and designating
    are two different decisions, and a drag that silently re-designated would
    change the product card behind the admin's back.
    """
    for index in range(3):
        upload(
            admin_api,
            admin_product_images_url,
            product.pk,
            png_upload(name="shot{0}.png".format(index)),
        )
    ids = [row["id"] for row in gallery(admin_api, admin_product_images_url, product.pk)]
    admin_api.patch(
        admin_product_images_url(product.pk),
        {"order": ids, "primary_id": ids[1]},
        format="json",
    )

    body = admin_api.patch(
        admin_product_images_url(product.pk),
        {"order": [ids[2], ids[0], ids[1]]},
        format="json",
    ).json()

    primary = [row["id"] for row in body["images"] if row["is_primary"]]
    assert primary == [ids[1]], "the middle image is still the primary one"


def test_a_reorder_can_move_the_primary_flag_when_it_is_asked_to(
    admin_api, admin_product_images_url, product, png_upload
):
    for index in range(2):
        upload(
            admin_api,
            admin_product_images_url,
            product.pk,
            png_upload(name="shot{0}.png".format(index)),
        )
    ids = [row["id"] for row in gallery(admin_api, admin_product_images_url, product.pk)]

    body = admin_api.patch(
        admin_product_images_url(product.pk),
        {"order": [ids[1], ids[0]], "primary_id": ids[1]},
        format="json",
    ).json()

    assert [row["is_primary"] for row in body["images"]] == [True, False]


def test_a_partial_order_is_refused_rather_than_half_applied(
    admin_api, admin_product_images_url, product, png_upload
):
    for index in range(3):
        upload(
            admin_api,
            admin_product_images_url,
            product.pk,
            png_upload(name="shot{0}.png".format(index)),
        )
    ids = [row["id"] for row in gallery(admin_api, admin_product_images_url, product.pk)]

    response = admin_api.patch(
        admin_product_images_url(product.pk), {"order": ids[:2]}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMAGE_ORDER_INCOMPLETE"
    assert [row["id"] for row in gallery(admin_api, admin_product_images_url, product.pk)] == ids


def test_an_image_from_another_product_cannot_be_ordered_into_this_one(
    admin_api, admin_product_images_url, product, category, png_upload
):
    upload(admin_api, admin_product_images_url, product.pk, png_upload())
    stranger = factories.make_product(category, slug="stranger", sku="STRANGER-2")
    intruder = factories.make_image(stranger)

    response = admin_api.patch(
        admin_product_images_url(product.pk), {"order": [intruder.pk]}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMAGE_NOT_FOUND"


def test_the_same_image_listed_twice_is_refused(
    admin_api, admin_product_images_url, product, png_upload
):
    upload(admin_api, admin_product_images_url, product.pk, png_upload())
    image_id = gallery(admin_api, admin_product_images_url, product.pk)[0]["id"]

    response = admin_api.patch(
        admin_product_images_url(product.pk),
        {"order": [image_id, image_id]},
        format="json",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMAGE_ORDER_DUPLICATE"


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------
def test_deleting_an_image_removes_it(
    admin_api, admin_product_images_url, admin_product_image_url, product, png_upload
):
    upload(admin_api, admin_product_images_url, product.pk, png_upload(name="a.png"))
    upload(admin_api, admin_product_images_url, product.pk, png_upload(name="b.png"))
    ids = [row["id"] for row in gallery(admin_api, admin_product_images_url, product.pk)]

    response = admin_api.delete(admin_product_image_url(product.pk, ids[0]))

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["images"]] == [ids[1]]
    assert not ProductImage.objects.filter(pk=ids[0]).exists()


def test_deleting_the_primary_promotes_the_next_image_rather_than_leaving_none(
    admin_api, admin_product_images_url, admin_product_image_url, product, png_upload
):
    upload(admin_api, admin_product_images_url, product.pk, png_upload(name="a.png"))
    upload(admin_api, admin_product_images_url, product.pk, png_upload(name="b.png"))
    ids = [row["id"] for row in gallery(admin_api, admin_product_images_url, product.pk)]

    body = admin_api.delete(admin_product_image_url(product.pk, ids[0])).json()

    assert body["images"][0]["is_primary"] is True


def test_deleting_another_products_image_is_refused(
    admin_api, admin_product_image_url, product, category
):
    stranger = factories.make_product(category, slug="stranger", sku="STRANGER-3")
    intruder = factories.make_image(stranger)

    response = admin_api.delete(admin_product_image_url(product.pk, intruder.pk))

    assert response.status_code == 422
    assert ProductImage.objects.filter(pk=intruder.pk).exists()
