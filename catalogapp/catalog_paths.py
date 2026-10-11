"""Find the shared Supreme workbook on each collaborator's computer."""

import os
import string
from pathlib import Path


CATALOG_RELATIVE_PATH = Path("Shared drives") / "SECONDSTATE" / "THE BOOKS" / "SUPREME.xlsx"
CATALOG_PATH_ENV = "SECONDSTATE_CATALOG_PATH"


def resolve_catalog_path():
    """Use a local override or find the Google Drive desktop mount."""

    configured = os.environ.get(CATALOG_PATH_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"{CATALOG_PATH_ENV} points to a missing catalog file:\n{path}")
        return path

    if os.name == "nt":
        # Keep the existing I: drive as the first choice for the Windows user.
        drives = "I" + string.ascii_uppercase[2:].replace("I", "")
        candidates = [Path(f"{drive}:\\") / CATALOG_RELATIVE_PATH for drive in drives]
    else:
        cloud_storage = Path.home() / "Library" / "CloudStorage"
        candidates = [
            drive / CATALOG_RELATIVE_PATH
            for drive in sorted(cloud_storage.glob("GoogleDrive-*"))
        ]

    matches = [path for path in candidates if path.is_file()]
    if matches:
        if os.name == "nt" or len(matches) == 1:
            return matches[0]
        raise FileNotFoundError(
            "More than one Google Drive account has a Supreme catalog. "
            f"Set {CATALOG_PATH_ENV} to the intended SUPREME.xlsx file."
        )

    raise FileNotFoundError(
        "Could not find Shared drives/SECONDSTATE/THE BOOKS/SUPREME.xlsx in Google Drive. "
        f"Check that Drive is mounted, or set {CATALOG_PATH_ENV} to its full path."
    )
