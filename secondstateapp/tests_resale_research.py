import base64
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from .models import AuctionWatchLot, HouseProposalEntry, LotResaleResearch
from .resale_research import resale_summary


class ResaleReportTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("resale-research", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = AuctionWatchLot.objects.create(source="Test", source_lot_id="pair", title="Pair of prints", artist="Artist")
        self.url = reverse("auction_lot_resale_report", args=[self.lot.pk])
        self.venues = [{
            "house": house, "department": "Prints and drawings", "low_usd": "450.00", "high_usd": 600,
            "fit": "Recent sales of the same series.", "basis": "Adjusted for the margin condition.",
            "sources": [{"label": "Print sale, lot 30", "note": "Verified USD hammer; sold as a pair.", "url": "https://example.org/sale/30"}],
        } for house in ("House A", "House B", "House C")]
        self.rows = [{
            "house": house, "season": "spring", "year": 2027, "work_key": "A",
            "artist": "Artist", "title": "Component A", "description": "Copy for " + house,
            "estimate_low": 200, "estimate_high": 300,
        } for house in ("House A", "House B")]
        self.payload = {"version": 0, "status": "ready", "resale_unit": "Pair sold together", "summary": "Two signed impressions.",
                        "venues": self.venues, "proposals": self.rows}

    def save(self, payload=None, **kwargs):
        return self.client.post(self.url, self.payload if payload is None else payload, content_type="application/json", **kwargs)

    def test_real_entry_report_navigation_and_cross_house_drafts(self):
        self.assertContains(self.client.get(self.url), "Add resale research")
        self.assertIsNone(resale_summary(self.lot))
        response = self.save()
        self.assertEqual(response.status_code, 200, response.content)
        # The same component appears in both recipient catalogs with independent copy.
        self.assertEqual(HouseProposalEntry.objects.count(), 2)
        lot = AuctionWatchLot.objects.select_related("resale_research").get(pk=self.lot.pk)
        summary = resale_summary(lot)
        self.assertEqual(summary["report_url"], self.url)
        self.assertEqual(summary["venues"][0], {"house": "House A", "low_usd": "450.00", "high_usd": "600.00"})
        page = self.client.get(self.url)
        self.assertContains(page, 'id="venue-1"')
        self.assertContains(page, 'href="https://example.org/sale/30"')
        self.assertContains(page, 'house=house-a')
        self.assertContains(page, '$450–$600')
        data = self.client.get(self.url, {"format": "json"}).json()["report"]
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["proposals"]), 2)
        self.assertEqual(data["proposals"][0]["estimate_low"], "200.00")

    def test_stale_writes_retries_and_partial_proposal_upserts(self):
        self.save()
        self.assertEqual(self.save().json()["version"], 1)
        data = deepcopy(self.payload)
        data.update(summary="Changed", proposals=[dict(self.rows[0], description="Revised copy")])
        self.assertEqual(self.save(data).status_code, 409)
        self.assertEqual(LotResaleResearch.objects.get().summary, "Two signed impressions.")
        data["version"] = 1
        self.assertEqual(self.save(data).json()["version"], 2)
        self.assertEqual(HouseProposalEntry.objects.get(house="House A").description, "Revised copy")
        self.assertEqual(HouseProposalEntry.objects.get(house="House B").description, "Copy for House B")
        entry = HouseProposalEntry.objects.get(house="House B")
        data.update(version=2, remove_proposal_ids=[entry.pk])
        self.assertEqual(self.save(data).json()["version"], 3)
        self.assertEqual(self.save(data).json()["version"], 3)
        self.assertEqual(HouseProposalEntry.objects.count(), 1)

    def test_unavailable_evidence_and_per_lot_deletions(self):
        self.save()
        other = AuctionWatchLot.objects.create(source="Test", source_lot_id="other")
        original_id = HouseProposalEntry.objects.first().pk
        response = self.client.post(reverse("auction_lot_resale_report", args=[other.pk]), {
            "version": 0, "status": "limited", "resale_unit": "Unresolved group",
            "summary": "The source cannot confirm whether the group is complete.",
            "remove_proposal_ids": [original_id], "venues": [],
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(HouseProposalEntry.objects.filter(pk=original_id).exists())
        self.assertEqual(resale_summary(AuctionWatchLot.objects.get(pk=other.pk))["venues"], [])

    def test_limited_estimate_and_later_completed_report_keep_prior_season_draft(self):
        data = deepcopy(self.payload)
        data.update(status="limited", venues=[dict(self.venues[0], low_usd=None, high_usd=None)], proposals=[
            dict(self.rows[0], estimate_low=None, estimate_high=None),
        ])
        self.assertEqual(self.save(data).json()["version"], 1)
        self.assertContains(self.client.get(self.url), "Estimate unavailable")
        saved = self.client.get(self.url, {"format": "json"}).json()["report"]
        self.assertIsNone(saved["venues"][0]["low_usd"])
        self.assertIsNone(saved["proposals"][0]["estimate_low"])
        partial = dict(data, venues=[dict(data["venues"][0], low_usd="100")])
        self.assertEqual(self.save(partial).status_code, 400)
        saved.update(status="ready", venues=self.venues)
        self.assertEqual(self.save(saved).json()["version"], 2)
        self.assertIsNone(HouseProposalEntry.objects.get().estimate_low)

    def test_public_copy_partial_edits_and_cloning_do_not_clear_other_fields(self):
        self.rows[0].update(literature="Published catalog, no. 52.", condition="Full margins.")
        self.assertEqual(self.save().json()["version"], 1)
        entry = HouseProposalEntry.objects.get(house="House A")
        def patch(version, rows):
            return self.save({"version": version, "proposals": rows})
        self.assertEqual(patch(1, [{"id": entry.pk, "description": "House A's revised note."}]).json()["version"], 2)
        entry.refresh_from_db()
        self.assertEqual(entry.literature, self.rows[0]["literature"])
        self.assertEqual(entry.condition, self.rows[0]["condition"])
        self.assertEqual(patch(2, [{"id": entry.pk, "season": "fall"}]).status_code, 400)
        new = dict(self.rows[0], season="fall", description="Fall selection.")
        self.assertEqual(patch(2, [new]).json()["version"], 3)
        self.assertEqual(patch(2, [new]).json()["version"], 3)
        self.assertEqual(HouseProposalEntry.objects.filter(house="House A").count(), 2)
        # The same identity can be used by the worker without knowing a row ID.
        fields = {"house": entry.house, "season": entry.season, "year": entry.year, "work_key": entry.work_key, "image_url": "https://example.org/work.jpg"}
        self.assertEqual(patch(3, [fields]).json()["version"], 4)
        entry.refresh_from_db()
        self.assertEqual(entry.description, "House A's revised note.")
        self.assertEqual(entry.literature, self.rows[0]["literature"])
        self.assertEqual(entry.image_url, fields["image_url"])
        self.assertEqual(LotResaleResearch.objects.get().venues[0]["house"], "House A")

    def test_oliver_return_and_invalid_json(self):
        self.lot.event_at = datetime(2026, 11, 20, 17, tzinfo=timezone.utc)
        self.lot.save(update_fields=["event_at"])
        page = self.client.get(self.url, {"scope": "oliver"})
        self.assertIn("scope=oliver", page.context["gallery_url"])
        self.assertIn("day=2026-11-20", page.context["gallery_url"])
        self.assertNotIn("scope=", self.client.get(self.url).context["gallery_url"])
        for raw in (b"[]", b'{"x": NaN}', b'{"status":{},"venues":[]}'):
            response = self.client.post(self.url, raw, content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_superseded_report_returns_to_original_saved_owner_on_visible_catalog_day(self):
        replacement = AuctionWatchLot.objects.create(source="New", source_lot_id="new",
            event_at=datetime(2026, 11, 27, 17, tzinfo=timezone.utc), artist="Artist", title="Pair of prints")
        self.lot.superseded_by = replacement
        self.lot.event_at = datetime(2026, 11, 26, 17, tzinfo=timezone.utc)
        self.lot.save(update_fields=["superseded_by", "event_at"])
        self.assertEqual(self.save().status_code, 200)
        url = self.client.get(self.url).context["gallery_url"]
        self.assertIn("day=2026-11-27", url)
        self.assertIn(f"lot={self.lot.pk}", url)
        self.assertIsNone(resale_summary(replacement))

    def test_invalid_sources_ranges_proposals_and_duplicate_houses_are_atomic(self):
        self.save()
        cases = [
            {"venues": self.venues[:2]},
            {"venues": [self.venues[0], self.venues[1], dict(self.venues[0], house="HOUSE A")]},
            {"venues": [*self.venues[:2], dict(self.venues[2], high_usd="200")]},
            {"venues": [*self.venues[:2], dict(self.venues[2], sources=[{"label": "Example", "url": "javascript:alert(1)", "note": "Untrusted"}])]},
            {"proposals": [self.rows[0], dict(self.rows[1], house="Unresearched house")]},
            {"proposals": [self.rows[0], dict(self.rows[1], estimate_high="Infinity")]},
            {"proposals": [dict(self.rows[0], image_url="file:///secret")]},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                response = self.save({**self.payload, "version": 1, "summary": "Should roll back", **changes})
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(LotResaleResearch.objects.get().version, 1)
        self.assertEqual(HouseProposalEntry.objects.count(), 2)

    def test_staff_csrf_and_normalized_images(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.staff)
        self.assertEqual(strict.post(self.url, self.payload, content_type="application/json").status_code, 403)
        with TemporaryDirectory() as directory, self.settings(MEDIA_ROOT=directory):
            image = BytesIO()
            Image.new("RGB", (16, 24), "white").save(image, format="PNG")
            blob = base64.b64encode(image.getvalue()).decode()
            response = self.client.post(self.url + "?upload=image", {"image_base64": blob}, content_type="application/json")
            self.assertEqual(response.status_code, 200, response.content)
            path = response.json()["image_url"]
            self.assertRegex(path, r"^/media/calendar-lots/[0-9a-f]{64}\.jpg$")
            self.rows[0]["image_base64"] = blob
            self.assertEqual(self.save().status_code, 200)
            self.assertEqual(HouseProposalEntry.objects.get(house="House A").image_url, path)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        ordinary = get_user_model().objects.create_user("nonstaff")
        self.client.force_login(ordinary)
        self.assertEqual(self.save().status_code, 302)
