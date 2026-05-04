"""
Invaluable catalog folder builder

What it does:
1. Visits each Invaluable catalog URL.
2. Extracts auction house name and sale month/year.
3. Creates:
   I:\\Shared drives\\SECONDSTATE\\Tables!\\{AUCTION HOUSE}\\{MONTH YEAR}
4. Saves a CSV report of what it did.

Install first:
    pip install requests beautifulsoup4 lxml
"""

from pathlib import Path
from urllib.parse import urlparse
import csv
import re
import time
import requests
from bs4 import BeautifulSoup

# ----------------------------
# SETTINGS
# ----------------------------

BASE_TABLES_FOLDER = Path(r"I:\Shared drives\SECONDSTATE\Tables!")

DRY_RUN = True
# Keep DRY_RUN=True for first test.
# After reviewing the printed results, change to False to actually create folders.

REQUEST_DELAY_SECONDS = 2

CATALOG_URLS = [
    "https://www.invaluable.com/catalog/1TL8FTD4GN?Fine%20Art=Prints&page=1&size=48",
    "https://www.invaluable.com/catalog/CF16MVF0KP?Fine%20Art=Prints&page=1&size=48",
    "https://www.invaluable.com/catalog/3WFUQN6K8D?Fine%20Art=Prints&page=1&size=48",
    "https://www.invaluable.com/catalog/G209G2LB4A?Fine%20Art=Prints&page=1&size=48",
    "https://www.invaluable.com/catalog/NAQ1M49W2B?Fine%20Art=Prints&page=1&size=48",
    "https://www.invaluable.com/catalog/U9DOFJNLXU?Fine%20Art=Prints&page=1&size=48",
    "https://www.invaluable.com/catalog/YMCH62UILP?Fine%20Art=Prints&page=1&size=144",
    "https://www.invaluable.com/catalog/K5TV41TM7D?Fine%20Art=Prints&page=1&size=48",
    "https://www.invaluable.com/catalog/0KS0LM434Z?Fine%20Art=Prints&page=1&size=48",
    "https://www.invaluable.com/catalog/Y3MTKN6N9V?Fine%20Art=Prints&page=1&size=48",
    "https://www.invaluable.com/catalog/8TTZ4WGNFO?Fine%20Art=Prints&page=1&size=144",
    "https://www.invaluable.com/catalog/777TJYCDL5?Fine%20Art=Prints&page=1&size=192",
]

MONTHS = {
    "january": "JANUARY",
    "february": "FEBRUARY",
    "march": "MARCH",
    "april": "APRIL",
    "may": "MAY",
    "june": "JUNE",
    "july": "JULY",
    "august": "AUGUST",
    "september": "SEPTEMBER",
    "october": "OCTOBER",
    "november": "NOVEMBER",
    "december": "DECEMBER",
}


# ----------------------------
# HELPERS
# ----------------------------

def clean_folder_name(name: str) -> str:
    """
    Removes characters Windows does not allow in folder names.
    """
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def get_catalog_id(url: str) -> str:
    path = urlparse(url).path
    return path.rstrip("/").split("/")[-1]


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def soup_text(soup: BeautifulSoup) -> str:
    return soup.get_text("\n", strip=True)


def extract_auction_house(soup: BeautifulSoup, text: str) -> str:
    """
    Tries several strategies because marketplace pages can shift layout.
    """

    # Strategy 1: page text pattern: "by Auction House Name"
    by_match = re.search(
        r"\bby\s+([A-Z][^\n]+?)(?:\n|Timed items|Register|May|June|July|August|September|October|November|December)",
        text)
    if by_match:
        candidate = by_match.group(1).strip()
        candidate = re.sub(r"\s+", " ", candidate)
        if 2 < len(candidate) < 100:
            return candidate

    # Strategy 2: breadcrumb-ish / title metadata
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    # Example title often ends with "- Auction House"
    parts = [p.strip() for p in title.split(" - ") if p.strip()]
    if parts:
        candidate = parts[-1]
        if "invaluable" not in candidate.lower() and len(candidate) < 100:
            return candidate

    raise ValueError("Could not find auction house name")


def extract_sale_month_year(text: str) -> str:
    """
    Finds first visible date like:
    May 20, 2026
    May  20, 8:00 AM UTC
    or a title containing May 2026.
    """

    # Full date: May 20, 2026
    full_date_match = re.search(
        r"\b("
        r"January|February|March|April|May|June|July|August|September|October|November|December"
        r")\s+\d{1,2},\s+(20\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )

    if full_date_match:
        month = MONTHS[full_date_match.group(1).lower()]
        year = full_date_match.group(2)
        return f"{month} {year}"

    # Month/year only: May 2026
    month_year_match = re.search(
        r"\b("
        r"January|February|March|April|May|June|July|August|September|October|November|December"
        r")\s+(20\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )

    if month_year_match:
        month = MONTHS[month_year_match.group(1).lower()]
        year = month_year_match.group(2)
        return f"{month} {year}"

    raise ValueError("Could not find sale month/year")


def extract_catalog_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)

    if soup.title:
        return soup.title.get_text(" ", strip=True)

    return ""


def extract_item_count(text: str) -> str:
    match = re.search(r"\b(\d{1,5})\s+items\b", text, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def create_folder(path: Path) -> str:
    if DRY_RUN:
        return "DRY RUN - not created"

    path.mkdir(parents=True, exist_ok=True)
    return "created or already existed"


# ----------------------------
# MAIN
# ----------------------------

def main():
    rows = []

    for url in CATALOG_URLS:
        print(f"\nProcessing: {url}")

        row = {
            "url": url,
            "catalog_id": get_catalog_id(url),
            "auction_house": "",
            "sale_month_year": "",
            "catalog_title": "",
            "item_count": "",
            "folder_path": "",
            "status": "",
            "error": "",
        }

        try:
            html = fetch_html(url)
            soup = BeautifulSoup(html, "lxml")
            text = soup_text(soup)

            auction_house = clean_folder_name(extract_auction_house(soup, text)).upper()
            sale_month_year = clean_folder_name(extract_sale_month_year(text))
            catalog_title = extract_catalog_title(soup)
            item_count = extract_item_count(text)

            auction_house_folder = BASE_TABLES_FOLDER / auction_house
            sale_folder = auction_house_folder / sale_month_year

            status = create_folder(sale_folder)

            row.update({
                "auction_house": auction_house,
                "sale_month_year": sale_month_year,
                "catalog_title": catalog_title,
                "item_count": item_count,
                "folder_path": str(sale_folder),
                "status": status,
            })

            print(f"  Auction house: {auction_house}")
            print(f"  Sale folder:    {sale_month_year}")
            print(f"  Folder path:    {sale_folder}")
            print(f"  Status:         {status}")

        except Exception as exc:
            row["status"] = "error"
            row["error"] = str(exc)
            print(f"  ERROR: {exc}")

        rows.append(row)
        time.sleep(REQUEST_DELAY_SECONDS)

    report_path = Path("invaluable_folder_report.csv")

    with report_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. Report saved to: {report_path.resolve()}")
    print(f"DRY_RUN is currently set to: {DRY_RUN}")


if __name__ == "__main__":
    main()
