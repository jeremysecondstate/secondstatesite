"""Market review evidence is valid for a specific set of catalog and venue facts."""

from hashlib import sha256
import json

from django.core.serializers.json import DjangoJSONEncoder

from .models import AuctionLotMarketReview


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


def mismatch_summary(lot, row):
    review = getattr(lot, "market_review", None)
    if not review or review.status != AuctionLotMarketReview.Status.MISMATCH:
        return None
    fingerprint = review_fingerprint(lot, row["attribution_label"], row["sale_country"], row["sale_region"])
    if fingerprint != review.fingerprint:
        return None
    return {
        "sale_market": review.sale_market, "stronger_market": review.stronger_market,
        "reason": review.reason, "sources": review.sources, "reviewed_at": review.reviewed_at.isoformat(),
    }
