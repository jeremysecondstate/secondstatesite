"""Offline coverage for public Artprice URL resolution and explicit backfills."""

from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from artpricelinkgen.artist_id_resolver import ArtpriceArtistIdResolver
from catalogapp.artprice_artist_links import artist_identity_key, extract_artprice_bookmarks
from catalogapp.artprice_link_backfill import (
    add_resolution_bookmarks,
    load_resolution_records,
    resolution_record,
    save_resolution_records,
)
from secondstateapp.models import AuctionWatchArtist, AuctionWatchLot


KELLY = "https://www.artprice.com/artist/15231/ellsworth-kelly"
SHEELER = "https://www.artprice.com/artist/26539/charles-r-sheeler"
BOOKMARKS = "<DL><p>\r\n    <DT><H3>ARTPRICE</H3>\r\n    <DL><p>\r\n    </DL><p>\r\n</DL><p>\r\n"


def evidence(name="Ellsworth Kelly", url=KELLY):
    return resolution_record(name, ArtpriceArtistIdResolver.candidate_from_url(name, url))


class ArtistIdResolverTests(SimpleTestCase):
    def test_complete_names_accents_and_comma_order_are_accepted(self):
        for name, url in (
            ("Kelly, Ellsworth", KELLY),
            ("Charles Sheeler", SHEELER),
            ("Charles R. Sheeler", SHEELER),
            ("Ellsworth Kelly (1923-2015)", KELLY),
            ("Joan Miró", "https://www.artprice.com/artist/19979/joan-miro"),
            ("Arman", "https://www.artprice.com/artist/788/arman"),
        ):
            with self.subTest(name=name):
                self.assertTrue(ArtpriceArtistIdResolver.candidate_from_url(name, url).is_high_confidence)

    def test_partial_names_extra_names_and_attributions_are_not_auto_accepted(self):
        for name, url in (
            ("Kelly", KELLY),
            ("Ellsworth Kelly", KELLY + "-jr"),
            ("Charles Sheeler", "https://www.artprice.com/artist/1/charles-john-sheeler"),
            ("After Ellsworth Kelly", KELLY),
            ("Vincent van Gogh", "https://www.artprice.com/artist/1/vincent-gogh"),
            ("Pablo Picasso", "https://www.artprice.com/artist/1/pablo-jose-ruiz-picasso"),
        ):
            with self.subTest(name=name, url=url):
                self.assertFalse(ArtpriceArtistIdResolver.candidate_from_url(name, url).is_high_confidence)

    def test_only_real_artprice_destination_urls_are_candidates(self):
        for url in (
            "https://example.com/?next=" + KELLY,
            "https://www.artprice.com.evil.test/artist/15231/ellsworth-kelly",
            "https://user@www.artprice.com/artist/15231/ellsworth-kelly",
            "https://www.artprice.com:444/artist/15231/ellsworth-kelly",
            "https://www.artprice.com/artist/15231/ellsworth-kelly.evil",
            "javascript:" + KELLY,
            KELLY + "\n#x",
        ):
            with self.subTest(url=url):
                self.assertIsNone(ArtpriceArtistIdResolver.candidate_from_url("Ellsworth Kelly", url))

    def test_conflicting_artist_ids_are_unresolved(self):
        resolver = ArtpriceArtistIdResolver()
        with patch.object(resolver, "search_candidate_urls", return_value=[KELLY, KELLY.replace("15231", "999")]):
            self.assertIsNone(resolver.resolve("Ellsworth Kelly"))

    def test_repeated_same_artist_id_is_resolved(self):
        resolver = ArtpriceArtistIdResolver()
        with patch.object(resolver, "search_candidate_urls", return_value=[KELLY, KELLY + "/lots/pasts"]):
            self.assertEqual(resolver.resolve("Ellsworth Kelly").artist_id, "15231")

    def test_wrapped_search_links_are_extracted_without_promoting_arbitrary_page_text(self):
        page = ('<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.artprice.com%2Fartist%2F15231%2Fellsworth-kelly'
                '&amp;rut=abc">Artist</a> ' + SHEELER)
        self.assertEqual(ArtpriceArtistIdResolver.extract_urls_from_search_html(page), [KELLY])

    def test_search_challenge_is_reported_as_failure(self):
        with patch("artpricelinkgen.artist_id_resolver.urlopen") as request:
            request.return_value.__enter__.return_value.read.return_value = b'<form id="challenge-form">anomaly.js</form>'
            with self.assertRaisesRegex(ValueError, "challenge"):
                ArtpriceArtistIdResolver().resolve("Ellsworth Kelly")

    def test_search_response_size_is_bounded_before_decoding(self):
        with patch("artpricelinkgen.artist_id_resolver.urlopen") as request:
            request.return_value.__enter__.return_value.read.return_value = b"\xc3\xa9" * 1_000_001
            with self.assertRaisesRegex(ValueError, "size limit"):
                ArtpriceArtistIdResolver().resolve("Ellsworth Kelly")


class ArtpriceRegistryPersistenceTests(SimpleTestCase):
    def test_persistence_is_idempotent_and_preserves_original_evidence(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "registry.json"
            first = evidence()
            self.assertEqual(save_resolution_records(target, [first]), 1)
            second = {**first, "resolved_at": "a later date"}
            self.assertEqual(save_resolution_records(target, [second]), 0)
            self.assertEqual(load_resolution_records(target), [first])

    def test_corrupt_registry_is_never_replaced(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "registry.json"
            target.write_text("not-json", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_resolution_records(target, [evidence()])
            self.assertEqual(target.read_text(encoding="utf-8"), "not-json")

    def test_conflicting_evidence_is_rejected_without_modifying_saved_registry(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "registry.json"
            original = evidence()
            save_resolution_records(target, [original])
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                save_resolution_records(target, [evidence(url=KELLY.replace("15231", "999"))])
            self.assertEqual(load_resolution_records(target), [original])

    def test_wrong_artist_name_or_source_path_cannot_be_saved_or_loaded(self):
        invalid_records = [
            {**evidence(), "name": "Jane Artist"},
            {**evidence(), "source_url": KELLY.replace("ellsworth-kelly", "kelly-ellsworth")},
            {**evidence(), "source_url": KELLY.replace("ellsworth-kelly", "pablo-picasso")},
        ]
        with TemporaryDirectory() as directory:
            target = Path(directory) / "registry.json"
            save_resolution_records(target, [evidence()])
            original_bytes = target.read_bytes()
            for record in invalid_records:
                with self.subTest(record=record):
                    with self.assertRaises(ValueError):
                        save_resolution_records(target, [record])
                    self.assertEqual(target.read_bytes(), original_bytes)
                    bad_target = Path(directory) / "invalid-registry.json"
                    bad_target.write_text(json.dumps({"version": 1, "artists": [record]}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_resolution_records(bad_target)

    def test_bookmark_insert_preserves_other_content_line_endings_and_is_idempotent(self):
        updated, count = add_resolution_bookmarks(BOOKMARKS, [evidence()])
        self.assertEqual(count, 1)
        self.assertNotIn("\n", updated.replace("\r\n", ""))
        extracted = extract_artprice_bookmarks(updated)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].artist_id, "15231")
        self.assertIn("&amp;p=1", updated)
        self.assertEqual(add_resolution_bookmarks(updated, [evidence()]), (updated, 0))
        self.assertEqual(updated.replace(next(line for line in updated.splitlines(keepends=True) if "<A " in line), ""), BOOKMARKS)

    def test_invalid_bookmark_folder_fails_before_write(self):
        with self.assertRaisesRegex(ValueError, "ARTPRICE folder"):
            add_resolution_bookmarks("<DL></DL>", [evidence()])


class ArtpriceBackfillCommandTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bookmarks = self.directory / "bookmarks.html"
        self.bookmarks.write_bytes(BOOKMARKS.encode("utf-8"))
        self.registry = self.directory / "registry.json"
        self.artist = AuctionWatchArtist.objects.create(
            name="Ellsworth Kelly", normalized_name=artist_identity_key("Ellsworth Kelly"),
        )
        self.candidate = ArtpriceArtistIdResolver.candidate_from_url("Ellsworth Kelly", KELLY)

    def command(self, **options):
        out, err = StringIO(), StringIO()
        call_command("backfill_artprice_artist_links", bookmarks=self.bookmarks, registry=self.registry,
                     stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    def test_default_is_dry_run(self):
        with patch("artpricelinkgen.artist_id_resolver.ArtpriceArtistIdResolver.resolve", return_value=self.candidate):
            output, errors = self.command()
        self.assertIn("Dry run: 1 match", output)
        self.assertFalse(errors)
        self.assertFalse(self.registry.exists())
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.artprice_url, "")
        self.assertEqual(self.bookmarks.read_bytes(), BOOKMARKS.encode("utf-8"))

    def test_apply_saves_registry_bookmarks_and_blank_db_link_without_changing_lot_link(self):
        lot = AuctionWatchLot.objects.create(source="Doyle", source_lot_id="1", artist=self.artist.name,
                                            watchlist_artist=self.artist, artprice_url="https://www.artprice.com/lot/123")
        with patch("artpricelinkgen.artist_id_resolver.ArtpriceArtistIdResolver.resolve", return_value=self.candidate) as resolve:
            self.command(apply=True, write_bookmarks=True)
            self.command(apply=True, write_bookmarks=True)
        resolve.assert_called_once_with("Ellsworth Kelly")
        self.artist.refresh_from_db()
        lot.refresh_from_db()
        self.assertEqual(self.artist.artprice_url, evidence()["url"])
        self.assertEqual(lot.artprice_url, "https://www.artprice.com/lot/123")
        self.assertEqual(len(json.loads(self.registry.read_text(encoding="utf-8"))["artists"]), 1)
        self.assertEqual(len(extract_artprice_bookmarks(self.bookmarks.read_text(encoding="utf-8"))), 1)

    def test_existing_manual_link_is_not_searched_or_overwritten(self):
        self.artist.artprice_url = KELLY + "/lots/pasts?idcategory=1"
        self.artist.save()
        with patch("artpricelinkgen.artist_id_resolver.ArtpriceArtistIdResolver.resolve") as resolve:
            self.command(apply=True)
        resolve.assert_not_called()
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.artprice_url, KELLY + "/lots/pasts?idcategory=1")

    def test_bookmarked_artist_is_reused_without_search(self):
        updated, _ = add_resolution_bookmarks(BOOKMARKS, [evidence()])
        self.bookmarks.write_text(updated, encoding="utf-8")
        with patch("artpricelinkgen.artist_id_resolver.ArtpriceArtistIdResolver.resolve") as resolve:
            self.command(apply=True)
        resolve.assert_not_called()
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.artprice_url, evidence()["url"])

    def test_lot_only_artist_is_discovered_without_creating_an_identity(self):
        self.artist.delete()
        AuctionWatchLot.objects.create(source="Phillips", source_lot_id="1", artist="Ellsworth Kelly")
        with patch("artpricelinkgen.artist_id_resolver.ArtpriceArtistIdResolver.resolve", return_value=self.candidate):
            self.command(apply=True)
        self.assertTrue(self.registry.exists())
        self.assertFalse(AuctionWatchArtist.objects.exists())

    def test_fuzzy_bookmark_match_cannot_fill_an_attributed_artist(self):
        updated, _ = add_resolution_bookmarks(BOOKMARKS, [evidence()])
        self.bookmarks.write_text(updated, encoding="utf-8")
        self.artist.name = "After Ellsworth Kelly"
        self.artist.normalized_name = artist_identity_key(self.artist.name)
        self.artist.save()
        with patch("artpricelinkgen.artist_id_resolver.ArtpriceArtistIdResolver.resolve", return_value=None) as resolve:
            output, _ = self.command(apply=True)
        resolve.assert_called_once_with("After Ellsworth Kelly")
        self.assertIn("UNRESOLVED After Ellsworth Kelly", output)
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.artprice_url, "")

    def test_explicit_artist_and_limit_bound_searches(self):
        with patch("artpricelinkgen.artist_id_resolver.ArtpriceArtistIdResolver.resolve", return_value=None) as resolve:
            self.command(artist=["Charles Sheeler", "Ellsworth Kelly"], limit=1)
        resolve.assert_called_once_with("Charles Sheeler")

    def test_failed_search_remains_unresolved_and_does_not_save_guessed_links(self):
        with patch("artpricelinkgen.artist_id_resolver.ArtpriceArtistIdResolver.resolve", side_effect=TimeoutError("timeout")):
            _, errors = self.command(apply=True)
        self.assertIn("UNRESOLVED Ellsworth Kelly: timeout", errors)
        self.assertFalse(self.registry.exists())
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.artprice_url, "")

    def test_write_bookmarks_requires_explicit_apply(self):
        with self.assertRaisesRegex(CommandError, "requires --apply"):
            self.command(write_bookmarks=True)

    def test_supplied_candidates_resolve_offline_and_use_keys_as_requested_artists(self):
        candidates = self.directory / "candidates.json"
        candidates.write_text(json.dumps({"Charles Sheeler": [SHEELER]}), encoding="utf-8")
        with patch("artpricelinkgen.artist_id_resolver.urlopen") as request:
            output, _ = self.command(candidates=candidates, apply=True)
        request.assert_not_called()
        records = load_resolution_records(self.registry)
        self.assertEqual([record["name"] for record in records], ["Charles Sheeler"])
        self.assertEqual(records[0]["source"], "supplied-public-url")
        self.assertIn("Artists: 1", output)

    def test_conflicting_supplied_candidates_cannot_be_persisted(self):
        candidates = self.directory / "candidates.json"
        candidates.write_text(json.dumps({"Ellsworth Kelly": [KELLY, KELLY.replace("15231", "999")]}), encoding="utf-8")
        with patch("artpricelinkgen.artist_id_resolver.urlopen") as request:
            output, _ = self.command(candidates=candidates, apply=True)
        request.assert_not_called()
        self.assertIn("UNRESOLVED Ellsworth Kelly", output)
        self.assertFalse(self.registry.exists())

    def test_artists_file_restricts_supplied_candidate_set_without_network(self):
        candidates = self.directory / "candidates.json"
        candidates.write_text(json.dumps({"Charles Sheeler": [SHEELER], "Ellsworth Kelly": [KELLY]}), encoding="utf-8")
        artists = self.directory / "artists.txt"
        artists.write_text("Ellsworth Kelly\n\n", encoding="utf-8")
        with patch("artpricelinkgen.artist_id_resolver.urlopen") as request:
            self.command(candidates=candidates, artists_file=artists, apply=True)
        request.assert_not_called()
        self.assertEqual([record["name"] for record in load_resolution_records(self.registry)], ["Ellsworth Kelly"])

    def test_missing_offline_candidate_does_not_fall_back_to_network(self):
        candidates = self.directory / "candidates.json"
        candidates.write_text("{}", encoding="utf-8")
        with patch("artpricelinkgen.artist_id_resolver.urlopen") as request:
            output, _ = self.command(candidates=candidates, artist=["Ellsworth Kelly"], apply=True)
        request.assert_not_called()
        self.assertIn("UNRESOLVED Ellsworth Kelly", output)
