import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .calendar_views import _group_lots, _lot_json
from .models import AuctionWatchLot
from .tests_calendar import CALENDAR_ZONE, stored_analysis, watch_lot


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class CalendarPresentationTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("presentation-admin", is_staff=True))

    def test_screenshot_examples_render_cleanly_without_rewriting_source_or_links(self):
        cases = (
            ("Victor Vasarely", "§ Victor Vasarely (1906–1997), Sir-Ris Negatif, 1974", "Vasarely, Victor"),
            ("David Hockney", "§ David Hockney OM, CH, RA (1937–2026)", "Hockney, David"),
            ("Christo", "Â§ Christo & Jeanne Claude (Bulgarian/American, 1935–2020) Wrapped Reichstag; Berlin and The wall", "Christo"),
            ("Alexander (1898) Calder", "After Alexander Calder (1898–1976)", "Calder, Alexander"),
        )
        source_rows = []
        for index, (artist, title, expected_artist) in enumerate(cases):
            lot = watch_lot(source_lot_id=f"presentation-{index}", artist=artist, artist_watchlist_name=artist, title=title)
            lot.refresh_from_db()
            source_rows.append((lot.pk, artist, title))
            artprice = "https://www.artprice.com/artist/19928/joan-miro/lots/pasts"
            invaluable = "https://www.invaluable.com/search?artistName=Christo"
            with patch("secondstateapp.calendar_views.artist_research_urls", return_value=(artprice, invaluable)) as lookup:
                displayed = _lot_json(lot, CALENDAR_ZONE)
            lookup.assert_called_once_with(artist)
            self.assertEqual(displayed["artist"], expected_artist)
            self.assertEqual(displayed["artist_source"], artist)
            self.assertEqual(displayed["title"], title.removeprefix("Â§ ").removeprefix("§ "))
            self.assertEqual(displayed["artist_artprice_url"], artprice)
            self.assertEqual(displayed["artist_invaluable_url"], invaluable)
            self.assertEqual(displayed["lot_url"], lot.lot_url)
            self.assertEqual(displayed["id"], lot.pk)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["calendar_data"]["2026-07-25"]), len(cases))
        for pk, artist, title in source_rows:
            lot = AuctionWatchLot.objects.get(pk=pk)
            self.assertEqual((lot.artist, lot.artist_watchlist_name, lot.title), (artist, artist, title))

    def test_sale_summary_uses_surname_labels_and_clean_display_text(self):
        lots = [
            watch_lot(source_lot_id="group-hockney", artist="David Hockney", artist_watchlist_name="David Hockney",
                      auction_house="Dawsonâ€™s", sale_title="Prints &amp; Multiples"),
            watch_lot(source_lot_id="group-calder", artist="Alexander (1898) Calder", artist_watchlist_name="Alexander (1898) Calder"),
        ]
        groups = _group_lots(lots, CALENDAR_ZONE)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["artists"], "Calder, Alexander; Hockney, David")
        self.assertEqual(groups[0]["auction_house"], "Dawson’s")
        self.assertEqual(groups[0]["sale_title"], "Prints & Multiples")
        self.assertEqual(groups[0]["lot_count"], 2)

    @patch.dict(os.environ, {"CATALOG_API_KEY": "presentation-test-key"}, clear=False)
    def test_later_capture_still_displays_cleanly_and_preserves_research_identity(self):
        lot = watch_lot(artist="Joan Miró", artist_watchlist_name="Joan Miró", title="Original source title",
                        artprice_url="https://www.artprice.com/artist/19928/joan-miro/lots/pasts", won_by_us=True)
        analysis = stored_analysis(lot)
        payload = {"lots": [{
            "source": lot.source, "source_lot_id": lot.source_lot_id,
            "artist": lot.artist, "artist_watchlist_name": lot.artist_watchlist_name,
            "title": "Â§ Attributed to Joan MirÃ³ — Composition",
            "medium": "Lithograph &amp; aquatint", "auction_house": lot.auction_house,
            "sale_title": lot.sale_title, "lot_number": lot.lot_number,
            "end_at": lot.event_at.isoformat(), "lot_url": lot.lot_url, "sale_url": lot.sale_url,
            "currency": "USD", "current_bid": 500, "bid_count": 2,
            "last_seen_at": "2026-10-22T06:00:00Z", "status": "changed",
        }]}
        response = self.client.post(reverse("auction_calendar_sync"), data=json.dumps(payload),
                                    content_type="application/json", HTTP_X_API_KEY="presentation-test-key")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["updated"], 1)
        lot.refresh_from_db()
        self.assertEqual(AuctionWatchLot.objects.count(), 1)
        self.assertEqual(lot.artist, "Joan Miró")
        self.assertEqual(lot.title, payload["lots"][0]["title"])
        self.assertTrue(lot.won_by_us)
        self.assertEqual(lot.artprice_url, "https://www.artprice.com/artist/19928/joan-miro/lots/pasts")
        self.assertEqual(lot.max_bid_analysis.pk, analysis.pk)
        displayed = _lot_json(lot, CALENDAR_ZONE)
        self.assertEqual(displayed["artist"], "Miró, Joan")
        self.assertEqual(displayed["title"], "Attributed to Joan Miró — Composition")
        self.assertEqual(displayed["medium"], "Lithograph & aquatint")
        self.assertTrue(displayed["artist_sort_key"].startswith("miro"))
