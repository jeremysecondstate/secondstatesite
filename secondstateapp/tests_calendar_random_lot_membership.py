import os
from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AuctionWatchArtist, AuctionWatchLot
from .tests_calendar import watch_lot


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
@patch.dict(os.environ, {"CATALOG_API_KEY": "audit-test-key"})
class RandomLotMembershipTests(TestCase):
    headers = {"HTTP_X_API_KEY": "audit-test-key"}
    day = "2026-07-25"
    create_mode = "random_lots_create_only"

    def setUp(self):
        self.membership = reverse("auction_calendar_random_lot_membership")
        self.sync = reverse("auction_calendar_sync")
        self.client.force_login(get_user_model().objects.create_user("collection-reviewer", is_staff=True))

    def row(self, lot):
        return {"id": lot.pk, "source": lot.source, "source_lot_id": lot.source_lot_id, "calendar_day": self.day}

    def post(self, url, payload):
        return self.client.post(url, payload, content_type="application/json", **self.headers)

    def gallery(self, day):
        return self.client.get(reverse("auction_calendar_random_lots"), {"day": day}).json()

    def test_worker_contract_and_access(self):
        self.assertEqual(self.client.get(self.membership).status_code, 401)
        self.assertEqual(self.client.post(self.membership).status_code, 401)
        capabilities = self.client.get(self.membership, **self.headers).json()
        self.assertEqual((capabilities["create_mode"], capabilities["schema_version"], capabilities["max_batch"]),
                         (self.create_mode, 1, 100))
        for payload in ({}, {"lots": [], "verify_only": True}, {"lots": [{}]},
                        {"lots": [{}], "verify_only": "false"}, {"lots": [{}] * 101}):
            self.assertEqual(self.post(self.membership, payload).status_code, 400)

    def test_mark_exact_survivors_once_and_reject_whole_stale_batch(self):
        outside = watch_lot(source_lot_id="off-roster-a", artist="Off-roster printmaker", artist_watchlist_name="")
        another = watch_lot(source_lot_id="off-roster-b")
        original = outside.synced_at
        rows = [self.row(outside), self.row(another)]
        before = self.client.get(self.membership, rows[0], **self.headers).json()["lots"][0]
        self.assertFalse(before["random_lot"])
        self.assertFalse(before["membership_added"])
        for wrong in ({"calendar_day": "2026-07-26"}, {"source": "another provider"}, {"source_lot_id": "wrong"}):
            self.assertEqual(self.post(self.membership, {"lots": [rows[0], rows[1] | wrong]}).status_code, 409)
            self.assertFalse(AuctionWatchLot.objects.filter(random_lot=True).exists())
        for expected_added in (True, False):
            result = self.post(self.membership, {"lots": rows}).json()["lots"]
            self.assertEqual([x["membership_added"] for x in result], [expected_added, expected_added])
            self.assertTrue(all(x["random_lot"] for x in result))
        readers = self.post(self.membership, {"lots": rows, "verify_only": True}).json()["lots"]
        self.assertTrue(all(x["random_lot"] and not x["membership_added"] for x in readers))
        outside.refresh_from_db()
        self.assertEqual(outside.synced_at, original)
        self.assertEqual({r["id"] for r in self.gallery(self.day)["lots"]}, {outside.pk, another.pk})
        tracked = self.client.get(reverse("auction_calendar_day_lots"), {"day": self.day}).json()
        self.assertNotIn(outside.pk, {r["id"] for r in tracked["lots"]})

    def test_legacy_and_new_merges_keep_one_membership_on_current_sale_day(self):
        survivor = watch_lot(source_lot_id="current", event_at=datetime(2026, 7, 26, 18, tzinfo=timezone.utc))
        middle = watch_lot(source_lot_id="middle", superseded_by=survivor)
        legacy = watch_lot(source="Drouot", source_lot_id="35991044", superseded_by=middle)
        watch_lot(source_lot_id="flagged-source", random_lot=True, superseded_by=middle)
        self.assertEqual(self.post(self.membership, {"lots": [self.row(legacy)]}).status_code, 409)
        self.assertEqual(self.gallery(self.day)["total"], 0)
        target = self.row(survivor) | {"calendar_day": "2026-07-26"}
        result = self.client.get(self.membership, target, **self.headers).json()["lots"][0]
        self.assertTrue(result["random_lot"])
        self.assertFalse(self.post(self.membership, {"lots": [target]}).json()["lots"][0]["membership_added"])
        self.assertEqual([r["id"] for r in self.gallery(target["calendar_day"])["lots"]], [survivor.pk])
        calendar = self.client.get(reverse("auction_calendar"), {"day": target["calendar_day"]})
        self.assertEqual(calendar.context["random_lots_by_day"], {"2026-07-26": 1})

    def test_audit_creation_is_atomic_and_normal_sync_keeps_membership(self):
        new = {"source": "Drouot", "source_lot_id": "new-print", "title": "Artist's proof", "medium": "Lithograph",
               "artist": "Off-roster printmaker", "end_at": "2026-07-26T03:30:00Z", "calendar_day": self.day}
        existing = watch_lot(source="Drouot", source_lot_id="existing-print", title="Original source title")
        matched = new | {"source_lot_id": existing.source_lot_id}
        def create(rows):
            return self.post(self.sync, {"mode": self.create_mode, "lots": rows})
        for invalid in (new | {"source_lot_id": ""}, matched | {"calendar_day": "2026-07-26"}):
            self.assertEqual(create([new, invalid]).status_code, 400)
            self.assertFalse(AuctionWatchLot.objects.filter(source_lot_id="new-print").exists())
        written = create([new, matched]).json()
        self.assertEqual((written["mode"], written["created"], written["updated"]), (self.create_mode, 1, 0))
        self.assertEqual([(row["created"], row["random_lot"]) for row in written["lots"]],
                         [(True, True), (False, False)])
        self.assertFalse(AuctionWatchArtist.objects.filter(name="Off-roster printmaker").exists())
        replay = create([new | {"title": "Should never replace the source"}]).json()["lots"][0]
        self.assertTrue(replay["random_lot"])
        self.assertFalse(replay["created"] or replay["membership_added"])
        self.assertEqual(AuctionWatchLot.objects.get(pk=replay["id"]).title, new["title"])
        existing.refresh_from_db()
        self.assertEqual(existing.title, "Original source title")
        self.assertFalse(existing.random_lot)
        self.assertEqual(self.post(self.sync, {"lots": [new | {"title": "Latest catalog", "end_at": "2026-07-27"}]}).status_code, 200)
        self.assertEqual(self.gallery(self.day)["total"], 0)
        self.assertEqual([r["id"] for r in self.gallery("2026-07-27")["lots"]], [replay["id"]])
