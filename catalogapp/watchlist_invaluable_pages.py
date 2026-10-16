"""Import visible Invaluable artist-search snapshots without a network request."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment

from catalogapp.bookmark_watchlist import BookmarkEntry, canonicalize_bookmark_url, source_for_url
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_models import NormalizedLot, lot_within_horizon, parse_lot_datetime
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult, _agenda_sort_key, _retain_missing_static_fields


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


def _search_scope(url: str) -> tuple[tuple[str, str], ...]:
    """Compare membership filters while allowing presentation-only URL changes."""
    ignored = {"artist", "artistname", "page", "sort", "view", "pagesize", "page_size", "hitsperpage", "perpage"}
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
    subcategory = InvaluableAdapter._artist_match_key(str(hit.get("subcategoryName") or ""))
    return any((not supercategory or supercategory == category) and (not subcategory or subcategory == value)
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
    conflicted: set[str] = set()
    undated = 0
    unmatched = 0
    seen_files = 0
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    for path in selected_paths:
        is_snapshot = path.suffix.casefold() == ".json"
        if path.suffix.casefold() not in {".html", ".htm", ".json"}:
            errors.append(f"{path.name}: choose a saved Invaluable HTML search page or JSON snapshot.")
            continue
        try:
            page = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            errors.append(f"{path.name}: the saved page could not be read.")
            continue
        captured_at = observed_at
        if is_snapshot:
            try:
                payload = json.loads(page)
                if not isinstance(payload, dict):
                    raise ValueError("the snapshot must contain a JSON object")
                page_url = _public_url(str(payload.get("source_url", "")))
                if (not page_url or source_for_url(page_url) != "Invaluable"
                        or urlsplit(page_url).path.rstrip("/").casefold() != "/search" or not _search_artist(page_url)):
                    raise ValueError("the snapshot needs an Invaluable artist-search source_url")
                captured_at = datetime.fromisoformat(str(payload.get("captured_at", "")).replace("Z", "+00:00"))
                if captured_at.tzinfo is None or captured_at.timestamp() > observed_at.timestamp() + 300:
                    raise ValueError("captured_at must include a timezone and cannot be in the future")
                catalog_result = adapter._catalog_result(payload)
                if catalog_result is None or len(payload.get("results", [])) != 1:
                    raise ValueError("the snapshot must contain exactly one catalog result with hits")
                if any(not isinstance(hit, dict) or not hit.get("artistName") for hit in catalog_result["hits"]):
                    raise ValueError("each snapshot lot must include its verified artistName")
            except (ValueError, TypeError, OverflowError) as exc:
                errors.append(f"{path.name}: invalid Invaluable snapshot ({exc}); no lots were imported from this file.")
                continue
        else:
            soup = BeautifulSoup(page, "html.parser")
            try:
                page_url = _saved_search_url(soup)
            except ValueError as exc:
                errors.append(f"{path.name}: {exc}; no lots were imported from this file.")
                continue
        artist = _search_artist(page_url)
        matching_entries = [entry for entry in by_artist.get(adapter._artist_match_key(artist), [])
                            if _search_scope(entry.url) == _search_scope(page_url)]
        if not matching_entries:
            errors.append(f"{path.name}: its artist, category, or search-query filters do not match a selected Invaluable bookmark.")
            continue
        if is_snapshot:
            scoped_hits = [hit for hit in catalog_result["hits"] if _hit_matches_category(hit, page_url)]
            unmatched += len(catalog_result["hits"]) - len(scoped_hits)
            cards = adapter.parse_search_page(json.dumps({"results": [{"hits": scoped_hits}]}), page_url, artist)
        else:
            headings = " ".join(node.get_text(" ", strip=True) for node in soup.select("title, h1")).casefold()
            if any(term in headings for term in ("javascript is disabled", "access denied", "verify you are human", "just a moment")):
                errors.append(f"{path.name}: this is an access page; save the search after its lot cards have loaded.")
                continue
            cards = _visible_cards(adapter, soup, page_url, artist)
        if not cards:
            if is_snapshot:
                seen_files += 1
                if not catalog_result["hits"] and type(catalog_result.get("nbHits")) is int and catalog_result["nbHits"] == 0:
                    notices.append(f"{path.name}: the captured search reported zero matching lots. This partial snapshot did not end or remove any cached lots.")
                else:
                    notices.append(f"{path.name}: the snapshot contains no readable lots matching the selected filters. Existing cached lots were retained.")
            else:
                notices.append(f"{path.name}: no readable lot cards were found. Save the loaded artist results page as Webpage, Complete.")
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
                errors.append(f"{path.name}: lot {card.lot_number or card.source_lot_id} has ambiguous cached identities; it was left unchanged.")
                continue
            cached = matches[0] if matches else None
            if is_snapshot and cached and _valid_date(cached.last_seen_at):
                previous_time = parse_lot_datetime(cached.last_seen_at)[0]
                if captured_at < previous_time:
                    notices.append(f"{path.name}: an older snapshot of lot {card.lot_number or card.source_lot_id} was skipped; its newer cached observation was retained.")
                    continue
            if card.sold_price is not None or (cached and cached.sold_price is not None):
                notices.append(f"{path.name}: a sold lot was excluded from the upcoming-page import; use Import saved sold results for posted prices.")
                continue
            lot = _merge_saved_card(card, cached, preserve_source_id=is_snapshot)
            if not _valid_date(lot.relevant_at):
                undated += 1
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
                errors.append(f"{path.name}: selected pages contain conflicting snapshots for lot {lot.lot_number or lot.source_lot_id}; that lot was left unchanged.")
                continue
            observed[key] = lot
            observation_times[key] = max(captured_at, observation_times.get(key, captured_at))
            memberships.setdefault(key, set()).update(entry.url for entry in matching_entries)

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
    lots = [lot for lot in combined.values() if lot_within_horizon(lot, observed_at, horizon_days)]
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
    if unmatched:
        notices.append(f"{unmatched} cards had incomplete lot identities or did not match the saved artist/category filters and were not imported.")
    return WatchlistResult(lots=lots, metrics=metrics, errors=errors, notices=list(dict.fromkeys(notices)), fallback_lot_keys=fallback)
