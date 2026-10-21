"""Preview a browser capture offline; --sync imports and uploads observed lots."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogapp.watchlist_bookmark_source import load_bookmark_source
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_invaluable_pages import import_saved_invaluable_pages
from catalogapp.watchlist_sync import sync_watchlist_lots


def default_cache_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".secondstate"))
    return root / "SecondState" / "ArtistWatchlist" / "watchlist.sqlite3"


def preview_capture(paths, entries, cache_path: Path, *, horizon_days: int = 7):
    """Use SQLite backup for a consistent, read-only copy of an existing cache."""
    with TemporaryDirectory(prefix="secondstate-capture-preview-") as directory:
        isolated = Path(directory) / "watchlist.sqlite3"
        if cache_path.exists():
            source = sqlite3.connect(cache_path.resolve().as_uri() + "?mode=ro", uri=True)
            target = sqlite3.connect(isolated)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        with WatchlistCache(isolated) as cache:
            return import_saved_invaluable_pages(paths, entries, cache, horizon_days=horizon_days)


def observed_lots(result):
    # The importer also returns previously cached lots for Studio's agenda.
    # A capture upload includes only observations accepted from this import.
    return [lot for lot in result.lots if lot.cache_key not in result.fallback_lot_keys]


def capture_report(result, *, mode: str):
    lots = observed_lots(result)
    return {
        "summary": {
            "mode": mode,
            "observed_lots": len(lots),
            "artists": len({lot.artist for lot in lots}),
            "sessions": dict(Counter(lot.relevant_at for lot in lots)),
            "observed_from": min((lot.last_seen_at for lot in lots), default=""),
            "observed_to": max((lot.last_seen_at for lot in lots), default=""),
            "cached_fallbacks_excluded": len(result.fallback_lot_keys),
            "metrics": asdict(result.metrics),
            "errors": result.errors,
            "notices": result.notices,
        },
        "lots": [{key: value for key, value in lot.to_dict().items() if key != "saved_image_base64"} for lot in lots],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path, help="Downloaded capture bundle(s) or legacy snapshot files.")
    parser.add_argument("--bookmarks", type=Path, default=ROOT / "docs" / "artist-links.html")
    parser.add_argument("--cache", type=Path, default=default_cache_path(),
                        help="Watchlist cache to compare against; preview never changes it. --sync also saves here.")
    parser.add_argument("--report", type=Path, help="Write a normalized lot audit without image pixels.")
    parser.add_argument("--sync", action="store_true", help="Save validated observations locally and upload them to Calendar.")
    args = parser.parse_args(argv)
    entries, _ = load_bookmark_source(args.bookmarks)
    chosen = [entry for entry in entries if entry.source == "Invaluable" and not entry.is_sale]
    if not chosen:
        parser.error("The bookmarks file has no Invaluable artist searches.")
    result = preview_capture(args.captures, chosen, args.cache)
    report = capture_report(result, mode="preview")
    print(json.dumps(report["summary"], ensure_ascii=True, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.errors:
        print("Resolve the reported capture errors before syncing. The original cache and Calendar were not changed.", file=sys.stderr)
        return 1
    if not args.sync:
        return 0
    if not observed_lots(result):
        print("No eligible observations to upload. The original cache and Calendar were not changed.")
        return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    api_key = os.environ.get("CATALOG_API_KEY", "")
    if not api_key:
        raise ValueError("CATALOG_API_KEY is required for Calendar sync; the original cache was not changed.")
    with WatchlistCache(args.cache) as cache:
        result = import_saved_invaluable_pages(args.captures, chosen, cache, horizon_days=7)
    if result.errors:
        print("Capture contents changed or conflicted during import. Calendar was not updated; inspect the local import errors.", file=sys.stderr)
        print(json.dumps(result.errors, ensure_ascii=True, indent=2))
        return 1
    lots = observed_lots(result)
    if not lots:
        print("No eligible observations remain to upload.")
        return 0
    _, research = load_bookmark_source(args.bookmarks, artist_names={lot.artist for lot in lots})
    response = sync_watchlist_lots(
        lots, base_url=os.environ.get("SECONDSTATE_BASE_URL", "https://secondstate.art"),
        api_key=api_key, artist_artprice_links=research.links_by_artist,
    )
    print(response.summary())
    if args.report:
        report = capture_report(result, mode="synced")
        report["summary"]["calendar_result"] = response.summary()
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"Capture import failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
