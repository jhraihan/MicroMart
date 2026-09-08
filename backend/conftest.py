"""
Test-run overrides that have to be in place before the test database exists.

CONN_MAX_AGE is 60 in dev (config/settings/base.py) so the dev server reuses
connections between requests. Under the suite that setting is actively
harmful: the concurrency tests in apps/orders and apps/payments open real
connections on real threads, and a persistent connection outlives the
TransactionTestCase that opened it. Django then rebuilds the test database
underneath those pooled connections, and every test collected after
apps/orders/tests/test_oversell_concurrency.py fails with

    (1049, "Unknown database 'test_ecom'")

Each half of the suite passes alone, which is what makes the cascade so
misleading -- it is not the concurrency tests that are broken, it is every
test that runs after them. Pinning CONN_MAX_AGE to 0 for the run means every
connection is closed when it is finished with, so nothing survives to point at
a dropped database.

This is a property of the test run, not of the environment, so it lives here
rather than in .env -- a developer should not have to remember an env var to
get a green suite.
"""


def pytest_configure():
    # pytest-django has already called django.setup() by the time conftest
    # hooks run, and django_db_setup (which creates test_ecom) is a session
    # fixture that runs later still, so mutating the settings dict here lands
    # before the first connection is ever opened.
    from django.conf import settings

    for alias in settings.DATABASES:
        settings.DATABASES[alias]["CONN_MAX_AGE"] = 0
