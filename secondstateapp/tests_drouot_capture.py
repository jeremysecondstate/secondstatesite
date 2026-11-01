"""Drouot browser evidence cannot turn keyword matches into artist observations."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlencode

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_drouot_pages import (
    CAPTURE_FORMAT, import_saved_drouot_capture, select_drouot_entries, validate_drouot_capture,
)
from catalogapp.watchlist_models import NormalizedLot
from scripts.import_drouot_capture import capture_report


NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
SEEN = NOW - timedelta(minutes=1)
ENTRY = BookmarkEntry(
    folder_path=("DROUOT \u2014 PRINTS",), title="Joan Mir\u00f3: Drouot \u2014 Prints",
    url="https://drouot.com/en/c/50/lithographs?query=Joan+Miro", artist="Joan Mir\u00f3", source="Drouot",
)


def evidence(identity=100, *, credit="Joan Mir\u00f3 (1893-1983)", medium="Lithograph", day=4):
    raw = {
        "id": identity, "num": 52, "lowEstim": 600, "highEstim": 800, "currentBid": 0,
        "nextBid": 0, "result": 0, "date": int(datetime(2026, 11, day, 12, tzinfo=timezone.utc).timestamp()),
        "saleType": "LIVE", "saleStatus": "CREATED", "saleId": 187317, "auctioneerId": 388,
        "saleFees": 30, "displayStartingPrice": True, "bidEndDate": 0,
        "description": credit + "\n*La Revue*, 1966 " + medium + " on paper",
        "timezone": "Europe/Paris", "currencyId": "EUR", "slug": "joan-miro-la-revue",
        "photo": {"path": "388/187317/03b2ca9e6231db6bcfe42ce8ee66a985", "w": 1536, "h": 1002},
    }
    card = {
        "id": str(identity), "url": f"https://drouot.com/en/l/{identity}-joan-miro-la-revue",
        "heading": credit, "description": raw["description"][:60],
        "text": "LIVE\nNOVEMBER 4 | 07:00 AM\n" + credit + "\nEstimation\n\u20ac600 - 800",
        "image_url": "https://cdn.drouot.com/d/lot/ftall/" + raw["photo"]["path"],
    }
    return raw, card


def bundle(*items):
    if not items:
        items = (evidence(),)
    raw, cards = zip(*items)
    return {
        "format": CAPTURE_FORMAT, "version": 1, "exported_at": NOW.isoformat(),
        "window": {"start_date": "2026-11-01", "end_date": "2026-11-08", "time_zone": "America/New_York"},
        "auctioneers": {"388": "Public Auction House"},
        "searches": [{"artist": ENTRY.artist, "source_url": ENTRY.url, "pages": [{
            "page_url": ENTRY.url, "captured_at": SEEN.isoformat(), "page": 1,
            "total_pages": 1, "total_results": len(raw),
            "request_url": "https://api.drouot.com/drouot/gingolem/neoGingo/lot/search?" + urlencode({
                "lang": "en", "q": "Joan Miro", "cat": "50", "page": "1", "facet": "false",
            }), "status": 200, "content_type": "application/json", "lots": list(raw), "cards": list(cards),
        }]}],
    }


class DrouotCaptureTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)

    def capture_file(self, payload):
        path = Path(self.directory.name) / "capture.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def run_import(self, payload):
        return import_saved_drouot_capture(self.capture_file(payload), [ENTRY], self.cache, now=NOW)

    def test_public_source_and_dom_normalize_stable_id_currency_and_real_image(self):
        raw, card = evidence()
        card["image_url"] = "data:image/png;base64,placeholder"
        result = self.run_import(bundle((raw, card)))
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.lots), 1)
        lot = result.lots[0]
        self.assertEqual(lot.cache_key, "drouot:100")
        self.assertEqual(lot.artist, ENTRY.artist)
        self.assertEqual(lot.artist_watchlist_name, ENTRY.artist)
        self.assertEqual(lot.title, "La Revue, 1966 Lithograph on paper")
        self.assertEqual(lot.auction_house, "Public Auction House")
        self.assertEqual((lot.currency, lot.estimate_low, lot.estimate_high), ("EUR", 600, 800))
        self.assertIsNone(lot.current_bid)
        self.assertIsNone(lot.bid_count)
        self.assertTrue(lot.image_url.startswith("https://cdn.drouot.com/"))
        self.assertEqual(lot.last_seen_at, SEEN.isoformat())
        self.assertEqual(result.capture_summary["source_results"], 1)

    def test_other_artists_keyword_mentions_and_nonprints_are_audited_exclusions(self):
        wrong, wrong_card = evidence(101, credit="Keith Haring (1958-1990)")
        wrong["description"] += " Mentioning Joan Miro in a bibliography."
        painting, painting_card = evidence(102, medium="Oil painting")
        result = self.run_import(bundle((wrong, wrong_card), (painting, painting_card)))
        self.assertEqual(result.errors, [])
        self.assertEqual(result.lots, [])
        self.assertEqual(len(result.rejected_lots), 2)
        self.assertEqual(self.cache.connection.execute("SELECT count(*) FROM lots").fetchone()[0], 0)

    def test_qualified_primary_credit_is_preserved_and_flagged_without_authorship_claim(self):
        for credit in ["(after) Joan MIRO (1893-1983)", "Attributed to Joan Mir\u00f3 (1893-1983)", "Joan Mir\u00f3 (1893-1983), after"]:
            with self.subTest(credit=credit):
                result = self.run_import(bundle(evidence(100, credit=credit)))
                self.assertFalse(result.errors)
                observed = [lot for lot in result.lots if lot.cache_key not in result.fallback_lot_keys]
                self.assertEqual(len(observed), 1)
                self.assertEqual(observed[0].artist_watchlist_name, ENTRY.artist)
                self.assertNotEqual(observed[0].artist, ENTRY.artist)
                self.assertIn(observed[0].artist, observed[0].title)
                self.assertEqual(len(result.attribution_notes), 1)

    def test_report_counts_watched_artists_separately_from_qualified_source_credits(self):
        result = self.run_import(bundle(evidence(100), evidence(101, credit="After Joan Mir\u00f3 (1893-1983)")))
        report = capture_report(result, mode="preview")
        self.assertEqual(report["summary"]["observed_lots"], 2)
        self.assertEqual(report["summary"]["artists"], 1)
        self.assertEqual(len(report["attribution_notes"]), 1)

    def test_missing_search_or_incomplete_page_leaves_entire_cache_unchanged(self):
        self.run_import(bundle())
        original = list(self.cache.connection.iterdump())
        missing = bundle()
        missing["searches"] = []
        incomplete = bundle()
        page = incomplete["searches"][0]["pages"][0]
        page.update(total_results=101, total_pages=2)
        for payload in (missing, incomplete):
            result = self.run_import(payload)
            self.assertTrue(result.errors)
            self.assertEqual(list(self.cache.connection.iterdump()), original)

    def test_scope_dom_mismatch_duplicates_and_private_fields_fail_before_writes(self):
        variants = []
        source = bundle()
        source["searches"][0]["pages"][0]["request_url"] = source["searches"][0]["pages"][0]["request_url"].replace("cat=50", "cat=164")
        variants.append(source)
        mismatch = bundle()
        mismatch["searches"][0]["pages"][0]["cards"][0]["id"] = "999"
        variants.append(mismatch)
        variants.append(bundle(evidence(), evidence()))
        private = bundle()
        private["searches"][0]["pages"][0]["lots"][0]["currentWinner"] = "private-user"
        variants.append(private)
        nested = bundle()
        nested["searches"][0]["pages"][0]["lots"][0]["saleFees"] = {"private": "do not retain"}
        variants.append(nested)
        for payload in variants:
            result = self.run_import(payload)
            self.assertTrue(result.errors)
            self.assertEqual(self.cache.connection.execute("SELECT count(*) FROM lots").fetchone()[0], 0)

    def test_newer_sold_and_absent_cached_observations_remain_untouched(self):
        accepted = self.run_import(bundle())
        previous = deepcopy(accepted.lots[0])
        newer = NOW + timedelta(minutes=1)
        previous.current_bid = 900
        previous.content_hash = previous.calculate_content_hash()
        self.cache.upsert(previous, watch_url=ENTRY.url, search_hash=previous.content_hash, observed_at=newer)
        absent = replace(previous, source_lot_id="999", lot_url="https://drouot.com/en/l/999-absent")
        self.cache.upsert(absent, watch_url=ENTRY.url, search_hash=absent.content_hash, observed_at=newer)
        before = list(self.cache.connection.iterdump())
        with patch.object(self.cache, "mark_missing_ended", side_effect=AssertionError("Never retire absent lots")):
            result = self.run_import(bundle())
        self.assertFalse(result.errors)
        self.assertEqual(list(self.cache.connection.iterdump()), before)
        self.assertEqual(result.fallback_lot_keys, {"drouot:100", "drouot:999"})
        previous.sold_price = 1200
        previous.sold_currency = "EUR"
        previous.content_hash = previous.calculate_content_hash()
        self.cache.upsert(previous, watch_url=ENTRY.url, search_hash=previous.content_hash, observed_at=SEEN - timedelta(minutes=1))
        sold_before = self.cache.get(previous.cache_key).to_dict()
        self.run_import(bundle())
        self.assertEqual(self.cache.get(previous.cache_key).to_dict(), sold_before)

    def test_repeated_capture_is_idempotent_and_outside_window_is_not_uploaded(self):
        self.run_import(bundle())
        second = self.run_import(bundle())
        self.assertEqual(second.metrics.unchanged_lots, 1)
        self.assertEqual(second.metrics.new_lots, 0)
        outside = self.run_import(bundle(evidence(101, day=14)))
        self.assertEqual(outside.metrics.new_lots, 0)
        self.assertEqual(outside.capture_summary["outside_window"], 1)

    def test_canonical_bookmark_name_is_independent_of_short_search_alias(self):
        html = '<DL><DT><H3>DROUOT &mdash; PRINTS</H3><DL><DT><A HREF="https://drouot.com/en/c/50/lithographs?query=Corita+Kent">Mary Corita Kent: Drouot &mdash; Prints</A></DL></DL>'
        entries = select_drouot_entries(html)
        self.assertEqual(entries[0].artist, "Mary Corita Kent")
        self.assertEqual(entries[0].source, "Drouot")

    def test_unrelated_and_archived_drouot_folders_do_not_expand_worker_scope(self):
        html = ('<DL><DT><H3>OTHER DROUOT</H3><DL><DT><A HREF="https://drouot.com/en/auctions/future">Other Drouot page</A></DL>'
                '<DT><H3>DROUOT &mdash; PRINTS</H3><DL><DT><A HREF="' + ENTRY.url + '">' + ENTRY.title + '</A>'
                '<DT><H3>OLD</H3><DL><DT><A HREF="https://drouot.com/en/c/50/lithographs?query=Old+Artist">Old Artist: Drouot &mdash; Prints</A></DL></DL></DL>')
        entries = select_drouot_entries(html)
        self.assertEqual([entry.artist for entry in entries], [ENTRY.artist])

    def test_nonprint_medium_cannot_be_qualified_by_a_provenance_or_biography_mention(self):
        for medium in ["Oil on canvas. Provenance: exhibition of Lithographs", "Oil on canvas, depicting a lithograph", "Painting. Biography: known for lithographs"]:
            with self.subTest(medium=medium):
                result = self.run_import(bundle(evidence(100, medium=medium)))
                self.assertFalse(result.errors)
                self.assertEqual([lot for lot in result.lots if lot.cache_key not in result.fallback_lot_keys], [])
                self.assertEqual(len(result.rejected_lots), 1)
        mixed = self.run_import(bundle(evidence(101, medium="Mixed media: watercolor over a lithograph")))
        self.assertFalse(mixed.errors)
        self.assertEqual(mixed.metrics.new_lots, 1)

    def test_multi_artist_credit_is_not_reassigned_to_one_watched_artist(self):
        result = self.run_import(bundle(evidence(101, credit="Joan Mir\u00f3 and Pablo Picasso")))
        self.assertFalse(result.errors)
        self.assertEqual(result.lots, [])
        self.assertEqual(len(result.rejected_lots), 1)

    def test_repeated_alias_credit_retains_resolved_collaboration_and_work_title(self):
        entry = replace(ENTRY, artist="Shepard Fairey", title="Shepard Fairey: Drouot \u2014 Prints",
                        url="https://drouot.com/en/c/50/lithographs?query=Shepard+Fairey")
        raw, card = evidence(35544233, credit="Shepard Fairey")
        raw["description"] = (
            "Shepard Fairey\nShepard FAIREY, also known as OBEY GIANT (1970), x Jamie REID\n"
            "Suburban Pressure\n\nOriginal color silkscreen print\nSigned and dated 2016 in pencil\n"
            "INFORMATION: This edition was created in collaboration with Jamie REID (SEX PISTOLS)"
        )
        payload = bundle((raw, card))
        search = payload["searches"][0]
        search.update(artist=entry.artist, source_url=entry.url)
        page = search["pages"][0]
        page["page_url"] = entry.url
        page["request_url"] = page["request_url"].replace("Joan+Miro", "Shepard+Fairey")
        result = validate_drouot_capture(payload, [entry], now=NOW)
        self.assertEqual(len(result.lots), 1)
        lot = result.lots[0]
        self.assertEqual(lot.artist, "Shepard FAIREY x Jamie REID")
        self.assertEqual(lot.artist_watchlist_name, "Shepard Fairey")
        self.assertEqual(lot.title, "Shepard FAIREY x Jamie REID \u2014 Suburban Pressure")
        self.assertEqual(result.attribution_notes, [{
            "source_lot_id": "35544233", "watched_artist": "Shepard Fairey",
            "source_artist_credit": "Shepard FAIREY x Jamie REID",
        }])
        for confirmation in ("", "The artist collaborated with Jamie REID on other works"):
            with self.subTest(confirmation=confirmation):
                candidate = deepcopy(payload)
                candidate["searches"][0]["pages"][0]["lots"][0]["description"] = (
                    raw["description"].split("INFORMATION:")[0] + confirmation
                )
                resolved = validate_drouot_capture(candidate, [entry], now=NOW)
                self.assertEqual(resolved.lots[0].artist, "Shepard FAIREY x Jamie REID")
                self.assertEqual(resolved.lots[0].title, "Shepard FAIREY x Jamie REID \u2014 Suburban Pressure")
        candidate = deepcopy(payload)
        candidate["searches"][0]["pages"][0]["lots"][0]["description"] = (
            raw["description"].split("INFORMATION:")[0]
            + "This edition was created in collaboration with Another Artist"
        )
        self.assertEqual(validate_drouot_capture(candidate, [entry], now=NOW).lots, [])

    def test_explicit_joint_credit_for_one_offered_diptych_needs_no_second_confirmation(self):
        raw, card = evidence(credit="Joan Miro")
        raw["description"] = (
            "Joan Miro\nJoan MIRO, also known as MIRO (1893), and Ernesto YERENA (1987)\n"
            "Day of the Dead Calavera\nOriginal color letterpress diptych\nSigned and dated 2021"
        )
        result = self.run_import(bundle((raw, card)))
        self.assertFalse(result.errors)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].artist, "Joan MIRO and Ernesto YERENA")
        self.assertEqual(result.lots[0].title, "Joan MIRO and Ernesto YERENA \u2014 Day of the Dead Calavera")
        self.assertEqual(result.lots[0].medium, "letterpress")
        self.assertEqual(result.attribution_notes[0]["source_artist_credit"], result.lots[0].artist)

    def test_leading_joint_credit_requires_matching_heading_and_one_resolved_work(self):
        entry = replace(ENTRY, artist="Pierre Soulages", title="Pierre Soulages: Drouot \u2014 Prints",
                        url="https://drouot.com/en/c/50/lithographs?query=Pierre+Soulages")
        raw, card = evidence(35544275, credit="Pierre Soulages and Philippe Geluck")
        raw["description"] = ("Pierre Soulages and Philippe Geluck\nPierre SOULAGES and Philippe GELUCK\n"
                              "Power Outage at the Soulages Museum\n\nSilkscreen print with printed signature")
        payload = bundle((raw, card))
        search = payload["searches"][0]
        search.update(artist=entry.artist, source_url=entry.url)
        page = search["pages"][0]
        page["page_url"] = entry.url
        page["request_url"] = page["request_url"].replace("Joan+Miro", "Pierre+Soulages")
        result = validate_drouot_capture(payload, [entry], now=NOW)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].artist, "Pierre SOULAGES and Philippe GELUCK")
        self.assertEqual(result.lots[0].title,
                         "Pierre SOULAGES and Philippe GELUCK \u2014 Power Outage at the Soulages Museum")
        self.assertEqual(result.lots[0].medium, "Silkscreen")
        self.assertEqual(result.attribution_notes[0]["source_artist_credit"], result.lots[0].artist)
        for mismatch in ("heading", "description", "multiple works"):
            with self.subTest(mismatch=mismatch):
                candidate = deepcopy(payload)
                altered = candidate["searches"][0]["pages"][0]
                if mismatch == "heading":
                    altered["cards"][0]["heading"] = "Pierre Soulages and Pablo Picasso"
                elif mismatch == "description":
                    altered["lots"][0]["description"] = raw["description"].replace(
                        "Pierre Soulages and Philippe Geluck", "Pierre Soulages and Pablo Picasso", 1)
                else:
                    altered["lots"][0]["description"] = raw["description"].replace(
                        "\n\nSilkscreen", "\nA Second Work\n\nSilkscreen")
                self.assertEqual(validate_drouot_capture(candidate, [entry], now=NOW).lots, [])

    def test_repeated_multi_artist_credit_without_resolution_is_not_single_authorship(self):
        for second_credit in [
            "Joan Miro, also known as MIRO (1893), and Another ARTIST (1987)",
            "Joan Miro x Another Artist",
        ]:
            with self.subTest(second_credit=second_credit):
                raw, card = evidence()
                raw["description"] = "Joan Miro\n" + second_credit + "\nThe Garden\nThe Moon\nOriginal color letterpress diptych"
                card["heading"] = "Joan Miro"
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(result.lots, [])
                self.assertEqual(result.rejected_lots[0]["reason"], "The source's multiple-artist credit is unresolved.")

    def test_joint_ampersand_mononym_needs_same_work_both_signature_evidence(self):
        entry = replace(ENTRY, artist="Damien Hirst", title="Damien Hirst: Drouot \u2014 Prints",
                        url="https://drouot.com/en/c/50/lithographs?query=Damien+Hirst")
        heading = 'Damien Hirst (b.1965) & Invader (b.1969)'
        raw, card = evidence(35496917, credit=heading)
        raw['description'] = (heading + '\n\nTT2. InvadHirst\n\nScreenprint in colours, 2025, '
                              'signed and dated by both artists in pencil, numbered from the edition of 1194, '
                              'published by HENI Editions, London, in the original publisher\'s cardboard box, '
                              'on Somerset wove paper, sheet 800 x 1200mm (framed)')
        payload = bundle((raw, card))
        search = payload['searches'][0]
        search.update(artist=entry.artist, source_url=entry.url)
        page = search['pages'][0]
        page['page_url'] = entry.url
        page['request_url'] = page['request_url'].replace('Joan+Miro', 'Damien+Hirst')
        result = validate_drouot_capture(payload, [entry], now=NOW)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].artist, 'Damien Hirst & Invader')
        self.assertEqual(result.lots[0].title, 'Damien Hirst & Invader \u2014 TT2. InvadHirst')
        self.assertEqual(result.lots[0].medium, 'Screenprint')
        self.assertEqual(result.attribution_notes[0]['source_artist_credit'], result.lots[0].artist)
        for case in ('no joint signature', 'other signature in bibliography', 'other works signed',
                     'heading mismatch', 'two works'):
            with self.subTest(case=case):
                candidate = deepcopy(payload)
                modified = candidate['searches'][0]['pages'][0]
                description = raw['description']
                if case in ('no joint signature', 'other signature in bibliography', 'other works signed'):
                    description = description.replace('signed and dated by both artists', 'signed by Hirst')
                    if case == 'other signature in bibliography':
                        description += '\nBibliography: Other works were signed and dated by both artists.'
                    elif case == 'other works signed':
                        description += '\nOther works were screenprints signed by both artists.'
                elif case == 'heading mismatch':
                    modified['cards'][0]['heading'] = heading.replace('Invader', 'Banksy')
                else:
                    description = description.replace('TT2. InvadHirst', 'TT2. InvadHirst\nAnother work')
                modified['lots'][0]['description'] = description
                self.assertEqual(validate_drouot_capture(candidate, [entry], now=NOW).lots, [])

    def test_joint_signed_project_photoprint_retains_both_creators_and_named_work(self):
        entry = replace(ENTRY, artist="Christo", title="Christo: Drouot \u2014 Prints",
                        url="https://drouot.com/en/c/50/lithographs?query=Christo")
        heading = 'CHRISTO (1935 - 2020) & JEANNE-CLAUDE (1935 - 2009)'
        raw, card = evidence(35570090, credit=heading, day=7)
        raw['description'] = (heading + '\nChristo & Jeanne-Claude signed photoprint of the project '
                              '"The Pont Neuf Wrapped, Paris" and print dated 1975/1985\n\n' + heading
                              + ' fotoprint op dibond : "The Pont Neuf Wrapped, Paris" - '
                              '67 x 67 getekend door beide en gedateerd (in de print) 1975 en 1985')
        payload = bundle((raw, card))
        search = payload['searches'][0]
        search.update(artist=entry.artist, source_url=entry.url)
        page = search['pages'][0]
        page['page_url'] = entry.url
        page['request_url'] = page['request_url'].replace('Joan+Miro', 'Christo')
        result = validate_drouot_capture(payload, [entry], now=NOW)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].artist, 'CHRISTO & JEANNE-CLAUDE')
        self.assertEqual(result.lots[0].title, 'CHRISTO & JEANNE-CLAUDE \u2014 The Pont Neuf Wrapped, Paris')
        self.assertEqual(result.lots[0].medium, 'photoprint')
        self.assertEqual(result.attribution_notes[0]['source_artist_credit'], result.lots[0].artist)
        for case in ('heading mismatch', 'repeated credit mismatch', 'no both signature', 'unnamed project'):
            with self.subTest(case=case):
                candidate = deepcopy(payload)
                modified = candidate['searches'][0]['pages'][0]
                description = raw['description']
                if case == 'heading mismatch':
                    modified['cards'][0]['heading'] = heading.replace('JEANNE-CLAUDE', 'OTHER ARTIST')
                elif case == 'repeated credit mismatch':
                    description = description.replace('Christo & Jeanne-Claude signed', 'Christo & Another Artist signed')
                elif case == 'no both signature':
                    description = description.replace('getekend door beide', 'getekend')
                else:
                    description = description.replace('"The Pont Neuf Wrapped, Paris" and print dated', 'an unnamed project and print dated')
                modified['lots'][0]['description'] = description
                self.assertEqual(validate_drouot_capture(candidate, [entry], now=NOW).lots, [])

    def test_shipping_allowance_does_not_establish_offered_work_print_medium(self):
        for work in ("Marker drawing", "Original color poster based on the artist's work", "Printed on heavy paper"):
            with self.subTest(work=work):
                raw, card = evidence()
                raw["description"] = ("Joan Miro\nThe Garden\n" + work
                                      + "\nShipping required; up to 5 lithographs in your package")
                card["heading"] = "Joan Miro"
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(result.lots, [])
                self.assertIn("No explicit print technique", result.rejected_lots[0]["reason"])

    def test_observed_print_process_names_are_retained_as_medium_evidence(self):
        for technique in ("Granolithograph", "Photolithograph", "Phototype", "Heliogravure", "Letterpress",
                          "Lithographic", "Collotype", "Chromolithograph", "Pochoir"):
            with self.subTest(technique=technique):
                raw, card = evidence(medium=technique)
                raw["description"] += "\nShipping required; up to 5 lithographs in your package"
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].medium, technique)

    def test_nonprint_named_title_does_not_override_explicit_offered_poster_technique(self):
        for title, offered, medium in (
            ("Gouache on paper, 1951", "Original poster\nHigh-quality four-color print", "print"),
            ("Gouache 11, 1957", "Lithograph and stencil (Jacomet process) based on a gouache by the artist", "Lithograph"),
        ):
            with self.subTest(title=title):
                raw, card = evidence()
                raw["description"] = "Joan Miro\n" + title + "\n\n" + offered + "\nOn thick paper"
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].medium, medium)
                self.assertEqual(result.lots[0].title, title)

    def test_nonprint_offered_medium_still_blocks_later_print_mention(self):
        raw, card = evidence()
        raw["description"] = "Joan Miro\nGouache on paper, 1951\nIncluded is a lithograph on paper"
        result = self.run_import(bundle((raw, card)))
        self.assertFalse(result.errors)
        self.assertEqual(result.lots, [])

    def test_repeated_work_year_is_not_discarded_as_artist_biography(self):
        for title in ("Painting, June 1, 1964, 1964", "Painting, July 4, 2021, 2021"):
            with self.subTest(title=title):
                raw, card = evidence(credit="Joan Miro (after) (1893-1983)")
                raw["description"] = (card["heading"]
                                      + "\nBarcelona, Spain (1893) / Palma, Spain (1983)\n"
                                      + title + "\n\nPoster, offset print on thick paper")
                result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].title, "Joan Miro (after) \u2014 " + title)
                self.assertEqual(result.lots[0].medium, "offset")

    def test_numbered_work_title_and_reference_do_not_establish_poster_technique(self):
        for title, offered in (
            ("Lithograph No. 22", 'Poster published based on "Lithograph No. 22". On thick paper.'),
            ("Etching XVIII", 'Poster published based on "Etching XVIII". On thick paper.'),
            ("Silkscreen No. 18, 1988", "Printed on heavy paper, after Silkscreen No. 18, 1988"),
        ):
            with self.subTest(title=title):
                raw, card = evidence()
                raw["description"] = "Joan Miro\n" + title + "\n\n" + offered
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(result.lots, [])
                self.assertIn("No explicit print technique", result.rejected_lots[0]["reason"])

    def test_plate_title_keeps_book_author_dates_without_using_artist_biography(self):
        raw, card = evidence(credit="Joan Miro (1893-1983)")
        title = ('*The Married Priest*, Plate I from *Sign of Survival in the Time of Love* '
                 'by Gui Rosey (1896\u20131981)')
        raw['description'] = (card['heading'] + '\nBarcelona, Spain (1893) / Palma, Spain (1983)\n'
                              + title + '\nColor etching, signed and numbered IX/XXV\nPublished in 1968')
        result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].title, title.replace('*', ''))
        self.assertEqual(result.lots[0].medium, 'etching')

    def test_catalog_stencil_prints_are_offered_technique_with_source_qualifier(self):
        raw, card = evidence(credit="Joan Miro (after) (1893-1983)")
        raw['description'] = (card['heading'] + '\nMiro, 1962\nOriginal exhibition catalog.\n'
                              'Illustrated with 8 stencil prints based on the original works,\n'
                              'produced by the Atelier Daniel Jacomet in Paris.\n18 pages.\n'
                              'Shipping required; up to 5 lithographs in your package')
        result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].medium, 'stencil prints')
        self.assertEqual(result.lots[0].artist, 'Joan Miro (after)')
        self.assertEqual(result.lots[0].title, 'Joan Miro (after) \u2014 Miro, 1962')
        self.assertEqual(result.attribution_notes[0]['source_artist_credit'], 'Joan Miro (after)')

    def test_stencil_print_titles_references_and_shipping_are_not_medium_evidence(self):
        for work in (
            'Exhibition catalog titled "Stencil Prints". No illustrations specified.',
            'Poster. Biography: known for stencil prints.',
            'Poster.\nShipping: room for eight stencil prints.',
        ):
            with self.subTest(work=work):
                raw, card = evidence()
                raw['description'] = 'Joan Miro\nThe Garden\n' + work
                result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
                self.assertEqual(result.lots, [])
                self.assertEqual(len(result.rejected_lots), 1)

    def test_counted_offered_prints_with_dimensions_keep_publisher_wording(self):
        entry = replace(ENTRY, artist="Andy Warhol", title="Andy Warhol: Drouot \u2014 Prints",
                        url="https://drouot.com/en/c/50/lithographs?query=Andy+Warhol")
        heading = "ANDY WARHOL SUNDAY B. MORNING CAMPBELL'S SOUP PRINTS (3) VEGETABLE, GREEN PEA & ONION"
        raw, card = evidence(35617231, credit=heading, day=2)
        raw['description'] = heading + " \n89cm x 59cm, unframed."
        payload = bundle((raw, card))
        search = payload['searches'][0]
        search.update(artist=entry.artist, source_url=entry.url)
        page = search['pages'][0]
        page['page_url'] = entry.url
        page['request_url'] = page['request_url'].replace('Joan+Miro', 'Andy+Warhol')
        result = validate_drouot_capture(payload, [entry], now=NOW)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].medium, 'PRINTS')
        self.assertEqual(result.lots[0].title,
                         "SUNDAY B. MORNING CAMPBELL'S SOUP PRINTS (3) VEGETABLE, GREEN PEA & ONION")

    def test_counted_print_references_titles_and_missing_dimensions_stay_excluded(self):
        for offered in (
            'Poster titled "PRINTS (3)".\n89cm x 59cm, unframed.',
            'Poster after PRINTS (3).\n89cm x 59cm, unframed.',
            'PRINTS (3) VEGETABLE, GREEN PEA & ONION',
            'Print (3)\n89cm x 59cm, unframed.',
            'Prints No. 3\n89cm x 59cm, unframed.',
            'Poster. Biography: known for PRINTS (3).\n89cm x 59cm, unframed.',
            'Poster.\nShipping: PRINTS (3) in a box 89cm x 59cm.',
        ):
            with self.subTest(offered=offered):
                raw, card = evidence()
                raw['description'] = 'Joan Miro\n' + offered
                result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
                self.assertEqual(result.lots, [])
                self.assertEqual(len(result.rejected_lots), 1)

    def test_offered_technique_overrides_numbered_and_print_series_titles(self):
        for title, offered, medium in (
            ("Etching XVI, 1961", "Poster, offset print on thick paper", "offset"),
            ("Silkscreen No. 1, 1973", "Poster, offset print on thick paper", "offset"),
            ("Psalm Print: Domino Confido", "Screenprint in colours, signed in pencil", "Screenprint"),
            ("Lithograph No. 38", "Color lithograph on vellum, signed and numbered", "lithograph"),
            ("Roland Garros", "Lithographic poster signed on the plate; color offset lithograph published in 2000", "offset"),
        ):
            with self.subTest(title=title):
                raw, card = evidence()
                raw["description"] = "Joan Miro\n" + title + "\n\n" + offered
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].medium, medium)
                self.assertEqual(result.lots[0].title, title)

    def test_expanded_dali_credit_does_not_replace_actual_work_title(self):
        entry = replace(ENTRY, artist="Salvador Dal\u00ed", title="Salvador Dal\u00ed: Drouot \u2014 Prints",
                        url="https://drouot.com/en/c/50/lithographs?query=Salvador+Dali")
        raw, card = evidence(credit="SALVADOR DALI Y DOMENECH")
        raw["description"] = (card["heading"] + '\nFigueras, Gerona (1904) / (1990)\n'
                              '"Man Kissing a Shoe (Homme baisant la chaussure)"\nPrint on Japan paper with watercolour.')
        payload = bundle((raw, card))
        search = payload["searches"][0]
        search.update(artist=entry.artist, source_url=entry.url)
        page = search["pages"][0]
        page["page_url"] = entry.url
        page["request_url"] = page["request_url"].replace("Joan+Miro", "Salvador+Dali")
        result = validate_drouot_capture(payload, [entry], now=NOW)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].artist, entry.artist)
        self.assertEqual(result.lots[0].title, "Man Kissing a Shoe (Homme baisant la chaussure)")

    def test_mononym_bookmark_retains_expanded_source_name_and_separate_after_credit(self):
        entry = replace(ENTRY, artist="Rembrandt", title="Rembrandt: Drouot \u2014 Prints",
                        url="https://drouot.com/en/c/50/lithographs?query=Rembrandt")
        raw, card = evidence(35434019, credit="REMBRANDT VAN RIJN, HARMENSZ (Leiden 1606 \u2013 1669 Amsterdam)")
        raw["description"] = (card["heading"] + '\nAfter: \u201cThe Three Trees\u201d\n'
                              'Heliogravure with etched sections on handmade paper')
        payload = bundle((raw, card))
        search = payload["searches"][0]
        search.update(artist=entry.artist, source_url=entry.url)
        page = search["pages"][0]
        page["page_url"] = entry.url
        page["request_url"] = page["request_url"].replace("Joan+Miro", "Rembrandt")
        result = validate_drouot_capture(payload, [entry], now=NOW)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].artist, "REMBRANDT VAN RIJN, HARMENSZ, After")
        self.assertEqual(result.lots[0].artist_watchlist_name, "Rembrandt")
        self.assertEqual(result.lots[0].title, "REMBRANDT VAN RIJN, HARMENSZ, After \u2014 The Three Trees")
        self.assertEqual(result.attribution_notes[0]["source_artist_credit"], result.lots[0].artist)

    def test_actual_repeated_and_inline_credit_layouts_preserve_work_titles_and_qualifiers(self):
        cases = [
            ("Joan Mir\u00f3\nJoan MIRO (1893-1983)\nSurrealist Composition in Blue\nOriginal color lithograph", "Surrealist Composition in Blue", False),
            ("Joan Mir\u00f3\nJoan MIRO (after) (1893-1983)\nWoman-Bird\nArt print on thick paper", "Joan MIRO (after) \u2014 Woman-Bird", True),
            ('JOAN MIRO\nBarcelona (1893) / Palma de Mallorca (1983)\n"Sculptures", 1974\nLithograph on paper.', 'Sculptures, 1974', False),
            ('JOAN MIRO\nMIRO JOAN\nBarcelona (Spain) 1893\nWoman and Birds\n1987\nVintage offset print', 'Woman and Birds', False),
            ('MIRO, JOAN (Montroig 1893 - 1983 Palma de Mallorca): \u201cThe Lithographer II\u201d\nColor lithograph', 'The Lithographer II', False),
            ('JOAN MIRO 1893-1983 Espriu - Miro (Sheet IV) 1975 - Etching, color aquatint on paper.\nPrinted by J.J. Torralba.', 'Espriu - Miro (Sheet IV) 1975', False),
            ('JOAN MIRO 1937 The Culture Carriers - Stamp Out Art 1971 - Offset lithograph.', 'The Culture Carriers - Stamp Out Art 1971 - Offset lithograph', False),
            ('After Joan MIRO (1893-1983) \u2013 Chalcographie du Louvre\nAmedeo MODIGLIANI (1884-1920), after\n*L\'italienne*\nAquatint executed by Joan Miro.', "After Joan MIRO \u2014 L'italienne", True),
        ]
        for description, expected_title, qualified in cases:
            with self.subTest(description=description):
                raw, card = evidence(100)
                raw["description"] = description
                card["heading"] = description.splitlines()[0]
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                observed = [lot for lot in result.lots if lot.cache_key not in result.fallback_lot_keys]
                self.assertEqual(len(observed), 1)
                self.assertEqual(observed[0].title, expected_title)
                self.assertEqual(bool(result.attribution_notes), qualified)

    def test_known_as_credit_line_does_not_replace_following_work_title(self):
        for alias_credit in ("known as MIRO THE GIANT (1893)", "also known as MIRO THE GIANT (1893)"):
            with self.subTest(alias_credit=alias_credit):
                raw, card = evidence(credit="Joan Miro")
                raw["description"] = ("Joan Miro\nJoan MIRO, " + alias_credit
                                      + "\nLiberty, Equality, Fraternity\nColor offset lithograph")
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].artist, ENTRY.artist)
                self.assertEqual(result.lots[0].title, "Liberty, Equality, Fraternity")

    def test_qualified_credit_is_bounded_before_inline_work_description_and_suffix_punctuation(self):
        cases = [
            ('After Joan Mir\u00f3 (Spanish, 1893-1983). Screenprint in colors from "Birds". Certificate and framed dimensions.', 'After Joan Mir\u00f3'),
            ('Joan Mir\u00f3 (1893-1983), after. The Language of Flowers. Print on velvet.', 'Joan Mir\u00f3, after'),
            ('Joan Mir\u00f3 (attributed to) - "Palestine". Print on paper.', 'Joan Mir\u00f3 (attributed to)'),
            ('Joan Mir\u00f3 (1893-1983) (after). "Seaside." Lithograph on paper.', 'Joan Mir\u00f3 (after)'),
            ('Joan Mir\u00f3 (Barcelona, 1893), After: "Abstract Painting". Lithograph.', 'Joan Mir\u00f3, After'),
        ]
        for description, expected_credit in cases:
            with self.subTest(description=description):
                raw, card = evidence(100)
                raw['description'] = description
                card['heading'] = description
                result = self.run_import(bundle((raw, card)))
                observed = [lot for lot in result.lots if lot.cache_key not in result.fallback_lot_keys]
                self.assertFalse(result.errors)
                self.assertEqual(len(observed), 1)
                self.assertEqual(observed[0].artist, expected_credit)
                self.assertEqual(len(result.attribution_notes), 1)
                self.assertTrue(observed[0].title.startswith(expected_credit + ' \u2014 '))

    def test_repeated_qualified_signature_line_does_not_replace_the_quoted_work_title(self):
        raw, card = evidence(100)
        raw['description'] = ('JOAN MIRO (1893-1983)\nafter Joan Miro plate signed print\n\n'
                              'MIRO JOAN (1893-1983) - NAAR print n\u00b0 71/500 : "Mickey Mouse (blue)" - 50 x 50')
        card['heading'] = 'JOAN MIRO (1893-1983)'
        result = self.run_import(bundle((raw, card)))
        self.assertFalse(result.errors)
        self.assertEqual(result.lots[0].artist, 'after Joan Miro')
        self.assertEqual(result.lots[0].title, 'after Joan Miro \u2014 Mickey Mouse (blue)')
        raw['description'] = raw['description'].replace('"Mickey Mouse (blue)" - 50 x 50', '"Mickey Mouse (double portrait) - 50 x 50')
        result = self.run_import(bundle((raw, card)))
        self.assertFalse(result.errors)
        self.assertEqual(result.lots[0].title, 'after Joan Miro \u2014 Mickey Mouse (double portrait)')

    def test_separate_after_label_preserves_source_credit_and_actual_work_title(self):
        cases = [
            ('JOAN MIRO (Barcelona, 1893)\nAfter: \u201cAbstract Painting\u201d\nColor offset print',
             'JOAN MIRO, After', 'Abstract Painting'),
            ('MIRO, JOAN (1893 Barcelona 1983)\nAfter: "Secret Poems of Apollinaire"\nCopperplate engraving and watercolor',
             'MIRO, JOAN, After', 'Secret Poems of Apollinaire'),
            ('MIRO, JOAN (Barcelona, 1893)\nAfter: "Joan Miro Jerusalem 1995,"\nColor offset print',
             'MIRO, JOAN, After', 'Joan Miro Jerusalem 1995,'),
        ]
        for description, credit, title in cases:
            with self.subTest(description=description):
                raw, card = evidence()
                raw['description'] = description
                card['heading'] = description.splitlines()[0]
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].artist, credit)
                self.assertEqual(result.lots[0].title, credit + ' \u2014 ' + title)
                self.assertEqual(result.attribution_notes, [{
                    'source_lot_id': '100', 'watched_artist': ENTRY.artist, 'source_artist_credit': credit,
                }])

    def test_spanish_and_dutch_credit_suffixes_do_not_replace_work_titles(self):
        cases = [
            ('JOAN MIRO (DESPUES)\nBarcelona (1893) / Palma de Mallorca (1983)\n\u201cL\'homme au mouton 1943\u201d, 1967\nLithograph heightened with pochoir.',
             'JOAN MIRO (DESPUES)', "L'homme au mouton 1943, 1967"),
            ('MIRO JOAN (1893 - 1983) - NAAR\n"Nude with blue eyes" print after Joan Miro\nMIRO JOAN (1893 - 1983) - NAAR print n\u00b0 40/150: "Nude with blue eyes"',
             'MIRO JOAN, NAAR', 'Nude with blue eyes print after Joan Miro'),
            ('JOAN MIRO (1893 - 1983)\nplate signed "Reclining nude" print after Joan Miro\n\nMIRO JOAN (1893 - 1983) - NAAR print n\u00b0 90/450: "Reclining nude" - 50 x 70',
             'MIRO JOAN, NAAR', 'Reclining nude'),
        ]
        for description, credit, title in cases:
            with self.subTest(description=description):
                raw, card = evidence()
                raw['description'] = description
                card['heading'] = description.splitlines()[0]
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].artist, credit)
                self.assertEqual(result.lots[0].title, credit + ' \u2014 ' + title)
                self.assertEqual(result.attribution_notes[0]['source_artist_credit'], credit)
                self.assertEqual(result.lots[0].artist_watchlist_name, ENTRY.artist)

    def test_after_work_titles_and_later_references_are_not_credit_qualifiers(self):
        for description, title in [
            ('JOAN MIRO (1893-1983)\nAfter the Rain\nLithograph on paper', 'After the Rain'),
            ('JOAN MIRO (1893-1983)\nNocturne\nLithograph on paper\nAfter: an exhibition catalogue', 'Nocturne'),
        ]:
            with self.subTest(description=description):
                raw, card = evidence()
                raw['description'] = description
                card['heading'] = description.splitlines()[0]
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(result.lots[0].artist, ENTRY.artist)
                self.assertEqual(result.lots[0].title, title)
                self.assertEqual(result.attribution_notes, [])

    def test_explicit_after_in_offered_print_medium_is_preserved_and_flagged(self):
        for source_line in [
            'Lithograph after a work by Joan Miro, numbered in pencil.',
            'Lithograph after an oil painting. Signed on the plate.',
            'Engraving after a pastel. Signed on the plate.',
            'Color lithograph engraved by Sorlier after a design by Joan Miro and under his direction.',
            'Joan Miro, "The Garden", after an original from 1949, colour silkscreen print, numbered 8/50.',
            'Joan Miro numbered lithograph printed in colors after the work "The Garden" from 1953.',
            'Color print after Joan Miro, numbered 8/50.',
            'A SET OF TEN POCHOIR AFTER THE DECOUPAGE',
            'A SET OF TEN ABSTRACT POCHOIR AFTER THE GOUCHE',
        ]:
            with self.subTest(source_line=source_line):
                raw, card = evidence()
                raw['description'] = 'JOAN MIRO (1893-1983)\nThe Garden\n\n' + source_line
                card['heading'] = 'JOAN MIRO (1893-1983)'
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(len(result.lots), 1)
                qualifier = 'AFTER' if 'AFTER' in source_line else 'after'
                self.assertEqual(result.lots[0].artist, 'JOAN MIRO, ' + qualifier)
                self.assertEqual(result.lots[0].title, 'JOAN MIRO, ' + qualifier + ' \u2014 The Garden')
                self.assertEqual(result.lots[0].artist_watchlist_name, ENTRY.artist)
                self.assertEqual(result.attribution_notes[0]['source_artist_credit'], 'JOAN MIRO, ' + qualifier)

    def test_offered_work_after_does_not_replace_a_more_specific_primary_credit(self):
        raw, card = evidence(credit='Attributed to Joan Miro (1893-1983)')
        raw['description'] = 'Attributed to Joan Miro (1893-1983)\nThe Garden\nLithograph after a painting.'
        result = self.run_import(bundle((raw, card)))
        self.assertFalse(result.errors)
        self.assertEqual(result.lots[0].artist, 'Attributed to Joan Miro')
        self.assertEqual(result.lots[0].title, 'Attributed to Joan Miro \u2014 The Garden')

    def test_work_level_after_ignores_titles_references_and_accompanying_works(self):
        for description in [
            'JOAN MIRO\nAfter the Painting\nLithograph on paper.',
            'JOAN MIRO\nThe Garden\nLithograph titled "After the Painting" on paper.',
            'JOAN MIRO\nThe Garden\nLithograph on paper. Provenance: a collection of lithographs after paintings.',
            'JOAN MIRO\nThe Garden\nLithograph on paper. Biography: known for lithographs after paintings.',
            'JOAN MIRO\nThe Garden\nLithograph on paper.\nInformation: the artist also made lithographs after paintings.',
            'JOAN MIRO\nThe Garden\nLithograph on paper.\nIncluded is a print after Jean Cocteau.',
            'JOAN MIRO\nThe Garden\nLithograph on paper.\nAccompanied by an engraving after an original painting.',
            'JOAN MIRO\nThe Garden\nLithograph after a painting by Pablo Picasso.',
            'JOAN MIRO\nThe Garden\nLithograph on paper, framed after restoration.',
            'JOAN MIRO\nThe Garden\nLithograph based on the artist\u2019s painting.',
        ]:
            with self.subTest(description=description):
                raw, card = evidence()
                raw['description'] = description
                card['heading'] = description.splitlines()[0]
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(result.lots[0].artist, ENTRY.artist)
                self.assertEqual(result.attribution_notes, [])

    def test_explicit_homage_credit_preserves_source_wording(self):
        for credit, expected in [
            ('Joan Miro - Hommage \u00e0', 'Joan Miro, Hommage \u00e0'),
            ('Homage to Joan Miro', 'Homage to Joan Miro'),
        ]:
            with self.subTest(credit=credit):
                raw, card = evidence(credit=credit)
                raw['description'] = credit + '\nThe Garden\nColor screen print on paper.'
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].artist, expected)
                self.assertEqual(result.lots[0].title, expected + ' \u2014 The Garden')
                self.assertEqual(len(result.attribution_notes), 1)

    def test_quoted_print_exhibition_title_is_not_medium_evidence(self):
        for quoted in ['\u201cA Print Retrospective\u201d', '"A Print Retrospective"', "'A Print Retrospective'"]:
            with self.subTest(quoted=quoted):
                raw, card = evidence(100)
                raw['description'] = 'After Joan Miro (1893-1983)\nSet of 11 display cards from the exhibition ' + quoted + ' held at a gallery. Signed. Dimensions: 18 x 18 cm.'
                card['heading'] = 'After Joan Miro (1893-1983)'
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual([lot for lot in result.lots if lot.cache_key not in result.fallback_lot_keys], [])
                self.assertEqual(len(result.rejected_lots), 1)

    def test_offered_print_conditions_derivations_and_book_production_are_medium_evidence(self):
        cases = [
            ('Joan Miro: "Spring Carnival," print (minor wear). 44.5 x 65 cm', 'print', False),
            ('Joan Miro, After\n"Anti-immigration"\nPrint based on the original work, in color on paper, '
             'signed and numbered 55/150 on the sheet.', 'Print', True),
            ('Joan Miro\nSeated Bather, circa 1897\nSoft varnish on paper, bearing the signature stamp\n'
             'Print produced for the book *La vie et l\u2019oeuvre*, Paris, 1919\nH. 27.5 cm - W. 19.5 cm', 'Print', False),
            ("Joan Miro\nJoan Miro print after the work 'Arabe' from 1962\n"
             "Joan Miro - NAAR grafiek naar het werk 'Arabe' uit 1962 - blad 56 x 75", 'print', True),
        ]
        for description, medium, qualified in cases:
            with self.subTest(description=description):
                raw, card = evidence()
                raw['description'] = description
                card['heading'] = description.splitlines()[0]
                result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].medium, medium)
                self.assertEqual(bool(result.attribution_notes), qualified)
                self.assertEqual(result.lots[0].source_lot_id, '100')
                if qualified:
                    self.assertIn(result.lots[0].artist, result.lots[0].title)

    def test_immediate_offered_medium_after_short_printer_credit_is_preserved(self):
        for offered, qualified in [
            ('Original color lithograph on untrimmed Arches paper. Signed on the plate.', False),
            ('Color lithograph after a painting on Arches paper.', True),
        ]:
            with self.subTest(offered=offered):
                raw, card = evidence()
                raw['description'] = 'Joan Miro - Dove Flying Toward the Rainbow. 1952. Printer: Mourlot. ' + offered
                card['heading'] = raw['description']
                result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].medium, 'lithograph')
                self.assertEqual(bool(result.attribution_notes), qualified)
                self.assertEqual(result.lots[0].source_lot_id, '100')

    def test_screenprinted_fabric_and_grapholithograph_retain_explicit_techniques(self):
        cases = [
            ('Joan Miro\n"Nephtali, of the Tribes of Israel", 1983\nScreenprinted fabric tapestry.\n'
             'Signed in the plate. Edition of 500 copies. Measurements: 178 x 133.5 cm.', 'Screenprinted', False),
            ('Joan Miro\nAfter: "Pantagruel\u2019s Whimsical Dreams"\nGrapholithograph\n'
             'Inscribed in pencil and numbered 196/250\n68x49 cm (image size), framed', 'Grapholithograph', True),
        ]
        for description, medium, qualified in cases:
            with self.subTest(description=description):
                raw, card = evidence()
                raw['description'] = description
                card['heading'] = 'Joan Miro'
                result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].medium, medium)
                self.assertEqual(bool(result.attribution_notes), qualified)
                if qualified:
                    self.assertIn('After', result.lots[0].artist)
                    self.assertIn(result.lots[0].artist, result.lots[0].title)

    def test_new_print_contexts_do_not_qualify_reference_titles_or_unprinted_fabric(self):
        for work in [
            'Woven fabric tapestry. Signed in the plate. Edition of 500 copies.',
            'Poster. Biography: the artist is known for grapholithographs.',
            'Poster. Provenance: Printer: Mourlot. Original color lithograph collection.',
            'Poster. Printer: Mourlot, known for lithographs.',
            'Poster. Printer: Mourlot. The workshop made lithographs.',
            'Display cards for the exhibition "Print after the Work". 44 x 65 cm.',
            'Print (exhibition title) on a display card.',
            'Poster.\nShipping required; room for a screenprinted tapestry.',
        ]:
            with self.subTest(work=work):
                raw, card = evidence()
                raw['description'] = 'Joan Miro\nThe Garden\n' + work
                card['heading'] = 'Joan Miro'
                result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
                self.assertEqual(result.lots, [])
                self.assertEqual(len(result.rejected_lots), 1)

    def test_sold_card_during_live_sale_is_rejected_without_overwriting_saved_observation(self):
        initial = self.run_import(bundle())
        saved = initial.lots[0]
        for sold_price in ['\u20ac2,800', 'CHF 300', 'USD 220']:
            with self.subTest(sold_price=sold_price):
                raw, card = evidence()
                raw.update(saleStatus='IN_PROGRESS', result=0)
                card['text'] = 'LIVE IN PROGRESS\nJoan Miro (1893-1983)\n\nSold\n\n' + sold_price
                result = self.run_import(bundle((raw, card)))
                self.assertFalse(result.errors)
                self.assertEqual(result.fallback_lot_keys, {'drouot:100'})
                self.assertEqual(result.lots[0].to_dict(), saved.to_dict())
                self.assertIn('Posted or ended', result.rejected_lots[0]['reason'])

    def test_sold_work_title_does_not_become_a_posted_result(self):
        raw, card = evidence()
        raw['description'] = 'Joan Miro\n"Sold"\nColor lithograph on paper'
        card['heading'] = 'Joan Miro — Sold'
        card['text'] = 'LIVE IN PROGRESS\nJoan Miro — Sold\n\nEstimation\n\u20ac600 - 800'
        result = validate_drouot_capture(bundle((raw, card)), [ENTRY], now=NOW)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].title, 'Sold')
