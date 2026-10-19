#!/usr/bin/env python3
"""Normalize scoped Gmail thread evidence and import it into Coordinate.

The outer app performs the only Gmail reads, using the manifest's exact thread
IDs. This process has no Gmail credentials, search, send or attachment APIs.
Raw observations and normalized retry payloads stay in ignored private_data.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

if __package__:
    from .coordinate_worker import CoordinateAPI, WorkerError
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from coordinate_worker import CoordinateAPI, WorkerError

ACCOUNT_EMAIL = "jeremy@secondstate.art"
GMAIL_LINK_ID = "link_6ad64868bc4c8191a85c62352cb4e3cf"
MAX_THREADS = 4
MAX_MESSAGES = 20
MAX_BODY = 24_000
MAX_PART_BYTES = 150_000
MAX_RAW_BYTES = 4_000_000
MAX_IMPORT_BYTES = 700_000
MAX_ATTACHMENTS = 20
SYNC_SECONDS = 60
STATE_DIR = Path(__file__).resolve().parents[1] / "private_data" / "coordinate-mail-runs"
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
EMAIL_PATTERN = re.compile(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+\Z")


def _text(value, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError("Invalid or oversized mail field.")
    return value.strip()


def gmail_id(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError("Invalid Gmail identifier.")
    return value


def aware_time(value):
    try:
        parsed = datetime.fromisoformat(_text(value, 64, True).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        raise ValueError("Mail observation time must include a timezone.") from None


def addresses(value):
    if not isinstance(value, str) or len(value) > 4000 or "\x00" in value:
        raise ValueError("Invalid mail address header.")
    if not value.strip():
        return []
    result = []
    for _, address in getaddresses([value]):
        address = address.strip().casefold()
        if not EMAIL_PATTERN.fullmatch(address) or len(address) > 254:
            raise ValueError("Invalid mail address header.")
        if address not in result:
            result.append(address)
    if len(result) > 30:
        raise ValueError("Too many mail participants.")
    return result


class PlainHTML(HTMLParser):
    """Text-only rendering; no network, scripts, images, links or active markup."""
    ignored = {"script", "style", "template", "noscript", "svg", "head"}
    blocks = {"br", "p", "div", "li", "tr", "section", "article", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.pieces = []

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored:
            self.hidden.append(tag)
        if not self.hidden and tag in self.blocks:
            self.pieces.append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in self.blocks:
            self.pieces.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.pieces.append(data)

    def result(self):
        return "\n".join(line for line in (" ".join(line.split()) for line in "".join(self.pieces).splitlines()) if line)


def _decode(data, charset="utf-8"):
    if not isinstance(data, str) or len(data) > MAX_PART_BYTES * 2 or not re.fullmatch(r"[A-Za-z0-9_\-=]*", data):
        raise ValueError("Mail body is not bounded Gmail base64url data.")
    try:
        raw = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
        if len(raw) > MAX_PART_BYTES:
            raise ValueError
        return raw.decode(charset, errors="replace")
    except (ValueError, LookupError):
        raise ValueError("Mail MIME body could not be decoded safely.") from None


def _headers(payload):
    values = payload.get("headers", [])
    if not isinstance(values, list) or len(values) > 150:
        raise ValueError("Invalid Gmail message headers.")
    result = {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Invalid Gmail message headers.")
        name = _text(value.get("name"), 100, True).casefold()
        content = _text(value.get("value", ""), 8000)
        if name in ("from", "to", "cc", "subject", "message-id", "in-reply-to", "references"):
            if name in result:
                raise ValueError("Ambiguous duplicate mail identity header.")
            result[name] = content
    return result


def _body(payload):
    attachments, plain, html = [], [], []
    count = [0]

    def visit(part, depth=0):
        count[0] += 1
        if not isinstance(part, dict) or depth > 10 or count[0] > 100:
            raise ValueError("Mail MIME tree exceeds the bounded import contract.")
        mime = _text(part.get("mimeType", ""), 100).casefold()
        filename = _text(part.get("filename", ""), 500)
        body = part.get("body") or {}
        if not isinstance(body, dict):
            raise ValueError("Invalid mail MIME body.")
        if filename or body.get("attachmentId"):
            size = body.get("size", 0)
            if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= 10_000_000_000:
                raise ValueError("Invalid mail attachment size.")
            if len(attachments) >= MAX_ATTACHMENTS:
                raise ValueError("Too many mail attachments.")
            attachments.append({"filename": filename[:200], "mime_type": mime, "size": size})
            return  # Attachment IDs/data never leave this parser and are never fetched.
        if mime in ("text/plain", "text/html") and body.get("data"):
            charset = "utf-8"
            for header in part.get("headers", []):
                if isinstance(header, dict) and str(header.get("name", "")).casefold() == "content-type":
                    match = re.search(r"charset\s*=\s*[\"']?([\w-]+)", str(header.get("value", "")), re.IGNORECASE)
                    if match:
                        charset = match.group(1)
            value = _decode(body["data"], charset)
            (plain if mime == "text/plain" else html).append(value)
        children = part.get("parts", [])
        if not isinstance(children, list):
            raise ValueError("Invalid nested mail MIME parts.")
        for child in children:
            visit(child, depth + 1)

    visit(payload)
    if plain:
        text = "\n".join(plain)
    else:
        parser = PlainHTML()
        parser.feed("\n".join(html))
        parser.close()
        text = parser.result()
    text = text.replace("\x00", "").replace("\r\n", "\n").strip()
    truncated = len(text) > MAX_BODY
    return text[:MAX_BODY], attachments, truncated


def normalize_message(raw, expected_thread, observed_at, now=None):
    if not isinstance(raw, dict):
        raise ValueError("Invalid Gmail message.")
    if gmail_id(raw.get("threadId")) != expected_thread:
        raise ValueError("Mail belongs to a different thread.")
    identifier = gmail_id(raw.get("id"))
    stamp = raw.get("internalDate")
    if not isinstance(stamp, (str, int)) or isinstance(stamp, bool) or not re.fullmatch(r"\d{10,16}", str(stamp)):
        raise ValueError("Mail lacks a valid Gmail internal date.")
    try:
        received = datetime.fromtimestamp(int(stamp) / 1000, timezone.utc)
    except (OverflowError, ValueError, OSError):
        raise ValueError("Invalid Gmail internal date.") from None
    now = now or datetime.now(timezone.utc)
    if received > min(observed_at, now) + timedelta(seconds=5):
        raise ValueError("Future mail cannot enter the case context.")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Mail requires observed headers and MIME parts, not a search snippet.")
    headers = _headers(payload)
    try:
        subject = str(make_header(decode_header(headers.get("subject", ""))))
    except (ValueError, LookupError, UnicodeError):
        raise ValueError("Mail subject encoding could not be decoded safely.") from None
    senders = addresses(headers.get("from", ""))
    if len(senders) != 1:
        raise ValueError("Mail must have exactly one sender.")
    to = addresses(headers.get("to", ""))
    cc = addresses(headers.get("cc", ""))
    text, attachments, truncated = _body(payload)
    if not text and not attachments:
        raise ValueError("Mail has no readable body or attachment metadata.")
    labels = raw.get("labelIds", [])
    if not isinstance(labels, list) or len(labels) > 100 or any(not isinstance(label, str) or len(label) > 100 for label in labels):
        raise ValueError("Invalid Gmail message labels.")
    return {"gmail_message_id": identifier, "gmail_thread_id": expected_thread, "sent_label": "SENT" in labels,
            "from_email": senders[0], "to_emails": to, "cc_emails": cc,
            "subject": subject[:200], "body_text": text,
            "body_truncated": truncated, "attachments": attachments,
            "rfc_message_id": headers.get("message-id", "")[:998],
            "in_reply_to": headers.get("in-reply-to", "")[:998],
            "references": headers.get("references", "")[:8000], "received_at": received.isoformat()}


def normalize_thread(raw, observed_at, now=None):
    if not isinstance(raw, dict):
        raise ValueError("Invalid Gmail thread evidence.")
    thread_id = gmail_id(raw.get("id"))
    messages = raw.get("messages")
    if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
        raise ValueError("A mail read must contain at most twenty recent messages.")
    normalized, seen = [], set()
    for message in messages:
        item = normalize_message(message, thread_id, observed_at, now)
        if item["gmail_message_id"] in seen:
            raise ValueError("Duplicate Gmail message in one observation.")
        seen.add(item["gmail_message_id"])
        normalized.append(item)
    return {"gmail_thread_id": thread_id, "messages": normalized}


def _read(path, limit):
    with Path(path).open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise WorkerError("Mail sync file exceeded its size limit.")
    try:
        value = json.loads(content)
    except (ValueError, UnicodeError):
        raise WorkerError("Mail sync file is not valid JSON.") from None
    if not isinstance(value, dict):
        raise WorkerError("Mail sync file must contain an object.")
    return value


def _write(path, value):
    from tempfile import NamedTemporaryFile
    path = Path(path)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def prepare(api, state_dir=STATE_DIR):
    manifest = api.post("/coordinate/api/mail/sync/", {"worker_id": "manual-codex"})
    if not manifest.get("threads") and not manifest.get("reconcile"):
        return {"status": "mail_idle", "thread_count": 0,
                "sync_enabled": bool(manifest.get("sync_enabled")),
                "mail_readiness": manifest.get("mail_readiness", {})}
    directory = Path(state_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    identifier = str(uuid4())
    path = directory / (identifier + ".json")
    manifest.update(base_url=api.base_url, status="prepared")
    _write(path, manifest)
    return {"status": "mail_sync_required", "manifest_path": str(path),
            "observations_path": str(directory / (identifier + ".observations.json")),
            "sync_deadline": manifest["sync_deadline"], "account_email": ACCOUNT_EMAIL,
            "link_id": GMAIL_LINK_ID, "max_messages": MAX_MESSAGES, "threads": manifest["threads"],
            "reconcile": manifest.get("reconcile", [])}


def complete(api, manifest_path, observations_path):
    manifest = _read(manifest_path, MAX_RAW_BYTES)
    if manifest.get("base_url") != api.base_url:
        raise WorkerError("Mail manifest belongs to another Coordinate server.")
    if manifest.get("status") == "completed":
        return manifest["result"]
    if "imports" not in manifest:
        evidence = _read(observations_path, MAX_RAW_BYTES)
        if evidence.get("account_email") != ACCOUNT_EMAIL:
            raise WorkerError("Mail observations belong to the wrong Gmail account.")
        observed = aware_time(evidence.get("observed_at"))
        now = datetime.now(timezone.utc)
        if not now - timedelta(minutes=5) <= observed <= now + timedelta(seconds=5):
            raise WorkerError("Mail observations are stale or from the future.")
        raw_threads = evidence.get("threads")
        if not isinstance(raw_threads, list) or len(raw_threads) > MAX_THREADS:
            raise WorkerError("Mail observations exceeded the scoped thread limit.")
        allowed = {thread["gmail_thread_id"] for thread in manifest["threads"]}
        normalized = [normalize_thread(thread, observed, now) for thread in raw_threads]
        if len({thread["gmail_thread_id"] for thread in normalized}) != len(normalized):
            raise WorkerError("Mail observations contain duplicate threads.")
        if any(thread["gmail_thread_id"] not in allowed for thread in normalized):
            raise WorkerError("Mail observations contain an unrequested thread.")
        manifest["imports"] = [{"worker_id": "manual-codex", "sync_token": manifest["sync_token"],
            "account_email": ACCOUNT_EMAIL, "observed_at": observed.isoformat(), "thread": thread} for thread in normalized]
        deliveries = evidence.get("deliveries", [])
        if not isinstance(deliveries, list) or len(deliveries) > 2:
            raise WorkerError("Too many delivery reconciliation observations.")
        requested = {item["delivery_id"]: item for item in manifest.get("reconcile", [])}
        seen = set()
        for delivery in deliveries:
            if not isinstance(delivery, dict) or delivery.get("delivery_id") not in requested or delivery["delivery_id"] in seen:
                raise WorkerError("Delivery reconciliation was not requested.")
            seen.add(delivery["delivery_id"])
            raw = delivery.get("message")
            if not isinstance(raw, dict):
                raise WorkerError("Delivery reconciliation needs exact observed message MIME evidence.")
            item = normalize_message(raw, gmail_id(raw.get("threadId")), observed, now)
            if item["rfc_message_id"] != requested[delivery["delivery_id"]]["rfc_message_id"] or not item["sent_label"]:
                raise WorkerError("Delivery observation is not the exact requested Sent message.")
            manifest["imports"].append({"worker_id": "manual-codex", "sync_token": manifest["sync_token"],
                "account_email": ACCOUNT_EMAIL, "observed_at": observed.isoformat(),
                "reconcile": {"delivery_id": delivery["delivery_id"], "message": item}})
        if any(len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_IMPORT_BYTES for payload in manifest["imports"]):
            raise WorkerError("Normalized mail exceeded its bounded import size.")
        manifest["results"] = []
        _write(manifest_path, manifest)
    for payload in manifest["imports"][len(manifest["results"]):]:
        # A failed response leaves the identical normalized payload on disk.
        # Server message-ID tombstones make later re-observation idempotent too.
        result = api.post("/coordinate/api/mail/import/", payload)
        manifest["results"].append(result)
        _write(manifest_path, manifest)
    result = {"status": "mail_synced", "thread_count": len(manifest["results"]),
              "imported": sum(item.get("imported", 0) for item in manifest["results"]),
              "duplicates": sum(item.get("duplicates", 0) for item in manifest["results"]),
              "reconciled": sum(item.get("status") == "reconciled" for item in manifest["results"])}
    manifest.update(status="completed", result=result)
    _write(manifest_path, manifest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("COORDINATE_BASE_URL", "https://secondstate.art"))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--complete", metavar="MANIFEST_PATH")
    parser.add_argument("--observations", metavar="JSON_PATH")
    args = parser.parse_args()
    if args.complete and not args.observations:
        parser.error("--complete requires --observations.")
    try:
        api = CoordinateAPI(args.base_url, os.environ.get("COORDINATE_WORKER_TOKEN", ""))
        result = prepare(api) if args.prepare else complete(api, args.complete, args.observations)
        print(json.dumps(result))
        return 0
    except (WorkerError, ValueError, OSError):
        print("Coordinate mail sync could not complete; private evidence is retained for a bounded retry.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
