"""Read and normalize only lot thumbnails from a saved page's asset folder."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit
import warnings

from bs4 import BeautifulSoup
from PIL import Image, ImageOps, UnidentifiedImageError

from catalogapp.watchlist_models import NormalizedLot


MAX_SAVED_IMAGE_BYTES = 512 * 1024
MAX_SAVED_IMAGE_DIMENSION = 1600
_MAX_SOURCE_BYTES = 10 * 1024 * 1024
_MAX_SOURCE_PIXELS = 20_000_000
_LOT_PATH = re.compile(r"/a/(\d+)-(\d+)\.s(?:/|$)", re.IGNORECASE)
_PLACEHOLDER_NAME = re.compile(r"(?:^|[-_.])(placeholder|spacer|transparent|loading|blank|pixel)(?:[-_.]|$)", re.I)


def heritage_preview_url(url: str) -> str:
    """Normalize a recognized public Heritage product image to a 612x600 preview.

    This only constructs a URL; it never fetches an image. Unrelated hosts,
    authenticated URLs, unexpected endpoints, and invalid image IDs are rejected.
    """

    value = (url or "").strip()
    if len(value) > 2048 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return ""
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not re.fullmatch(r"dyn[0-9]*\.heritagestatic\.com", parts.hostname or "")
            or parts.path != "/ha"
            or parts.username is not None or parts.password is not None
            or parts.port is not None or parts.fragment
        ):
            return ""
        query = parse_qs(parts.query, keep_blank_values=True)
    except ValueError:
        return ""
    identifiers = query.get("p", [])
    kinds = query.get("it", [])
    if (
        len(identifiers) != 1 or len(identifiers[0]) > 128
        or not re.fullmatch(r"[0-9]+(?:-[0-9]+)+", identifiers[0])
        or len(kinds) > 1 or (kinds and kinds[0] != "product")
    ):
        return ""
    normalized = [("p", identifiers[0]), ("w", "612"), ("h", "600")]
    if kinds:
        normalized.append(("it", kinds[0]))
    return urlunsplit(("https", parts.hostname, "/ha", urlencode(normalized), ""))


def _asset_heritage_preview_url(asset: Path) -> str:
    """Read only HostUrl from the already-confined asset's Windows origin stream."""

    try:
        with Path(f"{asset}:Zone.Identifier").open("rb") as stream:
            data = stream.read(8193)
    except OSError:
        return ""
    if len(data) > 8192:
        return ""
    for line in data.decode("utf-8-sig", errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip().casefold() == "hosturl":
            # Chromium appends a NUL on some saved resource origin values.
            return heritage_preview_url(value.strip().rstrip("\x00").strip())
    return ""


def _saved_jpeg_size(encoded: str) -> tuple[int, int] | None:
    if not encoded or len(encoded) > 4 * ((MAX_SAVED_IMAGE_BYTES + 2) // 3):
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
        if len(data) > MAX_SAVED_IMAGE_BYTES:
            return None
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                size = image.size
                if image.format != "JPEG" or min(size) < 16 or max(size) > MAX_SAVED_IMAGE_DIMENSION:
                    return None
                image.load()
                return size
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


def prefer_cached_saved_image(lot: NormalizedLot, cached: NormalizedLot) -> None:
    """Retain a valid larger cached JPEG for the same lot and primary image.

    A changed known public image ID takes precedence even when the new image is
    smaller. Older caches without that ID can still retain their better pixels
    when a later save includes only a small catalog thumbnail or no local asset.
    """

    if lot.source != "Heritage" or cached.source != "Heritage" or lot.cache_key != cached.cache_key:
        return
    current_url = heritage_preview_url(lot.image_url)
    cached_url = heritage_preview_url(cached.image_url)
    current_id = parse_qs(urlsplit(current_url).query).get("p", [""])[0]
    cached_id = parse_qs(urlsplit(cached_url).query).get("p", [""])[0]
    if current_id and cached_id and current_id != cached_id:
        return
    old_size = _saved_jpeg_size(cached.saved_image_base64)
    new_size = _saved_jpeg_size(lot.saved_image_base64)
    if old_size and (not new_size or old_size[0] * old_size[1] > new_size[0] * new_size[1]):
        lot.saved_image_base64 = cached.saved_image_base64
    if current_url or cached_url:
        lot.image_url = current_url or cached_url
    lot.content_hash = lot.calculate_content_hash()


def _saved_asset_path(page_path: Path, src: str) -> Path | None:
    """Resolve a relative image reference inside the exact companion folder."""

    raw = unquote((src or "").strip()).replace("\\", "/")
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc or parts.query or parts.fragment or "\x00" in raw:
        return None
    relative = PurePosixPath(parts.path)
    if relative.is_absolute() or ".." in relative.parts or any(":" in part for part in relative.parts):
        return None
    folder_name = f"{page_path.stem}_files"
    if len(relative.parts) < 2 or relative.parts[0] != folder_name:
        return None
    parent = page_path.parent.resolve()
    expected_root = parent / folder_name
    try:
        asset_root = expected_root.resolve(strict=True)
        # A replaced companion directory must not redirect reads elsewhere.
        if asset_root != expected_root or not asset_root.is_dir():
            return None
        candidate = (parent / Path(*relative.parts)).resolve(strict=True)
        if not candidate.is_relative_to(asset_root) or not candidate.is_file():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def normalize_saved_thumbnail(data: bytes) -> str:
    """Return a bounded, metadata-free JPEG as plain base64 text."""

    if not data or len(data) > _MAX_SOURCE_BYTES:
        raise ValueError("Saved thumbnail file is empty or too large.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as opened:
                if opened.format not in {"JPEG", "PNG", "WEBP"} or getattr(opened, "is_animated", False):
                    raise ValueError("Saved thumbnail is not a supported still image.")
                if min(opened.size) < 16 or opened.width * opened.height > _MAX_SOURCE_PIXELS:
                    raise ValueError("Saved thumbnail is a placeholder or exceeds the image size limit.")
                opened.load()
                oriented = ImageOps.exif_transpose(opened)
                rgba = oriented.convert("RGBA")
                if rgba.getchannel("A").getextrema()[1] == 0:
                    raise ValueError("Saved thumbnail is transparent.")
                # A fresh pixel canvas deliberately excludes EXIF, XMP, ICC,
                # comments, and any other metadata from the saved source.
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Saved thumbnail could not be decoded safely.") from exc
    if all(low == high for low, high in clean.getextrema()):
        raise ValueError("Saved thumbnail is a blank placeholder.")
    clean.thumbnail((MAX_SAVED_IMAGE_DIMENSION, MAX_SAVED_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
    while True:
        for quality in (85, 75, 65, 55, 45):
            output = BytesIO()
            clean.save(output, format="JPEG", quality=quality, optimize=True)
            payload = output.getvalue()
            if len(payload) <= MAX_SAVED_IMAGE_BYTES:
                return base64.b64encode(payload).decode("ascii")
        if min(clean.size) < 32:
            raise ValueError("Saved thumbnail could not fit within the image size limit.")
        clean.thumbnail((max(16, int(clean.width * .8)), max(16, int(clean.height * .8))), Image.Resampling.LANCZOS)


def attach_saved_heritage_images(
    page: str, page_path: str | Path, lots: Iterable[NormalizedLot]
) -> list[str]:
    """Attach only primary images matching already-normalized Heritage lot IDs.

    Neither raw source paths nor image metadata become part of the lot record.
    Public image URLs parsed by the source adapter remain available as fallback.
    """

    path = Path(page_path)
    selected = {lot.source_lot_id: lot for lot in lots if lot.source == "Heritage"}
    attached: set[str] = set()
    for node in BeautifulSoup(page, "html.parser").select(".item-block"):
        link = node.select_one("a.item-title[href]")
        match = _LOT_PATH.search(urlsplit(link["href"]).path) if link else None
        identity = f"{match[1]}-{match[2]}" if match else ""
        if identity not in selected or identity in attached:
            continue
        image = node.select_one("a.photo-holder img, img.thumbnail")
        if image is None:
            continue
        lot = selected[identity]
        asset = _saved_asset_path(path, image.get("src", ""))
        # The actual saved/displayed image is authoritative. A lazy-loading
        # data-src can still point to a previous primary image after an upgrade.
        preview = (
            heritage_preview_url(image.get("src", ""))
            or (_asset_heritage_preview_url(asset) if asset is not None else "")
            or heritage_preview_url(image.get("data-src", ""))
            or heritage_preview_url(lot.image_url)
        )
        if preview:
            lot.image_url = preview
            lot.content_hash = lot.calculate_content_hash()
        try:
            if asset is None or _PLACEHOLDER_NAME.search(asset.name) or asset.stat().st_size > _MAX_SOURCE_BYTES:
                continue
            with asset.open("rb") as stream:
                data = stream.read(_MAX_SOURCE_BYTES + 1)
            encoded = normalize_saved_thumbnail(data)
        except (OSError, ValueError):
            continue
        lot.saved_image_base64 = encoded
        lot.content_hash = lot.calculate_content_hash()
        attached.add(identity)

    missing = len(selected.keys() - attached)
    if not missing:
        return []
    subject = "Heritage lot has" if missing == 1 else "Heritage lots have"
    return [
        f"{missing} {subject} no usable saved thumbnail. Existing cached images and public links will be used where available. "
        "Save the catalog as Webpage, Complete with its matching _files folder beside the HTML, "
        "then import it again to include those images."
    ]
