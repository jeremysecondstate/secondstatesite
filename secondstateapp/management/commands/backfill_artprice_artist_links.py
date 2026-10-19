"""Resolve missing artist research links outside Calendar HTTP requests."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from artpricelinkgen.artist_id_resolver import ArtpriceArtistIdResolver
from catalogapp.artprice_artist_links import artist_identity_key, parse_artprice_artist_links
from catalogapp.artprice_link_backfill import (
    add_resolution_bookmarks,
    atomic_write_text,
    load_resolution_records,
    resolution_record,
    save_resolution_records,
)
from catalogapp.bookmark_watchlist import parse_bookmarks_html
from secondstateapp.models import AuctionWatchArtist, AuctionWatchLot


class Command(BaseCommand):
    help = (
        "Find missing Calendar/watchlist Artprice artist links using artpricelinkgen. "
        "Dry-run by default; --apply saves public URL evidence and fills blank artist links."
    )

    def add_arguments(self, parser):
        parser.add_argument("--artist", action="append", help="Resolve only this artist; repeat for several names.")
        parser.add_argument("--artists-file", type=Path, help="UTF-8 file with one artist name per line.")
        parser.add_argument("--candidates", type=Path,
                            help="Offline JSON object mapping artist names to lists of observed Artprice URLs; never searches the network.")
        parser.add_argument("--limit", type=int, default=20, help="Maximum missing artists to search (default: 20).")
        parser.add_argument("--timeout", type=int, default=8, help="Seconds per public search request (default: 8).")
        parser.add_argument("--bookmarks", type=Path, default=settings.BASE_DIR / "docs" / "artist-links.html")
        parser.add_argument("--registry", type=Path, default=settings.BASE_DIR / "docs" / "artprice-artist-links.json")
        parser.add_argument("--apply", action="store_true", help="Save matches and fill blank artist records.")
        parser.add_argument("--write-bookmarks", action="store_true", help="With --apply, also append to the ARTPRICE folder.")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 1000:
            raise CommandError("--limit must be between 1 and 1000.")
        if not 1 <= options["timeout"] <= 60:
            raise CommandError("--timeout must be between 1 and 60 seconds.")
        if options["write_bookmarks"] and not options["apply"]:
            raise CommandError("--write-bookmarks requires --apply.")
        try:
            # newline='' keeps the export's original line endings when adding links.
            with options["bookmarks"].open(encoding="utf-8", newline="") as handle:
                html = handle.read()
            records = load_resolution_records(options["registry"])
            supplied_candidates = self._read_candidates(options["candidates"]) if options["candidates"] else None
            file_names = []
            if options["artists_file"]:
                if options["artists_file"].stat().st_size > 2_000_000:
                    raise ValueError("The artists file exceeds 2 MB.")
                file_names = options["artists_file"].read_text(encoding="utf-8-sig").splitlines()
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        artists = list(AuctionWatchArtist.objects.all())
        if options["artist"] or options["artists_file"]:
            names = [*(options["artist"] or []), *file_names]
        elif supplied_candidates is not None:
            names = list(supplied_candidates)
        else:
            names = [artist.name for artist in artists]
            names.extend(
                watch_name or name
                for name, watch_name in AuctionWatchLot.objects.filter(superseded_by__isnull=True)
                .values_list("artist", "artist_watchlist_name").distinct()
            )
            names.extend(entry.artist for entry in parse_bookmarks_html(html) if entry.artist and not entry.is_sale)
        by_identity = {}
        for name in names:
            name = str(name or "").strip()
            if name and len(name) <= 255:
                by_identity.setdefault(artist_identity_key(name), name)
        names = sorted(by_identity.values(), key=str.casefold)
        bookmark_links = parse_artprice_artist_links(html, names).links_by_artist
        bookmark_links = {
            name: url for name, url in bookmark_links.items()
            if (candidate := ArtpriceArtistIdResolver.candidate_from_url(name, url))
            and candidate.is_high_confidence
        }
        existing = {artist_identity_key(name): url for name, url in bookmark_links.items()}
        existing.update({artist_identity_key(record["name"]): record["url"] for record in records})
        existing.update({artist_identity_key(artist.name): artist.artprice_url for artist in artists if artist.artprice_url})
        missing = [name for name in names if artist_identity_key(name) not in existing]
        self.stdout.write(f"Artists: {len(names)}; already linked: {len(names) - len(missing)}; missing: {len(missing)}.")
        resolver = ArtpriceArtistIdResolver(timeout_seconds=options["timeout"])
        candidates_by_key = {}
        for name, urls in (supplied_candidates or {}).items():
            candidates_by_key.setdefault(artist_identity_key(name), []).extend(urls)
        resolved = []
        for name in missing[:options["limit"]]:
            try:
                if supplied_candidates is None:
                    candidate = resolver.resolve(name)
                else:
                    candidate = resolver.resolve_candidates(name, candidates_by_key.get(artist_identity_key(name), []))
                    if candidate is not None:
                        candidate.source = "supplied-public-url"
                if candidate is None:
                    self.stdout.write(f"UNRESOLVED {name}: no unique complete-name match.")
                    continue
                record = resolution_record(name, candidate)
            except Exception as exc:
                self.stderr.write(f"UNRESOLVED {name}: {exc}")
                continue
            resolved.append(record)
            self.stdout.write(f'MATCH {name}: {record["url"]} (public search URL evidence)')

        if not options["apply"]:
            self.stdout.write(f"Dry run: {len(resolved)} match(es); no files or artist records changed. Use --apply to save.")
            return
        try:
            # Validate bookmark structure before any write. Include prior registry
            # rows so rerunning with --write-bookmarks can publish earlier matches.
            updated_html, bookmark_count = add_resolution_bookmarks(html, [*records, *resolved]) if options["write_bookmarks"] else (html, 0)
            saved = save_resolution_records(options["registry"], resolved)
            if bookmark_count:
                atomic_write_text(options["bookmarks"], updated_html)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        fill_links = {**existing, **{artist_identity_key(record["name"]): record["url"] for record in resolved}}
        updated = 0
        with transaction.atomic():
            for artist in artists:
                url = fill_links.get(artist_identity_key(artist.name))
                candidate = resolver.candidate_from_url(artist.name, url) if url else None
                if candidate and candidate.is_high_confidence and not artist.artprice_url:
                    updated += AuctionWatchArtist.objects.filter(pk=artist.pk, artprice_url="").update(artprice_url=url)
        self.stdout.write(f"Saved {saved} new registry match(es), {bookmark_count} bookmarks, and {updated} blank artist link(s).")

    @staticmethod
    def _read_candidates(path):
        if path.stat().st_size > 2_000_000:
            raise ValueError("The candidates file exceeds 2 MB.")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or len(payload) > 10000:
            raise ValueError("Candidates must be a JSON object mapping artist names to URL lists.")
        for name, urls in payload.items():
            if (not isinstance(name, str) or not name.strip() or len(name) > 255
                    or not isinstance(urls, list) or len(urls) > 100
                    or any(not isinstance(url, str) or len(url) > 2000 for url in urls)):
                raise ValueError("Each candidate artist must have a name and a list of at most 100 URL strings.")
        return payload
