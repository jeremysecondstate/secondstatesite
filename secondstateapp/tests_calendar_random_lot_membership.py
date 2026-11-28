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
        self.assertIs(capabilities["exclusive_catalogs"], True)
        for payload in ({}, {"lots": [], "verify_only": True}, {"lots": [{}]},
                        {"lots": [{}], "verify_only": "false"}, {"lots": [{}] * 101}):
            self.assertEqual(self.post(self.membership, payload).status_code, 400)

    def test_mark_exact_survivors_once_and_reject_whole_stale_batch(self):
        outside = watch_lot(source_lot_id="off-roster-a", artist="Off-roster printmaker", artist_watchlist_name="")
        another = watch_lot(source_lot_id="off-roster-b", artist="", artist_watchlist_name="")
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
        survivor = watch_lot(source_lot_id="current", artist="Off-roster artist", artist_watchlist_name="",
                             event_at=datetime(2026, 7, 26, 18, tzinfo=timezone.utc))
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

    def test_effective_membership_matches_default_catalog_and_ignores_unrelated_house_scope(self):
        tracked = watch_lot(source_lot_id="already-regular", active=False, auction_house="Small local house")
        mixed = watch_lot(source_lot_id="mixed-printmakers", artist="Various artists (portfolio)",
                          artist_watchlist_name="Joan Miró", random_lot=True)
        subject = watch_lot(source_lot_id="documentary-portrait", artist="A photographer, portrait of Joan Miró",
                            artist_watchlist_name="Joan Miró")
        unsaved = watch_lot(source_lot_id="not-filed", artist="Photographer", artist_watchlist_name="")
        self.assertEqual({row["id"] for row in self.client.get(reverse("auction_calendar_day_lots"),
                         {"day": self.day}).json()["lots"]}, {tracked.pk, mixed.pk})
        expected = {tracked.pk: (True, False), mixed.pk: (True, False),
                    subject.pk: (False, True), unsaved.pk: (False, False)}
        requested = [self.row(lot) for lot in (tracked, mixed, subject)]
        for added in (True, False):
            results = self.post(self.membership, {"lots": requested}).json()["lots"]
            self.assertEqual([(r["id"], r["regular_catalog"], r["random_lot"], r["membership_added"])
                              for r in results],
                             [(tracked.pk, True, False, False), (mixed.pk, True, False, False),
                              (subject.pk, False, True, added)])
        verify = self.post(self.membership, {"lots": [*requested, self.row(unsaved)], "verify_only": True}).json()
        self.assertEqual({row["id"]: (row["regular_catalog"], row["random_lot"]) for row in verify["lots"]}, expected)
        self.assertTrue(all(not row["membership_added"] for row in verify["lots"]))
        tracked.refresh_from_db()
        self.assertFalse(tracked.random_lot)
        self.assertEqual([row["id"] for row in self.gallery(self.day)["lots"]], [subject.pk])
        counts = self.client.get(reverse("auction_calendar"), {"day": self.day}).context
        self.assertEqual((counts["calendar_day_counts"][self.day]["lots"], counts["random_lots_count"]), (2, 1))
        census = self.client.get(reverse("calendar_reconciliation"),
                                 {"ids": ",".join(str(pk) for pk in expected)}, **self.headers).json()
        self.assertEqual({row["id"]: row["regular_catalog"] for row in census["lots"]},
                         {pk: regular for pk, (regular, _) in expected.items()})

    def test_inherited_and_legacy_memberships_do_not_compete_with_regular_survivors(self):
        date = datetime(2026, 7, 26, 18, tzinfo=timezone.utc)
        survivor = watch_lot(source_lot_id="canonical-tracked", event_at=date)
        middle = watch_lot(source_lot_id="alternate-middle", superseded_by=survivor)
        legacy = watch_lot(source="Drouot", source_lot_id="35991044", superseded_by=middle)
        watch_lot(source_lot_id="alternate-flagged", random_lot=True, superseded_by=survivor)
        direct_legacy = watch_lot(source_lot_id="207302212", event_at=date)
        other = watch_lot(source="Drouot", source_lot_id="other-impression", random_lot=True, event_at=date,
                          artist="Off-roster printmaker", artist_watchlist_name="")
        day = "2026-07-26"
        requested = [self.row(lot) | {"calendar_day": day} for lot in (survivor, direct_legacy)]
        for target in requested:
            receipt, = self.client.get(self.membership, target, **self.headers).json()["lots"]
            self.assertEqual((receipt["regular_catalog"], receipt["random_lot"], receipt["membership_added"]),
                             (True, False, False))
        self.assertEqual(self.post(self.membership, {"lots": [self.row(legacy)]}).status_code, 409)
        self.assertEqual(self.gallery(self.day)["total"], 0)
        params = {"day": day, "artists": "all", "facets": "1"}
        random = self.client.get(reverse("auction_calendar_random_lots"), params).json()
        self.assertEqual((random["day_total"], [row["id"] for row in random["lots"]]), (1, [other.pk]))
        self.assertEqual([c["label"] for c in random["facets"]["artists"]], ["Off-roster printmaker"])
        regular = self.client.get(reverse("auction_calendar_day_lots"), {"day": day}).json()
        self.assertEqual({row["id"] for row in regular["lots"]}, {survivor.pk, direct_legacy.pk})
        counts = self.client.get(reverse("auction_calendar"), {"day": day}).context["random_lots_by_day"]
        self.assertEqual(counts, {day: 1})

    def test_create_only_routes_tracked_prints_and_uses_the_saved_credit_on_replay(self):
        record = {"source": "Drouot", "source_lot_id": "regular-print", "title": "Artist's proof",
                  "artist": "Joan Miró", "start_at": "2026-07-25T19:00:00Z", "calendar_day": self.day}
        def create(entry):
            result = self.post(self.sync, {"mode": self.create_mode, "lots": [entry]})
            self.assertEqual(result.status_code, 200)
            return result.json()["lots"][0]

        created = create(record)
        self.assertEqual((created["created"], created["regular_catalog"], created["random_lot"],
                          created["membership_added"]), (True, True, False, False))
        replay = create(record | {"artist": "Different printmaker", "title": "Conflicting re-observation"})
        self.assertEqual((replay["id"], replay["created"], replay["regular_catalog"], replay["random_lot"],
                          replay["membership_added"]), (created["id"], False, True, False, False))
        lot = AuctionWatchLot.objects.get(pk=replay["id"])
        self.assertEqual((lot.artist, lot.title, lot.random_lot), ("Joan Miró", "Artist's proof", False))
        self.assertEqual([r["id"] for r in self.client.get(reverse("auction_calendar_day_lots"),
                         {"day": self.day}).json()["lots"]], [lot.pk])
        self.assertEqual(self.gallery(self.day)["total"], 0)

    def test_sync_changes_catalog_without_restoring_cleared_membership_or_disturbing_saved_work(self):
        lot = watch_lot(source="Drouot", source_lot_id="credit-changed", artist="Local artist",
                        artist_watchlist_name="", random_lot=True,
                        artprice_url="https://www.artprice.com/artist/1/local/lots/pasts")
        old = watch_lot(source_lot_id="formerly-saved-provider", superseded_by=lot, random_lot=True)
        neighbor = watch_lot(source="Invaluable", source_lot_id="separate-same-number", artist="Another artist",
                             artist_watchlist_name="", random_lot=True,
                             artprice_url="https://www.artprice.com/artist/2/another/lots/pasts")
        cards = {r["id"]: r for r in self.gallery(self.day)["lots"]}
        for card in cards.values():
            for url in (card["email_tray_update_url"], card["research_queue_update_url"]):
                response = self.client.post(url, {"selected": "true"})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertTrue(response.json()["selected"])

        source = {"source": lot.source, "source_lot_id": lot.source_lot_id, "title": lot.title,
                  "lot_number": lot.lot_number, "auction_house": lot.auction_house,
                  "end_at": "2026-07-25T19:00:00Z"}
        self.assertEqual(self.post(self.sync, {"lots": [source | {"artist": "Joan Miró"}]}).status_code, 200)
        lot.refresh_from_db()
        self.assertFalse(lot.random_lot)
        old.refresh_from_db()
        self.assertFalse(old.random_lot)
        regular = self.client.get(reverse("auction_calendar_day_lots"), {"day": self.day}).json()["lots"]
        self.assertEqual([r["id"] for r in regular], [lot.pk])
        self.assertTrue(regular[0]["email_tray_selected"] and regular[0]["research_queue_selected"])
        self.assertEqual([r["id"] for r in self.gallery(self.day)["lots"]], [neighbor.pk])

        self.assertEqual(self.post(self.sync, {"lots": [source | {"artist": "Local artist"}]}).status_code, 200)
        receipt, = self.client.get(self.membership, self.row(lot), **self.headers).json()["lots"]
        self.assertEqual((receipt["regular_catalog"], receipt["random_lot"]), (False, False))
        remaining, = self.gallery(self.day)["lots"]
        self.assertEqual(remaining["id"], neighbor.pk)
        self.assertTrue(remaining["email_tray_selected"] and remaining["research_queue_selected"])
        for added in (True, False):
            receipt, = self.post(self.membership, {"lots": [self.row(lot)]}).json()["lots"]
            self.assertEqual((receipt["regular_catalog"], receipt["random_lot"], receipt["membership_added"]),
                             (False, True, added))
