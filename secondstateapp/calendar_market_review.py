"""Market review evidence is valid for a specific set of catalog and venue facts."""

from datetime import date
from hashlib import sha256
import json

from django.core.serializers.json import DjangoJSONEncoder

from .models import AuctionLotMarketReview


FIRST_REVIEW_DAY = date(2026, 11, 20)
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


def market_review_fields(lot, row):
    review = getattr(lot, "market_review", None)
    if not review or review.fingerprint != review_fingerprint(
        lot, row["attribution_label"], row["sale_country"], row["sale_region"],
    ):
        return {"market_review_status": "unreviewed", "market_mismatch": None}
    finding = None
    if review.status == AuctionLotMarketReview.Status.MISMATCH:
        finding = {
            "sale_market": review.sale_market, "stronger_market": review.stronger_market,
            "reason": review.reason, "sources": review.sources, "reviewed_at": review.reviewed_at.isoformat(),
        }
    return {"market_review_status": review.status, "market_mismatch": finding}
