"""Validate briefing provenance and expose reviewable suggestions without applying them."""

from copy import deepcopy

from django.apps import apps

from scripts.coordinate_brief_contract import BRIEF_SCHEMA, validate_brief  # noqa: F401

from .coordinate_brief_models import CoordinateBrief


def _refs(brief):
    return {ref for item in [*brief["lots"], brief["plan"]] for ref in item["source_refs"]}


def _evidence(job, current_research=()):
    from .coordinate_shipping import visible_artifacts

    case = job.message.case
    evidence = {}
    # The first successful, visible source supplies each exact original URL.
    # A later failed fetch does not erase an earlier supported observation.
    saved = visible_artifacts(case.research.filter(job__message_id__lte=job.message_id, error="")).order_by("-fetched_at", "-id")
    for item in saved:
        if item.text.strip() and item.source_url not in evidence:
            evidence[item.source_url] = {
                "label": item.title or item.source_url,
                "url": item.final_url if item.source_kind == "browser" else item.source_url,
                "kind": item.source_kind, "text": item.text,
            }
    for item in current_research:
        if not item.get("error") and item.get("text", "").strip():
            evidence[item["source_url"]] = {
                "label": item.get("title") or item["source_url"],
                "url": item.get("final_url") if item.get("source_kind") == "browser" else item["source_url"],
                "kind": item.get("source_kind", "public"), "text": item["text"],
            }
    messages = case.messages.filter(role="staff", deleted_at__isnull=True, pk__lte=job.message_id)
    for item in messages:
        evidence[f"message:{item.pk}"] = {
            "label": "Staff message", "url": f"#coordinate-message-{item.pk}",
            "kind": "message", "text": item.body,
        }
    try:
        document_model = apps.get_model("secondstateapp", "CoordinateDocument")
    except LookupError:
        document_model = None
    if document_model is not None:
        documents = document_model.objects.filter(
            case=case, message__case=case, message_id__lte=job.message_id, message__deleted_at__isnull=True,
            extraction_status__in=["ready", "truncated"],
        ).only("id", "title", "text")
        for item in documents:
            if item.text.strip():
                evidence[f"document:{item.pk}"] = {
                    "label": item.title, "url": f"#coordinate-document-{item.pk}",
                    "kind": "document", "text": item.text,
                }
    return evidence


def _supported(brief, evidence):
    refs = _refs(brief)
    if not refs <= evidence.keys():
        raise ValueError("Briefing cites unavailable or unrelated case evidence.")
    plan = brief["plan"]
    if plan["pickup_deadline"]:
        basis = " ".join(plan["deadline_basis"].split())
        if not any(basis in " ".join(evidence[ref]["text"].split()) for ref in plan["source_refs"]):
            raise ValueError("The suggested pickup deadline wording is absent from its cited evidence.")


def save_brief(job, brief, current_research=()):
    """Save only an immutable suggestion; the caller owns the completion transaction."""
    brief = validate_brief(brief)
    if brief is None:
        return None
    if job.message.deleted_at or job.message.case.deleted_at:
        raise ValueError("Deleted case inputs cannot receive a briefing.")
    _supported(brief, _evidence(job, current_research))
    saved, created = CoordinateBrief.objects.get_or_create(
        job=job, defaults={"case": job.message.case, "payload": brief},
    )
    if not created and (saved.case_id != job.message.case_id or saved.payload != brief):
        raise ValueError("This job already has a different briefing.")
    return saved


def brief_state(case, max_message_id=None):
    from .coordinate_shipping import visible_artifacts

    if not case or case.deleted_at:
        return None
    candidates = visible_artifacts(case.briefs.select_related("job__message__case"))
    if max_message_id is not None:
        candidates = candidates.filter(job__message_id__lte=max_message_id)
    for item in candidates[:40]:
        try:
            brief = validate_brief(item.payload)
            evidence = _evidence(item.job)
            _supported(brief, evidence)
        except ValueError:
            # Removing an input hides every briefing derived from that evidence.
            continue
        result = deepcopy(brief)
        result.update(id=item.pk, job_id=str(item.job_id), created_at=item.created_at.isoformat())
        result["sources"] = {
            ref: {key: evidence[ref][key] for key in ("label", "url", "kind")}
            for ref in sorted(_refs(brief))
        }
        return result
    return None
