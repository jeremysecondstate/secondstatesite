"""Worker transport and process-boundary checks; live proof is documented separately."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
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


class CoordinateWorkerTests(TestCase):
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
                json.dumps({"body": "What is lot 17's pickup deadline?"}), encoding="utf-8"
            )
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

        with patch.object(worker.subprocess, "run", side_effect=fake_process):
            reply = worker.generate_reply(payload, "codex")
        self.assertIn("pickup deadline", reply)
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
                json.dumps({"body": "Test response generated with the requested model."}), encoding="utf-8"
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

    @patch.object(worker.subprocess, "run")
    def test_tool_operation_is_rejected(self, run):
        run.return_value = CompletedProcess([], 0, '\n'.join([
            '{"type":"item.completed","item":{"type":"mcp_tool_call"}}',
            '{"type":"turn.completed"}',
        ]), "")
        with self.assertRaisesRegex(worker.WorkerError, "tool operation"):
            worker.generate_reply(claim_payload(), "codex")

    @patch.object(worker, "generate_reply", return_value="Model response")
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
