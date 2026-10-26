"""Read saved Bid Boards without refreshing evidence or recalculating bids."""

from copy import deepcopy

from .bid_board import CASE_LABELS


def saved_board_summary(record):
    if record is None:
        return None
    analysis = record.analysis or {}
    case = analysis.get("selected_case", "working")
    detail = analysis.get("detail")
    qualifying = next(
        (pick for pick in analysis.get("shortlist", []) if pick.get("case_key") == case),
        {},
    )
    return {
        "selected_bid": analysis.get("selected_bid"),
        "selected_case": case,
        "selected_case_label": CASE_LABELS.get(case, case),
        "qualifies": detail.get("qualifies") if detail else None,
        "qualifying_bid": qualifying.get("bid"),
        "qualifying_coverage_limited": bool(qualifying.get("coverage_limited")),
        "coverage_limit": analysis.get("coverage_limit"),
        "detail": deepcopy(detail),
        "updated_at": record.updated_at.isoformat(),
        "include_in_email": record.include_in_email,
    }


def saved_board_snapshot(record):
    if record is None:
        return None
    analysis = deepcopy(record.analysis or {})
    # Older saves serialized these fields before the save completed. The row's
    # timestamp is authoritative; none of the financial snapshot is rebuilt.
    analysis.update(saved=True, updated_at=record.updated_at.isoformat(), evidence_changed_since_save=False)
    return {
        "analysis": analysis,
        "assumptions": deepcopy(record.assumptions),
        "selected_ids": deepcopy(record.selected_ids),
        "evidence_snapshot": deepcopy(record.evidence_snapshot),
        "summary": saved_board_summary(record),
        "updated_at": record.updated_at.isoformat(),
        "include_in_email": record.include_in_email,
    }
