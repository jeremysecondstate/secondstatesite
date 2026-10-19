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


COMPLETE_PUBLIC_TEXT = ("Artist: Artist A\nTitle: Work B\nAuction house: Auction Example\nAuction date: October 17, 2026\nLot 17\n"
                       "Oil on canvas. Dimensions 8 x 10 inches. Framed dimensions 12 x 14 inches. "
                       "Condition: good. Sold: USD 100. Auction date: October 17, 2026. "
                       "Location: Auction Example. Pickup within seven days, release after payment. "
                       "Shipping contact shipping@example.com. ")


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
        request = manifest["requests"][0]
        self.assertEqual(request["source_url"], self.url)
        self.assertEqual(request["public_error"], self.public["error"])
        self.assertIn("sold_price", request["missing_fields"])
        self.assertGreaterEqual(len(request["queries"]), 4)
        self.assertEqual(manifest["browser_deadline"], (self.now + timedelta(seconds=420)).isoformat())
        self.assertIn("search", manifest["tool_requirements"])
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
        self.research.return_value = []
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
        self.clock += timedelta(minutes=8)
        self.payload["job"] = None
        self.assertEqual(self.prepare()["status"], "idle")
        self.generate.assert_not_called()

    def test_200_shell_and_short_body_request_fallback(self):
        for text in ("Enable JavaScript " * 30, "Just a moment. Checking your browser. " * 15, "Lot 17"):
            with self.subTest(text=text):
                result = browser.browser_requests([{**self.public, "error": "", "text": text}])
                self.assertEqual(len(result), 1)
                self.assertTrue(result[0]["public_error"])
        request = browser.browser_requests([{**self.public, "error": "", "text": COMPLETE_PUBLIC_TEXT}])[0]
        self.assertEqual(request["public_error"], "")
        self.assertEqual(request["missing_fields"], ["verified_sale_identity"])

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
        self.assertEqual(source["source_kind"], "public_browser")
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
        self.assertEqual(generated_payload["source_evidence"][0], self.public)
        self.assertEqual(generated_payload["source_evidence"][1]["attempts"][0]["status"], "login_required")
        self.assertIn("sign-in", generated_payload["browser_research_notes"][0]["error"])
        self.assertEqual(self.api.post.call_args.args[1]["research"][0], self.public)

    def test_browser_failure_does_not_preserve_challenge_shell_as_facts(self):
        self.public.update(error="", title="Just a moment", text="Checking your browser. Verify you are human.")
        manifest = self.prepare()
        self.complete(manifest, unavailable="challenge")
        record = self.generate.call_args.args[0]["source_evidence"][0]
        self.assertEqual(record["source_kind"], "public_browser")
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
            {"fetched_at": (self.now + timedelta(seconds=421)).isoformat()},
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
        self.assertEqual(manifest["browser_deadline"], (self.now + timedelta(seconds=400)).isoformat())
        self.clock += timedelta(seconds=410)
        def generate(payload, *args):
            self.assertEqual(payload["job"]["lease_expires_at"], self.payload["job"]["lease_expires_at"])
            self.assertEqual(worker.generation_budget(payload), 310)
            return {"body": "Partial findings with the remaining generation allowance.", "drafts": []}
        self.generate.side_effect = generate
        with patch.object(worker, "datetime", wraps=datetime) as worker_datetime:
            worker_datetime.now.return_value = self.clock
            self.assertEqual(self.complete(manifest, unavailable="timeout")["status"], "completed")

    def test_early_research_handoff_allows_longer_generation_without_extending_lease(self):
        manifest = self.prepare()
        self.assertEqual(manifest["browser_deadline"], (self.now + timedelta(seconds=420)).isoformat())
        self.evidence(manifest)
        self.clock += timedelta(seconds=50)
        def generate(payload, *args):
            self.assertEqual(payload["job"]["lease_expires_at"], self.payload["job"]["lease_expires_at"])
            self.assertEqual(worker.generation_budget(payload), 600)
            return {"body": "Fresh sources support these findings.", "drafts": []}
        self.generate.side_effect = generate
        with patch.object(worker, "datetime", wraps=datetime) as worker_datetime:
            worker_datetime.now.return_value = self.clock
            result = self.complete(manifest, evidence_path=manifest["evidence_path"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(sum(call.args[0].endswith("/claim/") for call in self.api.post.call_args_list), 1)

    def test_generation_failure_reports_failure_and_releases_browser(self):
        manifest = self.prepare()
        self.generate.side_effect = worker.WorkerError("Generation unavailable.")
        with self.assertRaises(worker.WorkerError):
            self.complete(manifest, unavailable="unavailable")
        self.assertTrue(self.api.post.call_args.args[0].endswith("/fail/"))
        self.assertFalse((self.directory / ".browser-stage.json").exists())
        state = json.loads(Path(manifest["state_path"]).read_text())
        self.assertIn("observations", state)
        self.assertEqual(state["status"], "failed")

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

    def discovered(self, final="https://market.example/auction-lot/larsen-17", **changes):
        return {"source_url": self.url, "final_url": final, "source_kind": "public_fetch",
                "title": "Artist A, Work B, Lot 17", "text": "Auction Example. Lot 17. Artist A, Work B. Sold: USD 100.",
                "fetched_at": self.now.isoformat(), "error": "", "discovery_method": "search",
                "discovery_query": "Artist A Work B Auction Example October 17 2026 lot 17",
                "discovery_url": "", "match_reason": "Artist, title, house, sale date and lot number match the opened listing.",
                "identity_match": {"artist": "Artist A", "title": "Work B", "auction_house": "Auction Example",
                                   "auction_date": "2026-10-17", "lot_number": "17", "status": "exact"},
                "attempts": [{"method": "search", "query": "Artist A Work B Auction Example lot 17",
                              "url": "", "status": "success", "detail": "Opened a result discovered by web__run.",
                              "observed_at": self.now.isoformat()}], **changes}

    def test_closed_browser_is_not_a_research_dependency_or_website_failure(self):
        manifest = self.prepare()
        self.assertGreater(len(manifest["requests"][0]["queries"]), 1)
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        evidence = {"session_id": manifest["session_id"], "job_id": manifest["job_id"],
                    "records": [self.discovered()]}
        merged = browser.merge_evidence(state, evidence, worker)
        self.assertEqual(merged[0]["source_kind"], "public_fetch")
        self.assertEqual(merged[0]["error"], "")
        failed = browser.merge_evidence(state, None, worker, unavailable="unsupported_browser")[0]
        self.assertIn("website availability was not established", failed["error"])
        self.assertEqual(failed["attempts"][0]["method"], "browser_launch")
        self.assertEqual(failed["attempts"][0]["status"], "tool_unavailable")

    def test_long_successful_excerpt_missing_sold_price_requires_enrichment(self):
        self.public.update(error="", text=COMPLETE_PUBLIC_TEXT.replace("Sold: USD 100.", "Estimate: USD 80-120.") * 8)
        manifest = self.prepare()
        self.assertEqual(manifest["status"], "browser_research_required")
        self.assertEqual(manifest["requests"][0]["public_error"], "")
        self.assertIn("sold_price", manifest["requests"][0]["missing_fields"])
        self.public["text"] = COMPLETE_PUBLIC_TEXT.replace("Sold: USD 100.", "Sold: Sign in to view price.")
        self.assertIn("sold_price", browser.browser_requests([self.public])[0]["missing_fields"])

    def test_complete_price_without_sale_identity_still_requires_outer_verification(self):
        record = {**self.public, "error": "", "text": COMPLETE_PUBLIC_TEXT.replace("Lot 17\n", "")}
        request = browser.browser_requests([record])[0]
        self.assertIn("verified_sale_identity", request["missing_fields"])
        self.assertEqual(request["max_additional_sources"], 5)

    def test_all_parsed_identity_fields_still_require_verified_observation(self):
        self.public.update(error="", text=COMPLETE_PUBLIC_TEXT)
        manifest = self.prepare()
        self.assertEqual(manifest["status"], "browser_research_required")
        request = manifest["requests"][0]
        self.assertTrue(all(request["expected_identity"].values()))
        self.assertEqual(request["missing_fields"], ["verified_sale_identity"])
        self.generate.assert_not_called()

    def test_complete_exact_lot_still_prepares_grouped_shipping_discovery(self):
        self.public.update(error="", text=COMPLETE_PUBLIC_TEXT, source_kind="public_fetch",
                           identity_match={"status": "exact"})
        second = {**self.public, "source_url": "https://auction.example/lot/18", "final_url": "https://auction.example/lot/18"}
        self.research.return_value = [self.public, second]
        manifest = self.prepare()
        self.assertEqual(manifest["status"], "browser_research_required")
        self.assertEqual(manifest["requests"][0]["missing_fields"], [])
        self.assertTrue(manifest["requests"][0]["shipping_research"])
        self.assertEqual(len(manifest["shipping_requests"]), 1)
        shipping = manifest["shipping_requests"][0]
        self.assertEqual(shipping["related_source_urls"], [self.url, second["source_url"]])
        self.assertIn("third_party_release", shipping["check_topics"])
        self.assertIn("glazing", shipping["lot_handling_checks"])
        self.assertTrue(shipping["house_queries"])
        self.assertEqual(manifest["budget"]["reserved_shipping_attempts"], 1)
        self.assertEqual(manifest["budget"]["research_seconds"], 420)
        self.generate.assert_not_called()

    def test_marketplace_lots_from_different_houses_do_not_share_house_checks_or_memory(self):
        records = [{"source_url": f"https://www.invaluable.com/auction-lot/work-{number}", "error": "",
                    "text": f"Auction house: {house}\nLocation: Scottsdale, AZ\n"}
                   for number, house in ((1, "First House"), (2, "Second House"))]
        requests = browser.shipping_requests(records)
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(not item["house_memory_enabled"] for item in requests))
        self.assertIn("First House official", requests[0]["house_queries"][0])
        self.assertIn("Second House official", requests[1]["house_queries"][0])

    def test_shipping_checks_validate_opened_evidence_and_persist_bounded_history(self):
        manifest = self.prepare()
        policy = self.discovered("https://auction.example/shipping", source_kind="public_browser",
            text="Pickup by appointment. Third-party release requires authorization. shipping@auction.example.",
            identity_match={"status": "context", "auction_house": "Auction Example"})
        check = {"source_url": self.url, "topic": "third_party_release", "status": "found",
                 "source_refs": [policy["final_url"]], "detail": "Published authorization form applies.",
                 "observed_at": self.now.isoformat()}
        evidence = {"session_id": manifest["session_id"], "job_id": manifest["job_id"],
                    "records": [policy], "shipping_checks": [check]}
        Path(manifest["evidence_path"]).write_text(json.dumps(evidence), encoding="utf-8")
        self.complete(manifest, evidence_path=manifest["evidence_path"])
        payload = self.generate.call_args.args[0]
        checks = {item["topic"]: item for item in payload["shipping_research_notes"]}
        self.assertEqual(checks["third_party_release"]["status"], "found")
        self.assertEqual(checks["storage"]["status"], "not_checked")
        summary = payload["source_evidence"][0]["attempts"][-1]
        self.assertIn("third_party_release=found", summary["detail"])
        self.assertIn("storage=not_checked", summary["detail"])
        self.assertLessEqual(len(summary["detail"]), 300)
        memory = json.loads((self.directory / ".house-research-memory.json").read_text())
        self.assertEqual(memory["houses"]["auction.example"]["reopen_urls"], [policy["final_url"]])
        self.assertNotIn(policy["text"], json.dumps(memory))
        self.assertNotIn(self.payload["job"]["case_id"], json.dumps(memory))

    def test_shipping_checks_reject_snippets_unopened_refs_stale_and_unsearched_absence(self):
        manifest = self.prepare()
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        record = self.discovered(source_kind="search_only", identity_match={"status": "unverified"})
        check = {"source_url": self.url, "topic": "pickup", "status": "found",
                 "source_refs": [record["final_url"]], "detail": "Claimed fact", "observed_at": self.now.isoformat()}
        with self.assertRaisesRegex(worker.WorkerError, "opened sources"):
            browser._shipping_checks(state, {"shipping_checks": [check]}, [record], worker)
        opened = self.discovered()
        for changes in ({"source_refs": ["https://unopened.example/policy"]},
                        {"observed_at": (self.now - timedelta(seconds=1)).isoformat()},
                        {"topic": "private_destination"}, {"source_url": []}):
            with self.subTest(changes=changes), self.assertRaises(worker.WorkerError):
                browser._shipping_checks(state, {"shipping_checks": [{**check, **changes}]}, [opened], worker)
        missing = {**check, "status": "not_found", "source_refs": []}
        with self.assertRaisesRegex(worker.WorkerError, "actual bounded research"):
            browser._shipping_checks(state, {"shipping_checks": [missing]}, [self.public], worker)

    def test_house_memory_is_public_reopen_leads_only_and_expires(self):
        cache = {"version": 1, "houses": {"auction.example": {"checked_at": self.now.isoformat(),
                 "reopen_urls": ["https://auction.example/shipping", "https://provider.example/contact",
                                 "https://auction.example/account/invoice", "https://auction.example/shipping?secret=token",
                                 self.url, "https://127.1/private"], "checks": {"storage": "not_found"}}}}
        (self.directory / ".house-research-memory.json").write_text(json.dumps(cache))
        manifest = self.prepare()
        memory = manifest["shipping_requests"][0]["previous_public_checks"]
        self.assertEqual(memory["reopen_urls"], ["https://auction.example/shipping", "https://provider.example/contact"])
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        self.assertEqual(state["payload"]["source_evidence"], [self.public])
        self.assertNotIn("previous_public_checks", state["shipping_requests"][0])
        self.clock += timedelta(days=31)
        self.assertEqual(browser._memory_entries(self.directory, worker), {})

    def test_v2_prepared_state_remains_valid_after_shipping_manifest_upgrade(self):
        manifest = self.prepare()
        path = Path(manifest["state_path"])
        state = json.loads(path.read_text())
        state["version"] = 2
        state.pop("shipping_requests")
        for request in state["requests"]:
            request.pop("shipping_research", None)
        path.write_text(json.dumps(state))
        self.assertEqual(browser._load_state(path, self.api, worker)["version"], 2)

    def test_multiple_alternate_sources_preserve_direct_facts_and_specific_provenance(self):
        self.public.update(error="", text="Dimensions: 8 x 10 inches. Condition: good. " * 8)
        manifest = self.prepare()
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        record = self.discovered()
        shipping = self.discovered("https://auction.example/shipping", discovery_method="link", discovery_query="",
                                   discovery_url=record["final_url"], text="Pickup within seven days; shipping@auction.example.",
                                   identity_match={"status": "context", "auction_house": "Auction Example"},
                                   match_reason="Published shipping terms linked from the exact listing.")
        merged = browser.merge_evidence(state, {"session_id": manifest["session_id"], "job_id": manifest["job_id"],
                                               "records": [record, shipping]}, worker)
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0]["text"], self.public["text"])
        self.assertEqual(merged[1]["discovery_query"], record["discovery_query"])
        self.assertEqual(merged[2]["discovery_url"], record["final_url"])

    def test_same_page_listing_and_terms_remain_separate_validated_observations(self):
        manifest = self.prepare()
        listing = self.discovered(self.url, source_kind="public_browser", discovery_method="direct",
                                  discovery_query="", text="Artist A. Work B. Lot 17. Dimensions: 8 x 10 inches.")
        terms = self.discovered(self.url, source_kind="public_browser", title="Full auction terms",
            text="Contextual comparison only: Sold: $450.00. Pickup within five days.",
            discovery_query="Auction Example full sale terms", match_reason="Sale terms modal opened on the exact lot page.",
            identity_match={"status": "context", "auction_house": "Auction Example", "auction_date": "2026-10-17"})
        evidence = {"session_id": manifest["session_id"], "job_id": manifest["job_id"], "records": [listing, terms]}
        Path(manifest["evidence_path"]).write_text(json.dumps(evidence), encoding="utf-8")
        self.assertEqual(self.complete(manifest, evidence_path=manifest["evidence_path"])["status"], "completed")
        merged = self.generate.call_args.args[0]["source_evidence"]
        self.assertEqual(len(merged), 2)
        self.assertEqual([record["text"] for record in merged], [listing["text"], terms["text"]])
        self.assertEqual([record["identity_match"]["status"] for record in merged], ["exact", "context"])
        self.assertEqual(merged[1]["discovery_query"], terms["discovery_query"])
        browser.provenance.validate_research_bounds(merged)
        from scripts.coordinate_brief_contract import _price_supported
        price = {"kind": "sold", "basis": "unknown", "label": "Sold", "amount": "450.00",
                 "amount_high": "", "currency": "", "evidence_quote": "Sold: $450.00", "source_refs": [self.url]}
        observations = {self.url: {"observations": [{"kind": item["source_kind"], "text": item["text"],
                        "identity_match": item["identity_match"]} for item in merged]}}
        with self.assertRaisesRegex(ValueError, "matching this sale"):
            _price_supported(price, listing["identity_match"], observations)
        self.assertEqual(self.complete(manifest)["status"], "completed")
        self.assertEqual(self.generate.call_count, 1)

    def test_same_status_duplicate_stays_strict_and_context_does_not_bypass_validation(self):
        manifest = self.prepare()
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        listing = self.discovered()
        evidence = {"session_id": manifest["session_id"], "job_id": manifest["job_id"], "records": [listing, deepcopy(listing)]}
        with self.assertRaises(worker.WorkerError):
            browser.merge_evidence(state, evidence, worker)
        with self.assertRaises(ValueError):
            browser.provenance.validate_research_bounds(evidence["records"])
        for changes in ({"fetched_at": (self.now - timedelta(seconds=1)).isoformat()},
                        {"final_url": "https://127.1/terms"},
                        {"text": "x" * 6001},
                        {"error": "Blocked but listing facts still present"}):
            context = self.discovered(identity_match={"status": "context", "auction_house": "Auction Example"})
            context.update(changes)
            with self.subTest(changes=list(changes)), self.assertRaises(worker.WorkerError):
                browser.merge_evidence(state, {**evidence, "records": [listing, context]}, worker)
        self.assertEqual(browser.provenance.research_identity_key({"source_url": self.url}),
                         (self.url, "", "public", "unverified"))

    def test_wrong_year_and_lot_rejected_but_historical_label_can_be_retained(self):
        self.public.update(error="", text="Artist: Artist A\nTitle: Work B\nAuction house: Auction Example\nAuction date: October 17, 2026\nLot 17\n")
        manifest = self.prepare()
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        for field, wrong in (("auction_date", "2025-10-17"), ("lot_number", "18"), ("title", "Unrelated Work")):
            record = self.discovered()
            record["identity_match"][field] = wrong
            evidence = {"session_id": manifest["session_id"], "job_id": manifest["job_id"], "records": [record]}
            with self.subTest(field=field), self.assertRaises(worker.WorkerError):
                browser.merge_evidence(state, evidence, worker)
            record["identity_match"]["status"] = "historical"
            self.assertEqual(browser.merge_evidence(state, evidence, worker)[1]["identity_match"]["status"], "historical")

    def test_one_of_two_lots_succeeds_without_discarding_partial_evidence(self):
        second_url = "https://auction.example/lot/18"
        self.research.return_value = [self.public, {**self.public, "source_url": second_url, "final_url": second_url}]
        manifest = self.prepare()
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        merged = browser.merge_evidence(state, {"session_id": manifest["session_id"], "job_id": manifest["job_id"],
                                               "records": [self.discovered()]}, worker)
        self.assertEqual(len(merged), 2)
        self.assertTrue(merged[0]["text"])
        self.assertFalse(merged[0]["error"])
        self.assertEqual(merged[1]["source_url"], second_url)
        self.assertTrue(merged[1]["error"])

    def test_search_only_and_historical_contacts_cannot_authorize_draft_recipients(self):
        draft = {"recipient": "packer@example.com", "subject": "packing", "body": "hello", "purpose": "quote"}
        for kind, status in (("search_only", "unverified"), ("public_fetch", "historical")):
            self.payload["source_evidence"] = [self.discovered(source_kind=kind, text="packer@example.com",
                                                               identity_match={"status": status})]
            with self.subTest(kind=kind), self.assertRaisesRegex(worker.WorkerError, "unverified"):
                worker.validate_drafts([draft], self.payload)

    def test_no_research_completion_is_durable_before_post_and_replayed_after_restart(self):
        self.research.return_value = []
        calls = []
        def post(path, payload, **kwargs):
            calls.append(path)
            if path.endswith("/claim/"):
                return deepcopy(self.payload)
            if path.endswith("/complete/"):
                raise worker.APIError(503)
            return {"status": "retrying"}
        self.api.post.side_effect = post
        with self.assertRaises(worker.APIError):
            self.prepare()
        saved = [json.loads(path.read_text()) for path in self.directory.glob("*.json")]
        self.assertEqual(saved[0]["status"], "generated")
        self.api.post.side_effect = self.api_post
        self.assertEqual(self.prepare()["status"], "completed")
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(sum(path.endswith("/claim/") for path in calls), 1)

    def test_attempts_are_session_fresh_and_per_lot_budget_includes_direct_excerpt(self):
        self.public.update(error="", text="Condition: good. Dimensions: 8 x 10 inches.")
        manifest = self.prepare()
        state = browser._load_state(Path(manifest["state_path"]), self.api, worker)
        record = self.discovered()
        record["attempts"][0]["observed_at"] = (self.now - timedelta(seconds=1)).isoformat()
        evidence = {"session_id": manifest["session_id"], "job_id": manifest["job_id"], "records": [record]}
        with self.assertRaisesRegex(worker.WorkerError, "provenance"):
            browser.merge_evidence(state, evidence, worker)
        evidence["records"] = [self.discovered(f"https://market.example/lot/{i}") for i in range(6)]
        merged = browser.merge_evidence(state, evidence, worker)
        self.assertEqual(len(merged), 6)
        self.assertEqual(merged[0]["text"], self.public["text"])
        self.assertTrue(any("omitted 1" in attempt["detail"] for item in merged for attempt in item.get("attempts", [])))
        evidence["records"].pop()
        self.assertEqual(len(browser.merge_evidence(state, evidence, worker)), 6)
