"""Local, bounded handoff to supported Codex Computer Use; no browser driver.

The outer scheduled chat reads the manifest and supplies visible listing evidence.
Private claim state never includes the website token or browser credentials.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from uuid import UUID, uuid4

if __package__:
    from . import coordinate_sources as sources
    from . import coordinate_evidence as provenance
else:
    import coordinate_sources as sources
    import coordinate_evidence as provenance


BROWSER_SECONDS = 420
BROWSER_HANDOFF_SECONDS = 20
# Completion has four 20-second attempts plus 1/2/4-second backoff. Reserve a
# little more than that after the generator's bounded five-minute timeout.
TRANSPORT_MARGIN_SECONDS = 100
MAX_STATE_BYTES = 3_000_000
MAX_EVIDENCE_BYTES = 750_000
MAX_SHIPPING_HOUSES = 4
HOUSE_MEMORY_DAYS = 30
HOUSE_MEMORY_LIMIT = 40
DEFAULT_STATE_DIR = Path(__file__).resolve().parents[1] / "private_data" / "coordinate-browser-runs"
UNAVAILABLE_REASONS = {
    "unavailable": "The supported browser tool could not be opened; website availability was not established.",
    "login_required": "The browser requires the user's sign-in.",
    "challenge": "The browser requires a human verification step.",
    "timeout": "The browser research time budget expired.",
    "unsupported_browser": "The supported browser tools were unavailable; website availability was not established.",
}
SHELL_MARKERS = (
    "verify you are human", "checking your browser", "enable javascript",
    "javascript is disabled", "access denied", "sign in to continue",
    "log in to continue", "just a moment", "captcha", "are you a robot",
)


def _now():
    return datetime.now(timezone.utc)


def _timestamp(value, worker):
    try:
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise worker.WorkerError("Browser research has an invalid timestamp.") from None


def _read_json(path, limit, worker):
    try:
        with Path(path).open("rb") as stream:
            content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValueError
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError, UnicodeError):
        raise worker.WorkerError("Browser research file is missing, oversized, or invalid.") from None


def _write_json(path, value, worker):
    temporary = None
    try:
        path = Path(path)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".coordinate-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        raise worker.WorkerError("Could not save private browser research state.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _file_lock(path, worker):
    """An OS lock survives neither crashes nor closed processes; files may remain."""
    stream = None
    locked = False
    try:
        stream = Path(path).open("a+b")
        if stream.seek(0, 2) == 0:
            stream.write(b" ")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    except OSError:
        raise worker.WorkerError("Another browser research process is using this session.") from None
    finally:
        if stream is not None:
            if locked:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()


def _browser_stage(directory, session_id, worker, *, expires_at=None, release=False):
    marker = directory / ".browser-stage.json"
    with _file_lock(directory / ".browser-stage.lock", worker):
        active = _read_json(marker, 1000, worker) if marker.exists() else None
        if release:
            if active and active.get("session_id") == session_id:
                marker.unlink(missing_ok=True)
            return True
        if (active and active.get("session_id") != session_id
                and _timestamp(active.get("expires_at"), worker) > _now()):
            return False
        _write_json(marker, {"session_id": session_id, "expires_at": expires_at.isoformat()}, worker)
        return True


def _safe_url(value, *, allow_http=False):
    try:
        provenance.public_evidence_url(value, allow_http=allow_http)
        host, _ = sources._destination(value, allow_http=allow_http)
        if "." not in host or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not sources._public_ip(host):
            return None
        # Match the server's observed hostname contract exactly. Do not silently
        # canonicalize Unicode or trailing-dot hosts into a different source.
        return urlsplit(value).hostname.lower().removeprefix("www.")
    except (sources.SourceError, TypeError, ValueError):
        return None


def browser_requests(records, *, include_shipping=True):
    """Public discovery requests include incomplete successful listings too."""
    result = []
    for record in records[:sources.MAX_URLS]:
        if not _safe_url(record.get("source_url"), allow_http=True):
            continue
        error = record.get("error", "")
        if "non-public or reserved" in error:
            continue
        content = (record.get("title", "") + "\n" + record.get("text", "")).casefold()
        if not error and any(marker in content[:2500] for marker in SHELL_MARKERS):
            error = "The public page contains a sign-in, verification, or JavaScript shell."
        if not error and len(record.get("text", "").strip()) < 200:
            error = "The public page did not provide a usable listing excerpt."
        missing = sources.missing_fields(record)
        expected_identity = sources.public_identity(record)
        if (not error and "sold_price" not in missing
                and record.get("identity_match", {}).get("status") != "exact"):
            missing.append("verified_sale_identity")
        shipping = sources.shipping_discovery(record) if include_shipping else None
        if error or missing or shipping:
            result.append({"source_url": record["source_url"], "public_error": error[:200],
                           "missing_fields": missing, "expected_identity": expected_identity,
                           "queries": sources.discovery_queries(record),
                           "max_additional_sources": provenance.MAX_PER_SOURCE - int(
                               not record.get("error") and bool(record.get("text", "").strip())
                               and not any(marker in content[:2500] for marker in SHELL_MARKERS)),
                           **({"shipping_research": True} if shipping else {})})
    return result


def shipping_requests(records):
    """One public house pass can serve several lots without repeated searches."""
    result = {}
    for record in records[:sources.MAX_URLS]:
        if not _safe_url(record.get("source_url"), allow_http=True) or "non-public or reserved" in record.get("error", ""):
            continue
        request = sources.shipping_discovery(record)
        if request is None:
            continue
        host = request["house_host"]
        key = host if request["house_memory_enabled"] else (host, request["public_house_name"] or record["source_url"])
        if key in result:
            result[key]["related_source_urls"].append(record["source_url"])
            if not result[key]["public_pickup_city"] and request["public_pickup_city"]:
                result[key]["public_pickup_city"] = request["public_pickup_city"]
                result[key]["provider_queries"] = request["provider_queries"]
        elif len(result) < MAX_SHIPPING_HOUSES:
            result[key] = {**request, "related_source_urls": [record["source_url"]]}
    return list(result.values())


def _memory_entries(directory, worker):
    path = directory / ".house-research-memory.json"
    if not path.exists():
        return {}
    try:
        value = _read_json(path, 150_000, worker)
        entries = value.get("houses", {})
        if value.get("version") != 1 or not isinstance(entries, dict) or len(entries) > HOUSE_MEMORY_LIMIT:
            return {}
        cleaned = {}
        for host, entry in entries.items():
            if not isinstance(host, str) or _safe_url("https://" + host + "/") != host or not isinstance(entry, dict):
                continue
            checked = _timestamp(entry.get("checked_at"), worker)
            if not _now() - timedelta(days=HOUSE_MEMORY_DAYS) <= checked <= _now() + timedelta(seconds=5):
                continue
            urls = entry.get("reopen_urls", [])
            checks = entry.get("checks", {})
            if (not isinstance(urls, list) or len(urls) > 8 or not isinstance(checks, dict)
                    or set(checks) - set(sources.SHIPPING_CHECK_TOPICS)
                    or any(status not in ("found", "not_found", "unavailable", "not_checked") for status in checks.values())):
                continue
            safe_urls = [url for url in urls if _cacheable_policy_url(url)]
            cleaned[host] = {"checked_at": checked.isoformat(), "reopen_urls": safe_urls, "checks": checks}
        return cleaned
    except worker.WorkerError:
        return {}  # Corrupt/stale optional memory cannot block current research.


def _cacheable_policy_url(url):
    if not isinstance(url, str) or not _safe_url(url) or sources.public_lot_url(url):
        return False
    parts = urlsplit(url)
    return (not parts.query and not parts.fragment
            and not any(marker in parts.path.casefold() for marker in ("invoice", "account", "login", "checkout", "private")))


def _shipping_manifest(requests, directory, worker):
    memory = _memory_entries(directory, worker)
    return [{**request, "previous_public_checks": memory.get(request["house_host"], {}) if request["house_memory_enabled"] else {},
             "reuse_policy": "Previous URLs/checks are discovery leads only. Reopen sources; cached findings never satisfy current evidence or prices."}
            for request in requests]


def _identity(payload, worker_id):
    return {**{key: payload["job"][key] for key in ("claim_token", "case_id", "message_id")},
            "worker_id": worker_id}


def _fail(api, payload, worker_id, worker):
    try:
        api.post("/coordinate/api/jobs/" + payload["job"]["id"] + "/fail/",
                 {**_identity(payload, worker_id), "error": "Browser research could not complete; retry required."})
    except worker.WorkerError:
        pass


def _post_completion(api, payload, completion, worker):
    job = payload["job"]
    completed = api.post("/coordinate/api/jobs/" + job["id"] + "/complete/", completion, retry=True)
    if not isinstance(completed.get("reply_id"), int) or isinstance(completed["reply_id"], bool):
        raise worker.WorkerError("Coordinate API did not confirm a saved reply.")
    return {"status": "completed", "test_mode": payload["test_mode"], "draft_only": True,
            "job_id": job["id"], "case_id": job["case_id"], "message_id": job["message_id"],
            "reply_id": completed["reply_id"], "already_completed": completed.get("already_completed", False),
            "reply_sha256": hashlib.sha256(completion["body"].encode("utf-8")).hexdigest(),
            "research_count": len(completion["research"]), "draft_count": len(completion["drafts"])}


def _resume_generated(directory, api, executable, worker_id, worker):
    """A later scheduled prepare replays durable ambiguous completions first."""
    for path in sorted(directory.glob("*.json")):
        try:
            if str(UUID(path.stem)) != path.stem:
                continue
        except ValueError:
            continue
        try:
            state = _read_json(path, MAX_STATE_BYTES, worker)
        except worker.WorkerError:
            # An interrupted/corrupt local write cannot supply evidence. Its
            # server lease remains the recovery mechanism.
            continue
        if (state.get("status") != "generated" or state.get("base_url") != api.base_url
                or state.get("worker_id") != worker_id):
            continue
        try:
            return complete(api, executable, path, worker=worker)
        except worker.APIError as exc:
            if exc.status == 409:
                # The server may have invalidated the old claim after staff
                # changed context. complete() marks it failed before returning.
                continue
            raise
    return None


def prepare(api, executable, worker_id, model=None, reasoning_effort=None, *, state_dir=None, worker):
    directory = Path(state_dir or DEFAULT_STATE_DIR).resolve()
    session_id = str(uuid4())
    payload = None
    handed_off = False
    finish_started = False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        resumed = _resume_generated(directory, api, executable, worker_id, worker)
        if resumed is not None:
            return resumed
        if not _browser_stage(directory, session_id, worker,
                              expires_at=_now() + timedelta(seconds=sources.TOTAL_SECONDS + BROWSER_SECONDS)):
            return {"status": "browser_busy", "draft_only": True}
        payload = api.post("/coordinate/api/claim/", {"worker_id": worker_id})
        job = worker.validate_claim(payload)
        if job is None:
            return {"status": "idle", "test_mode": payload["test_mode"], "draft_only": True}
        payload["source_evidence"] = (
            worker.research_messages(payload["messages"])
            if not payload["test_mode"] and payload.get("draft_only") is True
            and payload.get("research_enabled") is True else []
        )
        requests = browser_requests(payload["source_evidence"])
        if not requests:
            _browser_stage(directory, session_id, worker, release=True)
            finish_started = True
            # Even direct-fetch-only work gets a durable completion before POST:
            # a restart after an ambiguous response must replay, not regenerate.
            prepared_at = _now()
            state_path = directory / (session_id + ".json")
            _write_json(state_path, {"version": 3, "session_id": session_id, "job_id": job["id"],
                "base_url": api.base_url, "worker_id": worker_id, "model": model,
                "reasoning_effort": reasoning_effort, "prepared_at": prepared_at.isoformat(),
                "browser_deadline": prepared_at.isoformat(), "requests": [], "shipping_requests": [], "payload": payload,
                "status": "prepared"}, worker)
            return complete(api, executable, state_path, unavailable="unavailable", worker=worker)
        prepared_at = _now()
        lease = _timestamp(job.get("lease_expires_at"), worker)
        deadline = min(prepared_at + timedelta(seconds=BROWSER_SECONDS),
                       lease - timedelta(seconds=worker.GENERATION_TIMEOUT + TRANSPORT_MARGIN_SECONDS + BROWSER_HANDOFF_SECONDS))
        if deadline <= prepared_at:
            raise worker.WorkerError("Not enough claim time remains for browser research; retry required.")
        state_path = directory / (session_id + ".json")
        evidence_path = directory / (session_id + ".evidence.json")
        house_requests = shipping_requests(payload["source_evidence"])
        state = {"version": 3, "session_id": session_id, "job_id": job["id"], "base_url": api.base_url,
                 "worker_id": worker_id, "model": model, "reasoning_effort": reasoning_effort,
                 "prepared_at": prepared_at.isoformat(), "browser_deadline": deadline.isoformat(),
                 "requests": requests, "shipping_requests": house_requests, "payload": payload, "status": "prepared"}
        _write_json(state_path, state, worker)
        _browser_stage(directory, session_id, worker, expires_at=deadline)
        handed_off = True
        return {"status": "browser_research_required", "session_id": session_id, "job_id": job["id"],
                "state_path": str(state_path), "evidence_path": str(evidence_path),
                "browser_deadline": deadline.isoformat(), "requests": requests,
                "shipping_requests": _shipping_manifest(house_requests, directory, worker),
                "research_contract_version": 3,
                "tool_requirements": {"search": ["web__run", "mcp__codex_apps__search_service_web_run"],
                                      "browser": "supported Computer Use; create/reacquire a public tab if needed",
                                      "authentication": "Only if required: jeremy@secondstate.art Chrome Profile 9; never Profile 15"},
                "budget": {"research_seconds": max(0, int((deadline-prepared_at).total_seconds())),
                           "max_queries": 24, "max_sources": 24, "max_sources_per_lot": 6,
                           "max_attempts": 64, "reserved_shipping_attempts": len(house_requests), "max_excerpt_chars": 6000},
                "stop_when": "Lot facts and practical house/provider shipping checks supported or bounded alternatives exhausted; preserve partial findings and unknown checks.",
                "privacy": "Search only public lot facts and the provided queries. Never search private invoice/email/message contents."}
    except OSError:
        if payload and payload.get("job") and not finish_started:
            _fail(api, payload, worker_id, worker)
        raise worker.WorkerError("Could not prepare private browser research state.") from None
    except worker.WorkerError:
        if payload and payload.get("job") and not finish_started:
            _fail(api, payload, worker_id, worker)
        raise
    finally:
        if not handed_off and directory.exists():
            _browser_stage(directory, session_id, worker, release=True)


def _load_state(path, api, worker):
    state = _read_json(path, MAX_STATE_BYTES, worker)
    try:
        session_id = str(UUID(state["session_id"]))
        job = worker.validate_claim(state["payload"])
        if (state.get("version") not in (1, 2, 3) or path.name != session_id + ".json" or job is None
                or job["id"] != state.get("job_id") or state.get("base_url") != api.base_url
                or state.get("worker_id") != "manual-codex"
                or state.get("status") not in ("prepared", "generated", "completed", "failed")
                or state.get("reasoning_effort") not in (None, *worker.REASONING_EFFORTS)
                or (state.get("model") is not None and not isinstance(state["model"], str))):
            raise ValueError
        requests = state["requests"]
        expected_requests = browser_requests(state["payload"]["source_evidence"], include_shipping=state["version"] >= 3)
        if state.get("version") == 1:
            expected_requests = [{key: item[key] for key in ("source_url", "public_error")}
                                 for item in expected_requests if item["public_error"]]
        if (not isinstance(requests, list) or not 0 <= len(requests) <= sources.MAX_URLS
                or requests != expected_requests):
            raise ValueError
        if state["version"] >= 3 and state.get("shipping_requests") != shipping_requests(state["payload"]["source_evidence"]):
            raise ValueError
        _timestamp(state["prepared_at"], worker)
        _timestamp(state["browser_deadline"], worker)
        if state["status"] in ("generated", "completed"):
            completion = state.get("completion")
            if (not isinstance(completion, dict)
                    or any(completion.get(key) != value for key, value in _identity(state["payload"], state["worker_id"]).items())
                    or not isinstance(completion.get("body"), str)
                    or not 1 <= len(completion["body"]) <= worker.MAX_REPLY_LENGTH
                    or not isinstance(completion.get("drafts"), list)
                    or not isinstance(completion.get("research"), list)):
                raise ValueError
        if state["status"] == "completed" and (not isinstance(state.get("result"), dict)
                                                or state["result"].get("job_id") != job["id"]):
            raise ValueError
        return state
    except (KeyError, TypeError, ValueError, AttributeError):
        raise worker.WorkerError("Browser research state does not match its prepared job.") from None


def merge_evidence(state, evidence, worker, *, unavailable=None):
    if unavailable is not None and unavailable not in UNAVAILABLE_REASONS:
        raise worker.WorkerError("Choose a supported browser-unavailable reason.")
    if evidence is not None and (evidence.get("session_id") != state["session_id"]
                                 or evidence.get("job_id") != state["job_id"]):
        raise worker.WorkerError("Browser evidence belongs to another session or job.")
    records = evidence.get("records", []) if evidence is not None else []
    try:
        provenance.validate_research_bounds(records)
    except (ValueError, TypeError, KeyError):
        raise worker.WorkerError("Browser evidence has an invalid record collection.") from None
    wanted = {item["source_url"]: item for item in state["requests"]}
    verified = {}
    prepared = _timestamp(state["prepared_at"], worker)
    deadline = _timestamp(state["browser_deadline"], worker)
    for item in records:
        if (not isinstance(item, dict) or not isinstance(item.get("source_url"), str)
                or item["source_url"] not in wanted):
            raise worker.WorkerError("Browser evidence contains an unrequested URL.")
        for key, limit in (("title", 300), ("text", 6000), ("error", 200), ("final_url", 2048)):
            if not isinstance(item.get(key, ""), str) or len(item.get(key, "")) > limit:
                raise worker.WorkerError("Browser evidence contains an invalid or oversized excerpt.")
        fetched = _timestamp(item.get("fetched_at"), worker)
        if not prepared <= fetched <= min(deadline, _now() + timedelta(seconds=5)):
            raise worker.WorkerError("Browser evidence is stale or outside this session's time budget.")
        error = item.get("error", "").strip()
        final_url = item.get("final_url", "")
        text = item.get("text", "").strip()
        title = item.get("title", "").strip()
        host = _safe_url(final_url)
        kind = item.get("source_kind", "browser")
        extra = {}
        if kind in provenance.NEW_SOURCE_KINDS:
            try:
                extra = provenance.validate_evidence_provenance(
                    item, expected_identity=wanted[item["source_url"]].get("expected_identity"))
                for attempt in extra["attempts"]:
                    stamp = _timestamp(attempt["observed_at"], worker)
                    if not prepared <= stamp <= min(deadline, _now() + timedelta(seconds=5)):
                        raise ValueError
            except (ValueError, TypeError):
                raise worker.WorkerError("Research evidence has invalid discovery, identity or attempt provenance.") from None
        elif kind != "browser" or final_url and host not in {_safe_url(item["source_url"], allow_http=True), "invaluable.com"}:
            raise worker.WorkerError("Browser evidence has an unrelated or unsafe final URL.")
        if error:
            if text or title:
                raise worker.WorkerError("Unavailable browser records must not contain listing facts.")
        elif not text or not final_url or not host:
            raise worker.WorkerError("Successful browser evidence needs visible text and an HTTPS final URL.")
        verified.setdefault(item["source_url"], []).append({"source_url": item["source_url"], "final_url": final_url,
            "title": title, "text": text, "fetched_at": fetched.isoformat(), "error": error,
            "source_kind": kind, "public_error": wanted[item["source_url"]]["public_error"], **extra})
    result = []
    for original in state["payload"]["source_evidence"]:
        source_url = original["source_url"]
        if source_url in verified:
            recovered = verified[source_url]
        elif source_url in wanted:
            reason = UNAVAILABLE_REASONS.get(unavailable, "The research tools did not return evidence for this source.")
            tool_failure = unavailable in ("unavailable", "unsupported_browser")
            attempt_method = "browser_launch" if tool_failure else "public_browser" if unavailable else "validation"
            recovered = [{"source_url": source_url, "final_url": "", "title": "", "text": "",
                         "fetched_at": _now().isoformat(), "source_kind": "public_browser",
                         "public_error": wanted[source_url]["public_error"],
                         "error": reason, "discovery_method": "direct", "discovery_query": "", "discovery_url": "",
                         "match_reason": "", "identity_match": {"status": "unverified"},
                         "attempts": [{"method": attempt_method,
                                       "query": "", "url": source_url, "status": "tool_unavailable" if tool_failure else unavailable or "unavailable",
                                       "detail": reason, "observed_at": _now().isoformat()}]}]
        else:
            result.append(dict(original))
            continue
        content = (original.get("title", "") + "\n" + original.get("text", "")).casefold()
        original_useful = (not original.get("error") and original.get("text", "").strip()
                           and not any(marker in content[:2500] for marker in SHELL_MARKERS))
        if original_useful:
            # A short public excerpt can still be useful. Preserve its facts and
            # separately tell the generator that browser supplementation failed.
            failures = [record["error"] for record in recovered if record["error"]]
            result.append({**original, **({"browser_error": "; ".join(failures)[:400]} if failures else {})})
        # Keep each opened alternate source. A failed second source must never
        # replace a useful direct fetch or another lot's successful evidence.
        result.extend(record for record in recovered if not original_useful or not record["error"]
                      or record.get("source_kind") in provenance.NEW_SOURCE_KINDS)
    result = _bounded_merge(result, deadline)
    try:
        provenance.validate_research_bounds(result)
    except (ValueError, TypeError):
        raise worker.WorkerError("Merged research exceeded the bounded per-lot evidence budget.") from None
    return result


def _bounded_merge(records, deadline):
    """Retain useful findings fairly when enrichment fills the source budget.

    Original excerpts and exact opened matches rank ahead of context, historical
    comparisons, search leads and failures. Select across lots before adding a
    second/third observation, so one prolific lot cannot crowd out another.
    """
    groups = {}
    def rank(record):
        if record.get("error"):
            return 0
        kind = record.get("source_kind", "public")
        if kind in ("public", "browser"):
            return 4
        return {"exact": 4, "context": 3, "historical": 2, "unverified": 1}.get(
            record.get("identity_match", {}).get("status"), 1)
    for record in records:
        groups.setdefault(record["source_url"], []).append(record)
    selected = []
    ranked = {key: sorted(group, key=rank, reverse=True)[:provenance.MAX_PER_SOURCE]
              for key, group in groups.items()}
    for position in range(provenance.MAX_PER_SOURCE):
        for group in ranked.values():
            if position < len(group) and len(selected) < provenance.MAX_RESEARCH:
                selected.append(group[position])
    # Preserve the familiar per-lot reading order after fair selection.
    selected_ids = {id(record) for record in selected}
    result = [record for group in ranked.values() for record in group if id(record) in selected_ids]
    omitted = len(records) - len(result)
    if omitted:
        diagnostic = next((record for record in result
                           if record.get("source_kind") in provenance.NEW_SOURCE_KINDS
                           and len(record.get("attempts", [])) < 16), None)
        if diagnostic is not None and sum(len(record.get("attempts", [])) for record in result) < provenance.MAX_ATTEMPTS:
            diagnostic.setdefault("attempts", []).append({"method": "validation", "query": "", "url": "",
                "status": "partial", "detail": f"Retained {len(result)} observations; omitted {omitted} lower-priority observations under the source budget.",
                "observed_at": min(_now(), deadline).isoformat()})
    return result


def _shipping_checks(state, evidence, records, worker):
    """Validate check claims against fresh opened sources; persist a compact log."""
    requests = {item["source_url"]: item for item in state.get("shipping_requests", [])}
    raw = evidence.get("shipping_checks", []) if evidence else []
    if not isinstance(raw, list) or len(raw) > MAX_SHIPPING_HOUSES * len(sources.SHIPPING_CHECK_TOPICS):
        raise worker.WorkerError("Shipping checks exceed their bounded collection.")
    supplied = {}
    prepared, deadline = _timestamp(state["prepared_at"], worker), _timestamp(state["browser_deadline"], worker)
    for item in raw:
        if not isinstance(item, dict) or set(item) - {"source_url", "topic", "status", "source_refs", "detail", "observed_at"}:
            raise worker.WorkerError("Invalid shipping research check.")
        source, topic, status = item.get("source_url"), item.get("topic"), item.get("status")
        if (not all(isinstance(value, str) for value in (source, topic, status))
                or source not in requests or topic not in sources.SHIPPING_CHECK_TOPICS
                or status not in ("found", "not_found", "unavailable") or (source, topic) in supplied):
            raise worker.WorkerError("Shipping checks must match this session's house and topics.")
        stamp = _timestamp(item.get("observed_at"), worker)
        if not prepared <= stamp <= min(deadline, _now() + timedelta(seconds=5)):
            raise worker.WorkerError("Shipping check is outside this research session.")
        refs, detail = item.get("source_refs", []), item.get("detail", "")
        if (not isinstance(refs, list) or len(refs) > 3 or any(not isinstance(ref, str) for ref in refs)
                or len(set(refs)) != len(refs) or not isinstance(detail, str) or len(detail) > 200):
            raise worker.WorkerError("Shipping check references or explanation are invalid.")
        related = [record for record in records if record["source_url"] in requests[source]["related_source_urls"]]
        opened = {record.get("final_url") for record in related if not record.get("error")
                  and record.get("source_kind", "public") != "search_only" and record.get("text")}
        if any(ref not in opened for ref in refs) or (status == "found" and not refs):
            raise worker.WorkerError("Found shipping facts need their actual opened sources; snippets are insufficient.")
        searched = any(attempt.get("method") in ("search", "public_fetch", "public_browser", "authenticated_browser")
                       for record in related for attempt in record.get("attempts", []))
        if status == "not_found" and not (opened or searched):
            raise worker.WorkerError("A not-found shipping check needs an actual bounded research attempt.")
        supplied[source, topic] = {"source_url": source, "topic": topic, "status": status,
            "source_refs": refs, "detail": detail, "observed_at": stamp.isoformat()}
    notes = []
    for source, request in requests.items():
        checks = [supplied.get((source, topic), {"source_url": source, "topic": topic, "status": "not_checked",
                  "source_refs": [], "detail": "No check result supplied in this bounded pass.",
                  "observed_at": min(_now(), deadline).isoformat()}) for topic in sources.SHIPPING_CHECK_TOPICS]
        notes.extend(checks)
        candidates = [record for record in records if record["source_url"] in request["related_source_urls"]
                      and record.get("source_kind") in provenance.NEW_SOURCE_KINDS and len(record.get("attempts", [])) < 16]
        if candidates:
            diagnostic = next((record for record in candidates if record.get("identity_match", {}).get("status") == "context"), candidates[0])
            diagnostic.setdefault("attempts", []).append({"method": "validation", "query": "", "url": "",
                "status": "success" if all(check["status"] == "found" for check in checks) else "partial",
                "detail": "Shipping checks: " + "; ".join(check["topic"] + "=" + check["status"] for check in checks),
                "observed_at": min(_now(), deadline).isoformat()})
        elif supplied:
            raise worker.WorkerError("Shipping checks need a retained source with room for the bounded check history.")
    try:
        provenance.validate_research_bounds(records)
    except ValueError:
        raise worker.WorkerError("Reserve one attempt per house for the shipping check summary.") from None
    return notes


def _save_house_memory(directory, state, worker):
    """Reusable public leads only, after the server accepts a visible completion."""
    if not state.get("shipping_requests"):
        return
    try:
        with _file_lock(directory / ".house-research-memory.lock", worker):
            memory = _memory_entries(directory, worker)
            records = state.get("observations", [])
            for request in state["shipping_requests"]:
                if not request["house_memory_enabled"]:
                    continue
                public = [record for record in records if record["source_url"] in request["related_source_urls"]
                          and record.get("source_kind") in ("public_fetch", "public_browser") and not record.get("error")]
                urls = list(dict.fromkeys(record["final_url"] for record in public
                       if record.get("identity_match", {}).get("status") == "context" and _cacheable_policy_url(record["final_url"])))[:8]
                public_urls = {record["final_url"] for record in public}
                checks = {item["topic"]: item["status"] for item in state.get("shipping_research_notes", [])
                          if item["source_url"] == request["source_url"]
                          and (item["status"] != "found" or set(item["source_refs"]) <= public_urls)}
                memory[request["house_host"]] = {"checked_at": _now().isoformat(), "reopen_urls": urls, "checks": checks}
            memory = dict(sorted(memory.items(), key=lambda pair: pair[1]["checked_at"], reverse=True)[:HOUSE_MEMORY_LIMIT])
            _write_json(directory / ".house-research-memory.json", {"version": 1, "houses": memory}, worker)
    except worker.WorkerError:
        pass  # Optional discovery memory cannot undo an accepted completion.


def complete(api, executable, state_path, *, evidence_path=None, unavailable=None, worker):
    path = Path(state_path).resolve()
    state = _load_state(path, api, worker)
    with _file_lock(path.with_suffix(".lock"), worker):
        state = _load_state(path, api, worker)
        payload = state["payload"]
        if state["status"] == "completed":
            return state["result"]
        if state["status"] == "failed":
            raise worker.WorkerError("This browser session failed; retrieve pending work with a new prepare run.")
        if state["status"] == "prepared":
            try:
                if (evidence_path is None) == (unavailable is None):
                    raise worker.WorkerError("Provide browser evidence or one browser-unavailable reason.")
                lease = _timestamp(payload["job"].get("lease_expires_at"), worker)
                if lease - _now() < timedelta(seconds=worker.GENERATION_TIMEOUT + TRANSPORT_MARGIN_SECONDS):
                    raise worker.WorkerError("Browser research left too little claim time; retry required.")
                evidence = _read_json(evidence_path, MAX_EVIDENCE_BYTES, worker) if evidence_path else None
                merged = merge_evidence(state, evidence, worker, unavailable=unavailable)
                shipping_notes = _shipping_checks(state, evidence, merged, worker)
                browser_notes = [{"source_url": item["source_url"], "error": item.pop("browser_error")}
                                 for item in merged if "browser_error" in item]
                # A malformed generator response must not erase expensive,
                # validated observations. Keep them in the private session even
                # if no website reply can be accepted on this attempt.
                state["observations"] = merged
                state["research_notes"] = browser_notes
                state["shipping_research_notes"] = shipping_notes
                _write_json(path, state, worker)
                _browser_stage(path.parent, state["session_id"], worker, release=True)
                # Keep the original prepared evidence in state for manifest validation.
                generation_payload = {**payload, "source_evidence": merged, "browser_research_notes": browser_notes,
                    "shipping_requests": state.get("shipping_requests", []), "shipping_research_notes": shipping_notes}
                generated = worker.generate_reply(generation_payload, executable, state["model"], state["reasoning_effort"])
                state["completion"] = worker.completion_payload(_identity(payload, state["worker_id"]), generated, merged)
                state["status"] = "generated"
                _write_json(path, state, worker)
            except worker.WorkerError:
                _fail(api, payload, state["worker_id"], worker)
                state["status"] = "failed"
                _write_json(path, state, worker)
                raise
            finally:
                _browser_stage(path.parent, state["session_id"], worker, release=True)
        # Do not fail or regenerate on an ambiguous completion transport error.
        # The identical persisted payload is replayed on the next invocation.
        try:
            result = _post_completion(api, payload, state["completion"], worker)
        except worker.APIError as exc:
            if exc.status in (400, 404, 409, 413, 422):
                _fail(api, payload, state["worker_id"], worker)
                state["status"] = "failed"
                _write_json(path, state, worker)
            raise
        state.update(status="completed", result=result)
        _write_json(path, state, worker)
        _save_house_memory(path.parent, state, worker)
        return result
