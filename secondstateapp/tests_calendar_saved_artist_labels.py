"""Saved Calendar screens format labels without editing source or email data."""

from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .auction_email import compose_auction_email
from .models import AuctionEmailBatch, AuctionEmailBatchItem, AuctionWatchLot
from .research_queue_models import ResearchQueueItem


class CalendarArtistLabelFilterTests(SimpleTestCase):
    def test_artist_label_still_escapes_source_markup(self):
        rendered = Template(
            '{% load calendar_filters %}{{ artist|artist_display_name }}'
        ).render(Context({"artist": '<Unknown & "Artist">'}))
        self.assertEqual(rendered, '&lt;Unknown &amp; &quot;Artist&quot;&gt;')


class CalendarSavedArtistLabelTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("artist-label-review", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = AuctionWatchLot.objects.create(
            source="Test", source_lot_id="source-artist-label", artist="After James Ensor",
            artist_watchlist_name="James Ensor", title="Study", lot_number="7",
            auction_house="Example House", event_at=datetime(2026, 11, 14, 9, tzinfo=timezone.utc),
            image_url="https://example.test/study.jpg", lot_url="https://example.test/lot/7",
            artprice_url="https://www.artprice.com/artist/123/example/lots/pasts",
        )

    def test_queue_formats_label_and_alt_without_changing_credit_or_selection(self):
        item = ResearchQueueItem.objects.create(lot=self.lot, selected=True, note="Keep this research")
        response = self.client.get(reverse("auction_research_queue"))
        self.assertContains(response, '<p class="research-queue-artist">Ensor, James</p>', html=True)
        self.assertContains(response, 'alt="Study by Ensor, James"')
        self.assertContains(response, 'href="https://example.test/lot/7"')
        self.lot.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((self.lot.artist, self.lot.artist_watchlist_name), ("After James Ensor", "James Ensor"))
        self.assertTrue(item.selected)
        self.assertEqual(item.note, "Keep this research")

    def test_tray_formats_both_labels_without_changing_outgoing_message(self):
        self.lot.artist, self.lot.artist_watchlist_name = "Joseph Beuys", ""
        self.lot.save(update_fields=["artist", "artist_watchlist_name"])
        batch = AuctionEmailBatch.objects.create()
        item = AuctionEmailBatchItem.objects.create(batch=batch, lot=self.lot, selected_by=self.staff)
        before = compose_auction_email([self.lot])
        response = self.client.get(reverse("auction_email_tray"))
        self.assertContains(response, '<p>Beuys, Joseph</p>', count=2, html=True)
        self.assertContains(response, 'href="https://example.test/lot/7"', count=2)
        self.assertContains(response, 'action="' + reverse("auction_email_lot_remove", args=[self.lot.pk]) + '"')
        self.lot.refresh_from_db()
        after = compose_auction_email([self.lot])
        self.assertEqual(self.lot.artist, "Joseph Beuys")
        self.assertEqual(before.text_body, after.text_body)
        self.assertEqual(before.html_body, after.html_body)
        self.assertIn("Joseph Beuys", after.text_body)
        self.assertTrue(AuctionEmailBatchItem.objects.filter(pk=item.pk, batch=batch, lot=self.lot).exists())
