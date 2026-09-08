"""
Low-stock digest (FR-INV-7), invoked by cron.

There is no Celery and no Redis in v1 -- a deliberate scope decision. A daily
digest does not need a broker, a worker and a result backend; it needs a cron
line:

    0 9 * * *  /path/to/.venv/bin/python /path/to/manage.py send_low_stock_digest

Nothing is sent when nothing is low. A digest that arrives every morning
saying "all clear" trains its readers to ignore it, and the one morning it
matters they will.
"""
from django.core.management.base import BaseCommand

from apps.catalog.services import inventory as inventory_services
from apps.dashboard.models import StoreSettings
from apps.orders.services import notifications


class Command(BaseCommand):
    help = "Email the low-stock digest to StoreSettings.low_stock_digest_recipients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be sent, and to whom, without sending it.",
        )
        parser.add_argument(
            "--recipient",
            action="append",
            dest="recipients",
            default=None,
            help="Override the configured recipients. Repeatable.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Send even when no variant is below its threshold.",
        )

    def handle(self, *args, **options):
        store = StoreSettings.load()
        recipients = options["recipients"] or list(
            store.low_stock_digest_recipients or []
        )
        variants = list(inventory_services.low_stock_variants())

        self.stdout.write(
            "{0} variant(s) at or below threshold.".format(len(variants))
        )
        for variant in variants:
            self.stdout.write(
                "  {0:>5}  {1}  {2}{3}".format(
                    variant.stock,
                    variant.sku,
                    variant.product.name,
                    " - {0}".format(variant.option_label) if variant.option_label else "",
                )
            )

        if not variants and not options["force"]:
            self.stdout.write(self.style.SUCCESS("Nothing to report. No email sent."))
            return

        if not recipients:
            self.stdout.write(
                self.style.WARNING(
                    "No digest recipients configured. Set "
                    "StoreSettings.low_stock_digest_recipients, or pass --recipient."
                )
            )
            return

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run -- would email {0}.".format(", ".join(recipients))
                )
            )
            return

        sent = notifications.send_low_stock_digest(
            variants=variants, recipients=recipients
        )
        self.stdout.write(
            self.style.SUCCESS("Digest sent to {0} recipient(s).".format(sent))
        )
