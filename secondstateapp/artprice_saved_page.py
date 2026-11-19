"""Read artwork thumbnails from a browser's saved Artprice page and companion files."""

import base64
from pathlib import PurePosixPath
import re
from urllib.parse import unquote
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from bs4 import BeautifulSoup

from .artprice_max_bid import parse_auction_results
from .calendar_images import MAX_SAVED_IMAGE_BYTES, prepare_saved_calendar_image


MAX_ARTPRICE_HTML_BYTES = 5 * 1024 * 1024
MAX_ARTPRICE_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_ARTPRICE_UNPACKED_BYTES = 100 * 1024 * 1024
_LOT_ID = re.compile(r"lot-([0-9]+)\Z")
_IMAGE_SUFFIXES = {"", ".jpg", ".jpeg", ".png", ".webp"}


def _safe_member_name(name):
    return (
        name
        and "\\" not in name and ":" not in name and "\0" not in name
        and all(part not in {"", ".", ".."} for part in name.split("/"))
    )


def _archive_members(archive):
    members = {}
    seen = set()
    entries = archive.infolist()
    if len(entries) > 4096 or sum(entry.file_size for entry in entries) > MAX_ARTPRICE_UNPACKED_BYTES:
        raise ValueError("The saved Artprice ZIP exceeds the unpacked size or file count limit.")
    for entry in entries:
        name = entry.orig_filename.removesuffix("/")
        if not _safe_member_name(name) or name in seen:
            raise ValueError("The saved Artprice ZIP contains an invalid or duplicate path.")
        seen.add(name)
        if not entry.is_dir():
            members[name] = entry
    return members


def _read_member(archive, member, limit, label):
    if member.file_size > limit:
        raise ValueError(f"The saved Artprice {label} exceeds its size limit.")
    with archive.open(member) as stream:
        content = stream.read(limit + 1)
    if len(content) != member.file_size or len(content) > limit:
        raise ValueError(f"The saved Artprice {label} has an invalid size.")
    return content


def _companion_image(page, src, members):
    # Saved browser URLs can escape spaces and parentheses. Look up only a
    # relative member of this page's own companion folder.
    if not isinstance(src, str) or "?" in src or "#" in src:
        return None
    name = unquote(src).removeprefix("./")
    if not _safe_member_name(name) or not name.startswith(page.stem + "_files/"):
        return None
    path = page.parent / name
    if path.suffix.lower() not in _IMAGE_SUFFIXES or path.stem.casefold() == "img-non-dispo":
        return None
    return members.get(str(path))


def _read_sale_images(archive, members, page, html):
    sold_ids = {sale.provider_id for sale in parse_auction_results(html)}
    images = {}
    decoded = {}
    decoded_size = 0
    soup = BeautifulSoup(html, "html.parser")
    for tile in soup.find_all("div", id=_LOT_ID):
        provider_id = tile["id"][4:]
        if provider_id not in sold_ids or provider_id in images:
            continue
        for image in tile.select(".lot-img img[src]"):
            if image.find_parent("div", id=_LOT_ID) is not tile:
                continue
            member = _companion_image(page, image["src"], members)
            if member is None:
                continue
            if member.filename not in decoded:
                raw = _read_member(archive, member, MAX_SAVED_IMAGE_BYTES, "artwork image")
                try:
                    jpeg = prepare_saved_calendar_image(base64.b64encode(raw).decode("ascii"))
                except ValueError as exc:
                    raise ValueError(f"The saved artwork image for Artprice sale {provider_id} is invalid.") from exc
                decoded_size += len(jpeg)
                if decoded_size > MAX_ARTPRICE_ARCHIVE_BYTES:
                    raise ValueError("The saved Artprice artwork exceeds the total image size limit.")
                decoded[member.filename] = jpeg
            images[provider_id] = decoded[member.filename]
            break
    return images


def read_artprice_saved_page(upload) -> tuple[str, bytes, dict[str, bytes]]:
    """Return HTML basename, original HTML bytes, and clean JPEGs keyed by sold Artprice lot ID."""
    try:
        upload.seek(0, 2)
        if upload.tell() > MAX_ARTPRICE_ARCHIVE_BYTES:
            raise ValueError("The saved Artprice ZIP must be 25 MB or smaller.")
        upload.seek(0)
        with ZipFile(upload) as archive:
            members = _archive_members(archive)
            pages = []
            for name in members:
                path = PurePosixPath(name)
                if (path.suffix.lower() in {".html", ".htm"}
                        and "__MACOSX" not in path.parts and not path.name.startswith("._")
                        and not any(part.casefold().endswith("_files") for part in path.parts[:-1])):
                    pages.append(path)
            if len(pages) != 1:
                raise ValueError("Include one saved Artprice HTML page and its companion folder in each ZIP.")
            page = pages[0]
            companion = str(page.with_name(page.stem + "_files")) + "/"
            if not any(name.startswith(companion) for name in members):
                raise ValueError("Include the saved HTML page's matching _files folder in the Artprice ZIP.")
            raw_html = _read_member(archive, members[str(page)], MAX_ARTPRICE_HTML_BYTES, "HTML page")
            images = _read_sale_images(archive, members, page, raw_html.decode("utf-8", errors="replace"))
            return page.name, raw_html, images
    except (BadZipFile, EOFError, OSError, RuntimeError, ZlibError) as exc:
        raise ValueError("The saved Artprice ZIP could not be read.") from exc
