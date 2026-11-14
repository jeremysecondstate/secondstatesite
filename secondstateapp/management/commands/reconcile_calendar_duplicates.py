"""Audit all Calendar lots and apply only explicitly reviewed replacement pairs."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from secondstateapp.calendar_duplicates import apply_pairs, audit_lots, rollback_receipt
from secondstateapp.models import AuctionWatchLot


class Command(BaseCommand):
    help = "Audit every saved Calendar day/lot. --apply requires a reviewed JSON plan; preserves all source records and saved work."

    def add_arguments(self, parser):
        parser.add_argument("--report", type=Path, help="Write the complete audit JSON here.")
        parser.add_argument("--apply", type=Path, help="Apply the pairs from this reviewed JSON plan.")
        parser.add_argument("--receipt", type=Path, help="Required new file for the reversible mutation receipt.")
        parser.add_argument("--rollback", type=Path, help="Undo suppression links from a prior receipt.")

    def handle(self, *args, **options):
        if options["apply"] and options["rollback"]:
            raise CommandError("Choose --apply or --rollback.")
        if (options["apply"] or options["rollback"]) and not options["receipt"]:
            raise CommandError("A new --receipt file is required for any mutation.")
        receipt_path = options["receipt"]
        if receipt_path and receipt_path.exists():
            raise CommandError("Receipt already exists; choose a new path.")
        try:
            if options["apply"] or options["rollback"]:
                source_path = options["apply"] or options["rollback"]
                payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                # A failed receipt write rolls back the database transaction.
                with transaction.atomic():
                    if options["apply"]:
                        receipt = apply_pairs(payload["pairs"])
                    else:
                        receipt = {"format": "secondstate-calendar-duplicate-rollback-v1",
                                   "restored": rollback_receipt(payload), "original_receipt": str(source_path)}
                    with receipt_path.open("x", encoding="utf-8") as handle:
                        json.dump(receipt, handle, indent=2, ensure_ascii=False)
                self.stdout.write(f"Saved receipt: {receipt_path}")
            report = audit_lots(AuctionWatchLot.objects.all(), timezone_name=settings.CALENDAR_TIME_ZONE)
            if options["report"]:
                options["report"].parent.mkdir(parents=True, exist_ok=True)
                options["report"].write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            self.stdout.write(json.dumps({key: report[key] for key in ("total_records", "visible_records", "superseded_records", "dated_days")}))
            self.stdout.write(f"Duplicate candidates: {len(report['pairs'])}; strong: {sum(pair['confidence'] == 'strong' for pair in report['pairs'])}")
            if not options["report"]:
                self.stdout.write("Use --report PATH to inspect every candidate and per-day coverage.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
