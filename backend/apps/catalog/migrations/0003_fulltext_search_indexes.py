"""
FULLTEXT indexes for keyword search (PRD §6.5).

Django has no declarative FULLTEXT index, so these are raw DDL. They are what
make MATCH ... AGAINST viable on the product list endpoint, which carries a
p95 < 500ms budget (PRD §9.1).
"""
from django.db import migrations

CREATE_PRODUCT_FT = (
    "CREATE FULLTEXT INDEX catalog_product_ft "
    "ON catalog_product (name, description)"
)
DROP_PRODUCT_FT = "DROP INDEX catalog_product_ft ON catalog_product"

CREATE_VARIANT_FT = (
    "CREATE FULLTEXT INDEX catalog_variant_sku_ft "
    "ON catalog_product_variant (sku)"
)
DROP_VARIANT_FT = "DROP INDEX catalog_variant_sku_ft ON catalog_product_variant"


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_PRODUCT_FT, reverse_sql=DROP_PRODUCT_FT),
        migrations.RunSQL(sql=CREATE_VARIANT_FT, reverse_sql=DROP_VARIANT_FT),
    ]
