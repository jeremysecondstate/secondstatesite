"""Import visible Invaluable artist-search snapshots without a network request."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup, Comment

from catalogapp.bookmark_watchlist import BookmarkEntry, canonicalize_bookmark_url, source_for_url
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_models import NormalizedLot, lot_within_horizon, parse_lot_datetime
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult, _agenda_sort_key, _retain_missing_static_fields


CAPTURE_BUNDLE_FORMAT = "secondstate-invaluable-capture"
MAX_CAPTURE_BYTES = 20 * 1024 * 1024
MAX_CAPTURE_PAGES = 500
MAX_CAPTURE_HITS = 1000
_CAPTURE_PUBLIC_FIELDS = frozenset({
    "artistName", "bidCount", "catalogRef", "categoryName", "countryName", "currencyCode", "currencySymbol",
    "currentBid", "dateTimeLocal", "dateTimeUTCUnix", "endTimeUTCUnix", "estimateHigh", "estimateLow",
    "houseName", "location", "lotDescription", "lotNumber", "lotRef", "lotTitle", "objectID", "photoPath",
    "soldPrice", "soldCurrencyCode", "stateName", "subcategoryName", "supercategoryName", "title",
})


@dataclass(frozen=True)
class _CaptureWindow:
    start: date
    end: date
    time_zone: str

    def contains(self, lot: NormalizedLot) -> bool:
        stamp, all_day = parse_lot_datetime(lot.relevant_at)
        if stamp is None:
            return False
        # A date-only sale is already a calendar date; UTC conversion would
        # incorrectly move it to the previous day in American time zones.
        day = stamp.date() if all_day else stamp.astimezone(ZoneInfo(self.time_zone)).date()
        return self.start <= day <= self.end


@dataclass
class _SavedInput:
    label: str
    content: object
    is_snapshot: bool
    window: _CaptureWindow | None = None


def _capture_time(value: object, observed_at: datetime, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO timestamp with a timezone")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.timestamp() > observed_at.timestamp() + 300:
            raise ValueError
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must include a timezone and cannot be in the future") from exc
    return stamp


def _capture_window(payload: object) -> _CaptureWindow:
    if not isinstance(payload, dict):
        raise ValueError("window must contain start_date, end_date and time_zone")
    try:
        start, end = payload["start_date"], payload["end_date"]
        zone = payload["time_zone"]
        if not all(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
                   for value in (start, end)) or not isinstance(zone, str):
            raise ValueError
        start, end = date.fromisoformat(start), date.fromisoformat(end)
        if not 0 <= (end - start).days < 90:
            raise ValueError
        ZoneInfo(zone)
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("window needs valid inclusive dates spanning at most 90 days and a valid time_zone") from exc
    return _CaptureWindow(start, end, zone)


def _snapshot_data(payload: object, observed_at: datetime, *, bundled: bool = False):
    """Validate the old single-page shape, with complete metadata for bundles."""
    if not isinstance(payload, dict):
        raise ValueError("the snapshot must contain a JSON object")
    page_url = _public_url(str(payload.get("source_url", "")))
    parts = urlsplit(page_url)
    if (not page_url or source_for_url(page_url) != "Invaluable"
            or parts.path.rstrip("/").casefold() != "/search" or not _search_artist(page_url)):
        raise ValueError("the snapshot needs an Invaluable artist-search source_url")
    if bundled and (parts.scheme != "https" or parts.netloc not in {"www.invaluable.com", "invaluable.com"}):
        raise ValueError("bundled snapshots need an HTTPS Invaluable artist-search source_url")
    captured_at = _capture_time(payload.get("captured_at"), observed_at, "captured_at")
    result = InvaluableAdapter._catalog_result(payload)
    if result is None or len(payload.get("results", [])) != 1:
        raise ValueError("the snapshot must contain exactly one catalog result with hits")
    if len(result["hits"]) > MAX_CAPTURE_HITS:
        raise ValueError(f"a snapshot may contain at most {MAX_CAPTURE_HITS} hits")
    if any(not isinstance(hit, dict) or not hit.get("artistName") for hit in result["hits"]):
        raise ValueError("each snapshot lot must include its verified artistName")
    if bundled:
        fields = ("page", "nbPages", "nbHits", "hitsPerPage")
        if any(type(result.get(key)) is not int or not 0 <= result[key] <= 2**53 - 1 for key in fields):
            raise ValueError("each bundled result needs integer page, nbPages, nbHits and hitsPerPage metadata")
        page, pages, count, size = (result[key] for key in fields)
        if (not 1 <= size <= MAX_CAPTURE_HITS or pages != (count + size - 1) // size
                or (page >= pages if count else page != 0)
                or len(result["hits"]) != min(size, max(0, count - page * size))):
            raise ValueError("bundled result pagination or hit count is inconsistent")
        url_pages = {value for key, value in parse_qsl(parts.query) if key.casefold() == "page"}
        if len(url_pages) > 1:
            raise ValueError("the snapshot URL has conflicting page numbers")
        url_page = next(iter(url_pages), "1")
        if not re.fullmatch(r"[0-9]+", url_page) or int(url_page) != page + 1:
            raise ValueError("the bundled result does not match its source URL page")
        ids, refs = set(), set()
        for hit in result["hits"]:
            for field in _CAPTURE_PUBLIC_FIELDS.intersection(hit):
                value = hit[field]
                if (isinstance(value, bool) or not isinstance(value, (str, int, float))
                        or isinstance(value, (int, float)) and not math.isfinite(value)):
                    raise ValueError(f"bundled hit field {field} must contain text or a finite number")
            ref, title, identity = hit.get("lotRef"), hit.get("lotTitle") or hit.get("title"), hit.get("objectID")
            if (not isinstance(ref, str) or not ref.strip()
                    or not isinstance(title, str) or not title.strip()
                    or not isinstance(hit.get("artistName"), str)
                    or (identity is not None and (isinstance(identity, bool)
                        or not isinstance(identity, (str, int, float))
                        or isinstance(identity, (int, float)) and not math.isfinite(identity)))):
                raise ValueError("a bundled hit has an invalid lot identity, artist or title")
            identity = str(identity or ref).strip()
            if not identity or identity in ids or ref in refs:
                raise ValueError("a bundled page contains duplicate or missing lot identities")
            ids.add(identity)
            refs.add(ref)
        # The browser exporter emits only this public scalar schema. Unknown
        # application/account fields must not reach normalization or reports.
        result = {**result, "hits": [{key: value for key, value in hit.items() if key in _CAPTURE_PUBLIC_FIELDS}
                                    for hit in result["hits"]]}
    return page_url, captured_at, result


def _saved_inputs(paths: list[Path], observed_at: datetime, errors: list[str], notices: list[str]) -> list[_SavedInput]:
    """Expand bounded bundles without trusting their progress/completeness claims."""
    inputs = []
    bundled_pages: dict[tuple, list[tuple[datetime, str, _SavedInput]]] = {}
    bundle_page_count = 0
    for path in paths:
        if path.suffix.casefold() not in {".html", ".htm", ".json"}:
            errors.append(f"{path.name}: choose a saved Invaluable HTML search page or JSON snapshot.")
            continue
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_CAPTURE_BYTES + 1)
            if len(raw) > MAX_CAPTURE_BYTES:
                errors.append(f"{path.name}: saved pages and capture bundles must be at most 20 MiB.")
                continue
        except OSError:
            errors.append(f"{path.name}: the saved page could not be read.")
            continue
        text = raw.decode("utf-8-sig", errors="replace")
        if path.suffix.casefold() != ".json":
            inputs.append(_SavedInput(path.name, text, False))
            continue
        try:
            payload = json.loads(text)
        except (ValueError, RecursionError):
            errors.append(f"{path.name}: invalid Invaluable snapshot (unreadable JSON); no lots were imported from this file.")
            continue
        if not isinstance(payload, dict) or not any(key in payload for key in ("format", "snapshots")):
            inputs.append(_SavedInput(path.name, payload, True))
            continue
        try:
            if payload.get("format") != CAPTURE_BUNDLE_FORMAT or type(payload.get("version")) is not int or payload["version"] != 1:
                raise ValueError("unsupported capture bundle format or version")
            exported = _capture_time(payload.get("exported_at"), observed_at, "exported_at")
            window = _capture_window(payload.get("window"))
            snapshots = payload.get("snapshots")
            if not isinstance(snapshots, list) or len(snapshots) > MAX_CAPTURE_PAGES:
                raise ValueError(f"snapshots must be a list of at most {MAX_CAPTURE_PAGES} pages")
            if bundle_page_count + len(snapshots) > MAX_CAPTURE_PAGES:
                raise ValueError(f"select at most {MAX_CAPTURE_PAGES} bundled pages per import")
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append(f"{path.name}: invalid Invaluable capture bundle ({exc}); no lots were imported from this file.")
            continue
        bundle_page_count += len(snapshots)
        for number, snapshot in enumerate(snapshots, 1):
            label = f"{path.name}, page capture {number}"
            try:
                url, captured, result = _snapshot_data(snapshot, observed_at, bundled=True)
                if captured > exported:
                    raise ValueError("captured_at is later than the bundle's exported_at")
                # A later capture of the same displayed page replaces the old
                # page. Different pages remain independent partial evidence.
                sorts = tuple(sorted(value.casefold() for key, value in parse_qsl(urlsplit(url).query) if key.casefold() == "sort"))
                key = (window, InvaluableAdapter._artist_match_key(_search_artist(url)),
                       _search_scope(url, ignore_date_controls=True), sorts, result["page"])
                fingerprint = json.dumps(result, sort_keys=True, ensure_ascii=True)
                unit = _SavedInput(label, snapshot, True, window)
                bundled_pages.setdefault(key, []).append((captured, fingerprint, unit))
            except (ValueError, TypeError, OverflowError) as exc:
                errors.append(f"{label}: invalid Invaluable snapshot ({exc}); this page was not imported.")
        notices.append(f"{path.name}: capture window {window.start} through {window.end} ({window.time_zone}); "
                       "only dated lots in that inclusive window are imported. Bundle progress does not establish complete source coverage.")
    for candidates in bundled_pages.values():
        latest = max(item[0] for item in candidates)
        current = [item for item in candidates if item[0] == latest]
        if len({item[1] for item in current}) != 1:
            errors.append(f"{current[0][2].label}: contradictory captures of the same page have the same timestamp; that page was left unchanged.")
            continue
        inputs.append(current[0][2])
    return inputs


def _public_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return ""
        return canonicalize_bookmark_url(value)
    except ValueError:
        return ""


def _search_artist(url: str) -> str:
    """Only an explicit artist facet identifies a saved artist search."""
    artists = {
        value.strip() for key, value in parse_qsl(urlsplit(url).query)
        if key.casefold() in {"artistname", "artist"} and value.strip()
    }
    return next(iter(artists)) if len(artists) == 1 else ""


def _search_scope(url: str, *, ignore_date_controls: bool = False) -> tuple[tuple[str, str], ...]:
    """Compare membership filters while allowing presentation-only URL changes."""
    ignored = {"artist", "artistname", "page", "sort", "view", "pagesize", "page_size", "hitsperpage", "perpage"}
    if ignore_date_controls:
        # A capture bundle supplies its own explicit window. The companion
        # removes only these old date controls from saved artist bookmarks;
        # categories, query terms and all other membership filters still match.
        ignored.update({"datetimeutcunix[min]", "datetimeutcunix[max]", "datetype"})
    filters = set()
    for key, value in parse_qsl(urlsplit(_public_url(url)).query):
        key = key.casefold()
        value = " ".join(value.split()).casefold()
        if key in ignored or not value:
            continue
        if key in {"keyword", "q"}:
            key = "query"
        filters.add((key, value))
    return tuple(sorted(filters))


def _hit_matches_category(hit: dict, source_url: str) -> bool:
    """Reject explicitly contradictory category metadata in a search snapshot."""
    categories = [(key, value) for key, value in _search_scope(source_url) if key in InvaluableAdapter._category_facets]
    if not categories:
        return True
    supercategory = InvaluableAdapter._artist_match_key(str(hit.get("supercategoryName") or ""))
    # URL facets describe supercategory -> category (Fine Art -> Prints).
    # subcategoryName is one level deeper: Genre, Figural, Nude, etc. A print
    # can legitimately have any of those subjects. Older snapshots omitted
    # categoryName; their verified source URL still supplies the category scope.
    category_name = InvaluableAdapter._artist_match_key(str(hit.get("categoryName") or ""))
    return any((not supercategory or supercategory == category) and (not category_name or category_name == value)
               for category, value in categories)


def _saved_search_url(soup: BeautifulSoup) -> str:
    candidates: list[str] = []
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        match = re.match(r"\s*saved from url=\(\d+\)(https?://\S+)", str(comment), re.I)
        if match:
            candidates.append(match[1])
    for node in soup.select('link[rel="canonical"], meta[property="og:url"]'):
        candidates.append(str(node.get("href") or node.get("content") or ""))
    searches: list[str] = []
    for value in candidates:
        url = _public_url(value)
        if not url or source_for_url(url) != "Invaluable":
            raise ValueError("the saved page does not have a valid Invaluable source address")
        if urlsplit(url).path.rstrip("/").casefold() == "/search" and _search_artist(url):
            searches.append(url)
    if not searches:
        raise ValueError("no saved Invaluable search address with an artist filter was found")
    if len({InvaluableAdapter._artist_match_key(_search_artist(url)) for url in searches}) != 1:
        raise ValueError("the saved page contains conflicting artist-search addresses")
    return searches[0]


def _lot_ref(url: str) -> str:
    match = re.search(r"-c-([a-z0-9]+)(?:/|$)", urlsplit(url).path, re.I)
    return match[1].casefold() if match else ""


def _valid_date(value: str) -> bool:
    try:
        return parse_lot_datetime(value)[0] is not None
    except (TypeError, ValueError, OverflowError):
        return False


def _safe_image_url(value: str) -> str:
    # Saving a complete webpage rewrites src to e.g. "Search_files/image.jpg".
    # The HTML adapter resolves that against the page URL; it is still a local
    # companion asset, not a public Invaluable image address.
    url = _public_url(value)
    if not url or re.search(r"(?:^|/)[^/]*_files(?:/|$)", unquote(urlsplit(url).path), re.I):
        return ""
    return url


def _without_recommendations(soup: BeautifulSoup) -> str:
    for node in list(soup.select('[hidden], [aria-hidden="true"], .related-lots, .recommended-lots, .recommendations, [data-testid*="related"], [data-testid*="recommend"]')):
        if node.parent is not None:
            node.decompose()
    # Arbitrary application state can include recommended and previously viewed
    # lots. A saved search imports only its visible cards, never that hidden state.
    for node in soup.find_all("script"):
        node.decompose()
    return str(soup)


def _visible_calendar_date(text: str) -> str:
    """Parse only a complete source date; relative dates never imply a year."""
    value = " ".join(text.split()).strip()
    if _valid_date(value):
        return value
    if not re.search(r"\b20\d{2}\b", value):
        return ""
    zone_match = re.search(r"\s+(UTC|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)$", value, re.I)
    offset = None
    if zone_match:
        offset = {"UTC": 0, "GMT": 0, "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
                  "MST": -7, "MDT": -6, "PST": -8, "PDT": -7}[zone_match[1].upper()]
        value = value[:zone_match.start()]
    for pattern in ("%b %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M %p", "%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p", "%b %d, %Y", "%B %d, %Y"):
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue
        if "%I" not in pattern or offset is None:
            return parsed.date().isoformat()
        return parsed.replace(tzinfo=timezone(timedelta(hours=offset))).isoformat()
    return ""


def _visible_cards(adapter: InvaluableAdapter, soup: BeautifulSoup, page_url: str, artist: str) -> list[NormalizedLot]:
    clean = BeautifulSoup(_without_recommendations(soup), "html.parser")
    modern = [node for node in clean.select(".content-holder") if node.select_one("a.lot-title[href]")]
    if not modern:
        nodes = clean.select("[data-lot-id], article.lot-card, .lot-card, .lot-item, [data-testid*='lot-card']")
        if not nodes:
            nodes = [anchor.parent for anchor in clean.find_all("a", href=adapter._lot_href)]
        raw_lots = [adapter._raw_from_card(node, page_url) for node in nodes if node]
        return _normalize_visible_cards(adapter, raw_lots, page_url, artist)
    raw_lots = []
    for node in modern:
        for converted in list(node.select(".converted-price")):
            converted.decompose()
        raw = adapter._raw_from_card(node, page_url)
        holders = node.find_all("div", class_="text-holder", recursive=False)
        for holder in holders:
            text = holder.get_text(" ", strip=True)
            if holder.select_one("a.lot-title"):
                continue
            if re.match(r"Est(?:imate)?\s*:", text, re.I):
                raw["estimate"] = text
                code = re.search(r"\b(USD|CAD|AUD|EUR|GBP|CHF|HKD|NZD|SEK|DKK|NOK|JPY)\b", text)
                if code:
                    raw["currency"] = code[1]
            elif holder.select_one(".text-live, .text-timed, time"):
                raw["endAt"] = raw["endAt"] or _visible_calendar_date(text)
            elif holder.select_one(".text-large"):
                raw["currentBid"] = text
            elif not raw["auctionHouse"] and text:
                raw["auctionHouse"] = text
        raw_lots.append(raw)
    return _normalize_visible_cards(adapter, raw_lots, page_url, artist)


def _normalize_visible_cards(adapter: InvaluableAdapter, raw_lots: list[dict], page_url: str, artist: str) -> list[NormalizedLot]:
    # Displayed lot numbers are reused by auction houses. Establish the source
    # reference before the adapter deduplicates, not after records are lost.
    for raw in raw_lots:
        ref = _lot_ref(urljoin(page_url, str(raw.get("lotUrl") or raw.get("url") or "")))
        if ref:
            raw["lotId"] = ref
    return adapter._normalize_and_deduplicate(raw_lots, page_url, artist)


def _merge_saved_card(card: NormalizedLot, cached: NormalizedLot | None, *, preserve_source_id: bool = False) -> NormalizedLot:
    if cached is None:
        # URL lot references are globally stable; a displayed lot number is not.
        if not preserve_source_id:
            card.source_lot_id = _lot_ref(card.lot_url) or card.source_lot_id
        card.content_hash = card.calculate_content_hash()
        return card
    card.source_lot_id = cached.source_lot_id
    card.lot_url = cached.lot_url
    # A saved search can be less detailed than an earlier full lot page. Keep
    # known static details and source dates where the visible card omits them.
    # Share the live-refresh rules: generic Print does not replace a known
    # technique, and cached pixels must not obscure a changed primary image.
    _retain_missing_static_fields(card, cached)
    for field in ("start_at", "end_at"):
        if not getattr(card, field):
            setattr(card, field, getattr(cached, field))
    card.content_hash = card.calculate_content_hash()
    return card


def import_saved_invaluable_pages(
    paths: Iterable[str | Path],
    entries: Iterable[BookmarkEntry],
    cache: WatchlistCache,
    *,
    now: datetime | None = None,
    horizon_days: int = 30,
    new_changed_only: bool = False,
) -> WatchlistResult:
    """Import selected artists' visible, dated search cards as partial snapshots.

    All files are inspected before writes. Independent readable files can still
    be imported if another file is invalid. Absent lots keep their membership,
    observation time, and cached provenance. Source-run errors are never cleared.
    Only normalized lot fields are retained; HTML and account data stay local.
    """
    chosen = []
    for entry in entries:
        url = _public_url(entry.url)
        if entry.source == "Invaluable" and url and source_for_url(url) == "Invaluable" and entry.artist:
            chosen.append(entry)
    chosen = list({entry.url: entry for entry in chosen}.values())
    if not chosen:
        raise ValueError("Select at least one bookmarked Invaluable artist before importing saved pages.")
    selected_paths = list(dict.fromkeys(Path(path) for path in paths))
    if not selected_paths:
        raise ValueError("Choose at least one saved Invaluable HTML search page or JSON snapshot.")
    adapter = InvaluableAdapter()
    by_artist: dict[str, list[BookmarkEntry]] = {}
    known: dict[str, NormalizedLot] = {}
    active: dict[str, NormalizedLot] = {}
    for entry in chosen:
        by_artist.setdefault(adapter._artist_match_key(_search_artist(entry.url) or entry.artist), []).append(entry)
        known.update({lot.cache_key: lot for lot in cache.lots_for_watch_url(entry.url)})
        active.update({lot.cache_key: lot for lot in cache.active_lots_for_watch_url(entry.url)})
    metrics = WatchlistMetrics(bookmark_urls=len(chosen), artists=len(by_artist))
    errors: list[str] = []
    notices: list[str] = []
    observed: dict[str, NormalizedLot] = {}
    observation_times: dict[str, datetime] = {}
    memberships: dict[str, set[str]] = {}
    bundle_observed_keys: set[str] = set()
    conflicted: set[str] = set()
    undated = 0
    unmatched = 0
    outside_window = 0
    seen_files = 0
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    for saved in _saved_inputs(selected_paths, observed_at, errors, notices):
        label = saved.label
        is_snapshot = saved.is_snapshot
        captured_at = observed_at
        if is_snapshot:
            try:
                page_url, captured_at, catalog_result = _snapshot_data(
                    saved.content, observed_at, bundled=saved.window is not None,
                )
            except (ValueError, TypeError, OverflowError) as exc:
                errors.append(f"{label}: invalid Invaluable snapshot ({exc}); no lots were imported from this page.")
                continue
        else:
            soup = BeautifulSoup(saved.content, "html.parser")
            try:
                page_url = _saved_search_url(soup)
            except ValueError as exc:
                errors.append(f"{label}: {exc}; no lots were imported from this file.")
                continue
        artist = _search_artist(page_url)
        matching_entries = [entry for entry in by_artist.get(adapter._artist_match_key(artist), [])
                            if _search_scope(entry.url, ignore_date_controls=saved.window is not None)
                            == _search_scope(page_url, ignore_date_controls=saved.window is not None)]
        if not matching_entries:
            errors.append(f"{label}: its artist, category, or search-query filters do not match a selected Invaluable bookmark.")
            continue
        if is_snapshot:
            scoped_hits = [hit for hit in catalog_result["hits"] if _hit_matches_category(hit, page_url)]
            unmatched += len(catalog_result["hits"]) - len(scoped_hits)
            cards = adapter.parse_search_page(json.dumps({"results": [{"hits": scoped_hits}]}), page_url, artist)
        else:
            headings = " ".join(node.get_text(" ", strip=True) for node in soup.select("title, h1")).casefold()
            if any(term in headings for term in ("javascript is disabled", "access denied", "verify you are human", "just a moment")):
                errors.append(f"{label}: this is an access page; save the search after its lot cards have loaded.")
                continue
            cards = _visible_cards(adapter, soup, page_url, artist)
        if not cards:
            if is_snapshot:
                seen_files += 1
                if not catalog_result["hits"] and type(catalog_result.get("nbHits")) is int and catalog_result["nbHits"] == 0:
                    notices.append(f"{label}: the captured search reported zero matching lots. This partial snapshot did not end or remove any cached lots.")
                else:
                    notices.append(f"{label}: the snapshot contains no readable lots matching the selected filters. Existing cached lots were retained.")
            else:
                notices.append(f"{label}: no readable lot cards were found. Save the loaded artist results page as Webpage, Complete.")
            continue
        seen_files += 1
        for card in cards:
            url = _public_url(card.lot_url)
            if (not url or source_for_url(url) != "Invaluable" or not adapter._lot_href.search(urlsplit(url).path)
                    or not card.title or adapter._artist_match_key(card.artist) != adapter._artist_match_key(artist)):
                unmatched += 1
                continue
            card.lot_url = url
            card.image_url = _safe_image_url(card.image_url)
            card.sale_url = _public_url(card.sale_url)
            if card.sale_url and source_for_url(card.sale_url) != "Invaluable":
                card.sale_url = ""
            for field in ("start_at", "end_at"):
                if getattr(card, field) and not _valid_date(getattr(card, field)):
                    setattr(card, field, "")
            ref = _lot_ref(url)
            matches = [lot for lot in {**observed, **known}.values() if lot.source == "Invaluable" and (
                lot.lot_url == url or (ref and _lot_ref(lot.lot_url) == ref)
            )]
            if not matches:
                lookup = cache.lookup(card)
                if lookup and (lookup.lot.lot_url == url or (ref and _lot_ref(lookup.lot.lot_url) == ref)):
                    matches = [lookup.lot]
            if len(matches) > 1:
                errors.append(f"{label}: lot {card.lot_number or card.source_lot_id} has ambiguous cached identities; it was left unchanged.")
                continue
            cached = matches[0] if matches else None
            if is_snapshot and cached and _valid_date(cached.last_seen_at):
                previous_time = parse_lot_datetime(cached.last_seen_at)[0]
                if captured_at < previous_time:
                    notices.append(f"{label}: an older snapshot of lot {card.lot_number or card.source_lot_id} was skipped; its newer cached observation was retained.")
                    continue
            if card.sold_price is not None or (cached and cached.sold_price is not None):
                notices.append(f"{label}: a sold lot was excluded from the upcoming-page import; use Import saved sold results for posted prices.")
                continue
            lot = _merge_saved_card(card, cached, preserve_source_id=is_snapshot)
            if not _valid_date(lot.relevant_at):
                undated += 1
                continue
            if saved.window is not None and not saved.window.contains(lot):
                outside_window += 1
                continue
            lot.artist_watchlist_name = matching_entries[0].artist
            lot.content_hash = lot.calculate_content_hash()
            key = lot.cache_key
            if key in conflicted:
                continue
            if key in observed and observed[key].content_hash != lot.content_hash:
                conflicted.add(key)
                observed.pop(key)
                observation_times.pop(key, None)
                memberships.pop(key, None)
                bundle_observed_keys.discard(key)
                errors.append(f"{label}: selected pages contain conflicting snapshots for lot {lot.lot_number or lot.source_lot_id}; that lot was left unchanged.")
                continue
            observed[key] = lot
            observation_times[key] = max(captured_at, observation_times.get(key, captured_at))
            memberships.setdefault(key, set()).update(entry.url for entry in matching_entries)
            if saved.window is not None:
                bundle_observed_keys.add(key)

    combined: dict[str, NormalizedLot] = {}
    fallback: set[str] = set()
    for key, lot in active.items():
        if key not in observed:
            combined[key] = lot
            fallback.add(key)
            metrics.cache_hits += 1
    for key, lot in observed.items():
        search_hash = lot.content_hash
        transitions = [cache.upsert(lot, watch_url=url, search_hash=search_hash, observed_at=observation_times[key])
                       for url in sorted(memberships[key])]
        transition = "new" if "new" in transitions else "changed" if "changed" in transitions else "unchanged"
        lot.status = transition
        cache.update_payload(lot)
        if transition == "new":
            metrics.new_lots += 1
        elif transition == "changed":
            metrics.changed_lots += 1
        else:
            metrics.unchanged_lots += 1
            metrics.cache_hits += 1
        combined[key] = lot
    # New saved evidence can invalidate an earlier complete/empty result, but
    # never proves that every live results page was checked. Preserve the last
    # real request time so offline imports do not postpone recovery attempts.
    imported_watch_urls = {url for urls in memberships.values() for url in urls}
    for watch_url in sorted(imported_watch_urls):
        cache.record_watch_coverage(
            watch_url, "partial",
            detail="Saved results imported; full live search remains unverified.",
            attempted=False,
        )
    lots = [lot for lot in combined.values() if lot.cache_key in bundle_observed_keys
            or lot_within_horizon(lot, observed_at, horizon_days)]
    if new_changed_only:
        lots = [lot for lot in lots if lot.cache_key not in fallback and lot.status in {"new", "changed"}]
    lots.sort(key=_agenda_sort_key)
    fallback.intersection_update(lot.cache_key for lot in lots)
    if seen_files:
        notices.append(f"Imported {len(observed)} dated Invaluable lots from {seen_files} saved search pages. "
                       "Saved pages are partial snapshots: only loaded cards were imported, and absent cached lots were retained. "
                       "Save and import the remaining results pages to include more lots. Live source access was not verified.")
    if undated:
        notices.append(f"{undated} Invaluable lot cards had no verified sale date and were not imported. "
                       "Save the results with their auction dates visible.")
    if outside_window:
        notices.append(f"{outside_window} captured lots fell outside their bundle's date window and were not imported.")
    if unmatched:
        notices.append(f"{unmatched} cards had incomplete lot identities or did not match the saved artist/category filters and were not imported.")
    return WatchlistResult(
        lots=lots, metrics=metrics, errors=errors, notices=list(dict.fromkeys(notices)),
        fallback_lot_keys=fallback, coverage=cache.coverage_for_entries(chosen),
    )
