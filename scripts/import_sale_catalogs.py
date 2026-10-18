"""Validate saved Doyle/Phillips catalogs and optionally upload them to Calendar."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogapp.bookmark_watchlist import canonicalize_bookmark_url
from catalogapp.watchlist_bookmark_source import load_bookmark_source
from catalogapp.watchlist_sale_pages import read_saved_sale_pages
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_sync import sync_watchlist_lots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bookmarks", type=Path, required=True)
    parser.add_argument("--source", choices=("Doyle", "Phillips"), required=True)
    parser.add_argument("--sale-url", help="Select one sale if the bookmarks contain several for this house.")
    parser.add_argument("--pages", type=Path, nargs="+", required=True)
    parser.add_argument("--cache", type=Path, help="Also retain normalized lots in this local Watchlist cache.")
    parser.add_argument("--report", type=Path, help="Write a public lot audit (without artwork pixels).")
    parser.add_argument("--sync", action="store_true", help="Upload validated lots using the configured Calendar API.")
    args = parser.parse_args()
    entries, _ = load_bookmark_source(args.bookmarks)
    selected = [entry for entry in entries if entry.source == args.source and entry.is_sale
                and (not args.sale_url or entry.url == canonicalize_bookmark_url(args.sale_url))]
    if len(selected) != 1:
        parser.error("Select exactly one sale with --sale-url, matching a sale in the bookmarks.")
    lots, notices = read_saved_sale_pages(args.pages, selected[0])
    _, research = load_bookmark_source(args.bookmarks, artist_names={lot.artist for lot in lots})
    summary = {
        "source": args.source, "sale_url": selected[0].url, "lots": len(lots),
        "artists": len({lot.artist for lot in lots}),
        "sessions": dict(Counter(lot.relevant_at for lot in lots)),
        "saved_images": sum(bool(lot.saved_image_base64) for lot in lots),
        "artist_bookmark_links": sum(lot.artist in research.links_by_artist for lot in lots),
        "title_unavailable": sum(lot.title == f"Lot {lot.lot_number}" for lot in lots),
        "notices": notices,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"summary": summary, "lots": [
            {key: value for key, value in lot.to_dict().items() if key != "saved_image_base64"}
            for lot in lots
        ]}, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.cache:
        with WatchlistCache(args.cache) as cache:
            for lot in lots:
                cache.import_shared_lot(lot, watch_urls=[selected[0].url])
    if args.sync:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        result = sync_watchlist_lots(
            lots, base_url=os.environ.get("SECONDSTATE_BASE_URL", "https://secondstate.art"),
            api_key=os.environ.get("CATALOG_API_KEY", ""), artist_artprice_links=research.links_by_artist,
        )
        print(result.summary())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Catalog import failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
