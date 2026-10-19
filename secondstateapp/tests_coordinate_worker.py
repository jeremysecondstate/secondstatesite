"""Worker transport and process-boundary checks; live proof is documented separately."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from subprocess import CompletedProcess
from threading import Thread
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from uuid import uuid4

from scripts import coordinate_worker as worker


def claim_payload():
    case_id = str(uuid4())
    return {
        "job": {"id": str(uuid4()), "case_id": case_id, "message_id": 41,
                "claim_token": str(uuid4())},
        "case": {"id": case_id, "title": "Local test", "coordinator": "manual-codex"},
        "messages": [{"id": 41, "role": "staff", "body": "We won lot 17!"}],
        "playbook": {"shipping": "Test mode. Never send email.", "packing": "Retain the mat."},
        "test_mode": True,
    }


class CoordinateGenerationBudgetTests(TestCase):
    def setUp(self):
        self.diagnostics = patch.object(worker, "_save_generation_diagnostics").start()
        self.addCleanup(patch.stopall)

    def payload_with_lease(self, seconds):
        payload = claim_payload()
        payload["job"]["lease_expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=seconds)
        ).isoformat()
        return payload

    def test_unused_research_time_extends_generation_to_ten_minutes_at_most(self):
        self.assertEqual(worker.generation_budget(self.payload_with_lease(900)), 600)
        self.assertEqual(worker.generation_budget(self.payload_with_lease(3600)), 600)
        self.assertEqual(worker.generation_budget(claim_payload()), 300)

    def test_late_generation_keeps_full_completion_transport_reserve(self):
        for remaining in (660, 410, 160):
            with self.subTest(remaining=remaining):
                budget = worker.generation_budget(self.payload_with_lease(remaining))
                self.assertLessEqual(budget, remaining - 100)
                self.assertGreater(budget, remaining - 102)

    def test_explicit_lease_offsets_and_utc_z_use_same_budget(self):
        now = datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc)
        with patch.object(worker, "datetime", wraps=datetime) as worker_datetime:
            worker_datetime.now.return_value = now
            for expiry in ("2026-10-19T18:08:20Z", "2026-10-19T14:08:20-04:00"):
                payload = claim_payload()
                payload["job"]["lease_expires_at"] = expiry
                with self.subTest(expiry=expiry):
                    self.assertEqual(worker.generation_budget(payload), 400)

    def test_malformed_expired_or_transport_only_lease_never_starts_model(self):
        for lease in ("not-a-timestamp", "2026-10-19T12:00:00", {},
                      (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                      (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()):
            payload = claim_payload()
            payload["job"]["lease_expires_at"] = lease
            with self.subTest(lease=lease), patch.object(worker.subprocess, "run") as process:
                with self.assertRaises(worker.WorkerError):
                    worker.generate_reply(payload, "codex")
                process.assert_not_called()

    def test_actual_process_timeout_uses_adaptive_budget(self):
        payload = self.payload_with_lease(900)
        with (patch.object(worker.time, "monotonic", return_value=1000),
              patch.object(worker.subprocess, "run", side_effect=subprocess.TimeoutExpired("codex", 600)) as process):
            with self.assertRaises(worker.WorkerError):
                worker.generate_reply(payload, "codex", "gpt-6-astra", "ultra")
        self.assertEqual(process.call_count, 1)
        self.assertEqual(process.call_args.kwargs["timeout"], 600)

    def test_validation_repair_shares_one_adaptive_deadline(self):
        payload = self.payload_with_lease(900)
        payload.update(test_mode=False, brief_enabled=True)
        clock = [1000.0]
        calls = []

        def process(command, **kwargs):
            calls.append(kwargs)
            (Path(kwargs["cwd"]) / "response.json").write_text(json.dumps({
                "body": "Supported findings remain available.", "drafts": [], "brief": None,
            }), encoding="utf-8")
            if len(calls) == 1:
                clock[0] += 425
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

        with (patch.object(worker.time, "monotonic", side_effect=lambda: clock[0]),
              patch.object(worker.subprocess, "run", side_effect=process),
              patch.object(worker, "generation_budget", wraps=worker.generation_budget) as budget,
              patch.object(worker, "validate_price_evidence", side_effect=[ValueError("Unsupported price"), None])):
            result = worker.generate_reply(payload, "codex", "gpt-6-astra", "ultra")
        self.assertEqual(result["brief"], None)
        budget.assert_called_once_with(payload)
        self.assertEqual([call["timeout"] for call in calls], [600, 175])
        self.assertIn("VALIDATION CORRECTION", calls[1]["input"])

    def test_invalid_output_at_generation_deadline_does_not_start_repair(self):
        payload = self.payload_with_lease(900)
        payload.update(test_mode=False, brief_enabled=True)
        clock = [1000.0]

        def process(command, **kwargs):
            (Path(kwargs["cwd"]) / "response.json").write_text(json.dumps({
                "body": "Unsupported brief.", "drafts": [], "brief": None,
            }), encoding="utf-8")
            clock[0] += 601
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

        with (patch.object(worker.time, "monotonic", side_effect=lambda: clock[0]),
              patch.object(worker.subprocess, "run", side_effect=process) as run,
              patch.object(worker, "validate_price_evidence", side_effect=ValueError("Unsupported price"))):
            with self.assertRaisesRegex(worker.WorkerError, "research is retained"):
                worker.generate_reply(payload, "codex")
        self.assertEqual(run.call_count, 1)


class CoordinateGenerationDiagnosticsTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        override = patch.object(worker, "GENERATION_DIAGNOSTIC_DIR", self.directory)
        override.start()
        self.addCleanup(override.stop)
        self.payload = claim_payload()
        self.payload.update(test_mode=False, brief_enabled=True)
        self.path = self.directory / (self.payload["job"]["id"] + ".json")

    def response(self, command, kwargs, body):
        (Path(kwargs["cwd"]) / "response.json").write_text(json.dumps({
            "body": body, "drafts": [], "brief": None, "unexpected": "UNEXPECTED FIELD",
        }), encoding="utf-8")
        return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "PRIVATE STDERR")

    def test_failure_is_retained_before_repair_timeout_without_credentials_or_context_dump(self):
        calls = []
        secret = "test-worker-credential-that-must-not-be-persisted"
        body = "PRIVATE GENERATED BODY " + self.payload["job"]["claim_token"] + " " + secret
        self.payload["messages"][0]["body"] = "PRIVATE SOURCE MESSAGE THAT MUST NOT BE COPIED"
        def process(command, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return self.response(command, kwargs, body)
            first = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertEqual(first["attempts"][0]["error"], "Unsupported price evidence.")
            self.assertEqual(first["response_attempt"], 1)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="PRIVATE STDOUT", stderr="PRIVATE STDERR")
        with (patch.dict(os.environ, {"COORDINATE_WORKER_TOKEN": secret}),
              patch.object(worker.subprocess, "run", side_effect=process),
              patch.object(worker, "validate_price_evidence", side_effect=ValueError("Unsupported price evidence.")),
              patch.object(worker.sys, "stdout", new_callable=StringIO) as stdout,
              patch.object(worker.sys, "stderr", new_callable=StringIO) as stderr):
            with self.assertRaisesRegex(worker.WorkerError, "bounded claim budget"):
                worker.generate_reply(self.payload, "codex")
        saved = self.path.read_text(encoding="utf-8")
        record = json.loads(saved)
        self.assertEqual([item["status"] for item in record["attempts"]], ["validation_failed", "timeout"])
        self.assertEqual(record["response_attempt"], 1)
        self.assertIn("PRIVATE GENERATED BODY", record["response"]["body"])
        self.assertEqual(record["response"]["body"].count("[redacted]"), 2)
        for value in (secret, self.payload["job"]["claim_token"], self.payload["messages"][0]["body"],
                      "PRIVATE STDOUT", "PRIVATE STDERR", "UNEXPECTED FIELD", "Retain the mat"):
            self.assertNotIn(value, saved)
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        self.assertTrue(all(item["elapsed_seconds"] >= 0 and item["timeout_seconds"] > 0 for item in record["attempts"]))
        self.assertFalse(Path(calls[0]["cwd"]).exists())

    def test_latest_failed_response_atomically_replaces_first_and_keeps_both_errors(self):
        calls = []
        def process(command, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                self.assertEqual(json.loads(self.path.read_text())["response"]["body"], "First attempted reply.")
            return self.response(command, kwargs, "First attempted reply." if len(calls) == 1 else "Second attempted reply.")
        with (patch.object(worker.subprocess, "run", side_effect=process),
              patch.object(worker, "validate_price_evidence", side_effect=[ValueError("First check failed."), ValueError("Second check failed.")])):
            with self.assertRaisesRegex(worker.WorkerError, "invalid case brief"):
                worker.generate_reply(self.payload, "codex")
        record = json.loads(self.path.read_text())
        self.assertEqual(record["response_attempt"], 2)
        self.assertEqual(record["response"]["body"], "Second attempted reply.")
        self.assertEqual([item["error"] for item in record["attempts"]], ["First check failed.", "Second check failed."])
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_first_pass_success_replaces_stale_failure_with_metadata_only(self):
        worker._save_generation_diagnostics(self.payload, {
            "response": {"body": "OLD PRIVATE FAILED RESPONSE"}, "response_attempt": 2,
            "attempts": [{"number": 2, "status": "validation_failed", "error": "Old failure."}],
        })
        with patch.object(worker.subprocess, "run", side_effect=lambda command, **kwargs:
                          self.response(command, kwargs, "NEW PRIVATE VALID RESPONSE")):
            generated = worker.generate_reply(self.payload, "codex")
        self.assertEqual(generated["body"], "NEW PRIVATE VALID RESPONSE")
        saved = self.path.read_text(encoding="utf-8")
        record = json.loads(saved)
        self.assertIsNone(record["response"])
        self.assertIsNone(record["response_attempt"])
        self.assertEqual(len(record["attempts"]), 1)
        self.assertEqual(record["attempts"][0]["status"], "validated")
        self.assertEqual(record["attempts"][0]["error"], "")
        self.assertNotIn("PRIVATE", saved)
        self.assertNotIn("Old failure", saved)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_repair_without_fresh_output_cannot_reuse_first_attempt_file(self):
        calls = []
        def process(command, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return self.response(command, kwargs, "Rejected first reply.")
            self.assertFalse((Path(kwargs["cwd"]) / "response.json").exists())
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")
        with (patch.object(worker.subprocess, "run", side_effect=process),
              patch.object(worker, "validate_price_evidence", side_effect=ValueError("Invalid evidence.")) as validate):
            with self.assertRaisesRegex(worker.WorkerError, "no valid final reply"):
                worker.generate_reply(self.payload, "codex")
        record = json.loads(self.path.read_text())
        self.assertEqual(record["response_attempt"], 1)
        self.assertEqual(record["attempts"][-1]["status"], "invalid_response")
        self.assertEqual(validate.call_count, 1)

    def test_diagnostic_size_is_bounded_and_write_failure_never_changes_worker_outcome(self):
        diagnostics = {"response": {"body": "PRIVATE " + "😀" * 100_000}, "response_attempt": 1,
                       "attempts": [{"number": 1, "status": "validation_failed", "error": "Invalid reply."}]}
        worker._save_generation_diagnostics(self.payload, diagnostics)
        self.assertLessEqual(self.path.stat().st_size, worker.MAX_GENERATION_DIAGNOSTIC_BYTES)
        record = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(record["response_truncated"])
        self.assertTrue(record["response_excerpt"])
        original = self.path.read_bytes()
        with patch.object(worker.os, "replace", side_effect=OSError("PRIVATE filesystem diagnostic")):
            worker._save_generation_diagnostics(self.payload, {"response": {"body": "Replacement"}})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.directory.iterdir()), [self.path])
        invalid = deepcopy(self.payload)
        invalid["job"]["id"] = "../escape"
        worker._save_generation_diagnostics(invalid, diagnostics)
        self.assertEqual(list(self.directory.iterdir()), [self.path])


class CoordinateShippingRepairTests(TestCase):
    def setUp(self):
        self.payload = claim_payload()
        self.payload.update(test_mode=False, brief_enabled=True)
        self.lot_url = "https://house.example/lot/17"
        self.terms_url = "https://house.example/shipping"
        self.payload["source_evidence"] = [
            {"source_url": self.lot_url, "final_url": self.lot_url, "source_kind": "public_browser", "error": "",
             "text": "Artist A. Work B. Lot 17. Sold: USD 120.00",
             "identity_match": {"status": "exact", "artist": "Artist A", "title": "Work B", "auction_house": "Example House",
                                "auction_date": "2026-10-17", "lot_number": "17"}},
            {"source_url": self.lot_url, "final_url": self.terms_url, "source_kind": "public_browser", "error": "",
             "text": "Collect within seven days. Example Packers: packing@example.test",
             "identity_match": {"status": "context", "auction_house": "Example House"}},
        ]
        lot = {key: "" for key in worker.BRIEF_SCHEMA["properties"]["lots"]["items"]["properties"]
               if key not in ("source_refs", "prices")}
        lot.update(label="Synthetic lot 17", artist="Artist A", title="Work B", auction_house="Example House",
                   auction_date="2026-10-17", lot_number="17", source_refs=[self.lot_url], prices=[{
                       "kind": "sold", "basis": "unknown", "label": "Sold", "amount": "120.00", "amount_high": "",
                       "currency": "USD", "evidence_quote": "Sold: USD 120.00", "source_refs": [self.lot_url],
                   }])
        self.shipping = {
            "working_currency": {"code": "", "basis": "unknown", "note": "", "source_refs": []},
            "quote_readiness": {"status": "conditional_ready", "note": "Request conditional quotes."},
            "actions": [], "providers": [{"name": "Example Packers", "email": "packing@example.test", "service_type": "unknown",
                "published_capability": "", "contact_quote": "Example Packers: packing@example.test", "source_refs": [self.terms_url]}],
            "site_checks": [{"topic": "pickup", "status": "found", "note": "Collect within seven days.", "source_refs": [self.terms_url]}],
        }
        self.brief = {
            "summary": "Verified sale details.", "lots": [lot],
            "plan": {"notes": "Prepare conditional quote requests.", "pickup_deadline": "", "deadline_basis": "", "source_refs": [self.terms_url]},
            "open_questions": [], "shipping": deepcopy(self.shipping),
        }
        self.invalid = deepcopy(self.brief)
        self.invalid["shipping"]["site_checks"][0]["note"] += " Arrange prompt collection."
        self.calls = []
        self.clock = [1000.0]
        self.diagnostics = patch.object(worker, "_save_generation_diagnostics").start()
        patch.object(worker, "generation_budget", return_value=600).start()
        patch.object(worker.time, "monotonic", side_effect=lambda: self.clock[0]).start()
        self.addCleanup(patch.stopall)

    def run_responses(self, responses):
        def process(command, **kwargs):
            self.calls.append({**kwargs, "schema": json.loads((Path(kwargs["cwd"]) / "response-schema.json").read_text())})
            response = responses[len(self.calls) - 1]
            (Path(kwargs["cwd"]) / "response.json").write_text(json.dumps(response), encoding="utf-8")
            self.clock[0] += 250 if len(self.calls) == 1 else 10
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")
        with patch.object(worker.subprocess, "run", side_effect=process):
            return worker.generate_reply(self.payload, "codex", "gpt-6-astra", "ultra")

    def test_shipping_only_repair_preserves_validated_lots_prices_plan_and_shared_budget(self):
        draft = {"recipient": "packing@example.test", "subject": "Conditional quote", "body": "Please quote packing and transport.", "purpose": "Comparable quote inquiry."}
        result = self.run_responses([
            {"body": "First text with a claim that needs correction.", "drafts": [], "brief": self.invalid},
            {"body": "Fresh supported conversation text.", "drafts": [draft], "site_checks": self.shipping["site_checks"]},
        ])
        self.assertEqual(result["body"], "Fresh supported conversation text.")
        self.assertEqual(result["drafts"], [draft])
        self.assertEqual(result["brief"], worker.validate_brief(self.brief))
        self.assertEqual([call["timeout"] for call in self.calls], [600, 350])
        self.assertEqual(set(self.calls[0]["schema"]["properties"]), {"body", "drafts", "brief"})
        self.assertEqual(set(self.calls[1]["schema"]["properties"]), {"body", "drafts", "site_checks"})
        self.assertEqual(self.calls[1]["schema"]["required"], ["body", "drafts", "site_checks"])
        self.assertFalse(self.calls[1]["schema"]["additionalProperties"])
        self.assertIn("Regenerate body and drafts", self.calls[1]["input"])
        worker.validate_price_evidence(result["brief"], worker.brief_evidence(self.payload))

    def test_invalid_core_price_keeps_whole_response_repair(self):
        self.invalid["lots"][0]["prices"][0]["amount"] = "999.00"
        result = self.run_responses([
            {"body": "Incorrect price and shipping.", "drafts": [], "brief": self.invalid},
            {"body": "Corrected full findings.", "drafts": [], "brief": self.brief},
        ])
        self.assertEqual(set(self.calls[1]["schema"]["properties"]), {"body", "drafts", "brief"})
        self.assertEqual(result["brief"]["lots"][0]["prices"][0]["amount"], "120.00")

    def test_shipping_shape_failure_keeps_whole_response_repair(self):
        self.invalid["shipping"]["unexpected"] = "not allowed"
        result = self.run_responses([
            {"body": "Malformed shipping.", "drafts": [], "brief": self.invalid},
            {"body": "Corrected full findings.", "drafts": [], "brief": self.brief},
        ])
        self.assertEqual(set(self.calls[1]["schema"]["properties"]), {"body", "drafts", "brief"})
        self.assertEqual(result["brief"], worker.validate_brief(self.brief))

    def test_mixed_provider_and_site_quote_failures_keep_whole_response_repair(self):
        self.invalid["shipping"]["providers"][0]["name"] = "Different Packers"
        result = self.run_responses([
            {"body": "Incorrect provider attribution and site quote.", "drafts": [], "brief": self.invalid},
            {"body": "Corrected full findings.", "drafts": [], "brief": self.brief},
        ])
        self.assertEqual(set(self.calls[1]["schema"]["properties"]), {"body", "drafts", "brief"})
        self.assertEqual(result["brief"]["shipping"]["providers"], self.brief["shipping"]["providers"])

    def test_targeted_repair_cannot_replace_core_or_leave_unsupported_shipping(self):
        for repair, error in (
            ({"body": "Attempted core replacement.", "drafts": [], "site_checks": self.shipping["site_checks"], "brief": self.brief}, "no valid final reply"),
            ({"body": "Still unsupported.", "drafts": [], "site_checks": self.invalid["shipping"]["site_checks"]}, "invalid case brief"),
        ):
            self.calls.clear()
            with self.subTest(error=error), self.assertRaisesRegex(worker.WorkerError, error):
                self.run_responses([{"body": "First response.", "drafts": [], "brief": self.invalid}, repair])
            self.assertEqual(len(self.calls), 2)

    def test_targeted_repair_revalidates_new_draft_recipients(self):
        draft = {"recipient": "unverified@example.test", "subject": "Quote", "body": "Please quote.", "purpose": "Inquiry"}
        with self.assertRaisesRegex(worker.WorkerError, "unverified draft recipient"):
            self.run_responses([
                {"body": "First response.", "drafts": [], "brief": self.invalid},
                {"body": "New response.", "drafts": [draft], "site_checks": self.shipping["site_checks"]},
            ])
        self.assertEqual(len(self.calls), 2)


class CoordinateWorkerTests(TestCase):
    def setUp(self):
        self.diagnostics = patch.object(worker, "_save_generation_diagnostics").start()
        self.addCleanup(patch.stopall)

    def test_manual_and_scheduled_runpy_entrypoints_import_sources_without_credentials(self):
        repository = Path(__file__).resolve().parents[1]
        commands = [
            [sys.executable, "scripts/coordinate_worker.py", "--help"],
            [sys.executable, "-c", "import runpy,sys; sys.argv=['scripts/coordinate_worker.py','--help']; "
             "runpy.run_path('scripts/coordinate_worker.py', run_name='__main__')"],
        ]
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run(command, cwd=repository, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--reasoning-effort", result.stdout)

    def test_origin_requires_https_except_loopback_and_forbids_credentials(self):
        for value in ("http://example.com", "https://secret@example.com", "https://example.com/path",
                      "https://example.com?q=secret", "https://example.com/#token", "file:///tmp"):
            with self.subTest(value=value), self.assertRaises(worker.WorkerError):
                worker.validate_base_url(value)
        self.assertEqual(worker.validate_base_url("http://127.0.0.1:8765/"), "http://127.0.0.1:8765")
        self.assertEqual(worker.validate_base_url("https://example.com"), "https://example.com")

    def test_redirect_does_not_forward_worker_token(self):
        visited = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                visited.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/credential-destination")
                self.end_headers()

            def do_GET(self):
                visited.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = worker.CoordinateAPI(f"http://127.0.0.1:{server.server_port}", "secret")
            with self.assertRaises(worker.APIError) as caught:
                api.post("/claim", {})
            self.assertEqual(caught.exception.status, 302)
            self.assertEqual(visited, ["/claim"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @patch.object(worker.time, "sleep")
    def test_completion_retries_identical_payload_without_leaking_response(self, sleep):
        api = worker.CoordinateAPI("http://localhost:8765", "secret")
        api.opener = Mock()
        api.opener.open.side_effect = [
            HTTPError("url", 503, "failure", {}, BytesIO(b"private server failure")),
            URLError("private network failure"),
            BytesIO(b'{"reply_id":42,"already_completed":true}'),
        ]
        payload = {"body": "Actual generated response", "claim_token": "same-claim"}
        result = api.post("/complete", payload, retry=True)
        self.assertEqual(result["reply_id"], 42)
        requests = [call.args[0] for call in api.opener.open.call_args_list]
        self.assertTrue(all(req.data == requests[0].data for req in requests))
        self.assertEqual(len(requests), 3)

    @patch.object(worker.time, "sleep")
    def test_stale_claim_is_never_retried(self, sleep):
        api = worker.CoordinateAPI("http://localhost:8765", "secret")
        api.opener = Mock()
        api.opener.open.side_effect = HTTPError("url", 409, "private detail", {}, None)
        with self.assertRaises(worker.APIError) as caught:
            api.post("/complete", {}, retry=True)
        self.assertEqual(str(caught.exception), "Coordinate API returned HTTP 409.")
        self.assertEqual(api.opener.open.call_count, 1)
        sleep.assert_not_called()

    def test_claim_requires_test_mode_matching_conversation_and_playbooks(self):
        valid = claim_payload()
        self.assertEqual(worker.validate_claim(valid), valid["job"])
        for change in ("test_mode", "case", "messages", "playbook"):
            invalid = deepcopy(valid)
            invalid[change] = False if change == "test_mode" else {}
            with self.subTest(change=change), self.assertRaises(worker.WorkerError):
                worker.validate_claim(invalid)
        invalid = deepcopy(valid)
        invalid["case"]["id"] = str(uuid4())
        with self.assertRaises(worker.WorkerError):
            worker.validate_claim(invalid)

    @patch.dict(os.environ, {
        "COORDINATE_WORKER_TOKEN": "website-secret", "GMAIL_TOKEN": "gmail-secret",
        "OPENAI_API_KEY": "api-secret", "CODEX_APP_TOOLS_PIPE_PATH": "app-pipe",
        "CODEX_THREAD_ID": "inherited-thread", "PATH": "path", "USERPROFILE": "profile",
    }, clear=True)
    def test_model_environment_drops_secrets_and_desktop_context(self):
        env = worker.model_environment()
        self.assertEqual(env["PATH"], "path")
        self.assertIn("CODEX_HOME", env)
        for key in ("COORDINATE_WORKER_TOKEN", "GMAIL_TOKEN", "OPENAI_API_KEY",
                    "CODEX_APP_TOOLS_PIPE_PATH", "CODEX_THREAD_ID"):
            self.assertNotIn(key, env)

    def test_model_has_fresh_context_no_claim_secret_and_disabled_action_tools(self):
        payload = claim_payload()
        captured = {}

        def fake_process(command, **kwargs):
            captured.update(command=command, **kwargs)
            (Path(kwargs["cwd"]) / "response.json").write_text(
                json.dumps({"body": "What is lot 17's pickup deadline?", "drafts": []}), encoding="utf-8"
            )
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

        with patch.object(worker.subprocess, "run", side_effect=fake_process):
            reply = worker.generate_reply(payload, "codex")
        self.assertIn("pickup deadline", reply["body"])
        self.assertEqual(reply["drafts"], [])
        self.assertIn("Retain the mat", captured["input"])
        self.assertIn("We won lot 17", captured["input"])
        self.assertNotIn(payload["job"]["claim_token"], captured["input"])
        self.assertIn("--ephemeral", captured["command"])
        self.assertIn("--ignore-user-config", captured["command"])
        self.assertIn("--no-daemon", captured["command"])
        self.assertIn('web_search="disabled"', captured["command"])
        self.assertIn("mcp_servers={}", captured["command"])
        self.assertIn("shell_tool", captured["command"])
        self.assertNotIn("--model", captured["command"])
        self.assertFalse(any(arg.startswith("model_reasoning_effort=") for arg in captured["command"]))
        self.assertFalse(Path(captured["cwd"]).exists())

    def test_cli_model_and_reasoning_effort_reach_actual_generation_command(self):
        payload = claim_payload()
        api = Mock()
        api.post.side_effect = [payload, {"reply_id": 42, "already_completed": False}]
        captured = {}

        def fake_process(command, **kwargs):
            captured.update(command=command, **kwargs)
            (Path(kwargs["cwd"]) / "response.json").write_text(
                json.dumps({"body": "Test response generated with the requested model.", "drafts": []}), encoding="utf-8"
            )
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

        with (
            patch.object(worker.sys, "argv", ["coordinate_worker.py", "--model", "gpt-6-astra",
                                             "--reasoning-effort", "ultra"]),
            patch.object(worker.sys, "stdout", new_callable=StringIO),
            patch.object(worker.shutil, "which", return_value="codex-executable"),
            patch.object(worker, "CoordinateAPI", return_value=api),
            patch.object(worker.subprocess, "run", side_effect=fake_process),
        ):
            self.assertEqual(worker.main(), 0)
        command = captured["command"]
        self.assertEqual(command[command.index("--model") + 1], "gpt-6-astra")
        effort_index = command.index('model_reasoning_effort="ultra"')
        self.assertEqual(command[effort_index - 1], "-c")
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--no-daemon", command)
        self.assertIn("mcp_servers={}", command)
        self.assertNotIn("COORDINATE_WORKER_TOKEN", captured["env"])
        self.assertEqual(api.post.call_args_list[1].args[1]["body"],
                         "Test response generated with the requested model.")

    def test_reasoning_effort_rejects_unsupported_option_before_claiming_work(self):
        with (
            patch.object(worker.sys, "argv", ["coordinate_worker.py", "--reasoning-effort", "unknown"]),
            patch.object(worker.sys, "stderr", new_callable=StringIO),
            patch.object(worker, "CoordinateAPI") as api,
            self.assertRaises(SystemExit) as caught,
        ):
            worker.main()
        self.assertEqual(caught.exception.code, 2)
        api.assert_not_called()

    def test_reasoning_effort_accepts_advertised_levels_and_rejects_direct_invalid_value(self):
        for effort in ("low", "medium", "high", "xhigh", "max", "ultra"):
            with self.subTest(effort=effort):
                command = worker.codex_command("codex", Path("temporary"), "gpt-6-astra", effort)
                self.assertIn('model_reasoning_effort="' + effort + '"', command)
        with self.assertRaises(worker.WorkerError):
            worker.codex_command("codex", Path("temporary"), "gpt-6-astra", 'ultra"\nmalicious=true')

    def test_production_requires_draft_only_and_accepts_server_created_review_message(self):
        payload = claim_payload()
        payload.update(test_mode=False, draft_only=True)
        payload["messages"][0]["role"] = "system"
        self.assertEqual(worker.validate_claim(payload), payload["job"])
        payload["draft_only"] = False
        with self.assertRaisesRegex(worker.WorkerError, "draft-only"):
            worker.validate_claim(payload)

    @patch.object(worker, "generate_reply", return_value={"body": "Prepared for review.", "drafts": []})
    @patch.object(worker, "research_messages")
    def test_research_requires_all_explicit_capability_flags(self, research, generate):
        for mode in ({}, {"test_mode": False, "draft_only": True},
                     {"test_mode": True, "draft_only": True, "research_enabled": True}):
            with self.subTest(mode=mode):
                payload = claim_payload()
                payload.update(mode)
                api = Mock()
                api.post.side_effect = [payload, {"reply_id": 42}]
                worker.run_once(api, "codex", "manual-codex")
                self.assertEqual(api.post.call_args_list[1].args[1]["research"], [])
        research.assert_not_called()

    @patch.object(worker, "generate_reply", return_value={"body": "The listing says 10 inches.", "drafts": []})
    @patch.object(worker, "research_messages")
    def test_public_evidence_reaches_generation_and_same_completion(self, research, generate):
        evidence = [{"source_url": "https://example.com/lot", "final_url": "https://example.com/lot",
                     "title": "Lot 17", "text": "Width 10 inches.", "error": "", "fetched_at": "2026-10-19T00:00:00Z"}]
        research.return_value = evidence
        payload = claim_payload()
        payload.update(test_mode=False, draft_only=True, research_enabled=True, coordination={"plan": {"stage": "research"}})
        api = Mock()
        api.post.side_effect = [payload, {"reply_id": 42}]
        result = worker.run_once(api, "codex", "manual-codex")
        research.assert_called_once_with(payload["messages"])
        self.assertEqual(generate.call_args.args[0]["source_evidence"], evidence)
        self.assertEqual(api.post.call_args_list[1].args[1]["research"], evidence)
        self.assertEqual(result["research_count"], 1)
        self.assertFalse(result["test_mode"])
        self.assertTrue(result["draft_only"])

    def test_generated_drafts_use_saved_contacts_and_coordination_context(self):
        payload = claim_payload()
        payload.update(test_mode=False, draft_only=True,
                       coordination={"plan": {"provider_email": "packer@example.com", "stage": "research"}})
        draft = {"recipient": "packer@example.com", "subject": "packing inquiry!",
                 "body": "hello! could you help with packing?", "purpose": "Request a quote after approval."}
        captured = {}

        def fake_process(command, **kwargs):
            captured.update(kwargs)
            (Path(kwargs["cwd"]) / "response.json").write_text(
                json.dumps({"body": "A draft is ready for website approval.", "drafts": [draft]}), encoding="utf-8"
            )
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

        with patch.object(worker.subprocess, "run", side_effect=fake_process):
            result = worker.generate_reply(payload, "codex")
        self.assertEqual(result["drafts"], [draft])
        self.assertIn('"coordination": {"plan":', captured["input"])
        self.assertIn('"test_mode": false', captured["input"])
        self.assertIn("The isolated\ngenerator cannot act", captured["input"])
        self.assertIn("Do not use tools. Do not send email", captured["input"])

    def test_shipping_requests_and_check_notes_reach_isolated_generator_as_context(self):
        payload = claim_payload()
        payload["shipping_requests"] = [{"source_url": "https://house.example/lot/17",
            "house_queries": ["site:house.example shipping recommended shippers"]}]
        payload["shipping_research_notes"] = [{"source_url": "https://house.example/lot/17",
            "topic": "storage", "status": "not_checked", "source_refs": [], "detail": "Not checked in this pass."}]
        captured = {}
        def fake_process(command, **kwargs):
            captured.update(kwargs)
            (Path(kwargs["cwd"]) / "response.json").write_text(json.dumps({"body": "Preparing comparable quotes.", "drafts": []}))
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")
        with patch.object(worker.subprocess, "run", side_effect=fake_process):
            worker.generate_reply(payload, "codex")
        context = json.loads(captured["input"].split("SAVED WEBSITE CONTEXT (JSON):\n", 1)[1])
        self.assertEqual(context["research"]["shipping_requests"], payload["shipping_requests"])
        self.assertEqual(context["research"]["shipping_research_notes"], payload["shipping_research_notes"])

    def test_generator_context_deduplicates_current_research_without_mutating_claim(self):
        record = {"source_url": "https://house.example/lot/17", "text": "Observed listing facts."}
        for top_level in (None, [], [record]):
            with self.subTest(top_level=top_level):
                payload = claim_payload()
                payload["coordination"] = {"plan": {"stage": "research"}, "research": [record]}
                if top_level is not None:
                    payload["research"] = top_level
                original = deepcopy(payload)
                contexts = []

                def process(command, **kwargs):
                    contexts.append(json.loads(kwargs["input"].split("SAVED WEBSITE CONTEXT (JSON):\n", 1)[1]))
                    (Path(kwargs["cwd"]) / "response.json").write_text(json.dumps({
                        "body": "Sources are available in the brief.", "drafts": [],
                    }), encoding="utf-8")
                    return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

                with patch.object(worker.subprocess, "run", side_effect=process):
                    worker.generate_reply(payload, "codex")
                self.assertEqual(payload, original)
                self.assertEqual(contexts[0]["coordination"]["plan"], payload["coordination"]["plan"])
                if top_level is None:
                    self.assertEqual(contexts[0]["coordination"]["research"], [record])
                else:
                    self.assertNotIn("research", contexts[0]["coordination"])
                    self.assertEqual(contexts[0]["research"]["previous"], top_level)

    def test_completion_preserves_provider_and_site_check_citations_under_size_pressure(self):
        provider, terms = "https://packer.example/contact", "https://house.example/shipping"
        brief = {"lots": [], "plan": {"source_refs": []}, "shipping": {
            "working_currency": {"source_refs": []}, "actions": [],
            "providers": [{"source_refs": [provider]}], "site_checks": [{"source_refs": [terms]}]}}
        generated = {"body": "Conditional inquiries are prepared.", "drafts": [], "brief": brief}
        evidence = [{"source_url": "https://house.example/lot/17", "final_url": ref,
                     "title": "Observed", "text": text, "source_kind": "public_browser", "error": "",
                     "fetched_at": "2026-10-19T00:00:00Z"}
                    for ref, text in ((provider, "Packer: packer@example.com. Framed-art packing. " + "P" * 500),
                                      (terms, "Release by written authorization; pickup by appointment. " + "T" * 500),
                                      ("https://house.example/other", "😀" * 3000))]
        with patch.object(worker, "MAX_COMPLETION_BYTES", 3000):
            result = worker.completion_payload({"claim_token": "same"}, generated, evidence)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 3000)
        retained = {item["final_url"]: item["text"] for item in result["research"]}
        self.assertEqual(retained[provider], evidence[0]["text"])
        self.assertEqual(retained[terms], evidence[1]["text"])
        self.assertEqual(result["brief"], brief)

    def test_draft_recipient_requires_staff_contact_or_successfully_fetched_evidence(self):
        draft = {"recipient": "packer@example.com", "subject": "inquiry", "body": "hello!", "purpose": "quote request"}
        payload = claim_payload()
        payload.update(test_mode=False, draft_only=True)
        payload["messages"].append({"role": "assistant", "body": "Maybe packer@example.com"})
        with self.assertRaisesRegex(worker.WorkerError, "unverified"):
            worker.validate_drafts([draft], payload)
        payload["source_evidence"] = [{"text": "packer@example.com", "error": "not retrieved"}]
        with self.assertRaisesRegex(worker.WorkerError, "unverified"):
            worker.validate_drafts([draft], payload)
        payload["source_evidence"][0]["error"] = ""
        self.assertEqual(worker.validate_drafts([draft], payload), [draft])
        payload["source_evidence"] = []
        payload["messages"][0]["body"] = "Use packer@example.com"
        self.assertEqual(worker.validate_drafts([draft], payload), [draft])
        payload["test_mode"] = True
        with self.assertRaisesRegex(worker.WorkerError, "Test-mode"):
            worker.validate_drafts([draft], payload)

    def test_quote_provider_contacts_and_pause_flags_match_backend_contract(self):
        draft = {"recipient": "packer@example.com", "subject": "inquiry", "body": "hello!", "purpose": "quote request"}
        payload = claim_payload()
        payload.update(test_mode=False, draft_only=True, coordination={"quotes": [
            {"id": 8, "provider_email": "PACKER@example.com", "provider_name": "Packer",
             "amount": "100.00", "latest_amount": "140.00", "accepted": True,
             "accepted_amount": "100.00", "paused": False, "change_amount": "40.00"},
        ]})
        self.assertEqual(worker.validate_drafts([draft], payload), [draft])
        payload["coordination"]["quotes"][0].update(paused=True, latest_amount="150.00", change_amount="50.00")
        with self.assertRaisesRegex(worker.WorkerError, "paused provider"):
            worker.validate_drafts([draft], payload)

    def test_legacy_test_mode_with_null_coordination_retains_empty_drafts(self):
        payload = claim_payload()
        payload["coordination"] = None
        self.assertEqual(worker.validate_drafts([], payload), [])

    def test_completion_bounds_multilingual_research_without_losing_generated_drafts(self):
        generated = {"body": "😀" * 12000, "drafts": [
            {"recipient": "packer@example.com", "subject": "😀" * 200,
             "body": "😀" * 3000, "purpose": "😀" * 300} for _ in range(3)
        ]}
        evidence = [{"source_url": "https://example.com/" + str(i), "final_url": "https://example.com/" + str(i),
                     "title": "😀" * 300, "text": "😀" * 6000, "error": "", "fetched_at": "2026-10-19T00:00:00Z"}
                    for i in range(8)]
        result = worker.completion_payload({"claim_token": "unchanged"}, generated, evidence)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode("utf-8")), worker.MAX_COMPLETION_BYTES)
        self.assertEqual(result["drafts"], generated["drafts"])
        self.assertEqual(result["body"], generated["body"])
        self.assertEqual(evidence[0]["text"], "😀" * 6000)

    @patch.object(worker.subprocess, "run")
    def test_tool_operation_is_rejected(self, run):
        run.return_value = CompletedProcess([], 0, '\n'.join([
            '{"type":"item.completed","item":{"type":"mcp_tool_call"}}',
            '{"type":"turn.completed"}',
        ]), "")
        with self.assertRaisesRegex(worker.WorkerError, "tool operation"):
            worker.generate_reply(claim_payload(), "codex")

    @patch.object(worker, "generate_reply", return_value={"body": "Model response", "drafts": []})
    def test_one_claim_one_generation_completion_uses_claim_identity(self, generate):
        payload = claim_payload()
        api = Mock()
        api.post.side_effect = [payload, {"reply_id": 42, "already_completed": False}]
        result = worker.run_once(api, "codex", "manual-codex")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["case_id"], payload["case"]["id"])
        self.assertEqual(generate.call_count, 1)
        posted = api.post.call_args_list[1]
        self.assertTrue(posted.kwargs["retry"])
        self.assertEqual(posted.args[1]["claim_token"], payload["job"]["claim_token"])
        self.assertEqual(posted.args[1]["body"], "Model response")

    @patch.object(worker, "generate_reply", side_effect=worker.WorkerError("Codex unavailable."))
    def test_generation_failure_records_safe_error_without_publishing(self, generate):
        payload = claim_payload()
        api = Mock()
        api.post.side_effect = [payload, {"status": "retrying"}]
        with self.assertRaises(worker.WorkerError):
            worker.run_once(api, "codex", "manual-codex")
        self.assertTrue(api.post.call_args_list[1].args[0].endswith("/fail/"))
        self.assertEqual(api.post.call_args_list[1].args[1]["error"], "Codex unavailable.")

    @patch.object(worker, "generate_reply")
    def test_idle_check_does_not_invoke_model(self, generate):
        api = Mock()
        api.post.return_value = {"job": None, "test_mode": True}
        self.assertEqual(worker.run_once(api, "codex", "manual-codex")["status"], "idle")
        generate.assert_not_called()
