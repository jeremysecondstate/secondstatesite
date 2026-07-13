"""Optional compact OpenAI enrichment for ambiguous normalized lot records only."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Iterable

import requests

from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_models import NormalizedLot


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5-mini"


@dataclass(slots=True)
class EnrichmentMetrics:
    records_enriched: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class OpenAIEnricher:
    def __init__(
        self,
        cache: WatchlistCache,
        *,
        api_key: str = "",
        enabled: bool = False,
        model: str = DEFAULT_MODEL,
        max_records_per_batch: int = 50,
        session: requests.Session | None = None,
    ) -> None:
        self.cache = cache
        self.api_key = api_key
        self.enabled = bool(enabled and api_key)
        self.model = model or DEFAULT_MODEL
        self.max_records_per_batch = max(1, min(int(max_records_per_batch), 100))
        self.session = session or requests.Session()

    @classmethod
    def from_environment(cls, cache: WatchlistCache, *, session: requests.Session | None = None) -> "OpenAIEnricher":
        enabled = os.environ.get("OPENAI_WATCHLIST_ENRICHMENT_ENABLED", "0").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            batch_size = int(os.environ.get("OPENAI_WATCHLIST_MAX_RECORDS_PER_BATCH", "50"))
        except ValueError:
            batch_size = 50
        return cls(
            cache,
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            enabled=enabled,
            model=os.environ.get("OPENAI_WATCHLIST_MODEL", DEFAULT_MODEL),
            max_records_per_batch=batch_size,
            session=session,
        )

    def enrich(self, lots: Iterable[NormalizedLot], *, zero_ai: bool = True) -> EnrichmentMetrics:
        metrics = EnrichmentMetrics()
        pending: list[NormalizedLot] = []
        for lot in lots:
            if not lot.ambiguities:
                continue
            cached = self.cache.get_enrichment(lot.content_hash, self.model)
            if cached is not None:
                lot.apply_enrichment(cached)
                metrics.cache_hits += 1
            elif not zero_ai and self.enabled:
                pending.append(lot)
        if zero_ai or not self.enabled:
            return metrics
        for offset in range(0, len(pending), self.max_records_per_batch):
            batch = pending[offset : offset + self.max_records_per_batch]
            payload = self._request_batch(batch)
            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
            metrics.input_tokens += int(usage.get("input_tokens") or 0)
            metrics.output_tokens += int(usage.get("output_tokens") or 0)
            metrics.total_tokens += int(
                usage.get("total_tokens") or (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
            )
            parsed = self._parse_structured_output(payload)
            by_index = {int(item["index"]): item for item in parsed if isinstance(item.get("index"), int)}
            for index, lot in enumerate(batch):
                result = by_index.get(index)
                if not result:
                    continue
                compact = {key: result.get(key) for key in self._result_keys() if key != "index"}
                self.cache.put_enrichment(lot.content_hash, self.model, compact)
                lot.apply_enrichment(compact)
                metrics.records_enriched += 1
        return metrics

    def _request_batch(self, lots: list[NormalizedLot]) -> dict[str, Any]:
        records = [self._compact_record(index, lot) for index, lot in enumerate(lots)]
        body = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Normalize only the ambiguous fields in these already-scraped auction lot records. "
                                "Do not search the web. Preserve unknown values as null."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps({"records": records}, ensure_ascii=False)}],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "watchlist_lot_enrichment",
                    "strict": True,
                    "schema": self._schema(),
                }
            },
            "max_output_tokens": max(300, len(records) * 120),
        }
        response = self.session.post(
            OPENAI_RESPONSES_URL,
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=(10, 60),
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            message = "OpenAI enrichment request failed."
            try:
                detail = response.json().get("error", {}).get("message")
                if detail:
                    message = f"OpenAI enrichment request failed: {detail}"
            except ValueError:
                pass
            raise RuntimeError(message) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("OpenAI enrichment returned an unreadable response.")
        return payload

    @staticmethod
    def _compact_record(index: int, lot: NormalizedLot) -> dict[str, Any]:
        # This allowlist intentionally excludes bookmark HTML, page HTML, cookies,
        # credentials, and URLs. Only compact normalized visible fields leave the PC.
        return {
            "index": index,
            "content_hash": lot.content_hash,
            "ambiguous_fields": list(lot.ambiguities),
            "watchlist_artist": lot.artist_watchlist_name,
            "parsed_artist": lot.artist,
            "title": lot.title,
            "medium": lot.medium,
            "auction_house": lot.auction_house,
            "sale_title": lot.sale_title,
            "lot_number": lot.lot_number,
            "start_at": lot.start_at,
            "end_at": lot.end_at,
            "estimate_low": lot.estimate_low,
            "estimate_high": lot.estimate_high,
            "currency": lot.currency,
        }

    @staticmethod
    def _result_keys() -> tuple[str, ...]:
        return (
            "index",
            "normalized_artist",
            "is_print",
            "medium",
            "end_at",
            "duplicate_group",
            "confidence",
        )

    @classmethod
    def _schema(cls) -> dict[str, Any]:
        properties = {
            "index": {"type": "integer", "minimum": 0},
            "normalized_artist": {"type": ["string", "null"]},
            "is_print": {"type": ["boolean", "null"]},
            "medium": {"type": ["string", "null"]},
            "end_at": {"type": ["string", "null"]},
            "duplicate_group": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }
        return {
            "type": "object",
            "properties": {
                "records": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": properties,
                        "required": list(cls._result_keys()),
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["records"],
            "additionalProperties": False,
        }

    @staticmethod
    def _parse_structured_output(payload: dict[str, Any]) -> list[dict[str, Any]]:
        text = payload.get("output_text")
        if not text:
            pieces: list[str] = []
            for item in payload.get("output", []):
                if not isinstance(item, dict):
                    continue
                for content in item.get("content", []):
                    if isinstance(content, dict) and content.get("text"):
                        pieces.append(str(content["text"]))
            text = "".join(pieces)
        try:
            decoded = json.loads(text or "")
        except (TypeError, ValueError) as exc:
            raise RuntimeError("OpenAI enrichment returned invalid structured output.") from exc
        records = decoded.get("records") if isinstance(decoded, dict) else None
        if not isinstance(records, list):
            raise RuntimeError("OpenAI enrichment returned no records array.")
        return [item for item in records if isinstance(item, dict)]
