"""Exercise the durable local helper against the actual Inventory API contract."""

from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from scripts import inventory_worker as worker
from .models import InventoryCase, InventoryJob, InventoryMessage


@override_settings(INVENTORY_WORKER_TOKEN="integration-test-token")
class InventoryWorkerAPIRoundtripTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.staff = get_user_model().objects.create_user("inventory-worker-test", is_staff=True)
        self.case = InventoryCase.objects.create(title="Example Auctions purchases", created_by=self.staff)
        self.message = InventoryMessage.objects.create(case=self.case, role="staff", body="We won Example Auctions lot 7.", author=self.staff)
        self.job = InventoryJob.objects.create(message=self.message)
        self.api = Mock(base_url="https://secondstate.art")
        self.api.post.side_effect = self.post

    def post(self, path, payload):
        response = self.client.post(path, json.dumps(payload), content_type="application/json",
                                    HTTP_AUTHORIZATION="Bearer integration-test-token")
        if response.status_code != 200:
            raise worker.InventoryError(f"Inventory API returned HTTP {response.status_code}.")
        return response.json()

    def result(self):
        path = self.root / "result.json"
        worker.write_json(path, {
            "body": "Recorded the supported details; acquisition invoice is still needed.",
            "result": {"summary": "Research saved.", "pending_fields": ["Acquisition invoice"]},
        })
        return path

    def test_lost_claim_response_recovers_same_server_claim_without_incrementing_attempts(self):
        def lost_response(path, payload):
            self.post(path, payload)
            raise worker.InventoryError("Response lost after server commit.")

        self.api.post.side_effect = lost_response
        with self.assertRaises(worker.InventoryError):
            worker.prepare(self.api, self.root)
        self.job.refresh_from_db()
        first_token = self.job.claim_token
        self.api.post.side_effect = self.post
        result = worker.prepare(self.api, self.root)
        self.job.refresh_from_db()
        self.assertEqual(self.job.claim_token, first_token)
        self.assertEqual(self.job.attempts, 1)
        self.assertEqual(result["status"], "inventory_work_required")
        self.assertEqual(worker.read_json(Path(result["state_file"]))["claim"]["job"]["claim_token"], str(first_token))

    def test_lost_completion_response_replays_one_server_reply(self):
        state_path = Path(worker.prepare(self.api, self.root)["state_file"])

        def lost_response(path, payload):
            self.post(path, payload)
            raise worker.InventoryError("Response lost after server commit.")

        self.api.post.side_effect = lost_response
        with self.assertRaises(worker.InventoryError):
            worker.complete(self.api, state_path, self.result())
        self.assertEqual(InventoryMessage.objects.filter(in_reply_to=self.message).count(), 1)
        self.api.post.side_effect = self.post
        outcome = worker.complete(self.api, state_path)
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(InventoryMessage.objects.filter(in_reply_to=self.message).count(), 1)
        self.assertTrue(worker.read_json(state_path.with_suffix(".receipt.json"))["already_completed"])
        self.assertEqual(worker.prepare(self.api, self.root), {"status": "idle"})

    def test_superseded_claim_is_archived_without_disclosing_replacement_token(self):
        state_path = Path(worker.prepare(self.api, self.root)["state_file"])
        InventoryJob.objects.filter(pk=self.job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        new_claim = self.post("/inventory/api/claim/", {"worker_id": worker.WORKER_ID, "request_id": str(uuid4())})
        outcome = worker.prepare(self.api, self.root)
        self.assertEqual(outcome["status"], "previous_superseded")
        self.assertFalse((self.root / "active.json").exists())
        status = worker.read_json(state_path.with_suffix(".status.json"))
        self.assertEqual(status["job"]["status"], "superseded")
        self.assertNotEqual(status["job"]["claim_token"], new_claim["job"]["claim_token"])
        self.assertNotIn(new_claim["job"]["claim_token"], json.dumps(status))
