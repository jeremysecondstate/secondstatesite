"""Every selected lot can enter the existing dossier before it has research."""
from datetime import datetime, timezone as datetime_timezone
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuctionBidBoardAnalysis, AuctionWatchLot, LiveArtResaleAnalysis
from .research_queue import select_lot, worker_action


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class ResearchQueueDossierTests(TestCase):
    def setUp(self):
        staff = get_user_model().objects.create_user("queue-dossier-staff", is_staff=True)
        self.client.force_login(staff)
        self.lot = AuctionWatchLot.objects.create(source="test", source_lot_id="unsaved-dossier", title="Unsaved work", event_at=datetime(2026, 11, 1, 1, 30, tzinfo=datetime_timezone.utc))
        self.item = select_lot(self.lot.pk, True)

    def test_unsaved_lot_has_internal_dossier_link_and_snapshot_uses_same_local_day(self):
        response = self.client.get(reverse("auction_research_queue"))
        self.assertEqual(response.status_code, 200)
        item = response.context["queue_items"][0]
        link = urlsplit(item.dossier_url)
        self.assertEqual(link.path, reverse("auction_calendar"))
        self.assertEqual(parse_qs(link.query), {"month": ["2026-10"], "day": ["2026-10-31"], "view": ["research"], "lot": [str(self.lot.pk)], "look": ["dossier"]})
        self.assertContains(response, "Open dossier ↗")
        self.assertEqual(item.research_url, "")
        self.assertEqual(item.board_url, "")
        self.assertNotContains(response, "Saved research ↗")
        self.assertNotContains(response, "Saved Bid Board ↗")
        run = worker_action({"action": "start", "request_id": "3ba596bd-28df-4fa1-8dc5-905baef8dced", "owner_token": "b2eb661f-792f-4d70-942a-5f77e3be91ca"})["run"]
        self.assertEqual(run["items"][0]["lot_snapshot"]["dossier_url"], item.dossier_url)

    def test_saved_artifact_links_remain_conditional_and_attention_label_is_not_duplicated(self):
        LiveArtResaleAnalysis.objects.create(lot=self.lot, retrieved_at=timezone.now())
        AuctionBidBoardAnalysis.objects.create(lot=self.lot)
        self.item.status = "needs_attention"
        self.item.save()
        response = self.client.get(reverse("auction_research_queue"))
        self.assertContains(response, "Open dossier ↗")
        self.assertContains(response, "Saved research ↗")
        self.assertContains(response, "Saved Bid Board ↗")
        self.assertContains(response, '<span class="research-queue-state is-needs_attention">Needs attention</span>', html=True)
        self.assertNotContains(response, '<strong class="research-queue-outcome">Needs attention</strong>', html=True)
