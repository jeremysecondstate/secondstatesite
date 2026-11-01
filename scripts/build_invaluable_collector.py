"""Build the unpacked Chrome/Edge collector with the shared snapshot validator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import parse_qsl, urlsplit
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogapp.bookmark_watchlist import (
    canonicalize_bookmark_url,
    invaluable_search_artists,
    parse_netscape_bookmarks,
    select_invaluable_intake_entries,
)

SOURCE = ROOT / "browser_extensions" / "invaluable_collector"
DEFAULT_OUTPUT = ROOT / "private_data" / "invaluable-collector"
DEFAULT_BOOKMARKS = ROOT / "docs" / "artist-links.html"


def build(output: Path) -> tuple[Path, Path]:
    output = output.resolve()
    if output == SOURCE.resolve() or SOURCE.resolve() in output.parents:
        raise ValueError("Choose a build directory outside the extension source folder.")
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    files = [path for path in SOURCE.iterdir() if path.is_file() and path.suffix in {".json", ".js", ".html", ".css"}]
    names = {path.name for path in files} | {"snapshot-core.js"}
    references = [manifest["background"]["service_worker"], manifest["action"]["default_popup"]]
    for script in manifest.get("content_scripts", []):
        references.extend(script.get("js", []))
        references.extend(script.get("css", []))
    if any(name not in names for name in references):
        raise ValueError("The extension manifest refers to a missing packaged file.")
    output.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copyfile(path, output / path.name)
    shutil.copyfile(ROOT / "scripts" / "invaluable_export_snapshot.js", output / "snapshot-core.js")
    archive = output.with_name(output.name + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(names):
            bundle.write(output / name, arcname=f"invaluable-collector/{name}")
    return output, archive


def portable_instructions(version: str, bookmarks: Path) -> str:
    """Describe the supplied export, including the selected split or legacy lists."""
    entries = select_invaluable_intake_entries(parse_netscape_bookmarks(
        bookmarks.read_text(encoding="utf-8", errors="replace")
    ))
    searches = {}
    for entry in entries:
        artists = invaluable_search_artists(entry.url)
        if artists:
            searches.setdefault(canonicalize_bookmark_url(entry.url), (entry, artists))
    bulk = {url: item for url, item in searches.items() if len(item[1]) > 1}
    selected = bulk or searches
    if not selected:
        raise ValueError("The bookmark export has no Invaluable artist searches.")
    artist_count = len({artist for _, artists in selected.values() for artist in artists})
    search_count = len(selected)
    search_label = "bulk searches" if bulk else "artist searches"
    list_counts = " + ".join(str(len(artists)) for _, artists in selected.values())
    category_keys = {"asian art", "collectibles", "decorative art", "fine art", "furniture", "jewelry"}
    categories = sorted({value for url in selected for key, value in parse_qsl(urlsplit(url).query)
                         if key.casefold() in category_keys and value}, key=str.casefold)
    category_note = ("Selected category filters: " + ", ".join(categories) + "."
                     if categories else "The selected searches have no category restriction.")
    return f"""SECONDSTATE INVALUABLE COLLECTOR v{version}

1. Copy this ZIP to the other PC and Extract All to a stable local folder.
2. In the browser profile where Invaluable loads, open chrome://extensions
   (or edge://extensions). Enable Developer mode, choose Load unpacked,
   and select the collector subfolder containing manifest.json.
3. Open SECONDSTATE Invaluable Collector from the Extensions menu.
4. Choose the included {bookmarks.name} and confirm
   {search_count} {search_label} covering {artist_count} distinct artists ({list_counts}).
5. Choose your inclusive dates and time zone, click Prepare capture, then Start.
6. Keep its auction tab open and let it click Load more automatically.
   If it pauses, inspect the page, resolve any verification yourself, then
   Resume. Resume reloads and recaptures earlier pages before continuing.
   Incomplete searches remain labeled and saved pages remain exportable.
7. Download bundle and save the JSON in the shared SECONDSTATE drive:
   ARTCAL / Invaluable Collector / Captures.

UPDATING AN EXISTING INSTALLATION
Export any previous capture first. Copy the new collector files into the
existing local extension folder, then click Reload on its Extensions card.
Reset the old run and choose these bookmarks to prepare {search_count} searches.
Keep the local extension folder in place after installation.

CALENDAR IMPORT
Collection needs no Python, Git, Studio, or Calendar credentials.
The downloaded JSON can be imported on the original PC. In updated Studio,
first use More > Scan bookmarks HTML with {bookmarks.name} to register all
{artist_count} selected artists individually. Then use More > Import browser capture and update
Calendar. Each lot stays under its own artist.
Tell Codex where the capture file is saved if you want it imported for you.

To import directly on the other PC, update its Studio repository and Python
dependencies and configure its Calendar connection. No credentials or browser
session are included in this package. Capture progress stays per browser
profile; exported JSON files can move between PCs.

The complete named BULK-1A, BULK-1B, BULK-2A, BULK-2B split takes precedence
over legacy bulk links. Otherwise, bulk links take precedence over individual
links. Files with only individual artist links still work.
{category_note}
Saved date filters are removed; your chosen window
filters the imported lots. Up to 100 pages per bulk list, 25 per single artist,
500 pages overall, and 7 MiB of local run data are supported.

After reloading the extension, confirm its first installed run shows
increasing page and lot counts. Packaging the export does not verify live
access or complete a capture.
"""


def build_portable(folder: Path, bookmarks: Path) -> Path:
    """Bundle a built extension and bookmark export without machine credentials."""
    version = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["version"]
    if not bookmarks.is_file():
        raise ValueError(f"Bookmark export not found: {bookmarks}")
    archive = folder.parent / f"SECONDSTATE-Invaluable-Collector-v{version}-bulk.zip"
    instructions = portable_instructions(version, bookmarks)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix in {".json", ".js", ".html", ".css"}:
                bundle.write(path, arcname=f"SECONDSTATE-Invaluable-Collector/collector/{path.name}")
        bundle.write(bookmarks, arcname=f"SECONDSTATE-Invaluable-Collector/{bookmarks.name}")
        bundle.writestr("SECONDSTATE-Invaluable-Collector/START-HERE.txt", instructions)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--portable", action="store_true", help="Also package the extension, bulk bookmarks, and setup guide for another PC.")
    parser.add_argument("--bookmarks", type=Path, default=DEFAULT_BOOKMARKS)
    args = parser.parse_args()
    folder, archive = build(args.output)
    print(f"Load unpacked: {folder}\nZIP: {archive}")
    if args.portable:
        print(f"Portable ZIP: {build_portable(folder, args.bookmarks)}")
