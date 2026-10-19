"""Only an explicit, CSRF-protected staff action dispatches reviewed mail."""
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import CoordinateDraft
from . import coordinate_mail as mail


@never_cache
@staff_member_required
@require_GET
def readiness(request):
    return JsonResponse(mail.mail_readiness())


@never_cache
@staff_member_required
@require_http_methods(["GET", "POST"])
def check_connection(request):
    result = mail.check_mail_connection() if request.method == "POST" else None
    if result is not None and request.headers.get("Accept") == "application/json":
        return JsonResponse(result)
    return render(request, "coordinate/mail_connection.html", {"result": result})


@transaction.non_atomic_requests
@never_cache
@staff_member_required
@require_POST
def send_draft(request, case_id, draft_id):
    from .coordinate_views import _state
    draft = get_object_or_404(CoordinateDraft.objects.select_related("case"), pk=draft_id, case_id=case_id)
    try:
        delivery, dispatch = mail.prepare_delivery(draft.pk, request.user,
            request.POST.get("content_digest"), request.POST.get("request_id"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    if dispatch:
        try:
            response = mail.send_snapshot(delivery)
            if not isinstance(response, dict):
                raise ValueError
            mail.record_provider_receipt(delivery.pk, response.get("id"), response.get("threadId"))
            delivery = mail.record_delivery_success(delivery.pk, response.get("id"), response.get("threadId"))
        except Exception as error:
            # Once dispatch was attempted, even a timeout may mean Gmail sent it.
            # Preserve the immutable record; neither this endpoint nor retries resend.
            mail.mark_delivery_unknown(delivery.pk, error)
            delivery.refresh_from_db()
    if request.headers.get("Accept") == "application/json":
        draft.case.refresh_from_db()
        return JsonResponse({**_state(draft.case), "delivery": {"id": str(delivery.pk), "status": delivery.status}})
    return redirect("coordinate_case", case_id=case_id)
