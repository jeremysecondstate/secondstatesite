from pathlib import Path

APP_TITLE = "Artprice Link Generator"

PACKAGE_DIR = Path(__file__).resolve().parent

DEFAULT_DATE_FROM = "2018-01-01"
DEFAULT_CATEGORY_ID = "2"
DEFAULT_SORT = "datesale_desc"

DEFAULT_ARTIST_ID_PATH = str(PACKAGE_DIR / "ARTIST IDs.xlsx")
DEFAULT_DAUMIER_IMAGE_PATH = str(PACKAGE_DIR / "daumier_smoking_guy.png")

FALLBACK_ARTIST_ID_FILENAMES = [
    "ARTIST IDs.xlsx",
    "ARTIST IDs - ARTIST IDs.csv",
    "ARTIST IDs Harvested v2.xlsx",
]

UNKNOWN_ARTIST_MESSAGE = "Sorry :( The artist ID # is not known!"

ARTPRICE_LINK_COLUMN = "Artprice Link"
ARTIST_COLUMN = "Extracted Artist"
TITLE_COLUMN = "Extracted Title"
ARTIST_ID_COLUMN = "Artprice Artist ID"
KEYWORD_COLUMN = "Artprice Keyword"
STATUS_COLUMN = "Artprice Status"
SOURCE_MODE_COLUMN = "Artprice Source Mode"
MISSING_SEARCH_COLUMN = "Artprice Artist Search"

BG = "#f6f2ea"
PANEL = "#fbf8f2"
TEXT = "#2a2118"
SUBTLE = "#6c5a45"
GOLD_1 = "#8c6a1b"
GOLD_2 = "#b88928"
GOLD_3 = "#d7b55a"
GOLD_4 = "#f6df9a"
GOLD_SHADOW = "#9b7a22"
PINK_1 = "#f5d7e1"
PINK_2 = "#dba8bb"
LINK_BLUE = "#1d4ed8"
