"""Staged browser handoff tests; no browser, website, model, or network is used."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from scripts import coordinate_browser_research as browser
from scripts import coordinate_worker as worker
from .tests_coordinate_worker import claim_payload


class CoordinateBrowserWorkerTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.now = datetime.now(timezone.utc)
        self.clock = self.now
        clock = patch.object(browser, "_now", side_effect=lambda: self.clock)
        clock.start()
        self.addCleanup(clock.stop)
        self.payload = claim_payload()
        self.payload.update(test_mode=False, draft_only=True, research_enabled=True)
        self.payload["job"]["lease_expires_at"] = (self.now + timedelta(minutes=15)).isoformat()
        self.url = "https://auction.example/lot/17-larsen"
        self.payload["messages"][0]["body"] = "Please research " + self.url
        self.public = {"source_url": self.url, "final_url": self.url, "title": "", "text": "",
                       "error": "The public page returned HTTP 403.", "fetched_at": self.now.isoformat()}
        self.api = Mock(base_url="https://secondstate.example")
        self.api.post.side_effect = self.api_post
        self.research = patch.object(worker, "research_messages", return_value=[self.public]).start()
        self.generate = patch.object(worker, "generate_reply", return_value={"body": "A cited listing reply.", "drafts": []}).start()
        self.addCleanup(patch.stopall)

    def api_post(self, path, payload, **kwargs):
        if path.endswith("/claim/"):
            return deepcopy(self.payload)
        if path.endswith("/complete/"):
            return {"reply_id": 42, "already_completed": False}
        if path.endswith("/fail/"):
            return {"status": "retrying"}
        self.fail("Unexpected API route")

    def prepare(self):
        return browser.prepare(self.api, "codex", "manual-codex", "gpt-6-astra", "ultra",
                               state_dir=self.directory, worker=worker)

    def evidence(self, manifest, **changes):
        record = {"source_url": self.url, "final_url": "https://www.invaluable.com/auction-lot/larsen-17-c-abc",
                  "title": "Lot 17, Larsen", "text": "Lot 17: Larsen. Sheet 8 x 10 inches. Framed. Auction Example.",
                  "error": "", "fetched_at": self.now.isoformat()}
        record.update(changes)
        evidence = {"session_id": manifest["session_id"], "job_id": manifest["job_id"], "records": [record]}
        Path(manifest["evidence_path"]).write_text(json.dumps(evidence), encoding="utf-8")
        return evidence

    def complete(self, manifest, **kwargs):
        return browser.complete(self.api, "codex", manifest["state_path"], worker=worker, **kwargs)

    def test_prepare_exposes_only_bounded_manifest_and_keeps_secrets_out(self):
        with patch.dict("os.environ", {"COORDINATE_WORKER_TOKEN": "website-secret"}):
            manifest = self.prepare()
        self.assertEqual(manifest["status"], "browser_research_required")
        self.assertEqual(manifest["requests"], [{"source_url": self.url, "public_error": self.public["error"]}])
        self.assertEqual(manifest["browser_deadline"], (self.now + timedelta(seconds=180)).isoformat())
        serialized = json.dumps(manifest)
        for value in (self.payload["job"]["claim_token"], "Retain the mat", "website-secret", "Please research"):
            self.assertNotIn(value, serialized)
        state = Path(manifest["state_path"]).read_text(encoding="utf-8")
        self.assertNotIn("website-secret", state)
        self.assertEqual(self.api.post.call_count, 1)
        self.generate.assert_not_called()

    def test_browser_success_merges_provenance_and_completes_original_claim_once(self):
        manifest = self.prepare()
        self.evidence(manifest)
        result = self.complete(manifest, evidence_path=manifest["evidence_path"])
        self.assertEqual(result["status"], "completed")
        context = self.generate.call_args.args[0]
        source = context["source_evidence"][0]
        self.assertEqual(source["source_kind"], "browser")
        self.assertEqual(source["public_error"], self.public["error"])
        self.assertEqual(source["error"], "")
        self.assertIn("8 x 10", source["text"])
        self.assertEqual(self.generate.call_args.args[2:], ("gpt-6-astra", "ultra"))
        completion = self.api.post.call_args.args[1]
        self.assertEqual(completion["claim_token"], self.payload["job"]["claim_token"])
        self.assertEqual(completion["research"], context["source_evidence"])
        self.assertFalse((self.directory / ".browser-stage.json").exists())
        self.assertEqual(self.complete(manifest), result)
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(self.api.post.call_count, 2)

    def test_no_candidate_keeps_public_flow_and_research_flags(self):
        self.research.return_value = [{**self.public, "error": "", "text": "A complete listing. " * 25}]
        self.assertEqual(self.prepare()["status"], "completed")
        self.assertEqual(self.generate.call_args.args[0]["source_evidence"], self.research.return_value)
        self.payload["test_mode"] = True
        self.research.reset_mock()
        self.assertEqual(self.prepare()["status"], "completed")
        self.research.assert_not_called()

    def test_prepare_requires_all_research_capability_flags(self):
        for change in ({"research_enabled": False}, {"test_mode": True}):
            with self.subTest(change=change):
                self.payload.update(change)
                self.research.reset_mock()
                self.assertEqual(self.prepare()["status"], "completed")
                self.research.assert_not_called()

    def test_idle_and_browser_busy_do_not_generate_or_claim_twice(self):
        self.prepare()
        self.assertEqual(self.prepare()["status"], "browser_busy")
        self.assertEqual(self.api.post.call_count, 1)
        self.generate.assert_not_called()
        self.clock += timedelta(minutes=4)
        self.payload["job"] = None
        self.assertEqual(self.prepare()["status"], "idle")
        self.generate.assert_not_called()

    def test_200_shell_and_short_body_request_fallback(self):
        for text in ("Enable JavaScript " * 30, "Just a moment. Checking your browser. " * 15, "Lot 17"):
            with self.subTest(text=text):
                result = browser.browser_requests([{**self.public, "error": "", "text": text}])
                self.assertEqual(len(result), 1)
                self.assertTrue(result[0]["public_error"])
        self.assertEqual(browser.browser_requests([{**self.public, "error": "", "text": "Valid lot details. " * 30}]), [])

    def test_unsafe_sources_never_enter_browser_manifest(self):
        for url in ("http://localhost/lot", "http://127.0.0.1/lot", "https://auction.internal/lot",
                    "https://user:secret@example.com/lot", "file:///secret", "https://example.com:444/lot",
                    "https://example.com\\@evil.test/lot", "https://example.com/\nlot"):
            with self.subTest(url=url):
                self.assertEqual(browser.browser_requests([{**self.public, "source_url": url}]), [])
        self.assertEqual(browser.browser_requests([{**self.public, "error": "The source resolves to a non-public or reserved address."}]), [])

    def test_browser_unavailable_retains_failure_provenance_without_listing_facts(self):
        manifest = self.prepare()
        self.complete(manifest, unavailable="login_required")
        source = self.generate.call_args.args[0]["source_evidence"][0]
        self.assertEqual(source["source_kind"], "browser")
        self.assertEqual(source["public_error"], self.public["error"])
        self.assertEqual(source["text"], "")
        self.assertIn("sign-in", source["error"])

    def test_missing_requested_record_gets_explicit_unavailable(self):
        manifest = self.prepare()
        evidence = {"session_id": manifest["session_id"], "job_id": manifest["job_id"], "records": []}
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        merged = browser.merge_evidence(state, evidence, worker)
        self.assertIn("did not return evidence", merged[0]["error"])
        self.assertEqual(merged[0]["text"], "")

    def test_browser_failure_preserves_useful_short_public_excerpt(self):
        self.public.update(error="", title="Lot 17", text="Dimensions: 8 x 10 inches. Pickup Friday.")
        manifest = self.prepare()
        self.complete(manifest, unavailable="login_required")
        generated_payload = self.generate.call_args.args[0]
        self.assertEqual(generated_payload["source_evidence"], [self.public])
        self.assertIn("sign-in", generated_payload["browser_research_notes"][0]["error"])
        self.assertEqual(self.api.post.call_args.args[1]["research"], [self.public])

    def test_browser_failure_does_not_preserve_challenge_shell_as_facts(self):
        self.public.update(error="", title="Just a moment", text="Checking your browser. Verify you are human.")
        manifest = self.prepare()
        self.complete(manifest, unavailable="challenge")
        record = self.generate.call_args.args[0]["source_evidence"][0]
        self.assertEqual(record["source_kind"], "browser")
        self.assertEqual(record["text"], "")

    def test_standard_http_original_can_recover_via_same_https_host(self):
        self.url = "http://auction.example/lot/17-larsen"
        self.public.update(source_url=self.url, final_url=self.url)
        manifest = self.prepare()
        self.evidence(manifest, final_url="https://www.auction.example/lot/17-larsen")
        self.assertEqual(self.complete(manifest, evidence_path=manifest["evidence_path"])["status"], "completed")

    def test_validation_rejects_foreign_urls_schemes_duplicates_failed_facts_and_large_text(self):
        manifest = self.prepare()
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        original = self.evidence(manifest)
        changes = [
            {"source_url": "https://unrequested.example/lot"}, {"source_url": []},
            {"final_url": "https://unrelated.example/lot"}, {"final_url": "https://invaluable.com.evil.test/lot"},
            {"final_url": "http://auction.example/lot"}, {"final_url": "https://user@invaluable.com/lot"},
            {"final_url": "https://invaluable.com:444/lot"}, {"final_url": ""},
            {"text": ""}, {"text": "x" * 6001}, {"error": "Blocked", "title": "", "text": "Claimed facts"},
            {"fetched_at": (self.now - timedelta(seconds=1)).isoformat()},
            {"fetched_at": (self.now + timedelta(seconds=181)).isoformat()},
            {"fetched_at": self.now.replace(tzinfo=None).isoformat()},
        ]
        for change in changes:
            evidence = deepcopy(original)
            evidence["records"][0].update(change)
            with self.subTest(change=change), self.assertRaises(worker.WorkerError):
                browser.merge_evidence(state, evidence, worker)
        for field in ("session_id", "job_id"):
            evidence = {**original, field: str(uuid4())}
            with self.subTest(field=field), self.assertRaises(worker.WorkerError):
                browser.merge_evidence(state, evidence, worker)
        with self.assertRaises(worker.WorkerError):
            browser.merge_evidence(state, {**original, "records": original["records"] * 2}, worker)

    def test_invalid_evidence_fails_claim_without_generation_or_new_claim(self):
        manifest = self.prepare()
        self.evidence(manifest, final_url="https://unrelated.example/lot")
        with self.assertRaises(worker.WorkerError):
            self.complete(manifest, evidence_path=manifest["evidence_path"])
        self.generate.assert_not_called()
        self.assertTrue(self.api.post.call_args.args[0].endswith("/fail/"))
        self.assertFalse((self.directory / ".browser-stage.json").exists())
        with self.assertRaisesRegex(worker.WorkerError, "session failed"):
            self.complete(manifest, unavailable="unavailable")
        self.assertEqual(self.api.post.call_count, 2)

    def test_stale_claim_rejects_before_generation_and_does_not_claim_new_work(self):
        manifest = self.prepare()
        self.clock += timedelta(minutes=16)
        with self.assertRaisesRegex(worker.WorkerError, "too little claim time"):
            self.complete(manifest, unavailable="timeout")
        self.generate.assert_not_called()
        self.assertEqual(sum(call.args[0].endswith("/claim/") for call in self.api.post.call_args_list), 1)

    def test_mismatched_saved_job_or_api_origin_is_rejected(self):
        manifest = self.prepare()
        state_path = Path(manifest["state_path"])
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["job_id"] = str(uuid4())
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(worker.WorkerError, "prepared job"):
            self.complete(manifest, unavailable="unavailable")
        self.assertEqual(self.api.post.call_count, 1)

    def test_browser_stage_is_released_before_isolated_generation(self):
        manifest = self.prepare()
        def generate(*args):
            self.assertFalse((self.directory / ".browser-stage.json").exists())
            with self.assertRaises(worker.WorkerError):
                with browser._file_lock(Path(manifest["state_path"]).with_suffix(".lock"), worker):
                    self.fail("Session lock must remain held during generation")
            return {"body": "Generated safely", "drafts": []}
        self.generate.side_effect = generate
        self.complete(manifest, unavailable="unavailable")

    def test_ambiguous_completion_replays_persisted_payload_without_regeneration(self):
        manifest = self.prepare()
        completions = []
        def post(path, payload, **kwargs):
            self.assertTrue(path.endswith("/complete/"))
            completions.append(deepcopy(payload))
            state = json.loads(Path(manifest["state_path"]).read_text(encoding="utf-8"))
            self.assertEqual(state["completion"], payload)
            if len(completions) == 1:
                raise worker.APIError(503)
            return {"reply_id": 42, "already_completed": True}
        self.api.post.side_effect = post
        with self.assertRaises(worker.APIError):
            self.complete(manifest, unavailable="unavailable")
        result = self.complete(manifest)
        self.assertTrue(result["already_completed"])
        self.assertEqual(completions[0], completions[1])
        self.assertEqual(self.generate.call_count, 1)

    def test_next_scheduled_prepare_recovers_ambiguous_completion_without_claiming(self):
        manifest = self.prepare()
        self.api.post.side_effect = worker.APIError(503)
        with self.assertRaises(worker.APIError):
            self.complete(manifest, unavailable="unavailable")
        self.api.post.reset_mock()
        self.api.post.side_effect = self.api_post
        result = self.prepare()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.api.post.call_count, 1)
        self.assertTrue(self.api.post.call_args.args[0].endswith("/complete/"))
        self.assertEqual(self.generate.call_count, 1)

    def test_stale_generated_completion_does_not_prevent_next_claim(self):
        manifest = self.prepare()
        self.api.post.side_effect = worker.APIError(503)
        with self.assertRaises(worker.APIError):
            self.complete(manifest, unavailable="unavailable")
        self.api.post.reset_mock()
        def post(path, payload, **kwargs):
            if path.endswith("/complete/") or path.endswith("/fail/"):
                raise worker.APIError(409)
            return {"job": None, "test_mode": False, "draft_only": True}
        self.api.post.side_effect = post
        self.assertEqual(self.prepare()["status"], "idle")
        state = json.loads(Path(manifest["state_path"]).read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")
        self.assertEqual(self.api.post.call_args.args[0], "/coordinate/api/claim/")

    def test_definitively_invalid_completion_fails_claim_instead_of_replaying_forever(self):
        manifest = self.prepare()
        def post(path, payload, **kwargs):
            if path.endswith("/complete/"):
                raise worker.APIError(400)
            return {"status": "retrying"}
        self.api.post.side_effect = post
        with self.assertRaises(worker.APIError):
            self.complete(manifest, unavailable="unavailable")
        state = json.loads(Path(manifest["state_path"]).read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")
        self.assertTrue(self.api.post.call_args.args[0].endswith("/fail/"))

    def test_browser_deadline_reserves_assembly_generation_and_full_api_retry_budget(self):
        self.payload["job"]["lease_expires_at"] = (self.now + timedelta(seconds=820)).isoformat()
        manifest = self.prepare()
        self.assertEqual(manifest["browser_deadline"], (self.now + timedelta(seconds=100)).isoformat())
        self.clock += timedelta(seconds=110)
        self.assertEqual(self.complete(manifest, unavailable="timeout")["status"], "completed")

    def test_generation_failure_reports_failure_and_releases_browser(self):
        manifest = self.prepare()
        self.generate.side_effect = worker.WorkerError("Generation unavailable.")
        with self.assertRaises(worker.WorkerError):
            self.complete(manifest, unavailable="unavailable")
        self.assertTrue(self.api.post.call_args.args[0].endswith("/fail/"))
        self.assertFalse((self.directory / ".browser-stage.json").exists())

    def test_completion_size_preserves_browser_contract_and_draft_contact_evidence(self):
        draft = {"recipient": "packer@example.com", "subject": "😀" * 200,
                 "body": "😀" * 3000, "purpose": "😀" * 300}
        generated = {"body": "😀" * 12000, "drafts": [draft] * 3}
        evidence = [{"source_url": "https://example.com/" + str(i) + "x" * 1900,
                     "final_url": "https://example.com/" + str(i) + "x" * 1900,
                     "title": "😀" * 300, "text": "😀" * 5900 + " packer@example.com",
                     "fetched_at": self.now.isoformat(), "error": "", "source_kind": "browser",
                     "public_error": self.public["error"]} for i in range(8)]
        completion = worker.completion_payload({"claim_token": "unchanged"}, generated, evidence)
        self.assertLessEqual(len(json.dumps(completion, ensure_ascii=False).encode()), worker.MAX_COMPLETION_BYTES)
        self.assertTrue(all(item["text"] for item in completion["research"]))
        self.assertTrue(any("packer@example.com" in item["text"] for item in completion["research"]))
        self.assertEqual(completion["drafts"], generated["drafts"])

    def test_prior_successful_browser_contact_remains_valid_for_followup_drafts(self):
        draft = {"recipient": "packer@example.com", "subject": "packing", "body": "hello", "purpose": "quote"}
        self.payload["research"] = [{"source_kind": "browser", "text": "Contact packer@example.com", "error": ""}]
        self.payload["source_evidence"] = [{"source_kind": "browser", "text": "", "error": "Login required"}]
        self.assertEqual(worker.validate_drafts([draft], self.payload), [draft])
        self.payload["research"][0]["error"] = "Unavailable"
        with self.assertRaisesRegex(worker.WorkerError, "unverified"):
            worker.validate_drafts([draft], self.payload)

    def test_cli_routes_prepare_without_changing_default_generator_configuration(self):
        with patch.object(worker.sys, "argv", ["coordinate_worker.py", "--prepare-browser-research",
                                               "--browser-state-dir", str(self.directory)]), \
                patch.object(worker.shutil, "which", return_value="codex"), \
                patch.object(worker, "CoordinateAPI", return_value=self.api), \
                patch.object(worker.sys, "stdout", new_callable=StringIO) as output:
            self.assertEqual(worker.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "browser_research_required")
        command = worker.codex_command("codex", self.directory, None)
        self.assertIn("computer_use", command)
        self.assertIn("browser_use", command)
        self.assertIn("mcp_servers={}", command)
        self.assertIn("--ignore-user-config", command)
