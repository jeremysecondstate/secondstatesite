"""Move the Artprice Tkinter App class into artpricelinkgen/app.py.

Run from the repository root:

    python scripts/migrate_artprice_app_class.py

Why this script exists:
The original artprice_link_generator.py file is large. This script performs the
class move locally using Python's AST line numbers, which is safer than manually
copying a long class in an editor.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "artpricelinkgen"
ORIGINAL_PATH = PACKAGE_DIR / "artprice_link_generator.py"
APP_PATH = PACKAGE_DIR / "app.py"
BACKUP_PATH = PACKAGE_DIR / "artprice_link_generator.py.before_app_migration.bak"

APP_IMPORTS = '''import os
import sys
import math
import time
import webbrowser
from pathlib import Path

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

from artpricelinkgen.artist_lookup import ArtistIdLookup
from artpricelinkgen.batch import BatchProcessor
from artpricelinkgen.config import *
from artpricelinkgen.extraction import ImageListingExtractor
from artpricelinkgen.models import ExtractedListing
from artpricelinkgen.ui_utils import blend_hex
from artpricelinkgen.url_builder import ArtpriceURLBuilder
from artpricelinkgen.widgets import GoldButton, HyperlinkText
from artpricelinkgen.workbook_formatting import format_output_workbook
'''

LAUNCHER = '''from artpricelinkgen.main import main


if __name__ == "__main__":
    main()
'''


def find_app_class(source: str) -> str:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "App":
            start = node.lineno - 1
            end = node.end_lineno
            return "".join(lines[start:end]).rstrip() + "\n"

    raise RuntimeError("Could not find a top-level class named App in artprice_link_generator.py")


def main() -> None:
    if not ORIGINAL_PATH.exists():
        raise FileNotFoundError(f"Could not find {ORIGINAL_PATH}")

    source = ORIGINAL_PATH.read_text(encoding="utf-8")
    app_class = find_app_class(source)

    if not BACKUP_PATH.exists():
        BACKUP_PATH.write_text(source, encoding="utf-8")
        print(f"Created backup: {BACKUP_PATH.relative_to(REPO_ROOT)}")
    else:
        print(f"Backup already exists: {BACKUP_PATH.relative_to(REPO_ROOT)}")

    APP_PATH.write_text(APP_IMPORTS + "\n\n" + app_class, encoding="utf-8")
    ORIGINAL_PATH.write_text(LAUNCHER, encoding="utf-8")

    print("Moved App class into artpricelinkgen/app.py")
    print("Replaced artpricelinkgen/artprice_link_generator.py with a tiny launcher")
    print("Next test command: python -m artpricelinkgen.main")


if __name__ == "__main__":
    main()
