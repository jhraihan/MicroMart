"""
Keyword search and relevance (FR-SRC-1).

The acceptance criterion that matters most: typing an exact model number or
SKU puts that product in first position. A search that returns the right
product in eighth place has failed for a customer holding the box.
"""
import pytest

from .factories import make_brand, make_category, make_product, result_slugs

pytestmark = pytest.mark.django_db


@pytest.fixture
def searchable_catalogue():
    gaming = make_category("Gaming Laptops", "gaming-laptops")
    accessories = make_category("Accessories", "accessories")
    asus = make_brand("Asus", "asus")
    lenovo = make_brand("Lenovo", "lenovo")

    laptop = make_product(
        gaming,
        brand=asus,
        name="Asus TUF Gaming F15 FX507ZC",
        slug="asus-tuf-gaming-f15-fx507zc",
        description="A gaming laptop with a thunderbolt port.",
        sku="FX507ZC-16-512",
        price="142000.00",
    )
    # Matches the same keyword through its name, so the exact-SKU product has
    # a real competitor for first place rather than winning by default.
    case = make_product(
        accessories,
        brand=asus,
        name="Carry case for FX507ZC-16-512",
        slug="carry-case-fx507zc",
        sku="CASE-FX-01",
        price="2500.00",
    )
    # Mentions the model number only in its SKU.
    battery = make_product(
        accessories,
        brand=asus,
        name="Spare battery pack",
        slug="spare-battery-pack",
        sku="FX507-SPARE-BAT",
        price="6500.00",
    )
    thinkpad = make_product(
        gaming,
        brand=lenovo,
        name="ThinkPad X1 Carbon",
        slug="thinkpad-x1-carbon",
        sku="X1C-16-1024",
        price="185000.00",
    )
    return {"laptop": laptop, "case": case, "battery": battery, "thinkpad": thinkpad}


def test_exact_sku_puts_that_product_first(api, products_url, searchable_catalogue):
    payload = api.get(products_url, {"q": "FX507ZC-16-512"}).json()
    slugs = result_slugs(payload)

    assert slugs[0] == searchable_catalogue["laptop"].slug
    # The carry case matches the same string by name, so this is a real
    # ranking decision and not a single-result accident.
    assert searchable_catalogue["case"].slug in slugs


def test_model_number_in_the_name_outranks_a_mention_in_a_sku(
    api, products_url, searchable_catalogue
):
    payload = api.get(products_url, {"q": "FX507"}).json()
    slugs = result_slugs(payload)

    assert searchable_catalogue["battery"].slug in slugs
    assert slugs.index(searchable_catalogue["laptop"].slug) < slugs.index(
        searchable_catalogue["battery"].slug
    )


def test_partial_sku_still_finds_the_product(api, products_url, searchable_catalogue):
    payload = api.get(products_url, {"q": "507ZC-16"}).json()

    assert searchable_catalogue["laptop"].slug in result_slugs(payload)


def test_search_matches_on_brand_name(api, products_url, searchable_catalogue):
    # "Lenovo" appears nowhere in the product's own name or SKU.
    payload = api.get(products_url, {"q": "Lenovo"}).json()

    assert result_slugs(payload) == [searchable_catalogue["thinkpad"].slug]


def test_short_keyword_below_the_fulltext_threshold_still_matches(
    api, products_url, searchable_catalogue
):
    # Under four characters there is no FULLTEXT arm at all, only LIKE.
    payload = api.get(products_url, {"q": "TUF"}).json()

    assert result_slugs(payload) == [searchable_catalogue["laptop"].slug]


def test_multi_word_search_narrows_rather_than_widens(
    api, products_url, searchable_catalogue
):
    payload = api.get(products_url, {"q": "carry case"}).json()

    assert result_slugs(payload) == [searchable_catalogue["case"].slug]


def test_search_with_no_matches_returns_an_empty_page_with_facets(
    api, products_url, searchable_catalogue
):
    response = api.get(products_url, {"q": "xylophone"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["count"] == 0
    assert payload["results"] == []
    assert payload["facets"]["brands"] == []
    assert payload["facets"]["price"] == {"min": None, "max": None}


def test_search_excludes_inactive_products(api, products_url, searchable_catalogue):
    laptop = searchable_catalogue["laptop"]
    laptop.is_active = False
    laptop.save(update_fields=["is_active"])

    payload = api.get(products_url, {"q": "FX507ZC-16-512"}).json()

    assert laptop.slug not in result_slugs(payload)


def test_relevance_sort_without_a_keyword_falls_back_to_newest(
    api, products_url, searchable_catalogue
):
    # Relevance is meaningless with nothing to be relevant to, so it degrades
    # rather than erroring.
    response = api.get(products_url, {"sort": "relevance"})
    payload = response.json()

    assert response.status_code == 200
    assert result_slugs(payload) == result_slugs(
        api.get(products_url, {"sort": "newest"}).json()
    )


def test_keyword_punctuation_cannot_negate_its_own_match(
    api, products_url, searchable_catalogue
):
    # In MySQL boolean mode "-" is NOT, so a raw SKU that is passed through
    # unstripped would exclude the very product it names.
    hyphenated = api.get(products_url, {"q": "FX507ZC-16-512"}).json()
    plain = api.get(products_url, {"q": "FX507ZC"}).json()

    assert searchable_catalogue["laptop"].slug in result_slugs(hyphenated)
    assert searchable_catalogue["laptop"].slug in result_slugs(plain)


@pytest.mark.django_db(transaction=True)
def test_fulltext_arm_matches_a_word_that_appears_only_in_the_description(
    api, products_url
):
    """
    The FULLTEXT arm is the only clause that reads `description`, so a
    description-only word proves MATCH ... AGAINST is really firing.

    This test commits, because InnoDB updates a FULLTEXT index at commit
    time -- rows written inside an open transaction are invisible to MATCH.
    """
    category = make_category("Gaming Laptops", "gaming-laptops")
    brand = make_brand("Asus", "asus")
    make_product(
        category,
        brand=brand,
        name="Asus TUF Gaming F15",
        slug="asus-tuf-gaming-f15",
        description="Ships with a thunderbolt dock in the box.",
        sku="TUF-FT-16-512",
        price="142000.00",
    )
    make_product(
        category,
        brand=brand,
        name="Asus Vivobook Go",
        slug="asus-vivobook-go",
        description="A quiet everyday machine.",
        sku="VIVO-FT-8-256",
        price="62000.00",
    )

    payload = api.get(products_url, {"q": "thunderbolt"}).json()

    assert result_slugs(payload) == ["asus-tuf-gaming-f15"]


@pytest.mark.django_db(transaction=True)
def test_brand_plus_model_in_one_query_finds_the_product(api, products_url):
    """
    "Brand + model" is the commonest shape a shopper types, and it used to
    land on the zero-result state.

    The brand was matched only by a LIKE over the *whole* query string, while
    the FULLTEXT arm required every token to appear in the product's own name
    or description -- so a query whose tokens split across the two matched
    nothing at all. The seed catalogue hid this because every seeded product
    name already begins with its brand name.

    Committed, because InnoDB updates a FULLTEXT index at commit time and the
    FULLTEXT arm must be genuinely in play for this to prove anything.
    """
    category = make_category("Gaming Laptops", "gaming-laptops")
    lenovo = make_brand("Lenovo", "lenovo")
    asus = make_brand("Asus", "asus")
    # The brand name appears nowhere in the product's own name or description.
    make_product(
        category,
        brand=lenovo,
        name="Legion 5 Pro",
        slug="legion-5-pro",
        sku="LEG5P-16-512",
        price="165000.00",
    )
    make_product(
        category,
        brand=asus,
        name="TUF Gaming F15",
        slug="tuf-gaming-f15",
        sku="TUF15-16-512",
        price="142000.00",
    )

    by_model = api.get(products_url, {"q": "legion"}).json()
    by_brand = api.get(products_url, {"q": "lenovo"}).json()
    by_both = api.get(products_url, {"q": "lenovo legion"}).json()

    assert result_slugs(by_model) == ["legion-5-pro"]
    assert result_slugs(by_brand) == ["legion-5-pro"]
    # Each half matched on its own; together they must narrow, not vanish.
    assert result_slugs(by_both) == ["legion-5-pro"]


@pytest.mark.django_db(transaction=True)
def test_a_brand_token_still_narrows_rather_than_widens(api, products_url):
    """The token chain ANDs. A brand hit alone must not drag in the whole shelf."""
    category = make_category("Gaming Laptops", "gaming-laptops")
    lenovo = make_brand("Lenovo", "lenovo")
    make_product(
        category, brand=lenovo, name="Legion 5 Pro", slug="legion-5-pro", sku="LEG-1"
    )
    make_product(
        category, brand=lenovo, name="ThinkPad X1", slug="thinkpad-x1", sku="TP-1"
    )

    payload = api.get(products_url, {"q": "lenovo thinkpad"}).json()

    assert result_slugs(payload) == ["thinkpad-x1"]


def test_like_wildcards_in_a_keyword_are_escaped_not_executed(api, products_url):
    # "%" must be searched for, not used as a wildcard that matches the whole
    # catalogue.
    category = make_category("Deals", "deals")
    make_product(category, name="Sale 50% off bundle", slug="sale-bundle", sku="DEAL-1")
    make_product(category, name="Regular price item", slug="regular-item", sku="DEAL-2")

    payload = api.get(products_url, {"q": "%"}).json()

    assert result_slugs(payload) == ["sale-bundle"]


def test_underscore_in_a_keyword_is_escaped(api, products_url):
    category = make_category("Deals", "deals")
    make_product(category, name="Model A_1 desktop", slug="model-a-1", sku="UND-1")
    make_product(category, name="Model AX1 desktop", slug="model-ax1", sku="UND-2")

    payload = api.get(products_url, {"q": "A_1"}).json()

    assert result_slugs(payload) == ["model-a-1"]


def test_sql_metacharacters_in_a_keyword_are_bound_not_interpolated(
    api, products_url, searchable_catalogue
):
    response = api.get(products_url, {"q": "' OR 1=1 -- "})

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_facets_are_counted_over_the_search_results(
    api, products_url, searchable_catalogue
):
    payload = api.get(products_url, {"q": "Lenovo"}).json()

    assert payload["facets"]["brands"] == [
        {"slug": "lenovo", "name": "Lenovo", "count": 1}
    ]
    assert payload["facets"]["categories"] == [
        {"slug": "gaming-laptops", "name": "Gaming Laptops", "count": 1}
    ]
