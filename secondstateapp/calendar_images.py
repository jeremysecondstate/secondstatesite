"""Validate and store the artwork images supplied with authenticated calendar syncs."""

from __future__ import annotations

import base64
import binascii
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
import warnings

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_SAVED_IMAGE_BYTES = 512 * 1024
MAX_SAVED_IMAGE_PIXELS = 4_000_000
MAX_SAVED_IMAGE_EDGE = 1600
MAX_ENCODED_IMAGE_LENGTH = 4 * ((MAX_SAVED_IMAGE_BYTES + 2) // 3)
SAVED_IMAGE_URL_PATTERN = re.compile(r"/media/calendar-lots/[0-9a-f]{64}\.jpg\Z")


def is_saved_calendar_image_url(value) -> bool:
    return isinstance(value, str) and SAVED_IMAGE_URL_PATTERN.fullmatch(value) is not None


def prepare_saved_calendar_image(value) -> bytes:
    """Decode in memory; do not write anything until all sync records are valid."""

    if not isinstance(value, str) or not value:
        raise ValueError("saved_image_base64 must contain a base64 JPEG, PNG, or WebP image")
    if len(value) > MAX_ENCODED_IMAGE_LENGTH:
        raise ValueError("saved_image_base64 exceeds the 512 KiB image limit")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("saved_image_base64 must be valid base64") from exc
    if len(raw) > MAX_SAVED_IMAGE_BYTES:
        raise ValueError("saved_image_base64 exceeds the 512 KiB image limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as probe:
                if probe.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("saved_image_base64 must be a JPEG, PNG, or WebP image")
                width, height = probe.size
                if min(width, height) <= 8 or width * height > MAX_SAVED_IMAGE_PIXELS:
                    raise ValueError("saved_image_base64 dimensions must exceed 8 pixels and contain at most 4 million pixels")
                if getattr(probe, "is_animated", False):
                    raise ValueError("saved_image_base64 must be a still image")
                probe.verify()
            with Image.open(BytesIO(raw)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                oriented.thumbnail((MAX_SAVED_IMAGE_EDGE, MAX_SAVED_IMAGE_EDGE), Image.Resampling.LANCZOS)
                rgba = oriented.convert("RGBA")
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
                output = BytesIO()
                # A new image removes EXIF, comments, and other source metadata.
                clean.save(output, format="JPEG", quality=85, optimize=True)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("saved_image_base64 contains an invalid image") from exc


def store_saved_calendar_image(content: bytes) -> str:
    """Write normalized bytes atomically, with one file per content digest."""

    digest = hashlib.sha256(content).hexdigest()
    directory = Path(settings.MEDIA_ROOT) / "calendar-lots"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{digest}.jpg"
    if not destination.is_file():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".upload-", delete=False) as upload:
                temporary = Path(upload.name)
                upload.write(content)
                upload.flush()
                os.fsync(upload.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return f"/media/calendar-lots/{digest}.jpg"
