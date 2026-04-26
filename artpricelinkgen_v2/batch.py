from pathlib import Path

import pandas as pd

from artpricelinkgen_v2.artist_id_resolver import ArtpriceArtistIdResolver
from artpricelinkgen_v2.artist_id_store import ArtistIdWorkbookStore
from artpricelinkgen_v2.config import (
    ARTPRICE_LINK_COLUMN,
    ARTIST_COLUMN,
    ARTIST_ID_COLUMN,
    KEYWORD_COLUMN,
    MISSING_SEARCH_COLUMN,
    SOURCE_MODE_COLUMN,
    STATUS_COLUMN,
    TITLE_COLUMN,
    UNKNOWN_ARTIST_MESSAGE,
)
from artpricelinkgen_v2.models import ExtractedListing
from artpricelinkgen_v2.url_builder import ArtpriceURLBuilder
from artpricelinkgen_v2.workbook_formatting import format_output_workbook


class BatchProcessor:
    def __init__(self, extractor, lookup, logger, resolve_missing_artist_ids: bool = True):
        self.extractor = extractor
        self.lookup = lookup
        self.logger = logger
        self.resolve_missing_artist_ids = resolve_missing_artist_ids
        self.resolver = ArtpriceArtistIdResolver()
        self._resolved_artist_cache = {}
        self._artist_id_store = None

    @staticmethod
    def detect_column(df: pd.DataFrame, names):
        lower_map = {str(col).strip().lower(): col for col in df.columns}
        for name in names:
            if name in lower_map:
                return lower_map[name]
        return None

    def detect_artist_column(self, df: pd.DataFrame):
        return self.detect_column(df, ["artist", "artists", "maker", "artist name", "name"])

    def detect_title_column(self, df: pd.DataFrame):
        return self.detect_column(df, ["title", "artwork title", "work title", "lot title", "object title"])

    def _artist_id_workbook_store(self):
        if self._artist_id_store is not None:
            return self._artist_id_store
        lookup_path = getattr(self.lookup, "path", None)
        if not lookup_path:
            return None
        self._artist_id_store = ArtistIdWorkbookStore(lookup_path, logger=self.logger)
        return self._artist_id_store

    def resolve_and_save_artist_id(self, artist_name: str):
        if not self.resolve_missing_artist_ids:
            return None

        cache_key = self.extractor.clean_artist_name(artist_name).lower()
        if cache_key in self._resolved_artist_cache:
            return self._resolved_artist_cache[cache_key]

        self.logger(f"Trying web resolver for missing artist ID: {artist_name}")
        try:
            candidate = self.resolver.resolve(artist_name)
        except Exception as exc:
            self.logger(f"Artist ID resolver failed for {artist_name}: {exc}")
            self._resolved_artist_cache[cache_key] = None
            return None

        if not candidate:
            self.logger(f"No high-confidence Artprice ID found for: {artist_name}")
            self._resolved_artist_cache[cache_key] = None
            return None

        self.logger(
            f"Resolved Artprice artist ID for {artist_name}: {candidate.artist_id} "
            f"({candidate.confidence}, score {candidate.score:.2f})"
        )
        self.logger(f"Resolver source URL: {candidate.url}")

        store = self._artist_id_workbook_store()
        if store:
            try:
                appended = store.append_artist_id(
                    artist=artist_name,
                    artist_id=candidate.artist_id,
                    source_url=candidate.url,
                    confidence=candidate.confidence,
                )
                if appended and getattr(self.lookup, "path", None):
                    self.lookup.load_file(self.lookup.path)
                    self.logger("Reloaded Artist ID lookup after resolver append.")
            except Exception as exc:
                self.logger(f"Could not append resolved Artist ID to workbook: {exc}")

        self._resolved_artist_cache[cache_key] = candidate.artist_id
        return candidate.artist_id

    def process_workbook(self, input_path: str, exact_match: bool, all_terms: bool, progress_callback=None):
        df = pd.read_excel(input_path)
        if df.empty:
            raise ValueError("The spreadsheet is empty.")

        artist_col = self.detect_artist_column(df)
        title_col = self.detect_title_column(df)
        if not (artist_col and title_col):
            raise ValueError("Could not find Artist and Title columns in that spreadsheet.")

        result_df = df.copy()
        result_df = result_df.astype(object)

        for col in [ARTIST_COLUMN, TITLE_COLUMN, ARTIST_ID_COLUMN, KEYWORD_COLUMN, ARTPRICE_LINK_COLUMN, STATUS_COLUMN, SOURCE_MODE_COLUMN]:
            if col not in result_df.columns:
                result_df[col] = ""

        missing_artists = set()
        total = len(result_df)

        for row_num, idx in enumerate(result_df.index, start=1):
            artist = str(result_df.at[idx, artist_col]).strip() if pd.notna(result_df.at[idx, artist_col]) else ""
            title = str(result_df.at[idx, title_col]).strip() if pd.notna(result_df.at[idx, title_col]) else ""

            if not artist or not title:
                result_df.at[idx, STATUS_COLUMN] = "Skipped: missing artist/title"
                result_df.at[idx, SOURCE_MODE_COLUMN] = "sheet"
                if progress_callback:
                    progress_callback(row_num, total, result_df.at[idx, STATUS_COLUMN])
                continue

            listing = ExtractedListing(
                artist=self.extractor.clean_artist_name(artist),
                title=self.extractor.clean_title(title),
                source_url=input_path,
            )

            result_df.at[idx, ARTIST_COLUMN] = listing.artist
            result_df.at[idx, TITLE_COLUMN] = listing.title
            result_df.at[idx, SOURCE_MODE_COLUMN] = "sheet"

            artist_id = self.lookup.lookup(listing.artist)
            resolved_by_web = False
            if not artist_id:
                artist_id = self.resolve_and_save_artist_id(listing.artist)
                resolved_by_web = bool(artist_id)

            keyword = ArtpriceURLBuilder.build_keyword(listing.title, exact_match, all_terms)

            if not artist_id:
                link = ArtpriceURLBuilder.build_url_without_artist(listing.title, exact_match, all_terms)
                result_df.at[idx, ARTIST_ID_COLUMN] = ""
                result_df.at[idx, KEYWORD_COLUMN] = keyword
                result_df.at[idx, ARTPRICE_LINK_COLUMN] = link
                result_df.at[idx, STATUS_COLUMN] = UNKNOWN_ARTIST_MESSAGE
                missing_artists.add(listing.artist)
                self.logger(f"Missing artist ID match: {listing.artist}")
                self.logger(f"Generated fallback batch link without artist ID for: {listing.artist}")
                if progress_callback:
                    progress_callback(row_num, total, result_df.at[idx, STATUS_COLUMN])
                continue

            link = ArtpriceURLBuilder.build_url(artist_id, listing.title, exact_match, all_terms)
            result_df.at[idx, ARTIST_ID_COLUMN] = str(artist_id)
            result_df.at[idx, KEYWORD_COLUMN] = keyword
            result_df.at[idx, ARTPRICE_LINK_COLUMN] = link
            result_df.at[idx, STATUS_COLUMN] = "OK - resolved artist ID" if resolved_by_web else "OK"
            if progress_callback:
                progress_callback(row_num, total, result_df.at[idx, STATUS_COLUMN])

        output_path = self.build_output_path(input_path)
        result_df.to_excel(output_path, index=False)
        format_output_workbook(output_path, link_header=ARTPRICE_LINK_COLUMN)
        missing_file = self.export_missing_artists_file(missing_artists)
        return output_path, missing_file, artist_col, title_col, result_df

    @staticmethod
    def build_output_path(input_path: str) -> str:
        p = Path(input_path)
        return str(p.with_name(f"{p.stem}_with_Artprice_Links{p.suffix}"))

    def export_missing_artists_file(self, missing_artists):
        if not missing_artists:
            return None
        desktop = Path.home() / "Desktop"
        try:
            desktop.mkdir(parents=True, exist_ok=True)
        except Exception:
            desktop = Path.cwd()

        output = desktop / "Missing Artist Artprice IDs.xlsx"
        rows = []
        for artist in sorted({self.extractor.clean_artist_name(a) for a in missing_artists if str(a).strip()}):
            rows.append(
                {
                    "Artist": artist,
                    "ID": "",
                    MISSING_SEARCH_COLUMN: ArtpriceURLBuilder.build_artist_search_url(artist),
                }
            )

        pd.DataFrame(rows).to_excel(output, index=False)
        format_output_workbook(str(output), link_header=MISSING_SEARCH_COLUMN)
        self.logger(f"Missing Artist Artprice IDs exported to desktop: {output}")
        return str(output)
