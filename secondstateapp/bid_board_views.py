"""Authenticated Bid Board previews and saves; never contacts paid APIs."""

import json
from datetime import timezone as datetime_timezone
from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .bid_board import BidBoardError, BidLadder, build_board, normalize_assumptions
from .models import AuctionBidBoardAnalysis, AuctionWatchLot, LiveArtResaleAnalysis


def _evidence(request, lot, payload, saved):
    # Reuse the existing trusted normalization and cross-source deduplication.
    # Only the opaque server-session research ID is accepted from the browser;
    # browser-submitted candidate prices or scenarios are never trusted.
    from .calendar_views import (
        MAX_SELECTED_RESALE_COMPS, _liveart_search_context, _merged_resale_candidates,
        _selected_resale_ids,
    )
    research_id = payload.get("research_id")
    if research_id:
        research = request.session.get(f"liveart_research_{lot.pk}")
        if not isinstance(research, dict) or research.get("research_id") != research_id:
            raise _StaleResearch("This research was replaced in another tab. Find LiveArt comps again or reload saved research.")
    elif saved:
        research = {
            "candidates": saved.candidates, "selected_ids": saved.selected_ids,
            "subject_match": saved.subject_match, "subject_matches": saved.subject_matches,
            "retrieved_at": saved.retrieved_at.isoformat(), "data_units_spent": saved.data_units_spent,
            **_liveart_search_context(saved.search_context),
        }
    else:
        research = {"candidates": [], "selected_ids": [], "retrieved_at": timezone.now().isoformat()}
    merged = _merged_resale_candidates(lot, research.get("candidates", []))
    candidates, seen = [], set()
    for candidate in merged:
        identity = (candidate.get("provider"), str(candidate.get("id")))
        if identity in seen:
            continue
        seen.add(identity)
        # Legacy unfiltered research remains inspectable in the workbench but
        # cannot become fresh Prints & Multiples evidence without verification.
        if candidate.get("provider") != "Artprice" and str(candidate.get("category_id")) != "2":
            continue
        candidates.append(candidate)
    allowed = {str(item.get("id")) for item in candidates if item.get("credible") is True and item.get("status") == "sold" and item.get("hammer_usd") is not None}
    if "selected_ids" in payload:
        selections = payload["selected_ids"]
        if not isinstance(selections, list) or len(selections) > MAX_SELECTED_RESALE_COMPS or any(isinstance(item, bool) or not isinstance(item, (str, int)) for item in selections):
            raise BidBoardError("Select up to 25 eligible sold USD hammer comparables.")
        selections = list(dict.fromkeys(str(item) for item in selections))
        if any(item not in allowed for item in selections):
            raise BidBoardError("Select only eligible sold USD hammer comparables; LiveArt evidence must be verified Prints & Multiples.")
    else:
        selections = _selected_resale_ids(
            candidates, [str(item) for item in research.get("selected_ids", []) if str(item) in allowed],
            previous_candidates=research.get("candidates", []), initialize_artprice=saved is None and not research_id,
        )
    return research, candidates, selections


class _StaleResearch(BidBoardError):
    pass


def _initial_assumptions(lot, resale):
    initial = {}
    if lot.current_bid is not None and lot.current_bid > 0 and lot.currency.upper() == "USD":
        initial["starting_hammer"] = str(lot.current_bid)
        initial["starting_basis"] = "opening" if lot.bid_count == 0 else "current"
    if resale:
        previous = resale.assumptions
        initial.update({
            "acquisition_costs": str(Decimal(previous.get("inbound_shipping", "200")) + Decimal(previous.get("other_buying_costs", "0"))),
            "selling_costs": str(Decimal(previous.get("outbound_shipping", "0")) + Decimal(previous.get("other_resale_costs", "0"))),
            "selling_commission_pct": previous.get("seller_commission_pct", "0"),
            "downside_factor": previous.get("downside_factor", "0.80"),
            "upside_factor": previous.get("upside_factor", "1.10"),
        })
    return initial


@never_cache
@staff_member_required
@require_http_methods(["GET", "POST"])
def auction_lot_bid_board(request, lot_id):
    lot = AuctionWatchLot.objects.filter(pk=lot_id).first()
    if lot is None:
        return JsonResponse({"ok": False, "error": "Auction lot not found."}, status=404)
    if len(request.body) > 25000:
        return JsonResponse({"ok": False, "error": "Bid Board request is too large."}, status=413)
    try:
        payload = json.loads(request.body or b"{}") if request.method == "POST" else {}
        if not isinstance(payload, dict):
            raise BidBoardError("Bid Board request must be an object.")
        action = payload.get("action", "preview")
        if action not in ("preview", "save"):
            raise BidBoardError("Choose preview or save for the Bid Board.")
        previous = AuctionBidBoardAnalysis.objects.filter(lot=lot).first()
        resale = LiveArtResaleAnalysis.objects.filter(lot=lot).first()
        supplied = payload.get("assumptions", {})
        if not isinstance(supplied, dict):
            raise BidBoardError("Bid assumptions must be an object.")
        assumptions = normalize_assumptions({**_initial_assumptions(lot, resale), **(previous.assumptions if previous else {}), **supplied})
        research, candidates, selected_ids = _evidence(request, lot, payload, resale)
        from .calendar_views import _candidates_with_selection, _liveart_search_context, _lot_resale_scenarios
        evidence_assumptions = {**(resale.assumptions if resale else {}), "downside_factor": assumptions["downside_factor"], "upside_factor": assumptions["upside_factor"]}
        evidence_assumptions, scenarios, summary = _lot_resale_scenarios(lot, candidates, selected_ids, evidence_assumptions, allow_unestimable=True)
        previous_state = previous.analysis if previous else {}
        selected_bid = payload.get("selected_bid", previous_state.get("selected_bid"))
        # A changed ladder must not make an otherwise valid cost preview fail.
        # The next explicit cell selection will establish the new chosen bid.
        if selected_bid is not None and assumptions["starting_hammer"] is not None:
            ladder = BidLadder(assumptions)
            try:
                bid = Decimal(str(selected_bid))
                if not bid.is_finite() or ladder.at(ladder.index_at_or_below(bid)) != bid:
                    selected_bid = None
            except (ArithmeticError, ValueError):
                selected_bid = None
        if not isinstance(payload.get("focus_selected", False), bool):
            raise BidBoardError("focus_selected must be true or false.")
        board = build_board(assumptions, scenarios, summary, page=payload.get("page", 0), selected_bid=selected_bid, selected_case=payload.get("selected_case", previous_state.get("selected_case", "working")), focus_selected=payload.get("focus_selected", False))
        selected_records = [{key: value for key, value in item.items() if key != "selected"} for item in candidates if str(item.get("id")) in selected_ids]
        previous_records = [{key: value for key, value in item.items() if key != "selected"} for item in previous.evidence_snapshot.get("selected_records", [])] if previous else []
        board.update({"selected_ids": selected_ids, "saved": bool(previous), "updated_at": previous.updated_at.isoformat() if previous else None,
                      "evidence_changed_since_save": bool(previous and (previous.evidence_snapshot.get("source_summary") != summary or previous_records != selected_records)),
                      "lot_currency": lot.currency or None})
        if lot.currency.upper() != "USD":
            board["notices"].append("This board calculates USD amounts. The lot's source currency is not USD or is unavailable; no exchange rate or hammer conversion has been assumed.")
        elif lot.current_bid is not None and lot.current_bid > 0:
            board["source_current_hammer"] = f"{lot.current_bid:.2f}"
            if assumptions["starting_hammer"] is not None and lot.current_bid > Decimal(assumptions["starting_hammer"]):
                board["notices"].append(f"The latest synced source reports a ${lot.current_bid:,.2f} USD hammer, above this board's starting amount. Update the current/opening input before relying on available bid ceilings; your saved assumption has been preserved.")
        if summary.get("calculation_error"):
            board["notices"].append(summary["calculation_error"])
        if request.method == "POST" and action == "save":
            retrieved_at = parse_datetime(str(research.get("retrieved_at") or "")) or timezone.now()
            if timezone.is_naive(retrieved_at):
                retrieved_at = timezone.make_aware(retrieved_at, datetime_timezone.utc)
            with transaction.atomic():
                AuctionWatchLot.objects.select_for_update().get(pk=lot.pk)
                # Save the selected evidence through the same model the Day
                # Workbench reads, so both stages always reopen one selection.
                LiveArtResaleAnalysis.objects.update_or_create(lot=lot, defaults={
                    "subject_match": research.get("subject_match") or {}, "subject_matches": research.get("subject_matches") or [],
                    "candidates": _candidates_with_selection(candidates, selected_ids), "selected_ids": selected_ids,
                    "assumptions": evidence_assumptions, "scenarios": scenarios, "source_summary": summary,
                    "search_context": _liveart_search_context(research), "retrieved_at": retrieved_at,
                    "data_units_spent": research.get("data_units_spent"), "created_by": request.user,
                })
                record, _created = AuctionBidBoardAnalysis.objects.update_or_create(lot=lot, defaults={
                    "assumptions": assumptions, "selected_ids": selected_ids, "analysis": board,
                    "evidence_snapshot": {"source_summary": summary, "selected_records": selected_records, "research_retrieved_at": retrieved_at.isoformat()},
                    "updated_by": request.user,
                })
            board.update({"saved": True, "updated_at": record.updated_at.isoformat(), "evidence_changed_since_save": False})
        return JsonResponse({"ok": True, "analysis": board})
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Bid Board request must be valid JSON."}, status=400)
    except _StaleResearch as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=409)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
