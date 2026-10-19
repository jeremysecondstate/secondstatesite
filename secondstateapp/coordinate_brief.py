"""Validate briefing provenance and expose reviewable suggestions without applying them."""

from copy import deepcopy

from django.apps import apps

from scripts.coordinate_brief_contract import BRIEF_SCHEMA, validate_brief, validate_price_evidence  # noqa: F401

from .coordinate_brief_models import CoordinateBrief


def _refs(brief):
    return {ref for item in [*brief["lots"], brief["plan"]] for ref in item["source_refs"]}


def _evidence(job, current_research=()):
    from .coordinate_shipping import visible_artifacts

    case = job.message.case
    evidence = {}

    def remember(ref, value):
        if ref not in evidence:
            evidence[ref] = {**value, "observations": []}
        evidence[ref]["observations"].append(value)

    def observation(item):
        get = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
        if get("error") or not get("text", "").strip() or get("source_kind") == "search_only":
            return
        original, opened = get("source_url"), get("final_url") or get("source_url")
        value = {"label": get("title") or opened, "url": opened,
                 "kind": get("source_kind", "public"), "text": get("text"),
                 "identity_match": get("identity_match", {}) or {}}
        # A discovered page is cited by its actual opened URL. The original
        # URL alias remains for old briefs and direct-page observations.
        remember(opened, value)
        if original != opened and get("source_kind") in ("public", "browser"):
            remember(original, value)

    # First observation wins, so current records precede previously saved
    # observations; later failed fetches never erase useful evidence.
    for item in current_research:
        observation(item)
    saved = visible_artifacts(case.research.filter(job__message_id__lte=job.message_id, error="")).order_by("-fetched_at", "-id")
    for item in saved:
        observation(item)
    messages = case.messages.filter(role="staff", deleted_at__isnull=True, pk__lte=job.message_id)
    for item in messages:
        evidence[f"message:{item.pk}"] = {
            "label": "Staff message", "url": f"#coordinate-message-{item.pk}",
            "kind": "message", "text": item.body,
        }
    from .coordinate_mail_sync import mail_context
    for item in mail_context(case, job.message_id):
        evidence[item["source_ref"]] = {
            "label": "Email from " + item["from_address"],
            "url": f"#coordinate-email-{item['id']}",
            "kind": "email", "text": item["text"],
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
    validate_price_evidence(brief, evidence)


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
