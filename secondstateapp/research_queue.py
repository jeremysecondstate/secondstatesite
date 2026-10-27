"""Finite research passes. Every mutation shares the singleton database lock.

Selection is independent of saved links/research. Runs never discover more work
after their explicit start, and no elapsed-time rule can steal ownership.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import json
import uuid
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max
from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict
from django.urls import reverse
from django.utils import timezone

from .models import AuctionBidBoardAnalysis, AuctionWatchLot, LiveArtResaleAnalysis
from .research_queue_models import ResearchQueueItem, ResearchQueueOperation, ResearchQueueRun, ResearchQueueRunItem, ResearchQueueState


class QueueError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _uuid(value, label):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise QueueError(f"{label} must be a UUID.", 400)


@contextmanager
def _locked():
    with transaction.atomic():
        state, _ = ResearchQueueState.objects.get_or_create(pk=1)
        ResearchQueueState.objects.select_for_update().get(pk=state.pk)
        # Also acquire SQLite's write lock before reading mutable queue state.
        ResearchQueueState.objects.filter(pk=1).update(revision=F("revision") + 1)
        yield


def selected_queue_state():
    return {row["lot_id"]: {"status": row["status"], "disposition": row["disposition"]} for row in ResearchQueueItem.objects.filter(selected=True).values("lot_id", "status", "disposition")}


def item_json(item):
    return {"id": item.pk, "lot_id": item.lot_id, "selected": item.selected,
            "position": item.position, "note": item.note, "status": item.status,
            "disposition": item.disposition, "generation": item.generation,
            "latest_result": item.latest_result}


def _workflow_url(lot, look):
    zone = ZoneInfo(settings.CALENDAR_TIME_ZONE)
    day = timezone.localtime(lot.event_at, zone).date() if lot.event_at else timezone.localdate(timezone=zone)
    params = {"month": day.strftime("%Y-%m"), "day": day.isoformat(), "view": "research", "lot": lot.pk, "look": look}
    return reverse("auction_calendar") + "?" + urlencode(params)


def queue_context():
    items = list(ResearchQueueItem.objects.filter(selected=True).select_related("lot", "lot__liveart_resale_analysis", "lot__bid_board_analysis"))
    for index, item in enumerate(items):
        item.can_move_up, item.can_move_down = index > 0, index < len(items) - 1
        item.dossier_url = _workflow_url(item.lot, "dossier")
        item.research_url = _workflow_url(item.lot, "workbench") if hasattr(item.lot, "liveart_resale_analysis") else ""
        item.board_url = _workflow_url(item.lot, "bidboard") if hasattr(item.lot, "bid_board_analysis") else ""
        item.image_url, item.sale_date = item.lot.image_url, item.lot.event_at
    return {"queue_items": items, "queue_count": len(items), "research_queue_count": len(items),
            "active_run": ResearchQueueRun.objects.filter(status="running").first(),
            "recent_runs": ResearchQueueRun.objects.all()[:10]}


def _update_current(item, **values):
    ResearchQueueItem.objects.filter(pk=item.queue_item_id, generation=item.queue_generation).update(updated_at=timezone.now(), **values)


def select_lot(lot_id, selected):
    if not isinstance(selected, bool):
        raise QueueError("selected must be true or false.", 400)
    with _locked():
        try:
            lot = AuctionWatchLot.objects.get(pk=lot_id)
        except AuctionWatchLot.DoesNotExist:
            raise QueueError("Lot not found.", 404)
        item = ResearchQueueItem.objects.filter(lot=lot).first()
        if not item:
            position = (ResearchQueueItem.objects.aggregate(value=Max("position"))["value"] or 0) + 1
            item = ResearchQueueItem.objects.create(lot=lot, selected=selected, position=position)
        elif item.selected != selected:
            item.selected, item.updated_at = selected, timezone.now()
            if selected:
                item.position = (ResearchQueueItem.objects.aggregate(value=Max("position"))["value"] or 0) + 1
            item.save(update_fields=["selected", "position", "updated_at"])
        if not selected:
            # A claimed item belongs to its immutable pass even after removal.
            for frozen in item.run_items.filter(status="queued", run__status="running"):
                frozen.status, frozen.disposition = "done", "skipped"
                frozen.reason = "Removed from the queue by staff before research began."
                frozen.completed_at = timezone.now()
                frozen.outcome = {"disposition": "skipped", "reason": frozen.reason, "source_proof": {"staff_queue_removal": True}}
                frozen.save(update_fields=["status", "disposition", "reason", "completed_at", "outcome"])
                _update_current(frozen, status="done", disposition="skipped", latest_result=frozen.outcome)
            item.refresh_from_db()
        return item


def change_item(lot_id, payload):
    action = payload.get("action")
    if action == "remove":
        return select_lot(lot_id, False)
    with _locked():
        try:
            item = ResearchQueueItem.objects.get(lot_id=lot_id)
        except ResearchQueueItem.DoesNotExist:
            raise QueueError("Queue item not found.", 404)
        if action == "note":
            note = payload.get("note", "")
            if not isinstance(note, str) or len(note) > 10000:
                raise QueueError("Note must be text of at most 10,000 characters.", 400)
            item.note = note
        elif action == "move":
            items = list(ResearchQueueItem.objects.filter(selected=True))
            if item.pk not in [row.pk for row in items]:
                raise QueueError("Only selected items can be reordered.")
            index = next(i for i, row in enumerate(items) if row.pk == item.pk)
            items.pop(index)
            direction = payload.get("direction")
            if direction in ("up", "down"):
                index = max(0, min(len(items), index + (-1 if direction == "up" else 1)))
            else:
                before = payload.get("before_lot_id")
                if before in (None, ""):
                    index = len(items)
                else:
                    try:
                        index = next(i for i, row in enumerate(items) if row.lot_id == int(before))
                    except (ValueError, TypeError, StopIteration):
                        raise QueueError("Move target is not selected.", 400)
            items.insert(index, item)
            for position, row in enumerate(items, 1):
                ResearchQueueItem.objects.filter(pk=row.pk).update(position=position)
            item.refresh_from_db()
        elif action == "requeue":
            reason = payload.get("reason")
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
                raise QueueError("An explicit retry reason of at most 2,000 characters is required.", 400)
            if item.run_items.filter(run__status="running", status__in=["queued", "researching"]).exists():
                raise QueueError("This lot still belongs to an unfinished pass.")
            if ResearchQueueOperation.objects.filter(item__queue_item=item, settled_at__isnull=True).exists():
                raise QueueError("Reconcile unresolved operations before explicitly requeueing this lot.")
            item.requeue_history = [*item.requeue_history, {"reason": reason.strip(), "previous_generation": item.generation, "previous_status": item.status, "at": timezone.now().isoformat()}]
            item.selected, item.status, item.disposition = True, "queued", ""
            item.generation += 1
        else:
            raise QueueError("Unknown queue action.", 400)
        item.updated_at = timezone.now()
        item.save()
        return item


def _lot_snapshot(lot):
    return {**{name: getattr(lot, name) for name in ("id", "source", "source_lot_id", "artist", "artist_watchlist_name", "title", "medium", "auction_house", "lot_number", "lot_url", "sale_url", "image_url", "artprice_url")}, "dossier_url": _workflow_url(lot, "dossier")}


def operation_json(operation):
    return {"operation_id": str(operation.pk), "kind": operation.kind, "details": operation.details,
            "status": "settled" if operation.settled_at else "intent", "result": operation.receipt,
            "units_spent": str(operation.units_spent) if operation.units_spent is not None else None}


def run_json(run):
    items = []
    for item in run.items.select_related("lot__liveart_resale_analysis", "lot__bid_board_analysis").prefetch_related("operations"):
        current_proof = {}
        for relation, prefix in (("liveart_resale_analysis", "liveart"), ("bid_board_analysis", "bid_board")):
            record = getattr(item.lot, relation, None)
            if record is not None:
                current_proof.update({f"{prefix}_analysis_id": record.pk, f"{prefix}_updated_at": record.updated_at.isoformat()})
        items.append({"id": item.pk, "lot_id": item.lot_id, "position": item.position,
                      "lot_snapshot": item.lot_snapshot, "note_snapshot": item.note_snapshot,
                      "status": item.status, "disposition": item.disposition, "reason": item.reason,
                      "claimed_at": item.claimed_at.isoformat() if item.claimed_at else None,
                      "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                      "outcome": item.outcome, "saved_revisions": item.saved_revisions,
                      "current_saved_proof": current_proof,
                      "operations": [operation_json(op) for op in item.operations.all()]})
    return {"id": str(run.pk), "request_id": str(run.request_id), "owner_token": str(run.owner_token),
            "thread_id": run.thread_id, "status": run.status, "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "block_reason": run.block_reason, "recovery_log": run.recovery_log,
            "completion_audit": run.completion_audit, "items": items}


def get_run(run_id):
    try:
        return ResearchQueueRun.objects.get(pk=_uuid(run_id, "run_id"))
    except ResearchQueueRun.DoesNotExist:
        raise QueueError("Run not found.", 404)


RESEARCH_CHECKS = ("google_original_researched", "liveart_browser_researched", "evidence_saved_reloaded", "board_saved_reloaded", "costs_verified", "selection_verified", "email_flags_verified")


def _revision(model):
    values = model_to_dict(model)
    values.update(id=model.pk, updated_at=model.updated_at.isoformat())
    return json.loads(json.dumps(values, cls=DjangoJSONEncoder))


def _validate_outcome(item, payload):
    disposition = payload.get("disposition")
    reason = payload.get("reason")
    if not isinstance(disposition, str) or disposition not in {"researched", "triaged", "skipped", "valuation_unavailable"}:
        raise QueueError("A distinct supported disposition is required.", 400)
    if not isinstance(reason, str) or not reason.strip():
        raise QueueError("A truthful outcome reason is required.", 400)
    if disposition in {"triaged", "skipped"}:
        if not isinstance(payload.get("source_proof"), dict) or not payload["source_proof"]:
            raise QueueError("This disposition requires source_proof explaining the decision.", 400)
        return {}
    if disposition == "valuation_unavailable" and (not isinstance(payload.get("source_proof"), dict) or not payload["source_proof"]):
        raise QueueError("Valuation unavailable requires source_proof explaining the limitation.", 400)
    checks, proof = payload.get("checks", {}), payload.get("proof", {})
    if not isinstance(checks, dict) or not isinstance(proof, dict):
        raise QueueError("Completion checks and saved-revision proof are required.", 400)
    gaps = proof.get("verification_gaps", {})
    for check in RESEARCH_CHECKS:
        if checks.get(check) is not True:
            if check == "email_flags_verified" and isinstance(gaps, dict) and isinstance(gaps.get("email_flags"), str) and gaps["email_flags"].strip():
                continue
            raise QueueError(f"Completion check missing: {check}.", 400)
    AuctionWatchLot.objects.select_for_update().get(pk=item.lot_id)
    analysis = LiveArtResaleAnalysis.objects.select_for_update().filter(lot_id=item.lot_id).first()
    board = AuctionBidBoardAnalysis.objects.select_for_update().filter(lot_id=item.lot_id).first()
    for model, prefix in ((analysis, "liveart"), (board, "bid_board")):
        if model is None or str(proof.get(f"{prefix}_analysis_id")) != str(model.pk) or proof.get(f"{prefix}_updated_at") != model.updated_at.isoformat():
            raise QueueError(f"Current saved {prefix} revision does not match completion proof.")
    if disposition == "researched" and (not analysis.candidates or not analysis.selected_ids):
        raise QueueError("Saved LiveArt evidence and a saved comparable selection are required.")
    if not board.evidence_snapshot or not board.analysis:
        raise QueueError("A saved Board with evidence and analysis is required.")
    selected = [str(value) for value in analysis.selected_ids]
    records = [{key: value for key, value in row.items() if key != "selected"} for row in analysis.candidates if isinstance(row, dict) and str(row.get("id")) in selected]
    # Match the Board's existing saved-evidence comparison. A newer evidence
    # save may exist alongside an older Board, even when both supplied timestamps
    # accurately name their current records.
    if ([str(value) for value in board.selected_ids] != selected
            or {str(row.get("id")) for row in records} != set(selected)
            or board.evidence_snapshot.get("selected_records") != records
            or board.evidence_snapshot.get("source_summary") != analysis.source_summary):
        raise QueueError("Saved evidence changed after the Board save; save and reload the Board with the current evidence before completing this lot.")
    return {"liveart": _revision(analysis), "bid_board": _revision(board)}


def _validate_completion_audit(run, audit):
    """Server proves scope; the supported local client verifies receipt files."""
    if not isinstance(audit, dict) or audit.get("schema_version") != 1 or audit.get("run_id") != str(run.pk) or audit.get("thread_id") != run.thread_id:
        raise QueueError("Completion audit identity and schema must match the frozen run.", 400)
    for key in ("bookkeeping_complete", "usage_accounted", "operations_settled", "cleanup_complete"):
        if audit.get(key) is not True:
            raise QueueError(f"Completion audit requires {key}=true.", 400)
    items = list(run.items.all())
    expected = {str(item.lot_id) for item in items}
    partitions = {}
    for key in ("lot_ids", "completed", "pending"):
        values = audit.get(key)
        if not isinstance(values, list) or any(type(value) not in (int, str) for value in values) or len(values) != len({str(value) for value in values}):
            raise QueueError(f"Completion audit {key} must contain distinct lot IDs.", 400)
        partitions[key] = {str(value) for value in values}
    done = {str(item.lot_id) for item in items if item.status == "done"}
    attention = {str(item.lot_id) for item in items if item.status == "needs_attention"}
    if partitions["lot_ids"] != expected or partitions["completed"] != done or partitions["pending"] != attention or done | attention != expected:
        raise QueueError("Completion audit must account for every frozen lot in its actual terminal state.")
    receipts, server_receipts = audit.get("lot_receipts", {}), audit.get("server_receipts", {})
    if not isinstance(receipts, dict) or not isinstance(server_receipts, dict):
        raise QueueError("Completion receipt maps must be objects.", 400)
    for item in items:
        lot_id = str(item.lot_id)
        if isinstance(receipts.get(lot_id), str) and receipts[lot_id].strip():
            continue
        proof = item.outcome.get("source_proof", {})
        untouched_exemption = item.claimed_at is None and (proof.get("staff_queue_removal") is True or item.outcome.get("shared_block") is True or item.outcome.get("explicit_stop") is True)
        reference = server_receipts.get(lot_id)
        if not untouched_exemption or not isinstance(reference, dict) or reference.get("run_id") != str(run.pk) or type(reference.get("item_id")) is not int or reference["item_id"] != item.pk:
            raise QueueError(f"Completion audit requires a local receipt for lot {lot_id}; only an untouched staff removal or shared stop may use its matching server receipt.")
    return audit


def worker_action(payload):
    action = payload.get("action")
    if not isinstance(action, str):
        raise QueueError("A worker action is required.", 400)
    with _locked():
        if action in {"start", "snapshot"}:
            request_id, owner = _uuid(payload.get("request_id"), "request_id"), _uuid(payload.get("owner_token"), "owner_token")
            run = ResearchQueueRun.objects.filter(request_id=request_id).first()
            if run:
                if run.owner_token != owner:
                    raise QueueError("Start request belongs to another owner.")
                return {"run": run_json(run)}
            if ResearchQueueRun.objects.filter(status="running").exists():
                raise QueueError("An unfinished research pass already exists; recover it explicitly.")
            if ResearchQueueOperation.objects.filter(settled_at__isnull=True).exists():
                raise QueueError("Reconcile every unresolved operation before starting another research pass.")
            selected = list(ResearchQueueItem.objects.filter(selected=True, status="queued").select_related("lot"))
            run = ResearchQueueRun.objects.create(request_id=request_id, owner_token=owner, thread_id=str(payload.get("thread_id", ""))[:100], status="running" if selected else "completed", completed_at=None if selected else timezone.now())
            ResearchQueueRunItem.objects.bulk_create([ResearchQueueRunItem(run=run, queue_item=row, lot=row.lot, queue_generation=row.generation, position=index, lot_snapshot=_lot_snapshot(row.lot), note_snapshot=row.note) for index, row in enumerate(selected, 1)])
            return {"run": run_json(run)}
        run = get_run(payload.get("run_id"))
        owner = _uuid(payload.get("owner_token", payload.get("expected_owner_token")), "owner_token")
        if run.owner_token != owner:
            last = run.recovery_log[-1] if run.recovery_log else {}
            if action == "handoff" and last.get("event") == "handoff" and str(owner) == last.get("from") and str(payload.get("expected_owner_token")) == last.get("from") and str(payload.get("new_owner_token")) == str(run.owner_token) == last.get("to") and payload.get("reason") == last.get("reason") and payload.get("recovery_checks") == last.get("checks") and str(payload.get("thread_id", run.thread_id))[:100] == run.thread_id:
                return {"run": run_json(run)}
            raise QueueError("Run is owned by another worker; elapsed time never transfers ownership.")
        if action == "handoff":
            expected = _uuid(payload.get("expected_owner_token"), "expected_owner_token")
            checks = payload.get("recovery_checks", {})
            if expected != run.owner_token or not payload.get("reason") or not isinstance(checks, dict) or any(checks.get(key) is not True for key in ("prior_owner_terminal", "no_active_descendants", "business_operations_clear")):
                raise QueueError("Explicit terminal-owner, descendant, and operation recovery checks are required.")
            if run.status == "completed" or ResearchQueueOperation.objects.filter(item__run=run, settled_at__isnull=True).exists():
                raise QueueError("A completed run or unresolved operation cannot be handed off.")
            new_owner = _uuid(payload.get("new_owner_token"), "new_owner_token")
            run.recovery_log = [*run.recovery_log, {"event": "handoff", "from": str(owner), "to": str(new_owner), "reason": str(payload["reason"]), "checks": checks, "at": timezone.now().isoformat()}]
            run.owner_token, run.thread_id = new_owner, str(payload.get("thread_id", run.thread_id))[:100]
            run.save(update_fields=["owner_token", "thread_id", "recovery_log"])
            return {"run": run_json(run)}
        if action == "stop":
            receipt = {"reason": payload.get("reason"), "reopening_condition": payload.get("reopening_condition"), "source_proof": payload.get("source_proof")}
            if any(not isinstance(receipt[key], str) or not receipt[key].strip() for key in ("reason", "reopening_condition")) or not isinstance(receipt["source_proof"], dict) or not receipt["source_proof"]:
                raise QueueError("Stop requires a reason, reopening_condition, and source_proof receipt.", 400)
            previous = next((row for row in reversed(run.recovery_log) if row.get("event") == "stop"), None)
            if previous:
                if previous.get("receipt") != receipt:
                    raise QueueError("A recorded stop receipt cannot be rewritten.")
                return {"run": run_json(run)}
            if run.status == "completed":
                raise QueueError("A completed run cannot be stopped.")
            run.status, run.block_reason = "blocked", receipt["reason"]
            run.recovery_log = [*run.recovery_log, {"event": "stop", "receipt": receipt, "at": timezone.now().isoformat()}]
            run.save(update_fields=["status", "block_reason", "recovery_log"])
            for remaining in run.items.filter(status__in=["queued", "researching"]):
                remaining.status, remaining.reason, remaining.completed_at = "needs_attention", receipt["reason"], timezone.now()
                remaining.outcome = {**receipt, "explicit_stop": True}
                remaining.save(update_fields=["status", "reason", "completed_at", "outcome"])
                _update_current(remaining, status="needs_attention", disposition="", latest_result=remaining.outcome)
            return {"run": run_json(run)}
        if action == "finish":
            if run.status == "completed":
                if run.completion_audit and payload.get("audit", run.completion_audit) != run.completion_audit:
                    raise QueueError("A completed run audit cannot be rewritten.")
                return {"run": run_json(run)}
            if run.items.filter(status__in=["queued", "researching"]).exists() or ResearchQueueOperation.objects.filter(item__run=run, settled_at__isnull=True).exists():
                raise QueueError("Finish requires all frozen items terminal and every operation reconciled.")
            run.completion_audit = _validate_completion_audit(run, payload.get("audit"))
            run.status, run.completed_at = "completed", timezone.now()
            run.save(update_fields=["status", "completed_at", "completion_audit"])
            return {"run": run_json(run)}
        if action == "claim":
            if run.status != "running":
                raise QueueError("Only a running pass can claim work.")
            item = run.items.filter(status="researching").first()
            if not item:
                if ResearchQueueOperation.objects.filter(settled_at__isnull=True).exists():
                    raise QueueError("Reconcile unresolved operations before claiming another lot.")
                item = run.items.filter(status="queued").first()
            if item and item.status == "queued":
                item.status, item.claimed_at = "researching", timezone.now()
                item.save(update_fields=["status", "claimed_at"])
                _update_current(item, status="researching")
            data = run_json(run)
            return {"run": data, "item_id": item.pk if item else None, "item": next((row for row in data["items"] if item and row["id"] == item.pk), None)}
        try:
            item = run.items.get(pk=payload.get("item_id"))
        except (ResearchQueueRunItem.DoesNotExist, ValueError, TypeError):
            raise QueueError("Frozen run item not found.", 404)
        if action == "settle":
            operation_id = _uuid(payload.get("operation_id"), "operation_id")
            operation = ResearchQueueOperation.objects.filter(pk=operation_id, item=item).first()
            if not operation:
                raise QueueError("Operation intent not found.", 404)
            receipt = payload.get("result")
            if not isinstance(receipt, dict) or not receipt:
                raise QueueError("A nonempty result receipt is required.", 400)
            if "units_spent" not in payload:
                raise QueueError("Explicit known units_spent or null with result.usage_unknown=true is required.", 400)
            if payload["units_spent"] is None:
                if receipt.get("usage_unknown") is not True:
                    raise QueueError("Unknown usage must remain explicit in result.usage_unknown.", 400)
                units = None
            else:
                try:
                    units = Decimal(str(payload["units_spent"]))
                    if not units.is_finite() or units < 0 or units > Decimal("9999999999.99") or units.as_tuple().exponent < -2:
                        raise InvalidOperation
                except (InvalidOperation, ValueError):
                    raise QueueError("units_spent must be a nonnegative finite decimal with at most two places.", 400)
            if operation.settled_at:
                if operation.receipt != receipt or operation.units_spent != units:
                    raise QueueError("Settled receipt cannot be rewritten.")
            else:
                operation.receipt, operation.units_spent, operation.settled_at = receipt, units, timezone.now()
                operation.save(update_fields=["receipt", "units_spent", "settled_at"])
            return {"run": run_json(run), "operation": operation_json(operation)}
        if action == "outcome" and item.status == "done":
            replay = {key: payload[key] for key in ("disposition", "reason", "checks", "proof", "source_proof") if key in payload}
            if replay != item.outcome:
                raise QueueError("A settled outcome cannot be rewritten.")
            return {"run": run_json(run)}
        if action == "block" and item.status == "needs_attention":
            replay = {"reason": str(payload.get("reason", "")), "reopening_condition": str(payload.get("reopening_condition", "")), "source_proof": payload.get("source_proof", {})}
            if payload.get("shared_block") is True:
                replay["shared_block"] = True
            if replay != item.outcome:
                raise QueueError("A blocked result cannot be rewritten.")
            return {"run": run_json(run)}
        if item.status != "researching" or run.status != "running":
            raise QueueError("This item is not currently claimed in a running pass.")
        if action == "intent":
            operation_id = _uuid(payload.get("operation_id"), "operation_id")
            kind, details = payload.get("kind"), payload.get("details", {})
            if not isinstance(kind, str) or kind not in {"search", "save_evidence", "save_board", "other"} or not isinstance(details, dict):
                raise QueueError("Supported operation kind and details object are required.", 400)
            operation = ResearchQueueOperation.objects.filter(pk=operation_id).first()
            if operation:
                if operation.item_id != item.pk or operation.kind != kind or operation.details != details:
                    raise QueueError("Operation ID already records a different intent.")
            else:
                if ResearchQueueOperation.objects.filter(settled_at__isnull=True).exists():
                    raise QueueError("Reconcile the previous operation before beginning a new operation.")
                operation = ResearchQueueOperation.objects.create(id=operation_id, item=item, kind=kind, details=details)
            return {"run": run_json(run), "operation": operation_json(operation)}
        if action == "block":
            if any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in ("reason", "reopening_condition")) or not isinstance(payload.get("source_proof", {}), dict):
                raise QueueError("A blocked item requires a reason and explicit reopening_condition.", 400)
            item.status, item.reason, item.completed_at = "needs_attention", str(payload["reason"]), timezone.now()
            item.outcome = {"reason": item.reason, "reopening_condition": str(payload["reopening_condition"]), "source_proof": payload.get("source_proof", {})}
            if payload.get("shared_block") is True:
                item.outcome["shared_block"] = True
            item.save(update_fields=["status", "reason", "completed_at", "outcome"])
            _update_current(item, status="needs_attention", disposition="", latest_result=item.outcome)
            if payload.get("shared_block") is True:
                if not isinstance(payload.get("source_proof"), dict) or not payload["source_proof"]:
                    raise QueueError("A shared block requires evidence in source_proof.", 400)
                run.status, run.block_reason = "blocked", item.reason
                run.save(update_fields=["status", "block_reason"])
                for remaining in run.items.filter(status="queued"):
                    remaining.status, remaining.reason, remaining.completed_at = "needs_attention", item.reason, timezone.now()
                    remaining.outcome = {**item.outcome, "shared_block": True}
                    remaining.save(update_fields=["status", "reason", "completed_at", "outcome"])
                    _update_current(remaining, status="needs_attention", disposition="", latest_result=remaining.outcome)
            return {"run": run_json(run)}
        if action == "outcome":
            if item.operations.filter(settled_at__isnull=True).exists():
                raise QueueError("Unknown operations must be reconciled before an outcome can be saved.")
            revisions = _validate_outcome(item, payload)
            item.status, item.disposition = "done", payload["disposition"]
            item.reason, item.completed_at, item.saved_revisions = payload["reason"], timezone.now(), revisions
            item.outcome = {key: payload[key] for key in ("disposition", "reason", "checks", "proof", "source_proof") if key in payload}
            item.save(update_fields=["status", "disposition", "reason", "completed_at", "saved_revisions", "outcome"])
            _update_current(item, status="done", disposition=item.disposition, latest_result=item.outcome)
            return {"run": run_json(run)}
        raise QueueError("Unknown worker action.", 400)
