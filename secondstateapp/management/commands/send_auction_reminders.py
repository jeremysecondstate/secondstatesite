from datetime import date
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from secondstateapp.auction_reminders import ReminderConfigurationError, run_auction_reminders


class Command(BaseCommand):
    help = "Send idempotent 3-, 2-, and 1-day Twilio reminder digests for watched auction sales."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print due messages without sending or recording them.")
        parser.add_argument("--date", help="Override today's calendar date (YYYY-MM-DD) for testing.")

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        if not dry_run and not settings.TWILIO_SMS_ENABLED:
            raise CommandError("SMS is disabled. Set TWILIO_SMS_ENABLED=true only after sender and recipients are verified.")
        if options.get("date"):
            try:
                today = date.fromisoformat(options["date"])
            except ValueError as exc:
                raise CommandError("--date must use YYYY-MM-DD format.") from exc
        else:
            today = timezone.localtime(timezone.now(), ZoneInfo(settings.CALENDAR_TIME_ZONE)).date()

        try:
            result = run_auction_reminders(today=today, dry_run=dry_run)
        except ReminderConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        if not result.digests:
            self.stdout.write(self.style.WARNING(f"No auction reminders are due for the run date {today}."))
            return
        for digest in result.digests:
            self.stdout.write(
                f"\n{digest.days_before}-day digest for {digest.target_date} "
                f"({digest.sale_count} sales, {digest.lot_count} lots):\n{digest.body}"
            )
        if dry_run:
            self.stdout.write(self.style.SUCCESS("\nDry run complete; no SMS messages were sent or recorded."))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Reminder run complete: {result.sent} sent, {result.skipped} already handled, {result.failed} failed."
            )
        )
        if result.failed:
            raise CommandError("One or more Twilio deliveries failed: " + " | ".join(result.errors))
