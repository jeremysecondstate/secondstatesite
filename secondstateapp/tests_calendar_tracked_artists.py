from datetime import datetime, timezone
from unittest.mock import patch
from bs4 import BeautifulSoup

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from catalogapp.artprice_artist_links import artist_identity_key
from .models import AuctionWatchArtist, AuctionWatchLot


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class CalendarTrackedArtistsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user("tracked-reviewer", is_staff=True)
        cls.day = "2026-12-03"
        cls.visible, cls.other = set(), set()
        for artist, label, tracked in [
            ("After Picasso, Pablo", "", True),
            ("(after) PICASSO, Pablo", "", True),
            ("Georges Test and Sonia Delaunay", "", True),
            ("D’après plusieurs artistes, de Dürer à Dufy", "Albrecht Dürer", True),
            ("Jean-Baptiste Piranèse", "", True),
            ("Joseph Beuys (German, 1921-1986)", "", True),
            ("After Henri Matisse (French 1869–1954)", "", True),
            ("Arman Vahanyan (American, 1930-2000)", "Arman", False),
            ("Joseph Beuys (exhibition catalogue, 1970)", "", False),
            ("Arman Vahanyan", "Arman", False),
            ("Vahanyan, Arman", "", False),
            ("Arman Vahanyan", "Arman Vahanyan", False),
            ("Inspired by Edgar Degas and Sonia Delaunay", "Edgar Degas", False),
            ("Style of Keith Haring", "Keith Haring", False),
            ("", "", False),
        ]:
            number = str(len(cls.visible) + len(cls.other) + 1)
            registry = None
            if label:
                registry, _ = AuctionWatchArtist.objects.get_or_create(
                    normalized_name=artist_identity_key(label), defaults={"name": label},
                )
            lot = AuctionWatchLot.objects.create(
                source="Invaluable", source_lot_id=number, artist=artist, artist_watchlist_name=label,
                watchlist_artist=registry, title="Study " + number, lot_number=number,
                auction_house="Example" if tracked else "Untracked House",
                event_at=datetime(2026, 12, 3, 18, tzinfo=timezone.utc),
            )
            (cls.visible if tracked else cls.other).add(lot.pk)

    def setUp(self):
        self.client.force_login(self.staff)

    @patch("secondstateapp.calendar_views.timezone.now", return_value=datetime(2026, 12, 1, tzinfo=timezone.utc))
    def test_default_and_all_saved_use_same_scope_across_views(self, _now):
        for scope, expected in [({}, self.visible), ({"artists": "all"}, self.visible | self.other)]:
            with self.subTest(scope=scope):
                params = {"day": self.day, **scope}
                month = self.client.get(reverse("auction_calendar"), {**params, "view": "catalog"})
                self.assertEqual(month.context["synced_lot_count"], len(expected))
                self.assertEqual(month.context["calendar_day_counts"][self.day]["lots"], len(expected))
                self.assertEqual(sum(sale["lot_count"] for sale in month.context["upcoming_groups"]), len(expected))
                inline = month.context["calendar_data"][self.day]
                self.assertEqual({row["id"] for row in inline}, expected)
                for endpoint in ("auction_calendar_day_lots", "auction_calendar_usd_prices"):
                    response = self.client.get(reverse(endpoint), params)
                    self.assertEqual({row["id"] for row in response.json()["lots"]}, expected)
                self.assertContains(month, "Show tracked artists" if scope else "Show all saved lots")
        self.assertEqual(AuctionWatchLot.objects.count(), len(self.visible | self.other))

    def test_saved_research_link_to_an_untracked_lot_opens_its_dossier(self):
        lot_id = min(self.other)
        page = self.client.get(reverse("auction_calendar"), {
            "day": self.day, "view": "research", "lot": lot_id, "look": "dossier",
        }, follow=True)
        self.assertTrue(page.context["all_saved_artists"])
        self.assertEqual(page.wsgi_request.GET["lot"], str(lot_id))
        self.assertIn(lot_id, [row["id"] for row in page.context["calendar_data"][self.day]])
        scope_link = BeautifulSoup(page.content, "html.parser").select_one("#calendar-artist-scope")["href"]
        tracked = self.client.get(reverse("auction_calendar") + scope_link)
        self.assertEqual(tracked.status_code, 200)
        self.assertFalse(tracked.context["all_saved_artists"])
        self.assertEqual(tracked.wsgi_request.GET["view"], "catalog")
        self.assertNotIn(lot_id, [row["id"] for row in tracked.context["calendar_data"][self.day]])
