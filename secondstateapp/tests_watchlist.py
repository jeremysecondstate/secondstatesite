import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import NoReverseMatch, reverse

from catalogapp.artprice_artist_links import (
    artist_identity_key,
    extract_artprice_bookmarks,
    parse_artprice_artist_links,
)
from catalogapp.bookmark_watchlist import (
    BookmarkEntry,
    artist_source_counts,
    canonicalize_bookmark_url,
    load_bookmarks_file,
    parse_bookmarks_html,
    repeatedly_decode,
)
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_enrichment import OpenAIEnricher
from catalogapp.watchlist_exports import render_csv, render_ics, render_markdown
from catalogapp.watchlist_fetch import HttpPageFetcher, SourceAccessError
from catalogapp.watchlist_models import NormalizedLot, mark_cross_source_duplicates
from catalogapp.watchlist_service import WatchlistService


FIXTURES = Path(__file__).parent / "test_fixtures" / "watchlist"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def sample_lot(**overrides):
    payload = {
        "source": "Invaluable",
        "source_lot_id": "inv-24",
        "artist": "Rufino Tamayo",
        "artist_watchlist_name": "Rufino Tamayo",
        "title": "Mixografía",
        "medium": "Color mixografía on paper",
        "auction_house": "House A",
        "sale_title": "Modern Prints",
        "lot_number": "24",
        "end_at": "2026-07-18T17:00:00-04:00",
        "estimate_low": 2000,
        "estimate_high": 3000,
        "currency": "USD",
        "lot_url": "https://www.invaluable.com/auction-lot/tamayo-mixografia-24",
        "sale_url": "https://www.invaluable.com/catalog/modern-prints",
    }
    payload.update(overrides)
    return NormalizedLot(**payload)


class BookmarkParserTests(SimpleTestCase):
    def test_selected_folder_allowed_domains_icon_ignored_and_deduplicated(self):
        entries = load_bookmarks_file(FIXTURES / "bookmarks.html", selected_folders=["ARTISTS INVALUABLE"])

        self.assertEqual(len(entries), 2)
        self.assertEqual({entry.artist for entry in entries}, {"Rufino Tamayo", "Thomas Hart Benton"})
        self.assertTrue(all(entry.source == "Invaluable" for entry in entries))
        self.assertNotIn("PRIVATE-ICON-DATA", repr(entries))
        self.assertNotIn("drive.google.com", repr(entries))

    def test_repeated_url_decoding_and_nested_artist_query(self):
        self.assertEqual(repeatedly_decode("Rufino%252520Tamayo"), "Rufino Tamayo")
        entries = load_bookmarks_file(FIXTURES / "bookmarks.html")
        self.assertIn("Joan Miró", {entry.artist for entry in entries})

    def test_folder_and_domain_filters_reject_private_urls(self):
        entries = load_bookmarks_file(FIXTURES / "bookmarks.html", selected_folders=["PRIVATE"])
        self.assertEqual(entries, [])

        html = '<DL><DT><H3>ARTISTS INVALUABLE</H3><DL><DT><A HREF="javascript:alert(1)">Bad</A></DL></DL>'
        self.assertEqual(parse_bookmarks_html(html), [])

    def test_canonical_url_deduplication_removes_tracking_and_sorts_query(self):
        first = canonicalize_bookmark_url(
            "HTTPS://WWW.INVALUABLE.COM/search/?utm_source=x&sort=end&keyword=Rufino%20Tamayo#results"
        )
        second = canonicalize_bookmark_url(
            "https://www.invaluable.com/search?keyword=Rufino%20Tamayo&sort=end"
        )
        self.assertEqual(first, second)

    def test_artist_preview_reports_source_counts(self):
        counts = artist_source_counts(load_bookmarks_file(FIXTURES / "bookmarks.html"))
        self.assertEqual(counts["Rufino Tamayo"], {"Invaluable": 1})
        self.assertEqual(counts["Joan Miró"], {"LiveAuctioneers": 1})


class ArtpriceArtistLinkParserTests(SimpleTestCase):
    @staticmethod
    def bookmarks(*folders):
        body = "".join(
            f"<DT><H3>{name}</H3><DL><p>{links}</DL><p>"
            for name, links in folders
        )
        return f"<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><p>{body}</DL><p>"

    @staticmethod
    def link(title, url, **attributes):
        extras = " ".join(f'{key}="{value}"' for key, value in attributes.items())
        return f'<DT><A HREF="{url}" {extras}>{title}</A>'

    def test_extracts_only_valid_artist_urls_from_artprice_folder(self):
        complete_url = "https://www.artprice.com/artist/28011/antoni-tapies/lots/pasts?idcategory[]=2&amp;p=1"
        root_domain_url = "http://artprice.com/artist/17457/sol-lewitt?sort=datesale_desc"
        html = self.bookmarks(
            ("OTHER", self.link("Wrong folder", complete_url)),
            (
                "ARTPRICE",
                self.link("Antoni Tàpies", complete_url, ICON="ignored", ADD_DATE="123")
                + self.link("Sol LEWITT", root_domain_url)
                + self.link("Wrong host", "https://artprice.com.evil.example/artist/1/name")
                + self.link("Not an artist", "https://www.artprice.com/search?q=Antoni"),
            ),
        )

        bookmarks = extract_artprice_bookmarks(html)

        self.assertEqual(
            {bookmark.url for bookmark in bookmarks},
            {
                "https://www.artprice.com/artist/28011/antoni-tapies/lots/pasts?idcategory[]=2&p=1",
                root_domain_url,
            },
        )
        self.assertNotIn("ignored", repr(bookmarks))
        self.assertNotIn("123", repr(bookmarks))

    def test_matches_accents_punctuation_casing_and_surname_first_names(self):
        html = self.bookmarks(
            (
                "ARTPRICE",
                self.link(
                    "TAPIES: sold lots by Antoni TAPIES - Artprice.com",
                    "https://www.artprice.com/artist/28011/antoni-tapies/lots/pasts?idcategory=2",
                )
                + self.link(
                    "TING Walasse: sold lots by TING Walasse - Artprice.com",
                    "https://www.artprice.com/artist/28448/walasse-ting/lots/pasts?idcategory[]=2",
                )
                + self.link(
                    "John SLOAN: sold lots by John SLOAN - Artprice.com",
                    "https://www.artprice.com/artist/26833/john-sloan/lots/pasts",
                )
                + self.link(
                    "Sol LEWITT (1928-2007) Estimate, Auction prices, Value – Artprice",
                    "https://www.artprice.com/artist/17457/sol-lewitt",
                )
                + self.link(
                    "LEWIS - Artprice.com",
                    "https://www.artprice.com/artist/42672/martin-lewis/lots/pasts?idcategory=2",
                ),
            ),
        )

        result = parse_artprice_artist_links(
            html,
            [
                "Antoni Tàpies",
                "TAPIES, ANTONI",
                "Walasse Ting",
                "SLOAN, JOHN",
                "LEWITT, SOL",
                "LEWIS, MARTIN",
            ],
        )

        self.assertEqual(artist_identity_key("Antoni Tàpies"), artist_identity_key("TAPIES, ANTONI"))
        self.assertIn("/28011/antoni-tapies/", result.links_by_artist["Antoni Tàpies"])
        self.assertEqual(result.links_by_artist["Antoni Tàpies"], result.links_by_artist["TAPIES, ANTONI"])
        self.assertIn("/28448/walasse-ting/", result.links_by_artist["Walasse Ting"])
        self.assertIn("/26833/john-sloan/", result.links_by_artist["SLOAN, JOHN"])
        self.assertIn("/17457/sol-lewitt", result.links_by_artist["LEWITT, SOL"])
        self.assertIn("/42672/martin-lewis/", result.links_by_artist["LEWIS, MARTIN"])

    def test_duplicate_bookmarks_choose_one_complete_url_deterministically(self):
        shorter = "https://www.artprice.com/artist/711/karel-appel/lots/pasts?idcategory[]=2"
        preferred = "https://www.artprice.com/artist/711/karel-appel/lots/pasts?idcategory=2&amp;p=1&amp;sort=datesale_desc"
        html = self.bookmarks(
            (
                "ARTPRICE",
                self.link("Karel APPEL: sold lots by Karel APPEL - Artprice.com", shorter)
                + self.link("Karel APPEL: sold lots by Karel APPEL - Artprice.com", preferred)
                + self.link("Karel APPEL duplicate", preferred),
            ),
        )

        first = parse_artprice_artist_links(html, ["APPEL, KAREL"])
        second = parse_artprice_artist_links(html, ["APPEL, KAREL"])

        self.assertEqual(first.links_by_artist, second.links_by_artist)
        self.assertEqual(
            first.links_by_artist,
            {"APPEL, KAREL": preferred.replace("&amp;", "&")},
        )

    def test_ambiguous_and_unmatched_bookmarks_are_not_attached(self):
        html = self.bookmarks(
            (
                "ARTPRICE",
                self.link("SMITH - Artprice.com", "https://www.artprice.com/artist/1/smith")
                + self.link("Unknown Artist", "https://www.artprice.com/artist/2/unknown-artist"),
            ),
        )

        result = parse_artprice_artist_links(html, ["John Smith", "Jane Smith", "Antoni Tàpies"])

        self.assertEqual(result.links_by_artist, {})
        self.assertIn("SMITH - Artprice.com", result.ambiguous_titles)
        self.assertIn("Unknown Artist", result.unmatched_titles)


class InvaluableAdapterTests(SimpleTestCase):
    def setUp(self):
        self.adapter = InvaluableAdapter()
        self.url = "https://www.invaluable.com/search?keyword=Rufino+Tamayo"

    def test_parses_dom_cards_and_embedded_json(self):
        page = fixture("invaluable_search.html")
        lots = self.adapter.parse_search_page(page, self.url, "Rufino Tamayo")

        self.assertEqual({lot.source_lot_id for lot in lots}, {"inv-24", "inv-81"})
        card = next(lot for lot in lots if lot.source_lot_id == "inv-24")
        self.assertEqual(card.estimate_low, 2000)
        self.assertEqual(card.current_bid, 1500)
        self.assertEqual(card.bid_count, 4)
        self.assertEqual(card.bid_label, "1,500 USD (4 bids)")
        self.assertEqual(card.end_at, "2026-07-18T17:00:00-04:00")
        self.assertEqual(card.sale_url, "https://www.invaluable.com/catalog/modern-prints")
        self.assertIn("https://www.invaluable.com/auction-lot/", self.adapter.extract_lot_links(page, self.url)[0])

    def test_detail_normalization_fills_missing_fields(self):
        detail = self.adapter.parse_lot_detail(
            fixture("invaluable_detail.html"),
            "https://www.invaluable.com/auction-lot/tamayo-lithograph-81",
            "Rufino Tamayo",
        )
        self.assertIsNotNone(detail)
        self.assertEqual(detail.medium, "Lithograph on wove paper")
        self.assertEqual(detail.auction_house, "House A")
        self.assertFalse(self.adapter.needs_detail(detail))

    def test_parses_zero_bids_from_combined_detail_text(self):
        detail = self.adapter.parse_lot_detail(
            """
            <html><body>
              <h1>Andy Warhol, Kiss. 1966.</h1>
              <div class="current-bid">$3,800 USD 0 bids</div>
            </body></html>
            """,
            "https://www.invaluable.com/auction-lot/andy-warhol-kiss-1966-237",
            "Andy Warhol",
        )

        self.assertIsNotNone(detail)
        self.assertEqual(detail.current_bid, 3800)
        self.assertEqual(detail.bid_count, 0)
        self.assertEqual(detail.bid_label, "No bids")

    def test_extracts_pagination(self):
        next_url = self.adapter.extract_next_page_url(fixture("invaluable_page_1.html"), self.url)
        self.assertEqual(next_url, "https://www.invaluable.com/search?keyword=Rufino+Tamayo&page=2")
        self.assertEqual(self.adapter.extract_next_page_url(fixture("invaluable_page_2.html"), next_url), "")

    def test_uses_public_catalog_feed_and_normalizes_results(self):
        search_url = (
            "https://www.invaluable.com/search?artistName=Rufino+Tamayo&"
            "Fine+Art=Prints&keyword=fine+art&query=fine+art&sort=endDateAsc"
        )
        response = {
            "results": [
                {
                    "page": 0,
                    "nbPages": 2,
                    "nbHits": 1,
                    "hits": [
                        {
                            "objectID": "205299494",
                            "lotRef": "FD04340A1D",
                            "lotNumber": "47",
                            "lotTitle": "Rufino Tamayo; Galaxia (Galaxy)",
                            "artistName": "Rufino Tamayo",
                            "lotDescription": "Mixografia in colors on wove paper",
                            "houseName": "Bonhams",
                            "catalogRef": "8NR19L2CW9",
                            "dateTimeUTCUnix": 1785355200,
                            "endTimeUTCUnix": 0,
                            "estimateLow": 10000,
                            "estimateHigh": 15000,
                            "currentBid": 10000,
                            "bidCount": 0,
                            "currencyCode": "USD",
                            "photoPath": "Bonhams/19/812345/H1234-Lprimary.jpg",
                        }
                    ],
                }
            ]
        }

        class CatalogFetcher:
            def __init__(self):
                self.calls = []

            def post_json(self, url, payload, *, referer=""):
                self.calls.append((url, payload, referer))
                return response

        fetcher = CatalogFetcher()
        page = self.adapter.fetch_search_page(search_url, fetcher)
        lots = self.adapter.parse_search_page(page, search_url, "Rufino Tamayo")

        self.assertEqual(fetcher.calls[0][0], "https://www.invaluable.com/catResults")
        self.assertEqual(fetcher.calls[0][2], search_url)
        request = fetcher.calls[0][1]["requests"][0]
        self.assertEqual(request["indexName"], "upcoming_lots_dateTimeUTCUnix_asc_prod")
        self.assertEqual(
            request["params"]["facetFilters"],
            [["artistName:Rufino Tamayo"], ["Fine Art:Prints"]],
        )
        self.assertNotIn("userToken", request["params"])
        self.assertEqual(len(lots), 1)
        lot = lots[0]
        self.assertEqual(lot.source_lot_id, "205299494")
        self.assertEqual(lot.medium, "Mixografia")
        self.assertEqual(lot.auction_house, "Bonhams")
        self.assertEqual(lot.estimate_high, 15000)
        self.assertEqual(lot.bid_count, 0)
        self.assertEqual(lot.bid_label, "No bids")
        self.assertEqual(lot.end_at, "2026-07-29T20:00:00+00:00")
        self.assertEqual(lot.sale_url, "https://www.invaluable.com/catalog/8NR19L2CW9")
        self.assertEqual(
            lot.image_url,
            "https://image.invaluable.com/housePhotos/Bonhams/19/812345/H1234-Lprimary.jpg",
        )
        self.assertEqual(
            lot.lot_url,
            "https://www.invaluable.com/auction-lot/rufino-tamayo-galaxia-galaxy-47-c-fd04340a1d",
        )
        self.assertFalse(self.adapter.needs_detail(lot))
        self.assertEqual(
            self.adapter.extract_next_page_url(page, search_url),
            "https://www.invaluable.com/search?artistName=Rufino+Tamayo&Fine+Art=Prints&keyword=fine+art&page=2&query=fine+art&sort=endDateAsc",
        )

    def test_batches_compatible_artist_searches_and_splits_paginated_hits(self):
        tamayo_url = (
            "https://www.invaluable.com/search?artistName=Rufino+Tamayo&"
            "Fine+Art=Prints&keyword=fine+art&query=fine+art&sort=endDateAsc"
        )
        haring_url = (
            "https://www.invaluable.com/search?artistName=Keith+Haring&"
            "Fine+Art=Prints&keyword=fine+art&query=fine+art&sort=priceDesc"
        )

        def hit(object_id, lot_ref, artist, lot_number):
            return {
                "objectID": object_id,
                "lotRef": lot_ref,
                "lotNumber": lot_number,
                "lotTitle": f"{artist} screenprint",
                "artistName": artist,
                "lotDescription": "Color screenprint on paper",
                "houseName": "House A",
                "dateTimeUTCUnix": 1785355200,
                "currencyCode": "USD",
            }

        class BatchFetcher:
            def __init__(self):
                self.calls = []
                self.pages_fetched = 0
                self.responses = [
                    {
                        "results": [
                            {
                                "page": 0,
                                "nbPages": 2,
                                "nbHits": 3,
                                "hits": [
                                    hit("tamayo-1", "TAMAYO1", "Rufino Tamayo", "1"),
                                    hit("haring-1", "HARING1", "Keith Haring", "2"),
                                ],
                            }
                        ]
                    },
                    {
                        "results": [
                            {
                                "page": 1,
                                "nbPages": 2,
                                "nbHits": 3,
                                "hits": [hit("haring-2", "HARING2", "Keith Haring", "3")],
                            }
                        ]
                    },
                ]

            def post_json(self, url, payload, *, referer=""):
                self.calls.append((url, payload, referer))
                self.pages_fetched += 1
                return self.responses.pop(0)

        fetcher = BatchFetcher()
        pages = self.adapter.fetch_search_batch(
            [(tamayo_url, "Rufino Tamayo"), (haring_url, "Keith Haring")],
            fetcher,
            max_pages=10,
        )

        self.assertEqual(len(fetcher.calls), 2)
        first_request = fetcher.calls[0][1]["requests"][0]
        self.assertEqual(first_request["indexName"], "upcoming_lots_dateTimeUTCUnix_asc_prod")
        self.assertEqual(
            first_request["params"]["facetFilters"][0],
            ["artistName:Rufino Tamayo", "artistName:Keith Haring"],
        )
        self.assertEqual(fetcher.calls[1][1]["requests"][0]["params"]["page"], 1)
        tamayo_lots = self.adapter.parse_search_page(pages[tamayo_url].page, tamayo_url, "Rufino Tamayo")
        haring_lots = self.adapter.parse_search_page(pages[haring_url].page, haring_url, "Keith Haring")
        self.assertEqual([lot.source_lot_id for lot in tamayo_lots], ["tamayo-1"])
        self.assertEqual({lot.source_lot_id for lot in haring_lots}, {"haring-1", "haring-2"})
        self.assertTrue(pages[tamayo_url].complete)
        self.assertTrue(pages[haring_url].complete)


class _Response:
    def __init__(self, status_code, text="", payload=None, headers=None, url=""):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.headers = headers or {"Content-Type": "text/html"}
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _HttpSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class FetcherTests(SimpleTestCase):
    def test_retries_transient_error_and_rate_limit_is_injected(self):
        sleeps = []
        session = _HttpSession([_Response(500), _Response(200, "<html>ok</html>")])
        fetcher = HttpPageFetcher(
            session=session,
            min_interval_seconds=0,
            max_retries=1,
            sleeper=sleeps.append,
        )

        page = fetcher.fetch("https://www.invaluable.com/search?q=test")

        self.assertEqual(page, "<html>ok</html>")
        self.assertEqual(fetcher.pages_fetched, 1)
        self.assertEqual(fetcher.http_attempts, 2)
        self.assertEqual(sleeps, [1.0])

    def test_rejects_redirect_outside_the_domain_allowlist(self):
        session = _HttpSession([_Response(200, "private", url="http://127.0.0.1/private")])
        fetcher = HttpPageFetcher(session=session, min_interval_seconds=0, max_retries=0)
        with self.assertRaises(SourceAccessError):
            fetcher.fetch("https://www.invaluable.com/search?q=test")

    def test_posts_json_with_the_same_allowlist_and_response_validation(self):
        payload = {"results": [{"hits": []}]}
        session = _HttpSession(
            [_Response(200, payload=payload, headers={"Content-Type": "application/json"})]
        )
        fetcher = HttpPageFetcher(session=session, min_interval_seconds=0, max_retries=0)

        result = fetcher.post_json(
            "https://www.invaluable.com/catResults",
            {"requests": []},
            referer="https://www.invaluable.com/search?q=test",
        )

        self.assertEqual(result, payload)
        self.assertEqual(fetcher.pages_fetched, 1)
        self.assertEqual(session.calls[0][1]["json"], {"requests": []})
        self.assertEqual(
            session.calls[0][1]["headers"]["Referer"],
            "https://www.invaluable.com/search?q=test",
        )


class CacheAndServiceTests(SimpleTestCase):
    def test_cache_new_changed_unchanged_and_ended_transitions(self):
        with WatchlistCache(":memory:") as cache:
            watch_url = "https://www.invaluable.com/search?q=tamayo"
            first = sample_lot()
            self.assertEqual(cache.upsert(first, watch_url=watch_url, search_hash="card-a"), "new")

            same = sample_lot()
            self.assertEqual(cache.upsert(same, watch_url=watch_url, search_hash="card-a"), "unchanged")
            self.assertIsNotNone(cache.lookup(same))

            changed = sample_lot(current_bid=1750)
            self.assertEqual(cache.upsert(changed, watch_url=watch_url, search_hash="card-b"), "changed")
            ended = cache.mark_missing_ended(watch_url, [])
            self.assertEqual([lot.status for lot in ended], ["ended"])

    def test_incremental_refresh_skips_unchanged_details_and_marks_removed_lot_ended(self):
        search_url = "https://www.invaluable.com/search?keyword=Rufino+Tamayo"
        detail_url = "https://www.invaluable.com/auction-lot/tamayo-lithograph-81"
        entry = BookmarkEntry(
            ("ARTISTS INVALUABLE",),
            "Rufino Tamayo",
            search_url,
            artist="Rufino Tamayo",
            source="Invaluable",
        )

        class Fetcher:
            def __init__(self, search_page):
                self.search_page = search_page
                self.pages_fetched = 0
                self.urls = []

            def fetch(self, url):
                self.pages_fetched += 1
                self.urls.append(url)
                if url == search_url:
                    return self.search_page
                if url == detail_url:
                    return fixture("invaluable_detail.html")
                raise AssertionError(f"Unexpected URL: {url}")

        fixed_now = lambda: datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
        with WatchlistCache(":memory:") as cache:
            first_fetcher = Fetcher(fixture("invaluable_search.html"))
            first = WatchlistService(cache, fetcher=first_fetcher, now=fixed_now).refresh(
                [entry], selected_artists=["Rufino Tamayo"], zero_ai=True
            )
            self.assertEqual(first.metrics.new_lots, 2)
            self.assertEqual(first.metrics.pages_fetched, 2)
            self.assertIn(detail_url, first_fetcher.urls)

            second_fetcher = Fetcher(fixture("invaluable_search.html"))
            second = WatchlistService(cache, fetcher=second_fetcher, now=fixed_now).refresh(
                [entry], selected_artists=["Rufino Tamayo"], zero_ai=True
            )
            self.assertEqual(second.metrics.pages_fetched, 1)
            self.assertEqual(second.metrics.cache_hits, 2)
            self.assertNotIn(detail_url, second_fetcher.urls)

            changed_fetcher = Fetcher(fixture("invaluable_search_changed.html"))
            changed = WatchlistService(cache, fetcher=changed_fetcher, now=fixed_now).refresh(
                [entry], selected_artists=["Rufino Tamayo"], zero_ai=True
            )
            self.assertEqual(changed.metrics.changed_lots, 1)

            one_lot_page = fixture("invaluable_search_changed.html").split('<script id="__NEXT_DATA__"')[0] + "</body></html>"
            ended_fetcher = Fetcher(one_lot_page)
            ended = WatchlistService(cache, fetcher=ended_fetcher, now=fixed_now).refresh(
                [entry], selected_artists=["Rufino Tamayo"], zero_ai=True, new_changed_only=True
            )
            self.assertEqual(ended.metrics.ended_lots, 1)
            self.assertIn("ended", {lot.status for lot in ended.lots})

    def test_service_follows_bounded_pagination(self):
        first_url = "https://www.invaluable.com/search?keyword=Rufino+Tamayo"
        second_url = "https://www.invaluable.com/search?keyword=Rufino+Tamayo&page=2"
        entry = BookmarkEntry(("ARTISTS INVALUABLE",), "Rufino Tamayo", first_url, artist="Rufino Tamayo", source="Invaluable")

        class Fetcher:
            pages_fetched = 0

            def fetch(self, url):
                self.pages_fetched += 1
                return fixture("invaluable_page_1.html" if url == first_url else "invaluable_page_2.html")

        with WatchlistCache(":memory:") as cache:
            result = WatchlistService(
                cache,
                fetcher=Fetcher(),
                now=lambda: datetime(2026, 7, 13, tzinfo=timezone.utc),
            ).refresh([entry], selected_artists=["Rufino Tamayo"])
        self.assertEqual(result.metrics.pages_fetched, 2)
        self.assertEqual(len(result.lots), 2)

    def test_service_uses_one_batched_request_for_multiple_artists(self):
        tamayo_url = "https://www.invaluable.com/search?artistName=Rufino+Tamayo&query=fine+art"
        haring_url = "https://www.invaluable.com/search?artistName=Keith+Haring&query=fine+art"
        entries = [
            BookmarkEntry(
                ("ARTISTS INVALUABLE",),
                artist,
                url,
                artist=artist,
                source="Invaluable",
            )
            for artist, url in (("Rufino Tamayo", tamayo_url), ("Keith Haring", haring_url))
        ]

        class BatchFetcher:
            pages_fetched = 0

            def __init__(self):
                self.calls = []

            def post_json(self, url, payload, *, referer=""):
                self.calls.append((url, payload, referer))
                self.pages_fetched += 1
                hits = []
                for object_id, lot_ref, artist in (
                    ("tamayo-1", "TAMAYO1", "Rufino Tamayo"),
                    ("haring-1", "HARING1", "Keith Haring"),
                ):
                    hits.append(
                        {
                            "objectID": object_id,
                            "lotRef": lot_ref,
                            "lotNumber": "1",
                            "lotTitle": f"{artist} screenprint",
                            "artistName": artist,
                            "lotDescription": "Color screenprint on paper",
                            "houseName": "House A",
                            "dateTimeUTCUnix": 1785355200,
                            "currencyCode": "USD",
                        }
                    )
                return {"results": [{"page": 0, "nbPages": 1, "nbHits": 2, "hits": hits}]}

        fetcher = BatchFetcher()
        with WatchlistCache(":memory:") as cache:
            result = WatchlistService(
                cache,
                fetcher=fetcher,
                now=lambda: datetime(2026, 7, 26, tzinfo=timezone.utc),
            ).refresh(entries, selected_artists=["Rufino Tamayo", "Keith Haring"])

        self.assertEqual(len(fetcher.calls), 1)
        self.assertEqual(result.metrics.pages_fetched, 1)
        self.assertEqual({lot.artist_watchlist_name for lot in result.lots}, {"Rufino Tamayo", "Keith Haring"})
        self.assertEqual(result.errors, [])

    def test_source_failure_keeps_last_known_active_lots(self):
        tamayo_url = "https://www.invaluable.com/search?artistName=Rufino+Tamayo&query=fine+art"
        haring_url = "https://www.invaluable.com/search?artistName=Keith+Haring&query=fine+art"
        entries = [
            BookmarkEntry(
                ("ARTISTS INVALUABLE",),
                artist,
                url,
                artist=artist,
                source="Invaluable",
            )
            for artist, url in (("Rufino Tamayo", tamayo_url), ("Keith Haring", haring_url))
        ]

        class BlockedFetcher:
            pages_fetched = 0

            def post_json(self, _url, _payload, *, referer=""):
                raise SourceAccessError("www.invaluable.com returned a temporary HTTP 403.")

        with WatchlistCache(":memory:") as cache:
            cache.upsert(sample_lot(), watch_url=tamayo_url, search_hash="cached")
            result = WatchlistService(
                cache,
                fetcher=BlockedFetcher(),
                now=lambda: datetime(2026, 7, 13, tzinfo=timezone.utc),
            ).refresh(entries, selected_artists=["Rufino Tamayo", "Keith Haring"])

        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].source_lot_id, "inv-24")
        self.assertEqual(result.metrics.cache_hits, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("2 artists", result.errors[0])
        self.assertIn("Showing 1 cached lots", result.errors[0])


class ExportTests(SimpleTestCase):
    def test_bid_labels_distinguish_current_no_bids_and_unavailable(self):
        current = sample_lot(current_bid=1700, bid_count=4)
        no_bids = sample_lot(current_bid=3800, bid_count=0)
        unavailable = sample_lot(current_bid=None, bid_count=None)

        self.assertEqual(current.bid_label, "1,700 USD (4 bids)")
        self.assertEqual(no_bids.bid_label, "No bids")
        self.assertEqual(unavailable.bid_label, "N/A")

    def test_markdown_csv_and_sale_grouped_ics(self):
        first = sample_lot(current_bid=1700, bid_count=4)
        second = sample_lot(source_lot_id="inv-81", lot_number="81", title="Lithograph", lot_url="https://www.invaluable.com/auction-lot/81")

        markdown = render_markdown([second, first])
        csv_text = render_csv([first, second])
        ics = render_ics([first, second], generated_at=datetime(2026, 7, 13, tzinfo=timezone.utc))

        self.assertIn("## 2026-07-18", markdown)
        self.assertIn("### Rufino Tamayo", markdown)
        self.assertEqual(csv_text.count("\n"), 3)
        self.assertIn("current_bid,bid_count,status", csv_text)
        self.assertIn("1700,4,unchanged", csv_text)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 1)
        self.assertIn("SUMMARY:Invaluable — 2 watched print lots", ics)
        self.assertTrue(ics.endswith("END:VCALENDAR\r\n"))
        self.assertNotIn("\n", ics.replace("\r\n", ""))

    def test_date_only_becomes_all_day_with_unverified_label(self):
        lot = sample_lot(end_at="2026-07-18")
        ics = render_ics([lot], generated_at=datetime(2026, 7, 13, tzinfo=timezone.utc))
        self.assertIn("DTSTART;VALUE=DATE:20260718", ics)
        self.assertIn("time is unverified", ics)

    def test_cross_source_duplicates_are_marked_not_hidden(self):
        first = sample_lot()
        second = sample_lot(source="Other", source_lot_id="other-1", lot_url="https://drouot.com/l/1")
        lots = mark_cross_source_duplicates([first, second])
        self.assertEqual(len(lots), 2)
        self.assertEqual(second.duplicate_of, first.cache_key)


class _OpenAISession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = {
            "output_text": json.dumps(
                {
                    "records": [
                        {
                            "index": index,
                            "normalized_artist": "Rufino Tamayo",
                            "is_print": True,
                            "medium": "Lithograph",
                            "end_at": "2026-07-18T17:00:00-04:00",
                            "duplicate_group": None,
                            "confidence": 0.97,
                        }
                        for index in range(len(kwargs["json"]["input"][1]["content"][0]["text"]) and 2)
                    ]
                }
            ),
            "usage": {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160},
        }
        return _Response(200, payload=payload, headers={"Content-Type": "application/json"})


class EnrichmentTests(SimpleTestCase):
    def ambiguous_lots(self):
        return [
            sample_lot(source_lot_id="a", medium="", ambiguities=["print_classification"]),
            sample_lot(source_lot_id="b", lot_url="https://www.invaluable.com/auction-lot/b", medium="", ambiguities=["print_classification"]),
        ]

    def test_zero_ai_mode_makes_no_request(self):
        session = _OpenAISession()
        with WatchlistCache(":memory:") as cache:
            metrics = OpenAIEnricher(cache, api_key="test", enabled=True, session=session).enrich(
                self.ambiguous_lots(), zero_ai=True
            )
        self.assertEqual(session.calls, [])
        self.assertEqual(metrics.records_enriched, 0)

    def test_compact_strict_batch_is_cached_by_content_hash(self):
        session = _OpenAISession()
        with WatchlistCache(":memory:") as cache:
            enricher = OpenAIEnricher(cache, api_key="test", enabled=True, session=session)
            lots = self.ambiguous_lots()
            metrics = enricher.enrich(lots, zero_ai=False)
            self.assertEqual(metrics.records_enriched, 2)
            self.assertEqual(metrics.total_tokens, 160)
            self.assertEqual(len(session.calls), 1)
            body = session.calls[0][1]["json"]
            body_text = json.dumps(body)
            self.assertTrue(body["text"]["format"]["strict"])
            self.assertNotIn("web_search", body_text)
            self.assertNotIn("lot_url", body_text)
            self.assertNotIn("bookmark", body["input"][1]["content"][0]["text"].casefold())

            cached_lots = self.ambiguous_lots()
            cached_metrics = enricher.enrich(cached_lots, zero_ai=False)
            self.assertEqual(len(session.calls), 1)
            self.assertEqual(cached_metrics.cache_hits, 2)


class LegacyRemovalRegressionTests(TestCase):
    def test_legacy_routes_are_not_registered(self):
        with self.assertRaises(NoReverseMatch):
            reverse("search_upcoming_print_auctions")
        response = self.client.get("/artworks/search_upcoming_print_auctions/")
        self.assertEqual(response.status_code, 404)

    def test_job_model_is_removed_from_runtime_and_delete_migration_is_additive(self):
        self.assertNotIn("AuctionSearchJob", {model.__name__ for model in apps.get_models()})
        old_migration = importlib.import_module("secondstateapp.migrations.0012_auctionsearchjob")
        delete_migration = importlib.import_module("secondstateapp.migrations.0013_delete_auctionsearchjob")
        self.assertEqual(old_migration.Migration.operations[0].name, "AuctionSearchJob")
        self.assertEqual(delete_migration.Migration.dependencies, [("secondstateapp", "0012_auctionsearchjob")])
        self.assertEqual(delete_migration.Migration.operations[0].name, "AuctionSearchJob")

    def test_old_desktop_and_backend_entry_points_are_gone(self):
        root = Path(settings.BASE_DIR)
        ui_source = (root / "catalogapp" / "catalogapp_inv_ui.py").read_text(encoding="utf-8")
        api_source = (root / "secondstateapp" / "catalog_api_views.py").read_text(encoding="utf-8")
        urls_source = (root / "secondstateapp" / "urls.py").read_text(encoding="utf-8")
        models_source = (root / "secondstateapp" / "models.py").read_text(encoding="utf-8")

        self.assertIn("Artist Watchlist", ui_source)
        self.assertNotIn("Auction Search", ui_source)
        self.assertNotIn("request_upcoming_auction_search", ui_source)
        self.assertNotIn("search_upcoming_print_auctions", api_source + urls_source)
        self.assertNotIn("AuctionSearchJob", api_source + models_source)

    def test_watchlist_modules_have_no_hosted_search_tool(self):
        root = Path(settings.BASE_DIR) / "catalogapp"
        sources = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("watchlist_*.py"))
        self.assertNotIn('"type": "web_search"', sources)
