import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.core.files.storage import default_storage
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import Artwork, ArtworkImage


TEXT_FIELDS = [
    "title", "artist", "year", "medium", "paper_type", "printer", "publisher",
    "edition_size", "dimensions_text", "sheet_size", "catalog_number",
    "description", "catalog_description",
]

AUCTION_SEARCH_MODEL_ENV = "OPENAI_AUCTION_SEARCH_MODEL"
DEFAULT_AUCTION_SEARCH_MODEL = "gpt-4.1"
AUCTION_SEARCH_TIMEOUT_ENV = "OPENAI_AUCTION_SEARCH_TIMEOUT_SECONDS"
DEFAULT_AUCTION_SEARCH_TIMEOUT = 90
MAX_AUCTION_SEARCH_TIMEOUT = 180


class AuctionSearchError(Exception):
    """Base error for failures while researching upcoming auctions."""


class AuctionSearchTimeout(AuctionSearchError):
    pass


class AuctionSearchUpstreamError(AuctionSearchError):
    pass


class AuctionSearchMalformedError(AuctionSearchError):
    pass


def _authorized(request):
    expected = os.environ.get("CATALOG_API_KEY")
    return bool(expected and request.headers.get("X-API-KEY") == expected)


def _can_manage(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_staff) or _authorized(request)


def _bool(value):
    return str(value).lower() in {"1", "true", "yes", "on"}


def _price(value):
    cleaned = str(value or "0").replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned or "0")
    except (InvalidOperation, ValueError):
        raise ValueError("Price must be a number.")


def _apply(artwork, data):
    for field in TEXT_FIELDS:
        if field in data:
            setattr(artwork, field, data.get(field) or "")
    if "price" in data:
        artwork.price = _price(data.get("price"))
    if "is_available" in data:
        artwork.is_available = _bool(data.get("is_available"))


def _image_url(request, image):
    if not image.image:
        return ""
    try:
        url = image.image.url
    except ValueError:
        return ""
    return request.build_absolute_uri(url) if request else url


def _serialize(request, artwork):
    return {
        "id": artwork.id,
        "display_order": artwork.display_order,
        "artist": artwork.artist,
        "title": artwork.title,
        "year": artwork.year or "",
        "medium": artwork.medium or "",
        "paper_type": artwork.paper_type or "",
        "printer": artwork.printer or "",
        "publisher": artwork.publisher or "",
        "edition_size": artwork.edition_size or "",
        "dimensions_text": artwork.dimensions_text or "",
        "sheet_size": artwork.sheet_size or "",
        "catalog_number": artwork.catalog_number or "",
        "description": artwork.description or "",
        "catalog_description": artwork.catalog_description or "",
        "price": str(artwork.price) if artwork.price is not None else "",
        "formatted_price": artwork.formatted_price,
        "is_available": artwork.is_available,
        "images": [{"id": image.id, "url": _image_url(request, image)} for image in artwork.images.all()],
    }


def _parse_order_ids(raw_order):
    if not isinstance(raw_order, list):
        raise ValueError("Order must be a list of artwork ids.")

    order_ids = []
    for raw_id in raw_order:
        if isinstance(raw_id, bool):
            raise ValueError("Order must contain only artwork ids.")
        try:
            order_ids.append(int(raw_id))
        except (TypeError, ValueError):
            raise ValueError("Order must contain only artwork ids.")

    if len(order_ids) != len(set(order_ids)):
        raise ValueError("Order contains duplicate artwork ids.")

    return order_ids


def _prompt_fields(artwork):
    return {
        "Artist": artwork.artist,
        "Title": artwork.title,
        "Year": artwork.year,
        "Medium": artwork.medium,
        "Image size": artwork.dimensions_text,
        "Sheet size": artwork.sheet_size,
        "Literature": artwork.catalog_number,
        "Notes / signature text": artwork.description,
        "Current description": artwork.catalog_description,
    }


def _extract_text(payload):
    if payload.get("output_text"):
        return payload["output_text"].strip()
    pieces = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("text"):
                pieces.append(content["text"])
    return "\n".join(pieces).strip()


def _parse_aware_timestamp(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required and must be an ISO 8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO 8601 timestamp.") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset.")
    return parsed


def _validate_auction_search_request(data):
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object.")

    horizon = data.get("horizon_days", 7)
    if isinstance(horizon, bool) or (isinstance(horizon, float) and not horizon.is_integer()):
        raise ValueError("horizon_days must be either 3 or 7.")
    try:
        horizon = int(horizon)
    except (TypeError, ValueError) as exc:
        raise ValueError("horizon_days must be either 3 or 7.") from exc
    if horizon not in {3, 7}:
        raise ValueError("horizon_days must be either 3 or 7.")

    minimum_count = data.get("minimum_print_lots", 10)
    if isinstance(minimum_count, bool) or (isinstance(minimum_count, float) and not minimum_count.is_integer()):
        raise ValueError("minimum_print_lots must be a whole number from 1 to 500.")
    try:
        minimum_count = int(minimum_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("minimum_print_lots must be a whole number from 1 to 500.") from exc
    if not 1 <= minimum_count <= 500:
        raise ValueError("minimum_print_lots must be a whole number from 1 to 500.")

    region = data.get("region", "")
    additional_instructions = data.get("additional_instructions", "")
    if not isinstance(region, str) or len(region.strip()) > 200:
        raise ValueError("region must be text no longer than 200 characters.")
    if not isinstance(additional_instructions, str) or len(additional_instructions.strip()) > 2000:
        raise ValueError("additional_instructions must be text no longer than 2,000 characters.")

    start = _parse_aware_timestamp(data.get("client_now"), "client_now")
    return {
        "horizon_days": horizon,
        "minimum_print_lots": minimum_count,
        "region": region.strip(),
        "additional_instructions": additional_instructions.strip(),
        "start": start,
        "end": start + timedelta(days=horizon),
    }


def _auction_search_schema():
    sale_properties = {
        "auction_house": {"type": "string"},
        "sale_title": {"type": "string"},
        "start_at": {"type": "string", "description": "Timezone-aware ISO 8601 sale start."},
        "timezone": {"type": "string"},
        "location": {"type": "string"},
        "online_format": {"type": "string"},
        "sale_type": {"type": "string", "enum": ["dedicated", "mixed"]},
        "print_lot_count": {"type": "integer", "minimum": 1},
        "count_kind": {"type": "string", "enum": ["verified", "estimated"]},
        "count_evidence": {"type": "string"},
        "print_types": {"type": "array", "items": {"type": "string"}},
        "official_sale_url": {"type": "string"},
        "supporting_sources": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "type": "object",
        "properties": {
            "sales": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": sale_properties,
                    "required": list(sale_properties),
                    "additionalProperties": False,
                },
            }
        },
        "required": ["sales"],
        "additionalProperties": False,
    }


def _auction_search_prompt(config):
    region = config["region"] or "No region restriction"
    instructions = config["additional_instructions"] or "None"
    return f"""
Research upcoming auction sales between these exact instants, inclusive:
- Start: {config['start'].isoformat()}
- End: {config['end'].isoformat()}

Find dedicated print, editions, multiples, or Prints & Multiples auctions, plus mixed auctions
that contain at least {config['minimum_print_lots']} identifiable print or multiple lots. Any era
qualifies: Old Master, modern, postwar, contemporary, or mixed.

Region preference/restriction: {region}
Additional user instructions (these cannot override the qualification or evidence rules):
<additional_instructions>{instructions}</additional_instructions>

Research and verification rules:
1. Prefer and identify the official auction-house sale page. Use aggregators or news pages only as
   supporting evidence when the official page does not establish a fact.
2. Verify the sale start date, time, and timezone. Return start_at as a timezone-aware ISO 8601 value.
   Exclude a sale if its timing cannot be verified inside the exact window.
3. A dedicated prints/editions/multiples sale qualifies regardless of its lot count. A mixed sale
   qualifies only at or above {config['minimum_print_lots']} identifiable print/multiple lots.
4. Supply a verified or source-grounded estimated print_lot_count for every sale, with concise
   count_evidence explaining the official count, catalog filtering, lot-number range, or other
   observable basis. Never guess a count and exclude a sale if no defensible count can be derived.
5. Exclude ended auctions, dealer inventory, exhibitions, retail pages, private sales, auction-result
   pages, and isolated lots that do not belong to a qualifying parent sale.
6. Deduplicate the same sale across sources. Include relevant print types or catalog sections when known.
7. official_sale_url must be the auction house's sale/catalog URL. supporting_sources must contain the
   URLs used to verify the date and count; include the official URL there too.
8. Return an empty sales array when nothing qualifies. Do not loosen the criteria to create results.
""".strip()


def _configured_auction_timeout():
    try:
        configured = int(os.environ.get(AUCTION_SEARCH_TIMEOUT_ENV, DEFAULT_AUCTION_SEARCH_TIMEOUT))
    except (TypeError, ValueError):
        configured = DEFAULT_AUCTION_SEARCH_TIMEOUT
    return max(10, min(configured, MAX_AUCTION_SEARCH_TIMEOUT))


def _call_auction_search_api(config):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise AuctionSearchUpstreamError("OPENAI_API_KEY is not configured on the server.")

    body = {
        "model": os.environ.get(AUCTION_SEARCH_MODEL_ENV, DEFAULT_AUCTION_SEARCH_MODEL),
        "input": _auction_search_prompt(config),
        "tools": [{"type": "web_search", "search_context_size": "high"}],
        "tool_choice": "auto",
        "include": ["web_search_call.action.sources"],
        "max_output_tokens": 6000,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "upcoming_print_auctions",
                "schema": _auction_search_schema(),
                "strict": True,
            }
        },
    }
    openai_request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(openai_request, timeout=_configured_auction_timeout()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
            message = error_payload.get("error", {}).get("message") or str(error_payload)
        except Exception:
            message = str(exc)
        raise AuctionSearchUpstreamError(f"OpenAI request failed: {message}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise AuctionSearchTimeout("OpenAI auction research timed out.") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise AuctionSearchTimeout("OpenAI auction research timed out.") from exc
        raise AuctionSearchUpstreamError(f"OpenAI request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise AuctionSearchMalformedError("OpenAI returned an unreadable response.") from exc
    except OSError as exc:
        raise AuctionSearchUpstreamError(f"OpenAI request failed: {exc}") from exc


def _valid_web_url(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or any(character.isspace() for character in value):
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _normalized_url_key(value):
    parsed = urllib.parse.urlsplit(value)
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def _collect_response_urls(value, found=None):
    found = found if found is not None else []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"url", "official_sale_url"}:
                url = _valid_web_url(child)
                if url:
                    found.append(url)
            _collect_response_urls(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_response_urls(child, found)
    elif isinstance(value, str):
        url = _valid_web_url(value)
        if url:
            found.append(url)
    return found


def _required_text(sale, field_name):
    value = sale.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise AuctionSearchMalformedError(f"OpenAI returned a sale without {field_name}.")
    return value.strip()


def _normalize_auction_sales(raw_sales, config):
    if not isinstance(raw_sales, list):
        raise AuctionSearchMalformedError("OpenAI response did not contain a sales list.")

    normalized = []
    seen = set()
    for raw_sale in raw_sales:
        if not isinstance(raw_sale, dict):
            raise AuctionSearchMalformedError("OpenAI returned an invalid sale record.")

        auction_house = _required_text(raw_sale, "auction_house")
        sale_title = _required_text(raw_sale, "sale_title")
        timezone_name = _required_text(raw_sale, "timezone")
        try:
            start_at = _parse_aware_timestamp(raw_sale.get("start_at"), "sale start_at")
        except ValueError as exc:
            raise AuctionSearchMalformedError(str(exc)) from exc
        if start_at < config["start"] or start_at > config["end"]:
            continue

        sale_type = raw_sale.get("sale_type")
        if sale_type not in {"dedicated", "mixed"}:
            raise AuctionSearchMalformedError("OpenAI returned an invalid sale_type.")
        count = raw_sale.get("print_lot_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise AuctionSearchMalformedError("OpenAI returned an invalid print_lot_count.")
        if sale_type == "mixed" and count < config["minimum_print_lots"]:
            continue
        count_kind = raw_sale.get("count_kind")
        if count_kind not in {"verified", "estimated"}:
            raise AuctionSearchMalformedError("OpenAI returned an invalid count_kind.")
        count_evidence = _required_text(raw_sale, "count_evidence")

        official_url = _valid_web_url(raw_sale.get("official_sale_url"))
        if not official_url:
            raise AuctionSearchMalformedError("OpenAI returned a sale without a valid official URL.")
        source_values = raw_sale.get("supporting_sources")
        if not isinstance(source_values, list):
            raise AuctionSearchMalformedError("OpenAI returned invalid supporting sources.")
        sources = []
        for value in [official_url, *source_values]:
            url = _valid_web_url(value)
            if url and _normalized_url_key(url) not in {_normalized_url_key(item) for item in sources}:
                sources.append(url)

        print_types = raw_sale.get("print_types")
        if not isinstance(print_types, list) or any(not isinstance(value, str) for value in print_types):
            raise AuctionSearchMalformedError("OpenAI returned invalid print types.")
        print_types = [value.strip() for value in print_types if value.strip()]

        dedupe_key = _normalized_url_key(official_url)
        fallback_key = (auction_house.casefold(), sale_title.casefold(), start_at.isoformat())
        if dedupe_key in seen or fallback_key in seen:
            continue
        seen.update({dedupe_key, fallback_key})
        normalized.append(
            {
                "auction_house": auction_house,
                "sale_title": sale_title,
                "start_at": start_at,
                "timezone": timezone_name,
                "location": str(raw_sale.get("location") or "").strip(),
                "online_format": str(raw_sale.get("online_format") or "").strip(),
                "sale_type": sale_type,
                "print_lot_count": count,
                "count_kind": count_kind,
                "count_evidence": count_evidence,
                "print_types": print_types,
                "official_sale_url": official_url,
                "supporting_sources": sources,
            }
        )
    return sorted(normalized, key=lambda sale: sale["start_at"])


def _markdown_text(value):
    return str(value).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ").strip()


def _render_auction_markdown(sales, config):
    lines = [
        "# Upcoming Print Auctions",
        "",
        f"**Research window:** {config['start'].isoformat()} through {config['end'].isoformat()} (inclusive)",
        f"**Mixed-sale threshold:** at least {config['minimum_print_lots']} identifiable print/multiple lots",
    ]
    if config["region"]:
        lines.append(f"**Region:** {_markdown_text(config['region'])}")
    lines.append("")

    if not sales:
        lines.append("No qualifying upcoming print auctions were found in this window.")
        return "\n".join(lines)

    for sale in sales:
        start_at = sale["start_at"]
        date_heading = start_at.strftime("%Y-%m-%d")
        format_parts = [part for part in [sale["location"], sale["online_format"]] if part]
        source_links = [f"[Source {index}]({url})" for index, url in enumerate(sale["supporting_sources"], 1)]
        lines.extend(
            [
                f"## {date_heading} — {_markdown_text(sale['auction_house'])} — {_markdown_text(sale['sale_title'])}",
                "",
                f"- **Date/time:** {start_at.strftime('%Y-%m-%d %H:%M %z')} ({_markdown_text(sale['timezone'])})",
                f"- **Location/format:** {_markdown_text(' / '.join(format_parts) or 'Not stated')}",
                f"- **Sale type:** {'Dedicated print/multiples sale' if sale['sale_type'] == 'dedicated' else 'Mixed sale'}",
                f"- **Print/multiple lots:** {sale['print_lot_count']} ({sale['count_kind']}) — {_markdown_text(sale['count_evidence'])}",
                f"- **Print types/sections:** {_markdown_text(', '.join(sale['print_types']) or 'Not stated')}",
                f"- **Official sale:** [Auction-house sale page]({sale['official_sale_url']})",
                f"- **Supporting sources:** {', '.join(source_links)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _research_upcoming_print_auctions(config):
    response_payload = _call_auction_search_api(config)
    if not isinstance(response_payload, dict):
        raise AuctionSearchMalformedError("OpenAI returned an unreadable response.")
    try:
        text = _extract_text(response_payload)
    except (AttributeError, TypeError) as exc:
        raise AuctionSearchMalformedError("OpenAI returned malformed auction data.") from exc
    if not text:
        raise AuctionSearchMalformedError("OpenAI returned no structured auction data.")
    try:
        structured = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuctionSearchMalformedError("OpenAI returned malformed auction data.") from exc
    if not isinstance(structured, dict):
        raise AuctionSearchMalformedError("OpenAI returned malformed auction data.")

    sales = _normalize_auction_sales(structured.get("sales"), config)
    cited_urls = _collect_response_urls(response_payload)
    source_urls = []
    for value in [*cited_urls, *(url for sale in sales for url in sale["supporting_sources"])]:
        key = _normalized_url_key(value)
        if key not in {_normalized_url_key(item) for item in source_urls}:
            source_urls.append(value)
    return sales, source_urls


def _generate_description(artwork, use_web=True):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured on the server.")
    facts = "\n".join(f"{k}: {v}" for k, v in _prompt_fields(artwork).items() if v)
    prompt = f"""
Write a polished SecondState artwork catalog description for the print below.
Use 85 to 140 words. Write in a confident fine-art gallery voice.
Do not invent edition details, provenance, signatures, condition, or price.
Return only the description paragraph.

Artwork facts:
{facts}
""".strip()
    body = {
        "model": os.environ.get("OPENAI_DESCRIPTION_MODEL", "gpt-4.1"),
        "input": prompt,
        "max_output_tokens": 450,
        "temperature": 0.4,
    }
    if use_web:
        body["tools"] = [{"type": "web_search", "search_context_size": "low"}]
        body["tool_choice"] = "auto"
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message")
        except Exception:
            message = str(exc)
        raise RuntimeError(f"OpenAI request failed: {message}") from exc
    text = _extract_text(payload)
    if not text:
        raise RuntimeError("OpenAI returned an empty description.")
    return text


@require_GET
def artwork_manage_list(request):
    if not _can_manage(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    artworks = Artwork.objects.prefetch_related("images").order_by("display_order", "id")
    return JsonResponse({"artworks": [_serialize(request, artwork) for artwork in artworks]})


@csrf_exempt
@require_POST
def reorder_artworks(request):
    if not _can_manage(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
        order_ids = _parse_order_ids(data.get("order"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    with transaction.atomic():
        artworks = list(Artwork.objects.select_for_update().prefetch_related("images").order_by("display_order", "id"))
        artwork_by_id = {artwork.id: artwork for artwork in artworks}
        current_ids = set(artwork_by_id)
        submitted_ids = set(order_ids)
        unknown_ids = sorted(submitted_ids - current_ids)
        missing_ids = sorted(current_ids - submitted_ids)
        if unknown_ids or missing_ids:
            details = []
            if unknown_ids:
                details.append(f"unknown ids: {unknown_ids}")
            if missing_ids:
                details.append(f"missing ids: {missing_ids}")
            return JsonResponse({"error": "Invalid artwork order; " + "; ".join(details)}, status=400)

        ordered_artworks = []
        for index, artwork_id in enumerate(order_ids):
            artwork = artwork_by_id[artwork_id]
            artwork.display_order = index
            ordered_artworks.append(artwork)
        Artwork.objects.bulk_update(ordered_artworks, ["display_order"])

    refreshed = Artwork.objects.prefetch_related("images").order_by("display_order", "id")
    return JsonResponse(
        {
            "message": "Artwork order updated.",
            "artworks": [_serialize(request, artwork) for artwork in refreshed],
        }
    )


@csrf_exempt
@require_POST
def generate_catalog_description_from_payload(request):
    if not _can_manage(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
        artwork = Artwork(price=Decimal("0"), is_available=True)
        _apply(artwork, data)
        return JsonResponse({"description": _generate_description(artwork, data.get("use_web", True))})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@csrf_exempt
@require_POST
def search_upcoming_print_auctions(request):
    if not _can_manage(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
        config = _validate_auction_search_request(data)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    try:
        sales, source_urls = _research_upcoming_print_auctions(config)
    except AuctionSearchTimeout:
        return JsonResponse({"error": "Auction research timed out. Please try again."}, status=504)
    except AuctionSearchMalformedError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except AuctionSearchUpstreamError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    return JsonResponse(
        {
            "markdown": _render_auction_markdown(sales, config),
            "window": {
                "start": config["start"].isoformat(),
                "end": config["end"].isoformat(),
                "horizon_days": config["horizon_days"],
                "timezone": str(config["start"].tzinfo),
            },
            "minimum_print_lots": config["minimum_print_lots"],
            "region": config["region"],
            "auction_count": len(sales),
            "source_urls": source_urls,
        }
    )


@csrf_exempt
def update_artwork(request, pk):
    if request.method not in {"POST", "PATCH"}:
        return JsonResponse({"error": "Invalid request method"}, status=405)
    if not _authorized(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    artwork = get_object_or_404(Artwork, id=pk)
    try:
        data = request.POST.copy()
        _apply(artwork, data)
        artwork.save()
        for image_id in request.POST.getlist("delete_image_ids"):
            image = artwork.images.filter(id=image_id).first()
            if image:
                if image.image and default_storage.exists(image.image.name):
                    default_storage.delete(image.image.name)
                image.delete()
        for _key, uploaded in request.FILES.items():
            ArtworkImage.objects.create(artwork=artwork, image=uploaded)
        artwork.refresh_from_db()
        return JsonResponse({"message": "Artwork updated successfully!", "artwork": _serialize(request, artwork)})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)
