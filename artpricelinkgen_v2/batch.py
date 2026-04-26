from pathlib import Path

import pandas as pd

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
    def __init__(self, extractor, lookup, logger):
        self.extractor = extractor
        self.lookup = lookup
        self.logger = logger

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
            result_df.at[idx, STATUS_COLUMN] = "OK"
            if progress_callback:
                progress_callback(row_num, total, "OK")

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
