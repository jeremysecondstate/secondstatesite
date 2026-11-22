"""Market review evidence is valid for a specific set of catalog and venue facts."""

from datetime import date
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

from .calendar_market_evidence import resale_auction_houses
from .models import AuctionLotMarketReview


FIRST_REVIEW_DAY = date(2026, 11, 20)
RECHECK_START_DAY = date(2026, 11, 21)
CATALOG_FIELDS = (
    "id", "source", "source_lot_id", "artist", "artist_watchlist_name", "title", "medium",
    "auction_house", "location", "sale_title", "lot_number", "lot_url", "sale_url",
    "event_at", "is_all_day", "currency", "estimate_low", "estimate_high",
)


def review_fingerprint(lot, attribution, country, region):
    facts = [getattr(lot, name) for name in CATALOG_FIELDS]
    facts.extend((attribution, country, region))
    encoded = json.dumps(facts, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def has_artist_signature(sources):
    for source in sources:
        evidence = source.get("artist_signature")
        if isinstance(evidence, dict) and evidence.get("artist") and evidence.get("observation"):
            return True
    return False


def missing_mismatch_evidence(lot, status, sources):
    if status != AuctionLotMarketReview.Status.MISMATCH or not lot.event_at:
        return None
    if lot.event_at.astimezone(ZoneInfo(settings.CALENDAR_TIME_ZONE)).date() < RECHECK_START_DAY:
        return None
    if not has_artist_signature(sources):
        return "cited evidence of the artist’s hand signature on the offered object"
    if not resale_auction_houses(sources):
        return "a cited resale venue labeled 'Resale auction house · House name · City, Country'"
    return None


def review_is_current(lot, review, fingerprint):
    return bool(review and review.fingerprint == fingerprint
                and not missing_mismatch_evidence(lot, review.status, review.sources))


def market_review_fields(lot, row):
    review = getattr(lot, "market_review", None)
    if not review or not review_is_current(lot, review, review_fingerprint(
        lot, row["attribution_label"], row["sale_country"], row["sale_region"],
    )):
        return {"market_review_status": "unreviewed", "market_mismatch": None}
    finding = None
    if review.status == AuctionLotMarketReview.Status.MISMATCH:
        finding = {
            "sale_market": review.sale_market, "stronger_market": review.stronger_market,
            "reason": review.reason, "sources": review.sources, "reviewed_at": review.reviewed_at.isoformat(),
            "resale_auction_houses": resale_auction_houses(review.sources),
        }
    return {"market_review_status": review.status, "market_mismatch": finding}
