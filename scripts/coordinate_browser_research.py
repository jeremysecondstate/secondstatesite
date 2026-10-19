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
else:
    import coordinate_sources as sources


BROWSER_SECONDS = 180
BROWSER_HANDOFF_SECONDS = 20
# Completion has four 20-second attempts plus 1/2/4-second backoff. Reserve a
# little more than that after the generator's full ten-minute timeout.
TRANSPORT_MARGIN_SECONDS = 100
MAX_STATE_BYTES = 3_000_000
MAX_EVIDENCE_BYTES = 240_000
DEFAULT_STATE_DIR = Path(__file__).resolve().parents[1] / "private_data" / "coordinate-browser-runs"
UNAVAILABLE_REASONS = {
    "unavailable": "The signed-in browser was unavailable.",
    "login_required": "The browser requires the user's sign-in.",
    "challenge": "The browser requires a human verification step.",
    "timeout": "The browser research time budget expired.",
    "unsupported_browser": "The supported browser tools could not access the page.",
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
    except (sources.SourceError, TypeError):
        return None


def browser_requests(records):
    """Only submitted public URLs enter the UI handoff, never unsafe fetch errors."""
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
        if error:
            result.append({"source_url": record["source_url"], "public_error": error[:200]})
    return result


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


def _generate_and_complete(api, payload, executable, worker_id, model, reasoning_effort, worker):
    try:
        generated = worker.generate_reply(payload, executable, model, reasoning_effort)
        completion = worker.completion_payload(_identity(payload, worker_id), generated, payload["source_evidence"])
    except worker.WorkerError:
        _fail(api, payload, worker_id, worker)
        raise
    return _post_completion(api, payload, completion, worker)


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
            return _generate_and_complete(api, payload, executable, worker_id, model, reasoning_effort, worker)
        prepared_at = _now()
        lease = _timestamp(job.get("lease_expires_at"), worker)
        deadline = min(prepared_at + timedelta(seconds=BROWSER_SECONDS),
                       lease - timedelta(seconds=worker.GENERATION_TIMEOUT + TRANSPORT_MARGIN_SECONDS + BROWSER_HANDOFF_SECONDS))
        if deadline <= prepared_at:
            raise worker.WorkerError("Not enough claim time remains for browser research; retry required.")
        state_path = directory / (session_id + ".json")
        evidence_path = directory / (session_id + ".evidence.json")
        state = {"version": 1, "session_id": session_id, "job_id": job["id"], "base_url": api.base_url,
                 "worker_id": worker_id, "model": model, "reasoning_effort": reasoning_effort,
                 "prepared_at": prepared_at.isoformat(), "browser_deadline": deadline.isoformat(),
                 "requests": requests, "payload": payload, "status": "prepared"}
        _write_json(state_path, state, worker)
        _browser_stage(directory, session_id, worker, expires_at=deadline)
        handed_off = True
        return {"status": "browser_research_required", "session_id": session_id, "job_id": job["id"],
                "state_path": str(state_path), "evidence_path": str(evidence_path),
                "browser_deadline": deadline.isoformat(), "requests": requests}
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
        if (state.get("version") != 1 or path.name != session_id + ".json" or job is None
                or job["id"] != state.get("job_id") or state.get("base_url") != api.base_url
                or state.get("worker_id") != "manual-codex"
                or state.get("status") not in ("prepared", "generated", "completed", "failed")
                or state.get("reasoning_effort") not in (None, *worker.REASONING_EFFORTS)
                or (state.get("model") is not None and not isinstance(state["model"], str))):
            raise ValueError
        requests = state["requests"]
        if (not isinstance(requests, list) or not 1 <= len(requests) <= sources.MAX_URLS
                or requests != browser_requests(state["payload"]["source_evidence"])):
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
    if not isinstance(records, list) or len(records) > len(state["requests"]):
        raise worker.WorkerError("Browser evidence has an invalid record collection.")
    wanted = {item["source_url"]: item for item in state["requests"]}
    verified = {}
    prepared = _timestamp(state["prepared_at"], worker)
    deadline = _timestamp(state["browser_deadline"], worker)
    for item in records:
        if (not isinstance(item, dict) or not isinstance(item.get("source_url"), str)
                or item["source_url"] not in wanted or item["source_url"] in verified):
            raise worker.WorkerError("Browser evidence contains an unrequested or duplicate URL.")
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
        if final_url and host not in {_safe_url(item["source_url"], allow_http=True), "invaluable.com"}:
            raise worker.WorkerError("Browser evidence has an unrelated or unsafe final URL.")
        if error:
            if text or title:
                raise worker.WorkerError("Unavailable browser records must not contain listing facts.")
        elif not text or not final_url or not host:
            raise worker.WorkerError("Successful browser evidence needs visible text and an HTTPS final URL.")
        verified[item["source_url"]] = {"source_url": item["source_url"], "final_url": final_url,
            "title": title, "text": text, "fetched_at": fetched.isoformat(), "error": error,
            "source_kind": "browser", "public_error": wanted[item["source_url"]]["public_error"]}
    result = []
    for original in state["payload"]["source_evidence"]:
        source_url = original["source_url"]
        if source_url in verified:
            recovered = verified[source_url]
        elif source_url in wanted:
            recovered = {"source_url": source_url, "final_url": "", "title": "", "text": "",
                         "fetched_at": _now().isoformat(), "source_kind": "browser",
                         "public_error": wanted[source_url]["public_error"],
                         "error": UNAVAILABLE_REASONS.get(unavailable, "The browser did not return evidence for this source.")}
        else:
            result.append(dict(original))
            continue
        content = (original.get("title", "") + "\n" + original.get("text", "")).casefold()
        if (recovered["error"] and not original.get("error") and original.get("text", "").strip()
                and not any(marker in content[:2500] for marker in SHELL_MARKERS)):
            # A short public excerpt can still be useful. Preserve its facts and
            # separately tell the generator that browser supplementation failed.
            result.append({**original, "browser_error": recovered["error"]})
        else:
            result.append(recovered)
    return result


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
                browser_notes = [{"source_url": item["source_url"], "error": item.pop("browser_error")}
                                 for item in merged if "browser_error" in item]
                _browser_stage(path.parent, state["session_id"], worker, release=True)
                # Keep the original prepared evidence in state for manifest validation.
                generation_payload = {**payload, "source_evidence": merged, "browser_research_notes": browser_notes}
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
        return result
