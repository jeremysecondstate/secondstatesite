"""Local dispatcher retry/budget tests: no actual mail or network calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from scripts import coordinate_quote_outreach as outreach
from scripts.coordinate_worker import APIError


class QuoteOutreachWorkerTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.api = Mock()

    def test_ambiguous_timeout_replays_same_durable_request_and_never_creates_another(self):
        first_id = str(uuid4())
        self.api.post.side_effect = APIError(503)
        with patch.object(outreach, "uuid4", return_value=first_id) as new_id:
            with self.assertRaises(APIError):
                outreach.dispatch(self.api, self.directory, limit=3)
            self.assertEqual(new_id.call_count, 1)
        path = self.directory / (first_id + ".pending.json")
        request = json.loads(path.read_text())
        self.assertEqual(request, {"worker_id": "manual-codex", "request_id": first_id})
        first_post = self.api.post.call_args
        self.api.post.side_effect = None
        self.api.post.return_value = {"status": "sent", "test_routed": True}
        with patch.object(outreach, "uuid4") as new_id:
            result = outreach.dispatch(self.api, self.directory, limit=1)
            new_id.assert_not_called()
        self.assertEqual(self.api.post.call_args.args, first_post.args)
        self.assertFalse(path.exists())
        saved = json.loads(path.with_name(first_id + ".completed.json").read_text())
        self.assertEqual(saved["request"], request)
        self.assertEqual(saved["result"], result[0])

    def test_idle_unknown_and_in_progress_stop_without_creating_second_request(self):
        for status in ("outreach_idle", "unknown", "sending"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                self.api.reset_mock()
                self.api.post.return_value = {"status": status}
                self.assertEqual(outreach.dispatch(self.api, directory, limit=3), [{"status": status}])
                self.assertEqual(self.api.post.call_count, 1)
                self.assertEqual(len(list(Path(directory).glob("*.completed.json"))), 1)
                self.assertFalse(list(Path(directory).glob("*.pending.json")))

    def test_dispatch_is_hard_bounded_to_three_requests(self):
        self.api.post.return_value = {"status": "sent"}
        with patch.object(outreach.time, "monotonic", return_value=0):
            self.assertEqual(len(outreach.dispatch(self.api, self.directory, limit=100)), 3)
        self.assertEqual(self.api.post.call_count, 3)
        self.assertEqual(len({call.args[1]["request_id"] for call in self.api.post.call_args_list}), 3)
        self.assertTrue(all(set(call.args[1]) == {"worker_id", "request_id"} for call in self.api.post.call_args_list))

    def test_network_timeout_cannot_extend_the_overall_85_second_budget(self):
        clock = [0]
        def post(path, data, **kwargs):
            clock[0] += kwargs["timeout"]
            return {"status": "sent"}
        self.api.post.side_effect = post
        with patch.object(outreach.time, "monotonic", side_effect=lambda: clock[0]):
            outreach.dispatch(self.api, self.directory, limit=3)
        self.assertLessEqual(clock[0], 85)
        self.assertLessEqual(self.api.post.call_count, 3)

    def test_corrupt_pending_state_fails_closed_before_any_new_request(self):
        (self.directory / "existing.pending.json").write_text("{unfinished")
        with patch.object(outreach, "uuid4") as new_id, self.assertRaises(ValueError):
            outreach.dispatch(self.api, self.directory)
        self.api.post.assert_not_called()
        new_id.assert_not_called()

    def test_terminal_and_runpy_entrypoints_work_without_credentials(self):
        repository = Path(__file__).resolve().parents[1]
        commands = [[sys.executable, "scripts/coordinate_quote_outreach.py", "--help"],
            [sys.executable, "-c", "import runpy,sys; sys.argv=['scripts/coordinate_quote_outreach.py','--help']; "
             "runpy.run_path('scripts/coordinate_quote_outreach.py', run_name='__main__')"]]
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run(command, cwd=repository, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--limit", result.stdout)
