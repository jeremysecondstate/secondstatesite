"""A new artist can reach Calendar from a dated snapshot after HTTP 202.

All lot data is synthetic and all uploads use Django's isolated test database.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogapp.artprice_artist_links import extract_artprice_bookmarks, match_artprice_bookmarks
from catalogapp.bookmark_watchlist import parse_bookmarks_html
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_fetch import HttpPageFetcher
from catalogapp.watchlist_invaluable_pages import import_saved_invaluable_pages
from catalogapp.watchlist_service import WatchlistService
from catalogapp.watchlist_sync import sync_watchlist_lots
from secondstateapp.models import AuctionWatchLot


NOW = datetime(2026, 10, 17, 3, tzinfo=timezone.utc)
SALE = datetime(2026, 10, 22, 19, tzinfo=timezone.utc)
BOOKMARKS = '''<DL><DT><H3>ARTISTS INVALUABLE</H3><DL>
<DT><A HREF="https://www.invaluable.com/search?artistName=John%2520W%2520Nieto&amp;Fine%20Art=Prints&amp;sort=endDateAsc&amp;query=fine%2520art&amp;keyword=fine%2520art">Nieto, John: Invaluable — Prints</A>
</DL><DT><H3>ARTPRICE</H3><DL>
<DT><A HREF="https://www.artprice.com/artist/190556/john-nieto/lots/pasts?idcategory=2">Nieto, John: Artprice</A>
</DL></DL>'''


class NewArtistCalendarRecoveryTests(TestCase):
    @patch.dict(os.environ, {"CATALOG_API_KEY": "recovery-test-key"})
    def test_blocked_new_artist_snapshot_reaches_calendar_without_duplicates(self):
        entries = parse_bookmarks_html(BOOKMARKS, selected_folders=["ARTISTS INVALUABLE"])
        self.assertEqual([entry.artist for entry in entries], ["John W Nieto"])
        entry = entries[0]
        links = match_artprice_bookmarks(extract_artprice_bookmarks(BOOKMARKS), [entry.artist]).links_by_artist
        self.assertIn(entry.artist, links)
        response = Mock(status_code=202, text="<html><title>Access denied</title></html>",
                        headers={"Content-Type": "text/html"}, url="https://www.invaluable.com/catResults")
        session = Mock(post=Mock(return_value=response))
        fetcher = HttpPageFetcher(session=session, min_interval_seconds=0)

        def upload(_url, *, headers, json, **_kwargs):
            return self.client.post(reverse("auction_calendar_sync"), data=json,
                                    content_type="application/json", HTTP_X_API_KEY=headers["X-API-KEY"])

        with TemporaryDirectory() as directory, WatchlistCache(":memory:") as cache:
            service = WatchlistService(cache, fetcher=fetcher, now=lambda: NOW)
            for _ in range(2):
                failed = service.refresh(entries, selected_artists=[entry.artist], horizon_days=30)
                self.assertEqual(failed.lots, [])
                self.assertIn("John W Nieto", " ".join(failed.errors))
                self.assertIn("HTTP 202", " ".join(failed.errors))
            # A recorded source error never prevents the next live attempt.
            self.assertEqual(session.post.call_count, 2)
            snapshot = Path(directory) / "nieto-test-snapshot.json"
            snapshot.write_text(json.dumps({
                "source_url": entry.url, "captured_at": NOW.isoformat(),
                "results": [{"page": 0, "nbPages": 1, "nbHits": 1, "hits": [{
                    "objectID": "synthetic-nieto-101", "lotRef": "syntheticnieto101",
                    "lotNumber": "101", "lotTitle": "Synthetic recovery print",
                    "artistName": entry.artist, "houseName": "Test Auction House",
                    "supercategoryName": "Fine Art", "subcategoryName": "Prints",
                    "dateTimeUTCUnix": SALE.timestamp(), "currencyCode": "USD",
                    "estimateLow": 200, "estimateHigh": 400, "currentBid": 100,
                }]}],
            }), encoding="utf-8")
            recovered = import_saved_invaluable_pages([snapshot], entries, cache, now=NOW)
            self.assertEqual(recovered.errors, [])
            self.assertEqual(len(recovered.lots), 1)
            self.assertEqual(recovered.fallback_lot_keys, set())
            first = sync_watchlist_lots(recovered.lots, base_url="https://testserver",
                                        api_key="recovery-test-key", artist_artprice_links=links,
                                        session=SimpleNamespace(post=upload))
            self.assertEqual((first.received, first.created), (1, 1))
            again = sync_watchlist_lots(recovered.lots, base_url="https://testserver",
                                        api_key="recovery-test-key", artist_artprice_links=links,
                                        session=SimpleNamespace(post=upload))
            self.assertEqual((again.created, again.updated), (0, 1))
            lot = AuctionWatchLot.objects.get()
            self.assertEqual(lot.artist, entry.artist)
            self.assertEqual(lot.event_at, SALE)
            self.assertEqual(lot.watchlist_artist.artprice_url, links[entry.artist])
            self.assertTrue(lot.active)
            # Snapshot recovery does not claim that live access is restored.
            self.assertIn("HTTP 202", cache.connection.execute("SELECT last_error FROM source_runs").fetchone()[0])

        staff = get_user_model().objects.create_user(username="recovery-staff", is_staff=True)
        self.client.force_login(staff)
        calendar = self.client.get(reverse("auction_calendar"), {"month": "2026-10", "day": "2026-10-22"})
        self.assertContains(calendar, "John W Nieto")
        self.assertContains(calendar, "Synthetic recovery print")
