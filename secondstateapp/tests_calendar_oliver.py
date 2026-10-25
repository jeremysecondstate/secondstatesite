"""Oliver's Calendar reuses lot identities and safely scopes its shared tray."""

from datetime import datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .calendar_views import _lot_json
from .models import AuctionEmailBatch, AuctionEmailBatchItem, AuctionWatchLot
from .oliver_houses import oliver_house_names
from .tests_calendar import CALENDAR_ZONE, watch_lot


@override_settings(
    CALENDAR_TIME_ZONE="America/Los_Angeles",
    SECONDSTATE_PUBLIC_URL="https://secondstate.art",
    AUCTION_EMAIL_SENDING_ENABLED=True,
    AUCTION_EMAIL_SENDER="jeremy@secondstate.art",
    AUCTION_EMAIL_RECIPIENT_JEREMY="jeremy@secondstate.art",
    AUCTION_EMAIL_RECIPIENT_OLIVER="oliver@secondstate.art",
    AUCTION_EMAIL_RECIPIENT_ALEX="alex@secondstate.art",
    GOOGLE_GMAIL_CLIENT_ID="test-client.apps.googleusercontent.com",
    GOOGLE_GMAIL_CLIENT_SECRET="test-client-secret",
    GOOGLE_GMAIL_REFRESH_TOKEN="test-refresh-token",
)
class OliverCalendarTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("oliver-calendar-admin", is_staff=True)
        self.client.force_login(self.staff)
        sender = patch("secondstateapp.calendar_views.send_auction_email", return_value="mock-oliver-message")
        self.sender = sender.start()
        self.addCleanup(sender.stop)

    def lot(self, identity, house="Bonhams", **changes):
        values = {
            "source_lot_id": identity,
            "title": f"Unique artwork {identity}",
            "auction_house": house,
            "artprice_url": "https://www.artprice.com/artist/1/example/lots/pasts",
            **changes,
        }
        lot = watch_lot(**values)
        lot.refresh_from_db()
        return lot

    def selected_batch(self, *lots):
        batch = AuctionEmailBatch.objects.create()
        for lot in lots:
            AuctionEmailBatchItem.objects.create(batch=batch, lot=lot, selected_by=self.staff)
        return batch

    def request_data(self, *lots, **changes):
        return {
            "recipients": ["jeremy", "oliver"],
            "scope_day": "2026-07-25",
            "scope_houses": "oliver",
            "expected_lot_ids": [str(lot.pk) for lot in lots],
            "return_view": "oliver",
            "day": "2026-07-25",
            "month": "2026-07",
            **changes,
        }

    def assert_oliver_redirect(self, response):
        self.assertEqual(response.status_code, 302)
        target = urlsplit(response["Location"])
        self.assertEqual(target.path, reverse("auction_calendar"))
        self.assertEqual(parse_qs(target.query), {
            "month": ["2026-07"], "day": ["2026-07-25"],
            "view": ["oliver"], "filter": ["tray"],
        })

    def test_eligibility_annotation_keeps_original_ids_fields_and_workflow_urls(self):
        partner = self.lot("partner")
        alias = self.lot("alias", "Bradford's")
        unrelated = self.lot("unrelated", "Another Auction Gallery")
        before = list(AuctionWatchLot.objects.order_by("pk").values())

        for lot, eligible, canonical_name in (
            (partner, True, "Bonhams"),
            (alias, True, "Bradford's Auction Galleries"),
            (unrelated, False, ""),
        ):
            with self.subTest(house=lot.auction_house):
                record = _lot_json(lot, CALENDAR_ZONE, {lot.pk})
                self.assertIs(record["oliver_house"], eligible)
                self.assertEqual(record["oliver_house_name"], canonical_name)
                self.assertEqual(record["id"], lot.pk)
                self.assertEqual(record["auction_house"], lot.auction_house)
                self.assertTrue(record["email_tray_selected"])
                for key, route in (
                    ("artprice_update_url", "auction_lot_artprice_link"),
                    ("artprice_analysis_url", "auction_lot_artprice_analysis"),
                    ("liveart_research_url", "auction_lot_liveart_research"),
                    ("liveart_analysis_url", "auction_lot_liveart_analysis"),
                    ("bid_board_url", "auction_lot_bid_board"),
                    ("saved_bid_board_url", "auction_lot_saved_bid_board"),
                    ("email_tray_update_url", "auction_email_lot_selection"),
                ):
                    self.assertEqual(record[key], reverse(route, args=(lot.pk,)))

        self.assertEqual(list(AuctionWatchLot.objects.order_by("pk").values()), before)

    def test_all_views_serialize_the_same_lots_and_only_annotate_house_membership(self):
        partner = self.lot("partner")
        unrelated = self.lot("unrelated", "Another Auction Gallery")

        for view in ("calendar", "catalog", "oliver", "research"):
            with self.subTest(view=view):
                response = self.client.get(reverse("auction_calendar"), {
                    "month": "2026-07", "day": "2026-07-25", "view": view,
                })
                self.assertEqual(response.status_code, 200)
                records = {record["id"]: record for record in response.context["calendar_data"]["2026-07-25"]}
                self.assertEqual(set(records), {partner.pk, unrelated.pk})
                self.assertTrue(records[partner.pk]["oliver_house"])
                self.assertFalse(records[unrelated.pk]["oliver_house"])
                self.assertEqual(response.context["oliver_house_count"], 17)
                self.assertEqual(response.context["oliver_house_names"], list(oliver_house_names()))
        self.sender.assert_not_called()

    def test_complete_workbook_house_list_is_available_on_empty_and_nonpartner_days(self):
        for populated in (False, True):
            with self.subTest(nonpartner_lot_present=populated):
                if populated:
                    self.lot("nonpartner-only", "Another Auction Gallery")
                response = self.client.get(reverse("auction_calendar"), {
                    "month": "2026-07", "day": "2026-07-25", "view": "oliver",
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["oliver_house_names"], list(oliver_house_names()))
                self.assertEqual(len(response.context["oliver_house_names"]), 17)
                records = response.context["calendar_data"].get("2026-07-25", [])
                self.assertFalse(any(record["oliver_house_name"] for record in records))
        self.sender.assert_not_called()

    def test_distinct_source_house_aliases_share_the_workbook_label_without_rewriting_lots(self):
        canonical = self.lot("canonical-house", "Bradford's Auction Galleries")
        alias = self.lot("alias-house", "Bradford's")
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07", "view": "oliver"})
        records = {record["id"]: record for record in response.context["calendar_data"]["2026-07-25"]}
        self.assertEqual(records[canonical.pk]["oliver_house_name"], "Bradford's Auction Galleries")
        self.assertEqual(records[alias.pk]["oliver_house_name"], "Bradford's Auction Galleries")
        self.assertEqual(records[canonical.pk]["auction_house"], "Bradford's Auction Galleries")
        self.assertEqual(records[alias.pk]["auction_house"], "Bradford's")
        canonical.refresh_from_db()
        alias.refresh_from_db()
        self.assertEqual(canonical.auction_house, "Bradford's Auction Galleries")
        self.assertEqual(alias.auction_house, "Bradford's")

    def test_oliver_send_preserves_hidden_houses_and_other_days_in_shared_tray(self):
        partner = self.lot("partner")
        alias = self.lot("alias", "Bradford's")
        hidden = self.lot("hidden", "Another Auction Gallery", artprice_url="")
        other_day = self.lot(
            "other-day", event_at=datetime(2026, 7, 26, 9, tzinfo=CALENDAR_ZONE), artprice_url="",
        )
        batch = self.selected_batch(partner, alias, hidden, other_day)
        retained = {item.lot_id: (item.selected_at, item.selected_by_id) for item in batch.items.all()}

        response = self.client.post(reverse("auction_email_send"), self.request_data(partner, alias))

        self.assert_oliver_redirect(response)
        self.sender.assert_called_once()
        body = self.sender.call_args.kwargs["text_body"]
        self.assertIn(partner.title, body)
        self.assertIn(alias.title, body)
        self.assertNotIn(hidden.title, body)
        self.assertNotIn(other_day.title, body)
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.SENT)
        self.assertFalse(batch.is_active)
        self.assertSetEqual(set(batch.items.values_list("lot_id", flat=True)), {partner.pk, alias.pk})
        remaining = AuctionEmailBatch.objects.get(is_active=True)
        self.assertSetEqual(set(remaining.items.values_list("lot_id", flat=True)), {hidden.pk, other_day.pk})
        for item in remaining.items.all():
            self.assertEqual((item.selected_at, item.selected_by_id), retained[item.lot_id])
            self.assertEqual(item.lot_snapshot, {})
        # A stale resubmission cannot send the hidden remainder.
        self.client.post(reverse("auction_email_send"), self.request_data(partner, alias))
        self.sender.assert_called_once()

    def test_regular_catalog_send_keeps_full_day_behavior(self):
        partner = self.lot("partner")
        unrelated = self.lot("unrelated", "Another Auction Gallery")
        batch = self.selected_batch(partner, unrelated)

        response = self.client.post(reverse("auction_email_send"), self.request_data(
            partner, unrelated, return_view="catalog", scope_houses="",
        ))

        self.assertIn("view=catalog", response["Location"])
        self.sender.assert_called_once()
        self.assertSetEqual(set(batch.items.values_list("lot_id", flat=True)), {partner.pk, unrelated.pk})
        self.assertFalse(AuctionEmailBatch.objects.filter(is_active=True).exists())

    def test_house_scope_is_allowlisted_and_requires_reviewed_day(self):
        partner = self.lot("partner")
        batch = self.selected_batch(partner)
        requests = [self.request_data(partner, scope_houses=value) for value in (
            "all", "Bonhams", "OLIVER", " oliver", "oliver ", ["oliver", ""],
        )]
        no_day = self.request_data(partner)
        no_day.pop("scope_day")
        requests.append(no_day)
        missing_house_scope = self.request_data(partner)
        missing_house_scope.pop("scope_houses")
        requests.append(missing_house_scope)
        requests.append(self.request_data(partner, scope_houses=""))

        for values in requests:
            with self.subTest(values=values):
                self.assertEqual(self.client.post(reverse("auction_email_send"), values).status_code, 302)
        self.sender.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.DRAFT)
        self.assertEqual(batch.attempt_count, 0)
        self.assertEqual(batch.items.get().lot_snapshot, {})

    def test_forged_or_incomplete_expected_ids_cannot_include_hidden_houses(self):
        first = self.lot("first")
        second = self.lot("second", "Phillips")
        hidden = self.lot("hidden", "Another Auction Gallery")
        batch = self.selected_batch(first, second, hidden)
        for ids in (
            [], [str(first.pk)], [str(first.pk), str(hidden.pk)],
            [str(first.pk), str(second.pk), str(hidden.pk)],
            [str(first.pk), str(second.pk), "999999"],
            [str(first.pk), str(second.pk), str(second.pk)],
            ["not-an-id"],
        ):
            with self.subTest(ids=ids):
                response = self.client.post(reverse("auction_email_send"), self.request_data(expected_lot_ids=ids))
                self.assert_oliver_redirect(response)
        self.sender.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.attempt_count, 0)
        self.assertEqual(batch.items.count(), 3)

    def test_newly_selected_partner_invalidates_the_old_review(self):
        first = self.lot("first")
        batch = self.selected_batch(first)
        second = self.lot("new-partner", "Phillips")
        AuctionEmailBatchItem.objects.create(batch=batch, lot=second)

        response = self.client.post(reverse("auction_email_send"), self.request_data(first), follow=True)

        self.assertContains(response, "The selected lots for this day changed.")
        self.assertEqual(response.wsgi_request.GET["view"], "oliver")
        self.sender.assert_not_called()
        self.assertEqual(batch.items.count(), 2)

    def test_newly_selected_nonpartner_stays_in_tray_without_invalidating_scoped_review(self):
        first = self.lot("first")
        batch = self.selected_batch(first)
        hidden = self.lot("new-hidden", "Another Auction Gallery", artprice_url="")
        AuctionEmailBatchItem.objects.create(batch=batch, lot=hidden)

        self.client.post(reverse("auction_email_send"), self.request_data(first))

        self.sender.assert_called_once()
        self.assertEqual(batch.items.get().lot_id, first.pk)
        self.assertEqual(AuctionEmailBatch.objects.get(is_active=True).items.get().lot_id, hidden.pk)

    def test_failed_oliver_send_retry_preserves_same_day_hidden_houses(self):
        selected = self.lot("selected")
        hidden = self.lot("hidden", "Another Auction Gallery", artprice_url="")
        batch = self.selected_batch(selected, hidden)
        values = self.request_data(selected)
        self.sender.side_effect = RuntimeError("Mock delivery failure")

        failed = self.client.post(reverse("auction_email_send"), values)

        self.assert_oliver_redirect(failed)
        batch.refresh_from_db()
        self.assertTrue(batch.is_active)
        self.assertEqual(batch.status, AuctionEmailBatch.Status.FAILED)
        self.assertEqual(batch.items.count(), 2)
        self.assertEqual(batch.items.get(lot=hidden).lot_snapshot, {})
        self.sender.side_effect = None
        retried = self.client.post(reverse("auction_email_retry"), values)
        self.assert_oliver_redirect(retried)
        self.assertEqual(self.sender.call_count, 2)
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.SENT)
        self.assertEqual(batch.attempt_count, 2)
        self.assertEqual(batch.items.get().lot_id, selected.pk)
        self.assertEqual(AuctionEmailBatch.objects.get(is_active=True).items.get().lot_id, hidden.pk)

    def test_oliver_scope_cannot_send_a_day_with_only_nonpartners(self):
        hidden = self.lot("hidden", "Another Auction Gallery")
        batch = self.selected_batch(hidden)

        response = self.client.post(reverse("auction_email_send"), self.request_data(hidden))

        self.assert_oliver_redirect(response)
        self.sender.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.DRAFT)
        self.assertEqual(batch.items.get().lot_id, hidden.pk)
