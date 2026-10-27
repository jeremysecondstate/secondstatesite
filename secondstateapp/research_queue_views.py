"""Session/CSRF staff controls and the existing catalog-key worker boundary."""
import json
import os
import secrets

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .research_queue import QueueError, change_item, get_run, item_json, queue_context, run_json, select_lot, selected_queue_state, worker_action


def _payload(request):
    length = request.META.get("CONTENT_LENGTH", "")
    if str(length).isdigit() and int(length) > 1_000_000:
        raise QueueError("Request is too large.", 400)
    if request.content_type != "application/json":
        # CSRF middleware has already read multipart forms. Reading .body again
        # would raise RawPostDataException on the normal staff form path.
        return request.POST.dict()
    if len(request.body) > 1_000_000:
        raise QueueError("Request is too large.", 400)
    try:
        def invalid_constant(value):
            raise ValueError("Nonfinite JSON value")
        value = json.loads(request.body or b"{}", parse_constant=invalid_constant)
    except (ValueError, UnicodeDecodeError):
        raise QueueError("Invalid JSON.", 400)
    if not isinstance(value, dict):
        raise QueueError("JSON must be an object.", 400)
    return value


def _success(item):
    count = len(selected_queue_state())
    return JsonResponse({"ok": True, "item": item_json(item), "selected": item.selected,
                         "selected_count": count, "queue_count": count,
                         "message": "Research Queue selection saved."})


@never_cache
@staff_member_required
@require_GET
def auction_research_queue(request):
    return render(request, "calendar/research_queue.html", queue_context())


@never_cache
@staff_member_required
@require_POST
def research_queue_selection(request, lot_id):
    try:
        payload = _payload(request)
        selected = payload.get("selected")
        if request.content_type != "application/json":
            selected = {"true": True, "false": False}.get(selected, selected)
        return _success(select_lot(lot_id, selected))
    except QueueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=exc.status)


@never_cache
@staff_member_required
@require_POST
def auction_research_queue_item(request, lot_id):
    try:
        item = change_item(lot_id, _payload(request))
        if request.content_type == "application/json":
            return _success(item)
        return redirect("auction_research_queue")
    except QueueError as exc:
        if request.content_type == "application/json":
            return JsonResponse({"ok": False, "error": str(exc)}, status=exc.status)
        context = queue_context()
        context.update(form_errors={lot_id: str(exc)}, queue_error=str(exc))
        for item in context["queue_items"]:
            if item.lot_id == lot_id:
                item.form_error = str(exc)
                item.error_action = request.POST.get("action", "")
                item.retry_reason = request.POST.get("reason", "")
        if request.POST.get("action") == "note":
            for item in context["queue_items"]:
                if item.lot_id == lot_id:
                    item.note = request.POST.get("note", "")
        return render(request, "calendar/research_queue.html", context, status=exc.status)


@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def research_queue_worker(request):
    expected = os.environ.get("CATALOG_API_KEY", "").strip()
    provided = request.headers.get("X-API-KEY", "").strip()
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        return JsonResponse({"ok": False, "error": "Unauthorized"}, status=401)
    try:
        if request.method == "GET":
            if request.GET.get("run_id"):
                result = {"run": run_json(get_run(request.GET["run_id"]))}
            else:
                result = {"selected": selected_queue_state()}
        else:
            result = worker_action(_payload(request))
        return JsonResponse({"ok": True, **result})
    except QueueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=exc.status)
