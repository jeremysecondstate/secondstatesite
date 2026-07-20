import json
import os
from datetime import date, datetime, timedelta
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_sync import CalendarSyncError, sync_watchlist_lots
from secondstateapp.auction_reminders import (
    ReminderConfigurationError,
    TwilioSendResult,
    TwilioSmsSender,
    build_due_digests,
    run_auction_reminders,
)
from secondstateapp.models import AuctionReminderDelivery, AuctionWatchLot


CALENDAR_ZONE = ZoneInfo("America/Los_Angeles")


def watch_lot(**overrides):
    values = {
        "source": "Invaluable",
        "source_lot_id": "inv-100",
        "artist": "Joan Miró",
        "artist_watchlist_name": "Joan Miró",
        "title": "Jeune fille aux papillons",
        "medium": "Lithograph",
        "auction_house": "Bonhams",
        "sale_title": "Modern Prints",
        "lot_number": "25",
        "event_at": datetime(2026, 7, 25, 13, 30, tzinfo=CALENDAR_ZONE),
        "estimate_low": 2000,
        "estimate_high": 3000,
        "currency": "USD",
        "lot_url": "https://www.invaluable.com/auction-lot/example-100",
        "sale_url": "https://www.invaluable.com/catalog/example-sale",
        "source_status": "new",
        "active": True,
    }
    values.update(overrides)
    return AuctionWatchLot.objects.create(**values)


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class AuctionCalendarViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("calendar-admin", password="test-pass", is_staff=True)

    def test_calendar_is_staff_password_protected(self):
        response = self.client.get(reverse("auction_calendar"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

        ordinary = get_user_model().objects.create_user("ordinary", password="test-pass")
        self.client.force_login(ordinary)
        response = self.client.get(reverse("auction_calendar"))
        self.assertEqual(response.status_code, 302)

    def test_calendar_groups_lots_and_exposes_details_for_staff(self):
        watch_lot()
        watch_lot(source_lot_id="inv-101", artist="Henri Matisse", artist_watchlist_name="Henri Matisse")
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "July 2026")
        self.assertContains(response, "Bonhams")
        self.assertContains(response, "Joan Miró")
        self.assertContains(response, "Henri Matisse")
        self.assertEqual(response.context["calendar_data"]["2026-07-25"][0]["estimate"], "$2,000–3,000 estimate")
        self.assertEqual(response.context["weeks"][0][0]["date"].weekday(), 0)

    def test_invalid_month_falls_back_without_error(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("auction_calendar"), {"month": "not-a-month"})
        self.assertEqual(response.status_code, 200)


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class CalendarSyncApiTests(TestCase):
    endpoint = "/calendar/sync/"

    def _payload(self, **overrides):
        lot = {
            "source": "Invaluable",
            "source_lot_id": "205299494",
            "artist": "Rufino Tamayo",
            "artist_watchlist_name": "Rufino Tamayo",
            "title": "Galaxia",
            "medium": "Mixografia",
            "auction_house": "Bonhams",
            "sale_title": "Prints & Multiples",
            "lot_number": "47",
            "end_at": "2026-07-29T13:00:00-07:00",
            "estimate_low": 10000,
            "estimate_high": 15000,
            "currency": "USD",
            "lot_url": "https://www.invaluable.com/auction-lot/rufino-tamayo-galaxia",
            "sale_url": "https://www.invaluable.com/catalog/example",
            "first_seen_at": "2026-07-20T10:00:00Z",
            "last_seen_at": "2026-07-20T10:00:00Z",
            "status": "new",
        }
        lot.update(overrides)
        return {"lots": [lot]}

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_sync_requires_the_catalog_api_key(self):
        response = self.client.post(self.endpoint, data=json.dumps(self._payload()), content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(AuctionWatchLot.objects.count(), 0)

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_sync_creates_updates_and_ends_a_lot(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload()),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 1)
        lot = AuctionWatchLot.objects.get()
        self.assertEqual(lot.title, "Galaxia")
        self.assertEqual(lot.event_at.astimezone(CALENDAR_ZONE).hour, 13)
        self.assertTrue(lot.active)

        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(title="Galaxia (updated)", status="ended")),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        lot.refresh_from_db()
        self.assertEqual(response.json()["updated"], 1)
        self.assertEqual(response.json()["ended"], 1)
        self.assertEqual(lot.title, "Galaxia (updated)")
        self.assertFalse(lot.active)

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_date_only_sale_is_all_day_and_bad_data_is_atomic(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(end_at="2026-07-29")),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AuctionWatchLot.objects.get().is_all_day)

        bad = self._payload(source_lot_id="bad", estimate_low="not-money")
        response = self.client.post(
            self.endpoint,
            data=json.dumps(bad),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuctionWatchLot.objects.filter(source_lot_id="bad").exists())

        invalid_date = self._payload(source_lot_id="bad-date", end_at="2026-99-99")
        response = self.client.post(
            self.endpoint,
            data=json.dumps(invalid_date),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuctionWatchLot.objects.filter(source_lot_id="bad-date").exists())

    @patch.dict(os.environ, {"CATALOG_API_KEY": ""}, clear=False)
    def test_unconfigured_sync_returns_service_unavailable(self):
        response = self.client.post(self.endpoint, data='{"lots": []}', content_type="application/json")
        self.assertEqual(response.status_code, 503)


class _FakeSender:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def send(self, recipient, body):
        self.calls.append((recipient, body))
        if self.fail:
            raise RuntimeError("test failure")
        return TwilioSendResult(message_sid=f"SM{len(self.calls):032d}", status="queued")


@override_settings(
    CALENDAR_TIME_ZONE="America/Los_Angeles",
    SECONDSTATE_PUBLIC_URL="https://secondstate.art",
    SECRET_KEY="reminder-test-secret",
)
class AuctionReminderTests(TestCase):
    today = date(2026, 7, 20)

    def _event(self, days_ahead, **overrides):
        target = self.today + timedelta(days=days_ahead)
        return watch_lot(
            source_lot_id=f"due-{days_ahead}-{AuctionWatchLot.objects.count()}",
            event_at=datetime.combine(target, datetime.min.time(), tzinfo=CALENDAR_ZONE) + timedelta(hours=13),
            **overrides,
        )

    def test_builds_only_the_remaining_three_two_one_day_digests(self):
        self._event(3)
        self._event(2)
        self._event(1)
        self._event(4)
        self._event(0)

        digests = build_due_digests(self.today)

        self.assertEqual([item.days_before for item in digests], [3, 2, 1])
        self.assertTrue(all("Calendar: https://secondstate.art/calendar/" in item.body for item in digests))

    def test_late_discovery_one_day_before_sends_only_one_reminder(self):
        self._event(1)
        digests = build_due_digests(self.today)
        self.assertEqual(len(digests), 1)
        self.assertEqual(digests[0].days_before, 1)

    def test_delivery_is_idempotent_and_phone_is_not_stored_in_plaintext(self):
        self._event(3)
        sender = _FakeSender()
        recipient = "+12065550123"

        first = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)
        second = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)

        self.assertEqual(first.sent, 1)
        self.assertEqual(second.skipped, 1)
        self.assertEqual(len(sender.calls), 1)
        delivery = AuctionReminderDelivery.objects.get()
        self.assertEqual(delivery.status, AuctionReminderDelivery.Status.SENT)
        self.assertEqual(delivery.recipient_display, "***0123")
        self.assertNotIn(recipient, delivery.recipient_hash)

    def test_failed_delivery_is_recorded_and_can_retry(self):
        self._event(2)
        failed = run_auction_reminders(today=self.today, recipients=["+12065550123"], sender=_FakeSender(fail=True))
        retried_sender = _FakeSender()
        retried = run_auction_reminders(today=self.today, recipients=["+12065550123"], sender=retried_sender)

        self.assertEqual(failed.failed, 1)
        self.assertEqual(retried.sent, 1)
        self.assertEqual(AuctionReminderDelivery.objects.get().status, AuctionReminderDelivery.Status.SENT)

    def test_new_sale_added_after_a_digest_gets_one_supplemental_message(self):
        self._event(2, auction_house="Bonhams", sale_url="https://example.com/sale/bonhams")
        sender = _FakeSender()
        recipient = "+12065550123"
        first = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)

        self._event(2, auction_house="Phillips", sale_url="https://example.com/sale/phillips")
        supplemental = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)
        unchanged = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)

        self.assertEqual(first.sent, 1)
        self.assertEqual(supplemental.sent, 1)
        self.assertEqual(unchanged.skipped, 1)
        self.assertEqual(len(sender.calls), 2)
        self.assertIn("Phillips", sender.calls[1][1])
        self.assertNotIn("Bonhams", sender.calls[1][1])
        self.assertEqual(len(AuctionReminderDelivery.objects.get().covered_sale_hashes), 2)

    def test_dry_run_command_does_not_require_or_send_twilio_configuration(self):
        self._event(1)
        stdout = StringIO()
        call_command("send_auction_reminders", "--dry-run", "--date", "2026-07-20", stdout=stdout)
        self.assertIn("1-day digest", stdout.getvalue())
        self.assertEqual(AuctionReminderDelivery.objects.count(), 0)


class _JsonResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class _RecordingSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class TwilioSenderTests(SimpleTestCase):
    def test_api_key_auth_and_messaging_service_are_sent_to_twilio(self):
        session = _RecordingSession(_JsonResponse(201, {"sid": "SM123", "status": "queued"}))
        account_sid = "AC" + "1" * 32
        api_key_sid = "SK" + "2" * 32
        messaging_service_sid = "MG" + "3" * 32
        sender = TwilioSmsSender(
            account_sid=account_sid,
            api_key_sid=api_key_sid,
            api_key_secret="secret",
            messaging_service_sid=messaging_service_sid,
            session=session,
        )

        result = sender.send("+12065550123", "Reminder")

        self.assertEqual(result.message_sid, "SM123")
        self.assertEqual(session.calls[0][1]["auth"], (api_key_sid, "secret"))
        self.assertEqual(session.calls[0][1]["data"]["MessagingServiceSid"], messaging_service_sid)
        self.assertNotIn("From", session.calls[0][1]["data"])

    def test_placeholder_messaging_service_sid_fails_before_a_request(self):
        with self.assertRaisesMessage(
            ReminderConfigurationError,
            "TWILIO_MESSAGING_SERVICE_SID must be empty or a valid MG-prefixed Messaging Service SID.",
        ):
            TwilioSmsSender(
                account_sid="AC" + "1" * 32,
                api_key_sid="SK" + "2" * 32,
                api_key_secret="secret",
                from_number="+12065550123",
                messaging_service_sid="???",
            )


class DesktopCalendarSyncTests(SimpleTestCase):
    def test_sync_uploads_only_normalized_calendar_fields(self):
        lot = NormalizedLot(
            source="Invaluable",
            source_lot_id="lot-1",
            artist="Joan Miró",
            artist_watchlist_name="Joan Miró",
            title="Lithograph",
            end_at="2026-07-25T13:00:00-07:00",
            image_url="https://images.example/private.jpg",
            ambiguities=["example"],
        )
        session = _RecordingSession(
            _JsonResponse(200, {"ok": True, "received": 1, "created": 1, "updated": 0, "ended": 0})
        )

        result = sync_watchlist_lots(
            [lot],
            base_url="https://secondstate.art",
            api_key="catalog-key",
            session=session,
        )

        self.assertEqual(result.created, 1)
        url, request = session.calls[0]
        self.assertEqual(url, "https://secondstate.art/calendar/sync/")
        self.assertEqual(request["headers"]["X-API-KEY"], "catalog-key")
        sent_lot = request["json"]["lots"][0]
        self.assertNotIn("image_url", sent_lot)
        self.assertNotIn("ambiguities", sent_lot)
        self.assertNotIn("content_hash", sent_lot)

    def test_remote_plain_http_is_rejected(self):
        with self.assertRaises(CalendarSyncError):
            sync_watchlist_lots([], base_url="http://secondstate.art", api_key="key")
