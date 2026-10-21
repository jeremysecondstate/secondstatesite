"""Local Inventory handoffs survive ambiguous network outcomes without replaying work."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from uuid import uuid4

from scripts import inventory_worker as worker


def claim_response():
    return {
        "status": "claimed",
        "job": {
            "id": str(uuid4()), "case_id": str(uuid4()), "message_id": 41,
            "claim_token": str(uuid4()), "lease_expires_at": "2026-10-21T18:00:00+00:00",
            "status": "processing",
        },
        "messages": [{"id": 41, "role": "staff", "body": "We won Example Auctions lot 7."}],
    }


class InventoryHandoffTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.api = Mock(base_url="https://secondstate.art")
        self.claim = claim_response()

    def prepare(self):
        self.api.post.return_value = self.claim
        result = worker.prepare(self.api, self.root)
        self.api.post.reset_mock()
        return Path(result["state_file"])

    def result_file(self):
        path = self.root / "result.json"
        worker.write_json(path, {"body": "Added four researched lots.", "result": {"rows": [28, 29, 30, 31]}})
        return path

    def test_lost_claim_response_reuses_durable_request_identity(self):
        self.api.post.side_effect = worker.InventoryError("Connection interrupted.")
        with self.assertRaises(worker.InventoryError):
            worker.prepare(self.api, self.root)
        first_request = deepcopy(self.api.post.call_args.args[1])
        pointer = worker.read_json(self.root / "active.json")
        saved = worker.read_json(self.root / (pointer["request_id"] + ".json"))
        self.assertEqual(saved["request_id"], first_request["request_id"])
        self.assertNotIn("claim", saved)

        self.api.post.side_effect = None
        self.api.post.return_value = self.claim
        result = worker.prepare(self.api, self.root)
        self.assertEqual(self.api.post.call_args.args[1], first_request)
        self.assertEqual(result["status"], "inventory_work_required")
        self.assertEqual(worker.read_json(Path(result["state_file"]))["claim"], self.claim)

    def test_existing_claim_resumes_without_claiming_another_job(self):
        path = self.prepare()
        self.api.post.return_value = {"job": {"status": "processing"}}
        result = worker.prepare(self.api, self.root)
        self.assertEqual(result["status"], "inventory_resume_required")
        self.assertEqual(result["state_file"], str(path))
        self.api.post.assert_called_once_with(worker.endpoint(worker.read_json(path), "status"),
                                              worker.claim_fields(worker.read_json(path)))

    def test_completed_claim_is_archived_before_next_request(self):
        path = self.prepare()
        self.api.post.return_value = {"job": {"status": "completed"}, "body": "Done", "result": {"rows": [28]}}
        result = worker.prepare(self.api, self.root)
        self.assertEqual(result["status"], "previous_completed")
        self.assertFalse((self.root / "active.json").exists())
        self.assertEqual(worker.read_json(path.with_suffix(".status.json"))["result"], {"rows": [28]})

    def test_expired_claim_recovery_does_not_resume_work_under_old_lease(self):
        self.api.post.side_effect = worker.InventoryError("Connection interrupted.")
        with self.assertRaises(worker.InventoryError):
            worker.prepare(self.api, self.root)
        first_request_id = self.api.post.call_args.args[1]["request_id"]
        self.api.post.side_effect = None
        self.claim["job"]["status"] = "expired"
        self.api.post.return_value = self.claim
        result = worker.prepare(self.api, self.root)
        self.assertEqual(self.api.post.call_args.args[1]["request_id"], first_request_id)
        self.assertEqual(result["status"], "previous_expired")
        self.assertFalse((self.root / "active.json").exists())
        self.assertTrue(Path(result["state_file"]).with_suffix(".status.json").exists())

    def test_unknown_saved_job_status_retains_handoff_and_does_not_start_other_work(self):
        self.prepare()
        self.api.post.return_value = {"job": {"status": "unrecognized"}}
        with self.assertRaises(worker.InventoryError):
            worker.prepare(self.api, self.root)
        self.assertTrue((self.root / "active.json").exists())
        self.assertEqual(self.api.post.call_count, 1)

    def test_explicit_idle_clears_pointer_but_unknown_claim_response_does_not(self):
        self.api.post.return_value = {"job": None}
        self.assertEqual(worker.prepare(self.api, self.root), {"status": "idle"})
        self.assertFalse((self.root / "active.json").exists())
        self.api.post.return_value = {"error": "Unexpected server result"}
        with self.assertRaises(worker.InventoryError):
            worker.prepare(self.api, self.root)
        self.assertTrue((self.root / "active.json").exists())

    def test_different_origin_cannot_receive_claim_or_completion_secrets(self):
        path = self.prepare()
        other_api = Mock(base_url="https://another.example")
        with self.assertRaisesRegex(worker.InventoryError, "different site"):
            worker.prepare(other_api, self.root)
        with self.assertRaisesRegex(worker.InventoryError, "different site"):
            worker.complete(other_api, path, self.result_file())
        other_api.post.assert_not_called()
        self.assertTrue((self.root / "active.json").exists())

    def test_ambiguous_completion_is_replayed_exactly_without_new_research(self):
        path = self.prepare()
        result_path = self.result_file()
        self.api.post.side_effect = worker.InventoryError("Connection interrupted.")
        with self.assertRaises(worker.InventoryError):
            worker.complete(self.api, path, result_path)
        first_payload = deepcopy(self.api.post.call_args.args[1])
        self.assertEqual(worker.read_json(path.with_suffix(".completion.json")), first_payload)
        self.assertTrue((self.root / "active.json").exists())

        self.api.post.side_effect = None
        self.api.post.return_value = {"already_completed": True, "reply_id": 42}
        result = worker.complete(self.api, path)
        self.assertEqual(self.api.post.call_args.args[1], first_payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["reply_id"], 42)
        self.assertFalse((self.root / "active.json").exists())
        self.assertTrue(path.with_suffix(".receipt.json").exists())

    def test_prepared_completion_cannot_be_replaced_after_transport_failure(self):
        path = self.prepare()
        result_path = self.result_file()
        self.api.post.side_effect = worker.InventoryError("Connection interrupted.")
        with self.assertRaises(worker.InventoryError):
            worker.complete(self.api, path, result_path)
        self.api.post.reset_mock()
        worker.write_json(result_path, {"body": "Different outcome", "result": {}})
        with self.assertRaisesRegex(worker.InventoryError, "exact saved content"):
            worker.complete(self.api, path, result_path)
        self.api.post.assert_not_called()

    def test_unrecognized_completion_response_does_not_claim_success_or_clear_pointer(self):
        path = self.prepare()
        self.api.post.return_value = {"error": "Unexpected server result"}
        with self.assertRaises(worker.InventoryError):
            worker.complete(self.api, path, self.result_file())
        self.assertTrue((self.root / "active.json").exists())
        self.assertTrue(path.with_suffix(".completion.json").exists())
        self.assertFalse(path.with_suffix(".receipt.json").exists())

    def test_replay_cannot_use_completion_bound_to_a_different_claim(self):
        path = self.prepare()
        state = worker.read_json(path)
        payload = {**worker.claim_fields(state), **worker.read_json(self.result_file())}
        payload["claim_token"] = str(uuid4())
        worker.write_json(path.with_suffix(".completion.json"), payload)
        with self.assertRaises(worker.InventoryError):
            worker.complete(self.api, path)
        self.api.post.assert_not_called()


class InventoryTransportTests(TestCase):
    def test_status_console_output_omits_claim_credential_and_private_reply(self):
        claim = claim_response()
        state = {"claim": claim, "worker_id": worker.WORKER_ID}
        api = Mock()
        api.post.return_value = {"job": claim["job"], "body": "Private workbook details", "result": {}}
        output = StringIO()
        with (patch("dotenv.load_dotenv"), patch.object(worker, "InventoryAPI", return_value=api),
              patch.object(worker, "saved_state", return_value=state),
              patch("sys.argv", ["inventory_worker.py", "--status", "--state", "private-state.json"]),
              patch("sys.stdout", output)):
            self.assertEqual(worker.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "processing")
        self.assertNotIn(claim["job"]["claim_token"], output.getvalue())
        self.assertNotIn("Private workbook details", output.getvalue())

    def test_origin_validation_blocks_credentials_paths_and_unencrypted_remote_hosts(self):
        for value in (
            "http://example.com", "https://user:secret@example.com", "https://example.com/path",
            "https://example.com?query=1", "https://example.com#fragment", "file:///tmp/example",
            "https://example.com:invalid", "https:///example.com",
        ):
            with self.subTest(value=value), self.assertRaises(worker.InventoryError):
                worker.InventoryAPI(value, "test-secret")
        for value in ("http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"):
            self.assertEqual(worker.InventoryAPI(value, "test-secret").base_url, value)

    def test_redirect_response_does_not_forward_token_or_replay_post(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.headers.get("Authorization")))
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(307)
                self.send_header("Location", "/outside-inventory/")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = worker.InventoryAPI(f"http://127.0.0.1:{server.server_port}", "test-secret")
            with self.assertRaisesRegex(worker.InventoryError, "HTTP 307"):
                api.post("/inventory/api/claim/", {"worker_id": "test"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(received, [("/inventory/api/claim/", "Bearer test-secret")])

    def test_transport_errors_omit_private_response_and_token(self):
        api = worker.InventoryAPI("https://secondstate.art", "test-secret")
        for exc in (
            HTTPError(api.base_url, 500, "test-secret", {}, BytesIO(b"private staff body test-secret")),
            URLError("private staff body test-secret"),
        ):
            api.opener = Mock()
            api.opener.open.side_effect = exc
            with self.subTest(exc=type(exc).__name__), self.assertRaises(worker.InventoryError) as raised:
                api.post("/inventory/api/claim/", {})
            self.assertNotIn("test-secret", str(raised.exception))
            self.assertNotIn("private staff body", str(raised.exception))

    def test_oversized_and_nonobject_json_responses_are_rejected(self):
        api = worker.InventoryAPI("https://secondstate.art", "test-secret")
        for raw in (b"x" * (worker.MAX_BYTES + 1), b"[]", b"not-json"):
            api.opener = Mock()
            api.opener.open.return_value.__enter__ = Mock(return_value=BytesIO(raw))
            api.opener.open.return_value.__exit__ = Mock(return_value=False)
            with self.subTest(size=len(raw)), self.assertRaises(worker.InventoryError):
                api.post("/inventory/api/claim/", {})
