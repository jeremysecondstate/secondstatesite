"""Inventory trash protects existing purchases and makes cancellation recoverable."""
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import InventoryCase, InventoryJob, InventoryMessage


@override_settings(INVENTORY_WORKER_TOKEN="inventory-trash-test")
class InventoryTrashTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("inventory-trash-staff", is_staff=True)
        self.client.force_login(self.staff)

    def case(self, title="Synthetic inventory request", body="Synthetic purchase details."):
        case = InventoryCase.objects.create(title=title, created_by=self.staff)
        message = self.message(case, body)
        return case, message, message.job

    def message(self, case, body="Follow-up inventory details."):
        message = InventoryMessage.objects.create(case=case, role="staff", body=body,
            author=self.staff, client_message_id=uuid4())
        InventoryJob.objects.create(message=message)
        return message

    def post(self, route, *args, **data):
        return self.client.post(reverse(route, args=args), data, HTTP_ACCEPT="application/json")

    def worker(self, route, claim=None, **data):
        payload = {"worker_id": "inventory-codex", **data}
        if claim:
            payload.update({key: claim["job"][key] for key in ("case_id", "message_id", "claim_token")})
        return self.client.post(reverse(route, args=[claim["job"]["id"]] if claim else []),
            json.dumps(payload), content_type="application/json", HTTP_AUTHORIZATION="Bearer inventory-trash-test")

    def claim(self, request_id=None):
        response = self.worker("inventory_worker_claim", request_id=str(request_id or uuid4()))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def complete(self, claim):
        response = self.worker("inventory_worker_complete", claim, body="Saved synthetic inventory receipt.",
            result={"workbook": {"path": "SUPREME.xlsx", "sheet": "Inventory for Fall 2026", "rows": [10]}, "pending_fields": ["Shipping"]})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def token(self):
        response = self.client.get(reverse("inventory_empty_trash"))
        self.assertEqual(response.status_code, 200, response.content)
        return response.context["trash_token"]

    def empty(self, token):
        return self.client.post(reverse("inventory_empty_trash"), {"trash_token": token, "confirm_empty_trash": "yes"})

    def test_case_trash_is_reversible_excluded_from_queue_and_retains_claim_receipt(self):
        case, message, job = self.case()
        request_id = uuid4()
        claim = self.claim(request_id)
        response = self.post("inventory_delete_case", case.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cases"], [])
        self.assertEqual(response.json()["trash_cases"][0]["id"], str(case.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, "cancelled")
        self.assertEqual(str(job.claim_token), claim["job"]["claim_token"])
        self.assertIsNone(job.lease_expires_at)
        self.assertEqual(self.worker("inventory_worker_status", claim).json()["job"]["status"], "cancelled")
        replay = self.claim(request_id)
        self.assertEqual(replay["job"]["status"], "cancelled")
        self.assertEqual(replay["messages"], [])
        self.assertIsNone(self.claim()["job"])
        self.assertEqual(self.post("inventory_restore_case", case.pk).status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIsNone(self.claim()["job"])
        self.post("inventory_retry", job.pk)
        self.assertEqual(self.claim()["job"]["message_id"], message.pk)

    def test_trashed_work_rejects_all_worker_writes_and_staff_submission_retry(self):
        case, message, job = self.case()
        claim = self.claim()
        self.post("inventory_delete_message", case.pk, message.pk)
        self.assertEqual(self.worker("inventory_worker_complete", claim, body="Late reply", result={}).status_code, 409)
        self.assertEqual(self.worker("inventory_worker_fail", claim, error="Late failure").status_code, 409)
        lot = {"id": 1, "source_lot_id": "test-1", "lot_number": "1", "auction_house": "Example",
            "sale_date": "2026-10-20", "lot_url": "https://example.test/1"}
        self.assertEqual(self.worker("inventory_worker_purchases", claim, lots=[lot]).status_code, 409)
        self.assertEqual(self.post("inventory_retry", job.pk).status_code, 409)
        self.assertEqual(self.post("inventory_create", body=message.body, title=case.title,
            client_message_id=message.client_message_id).status_code, 409)
        self.post("inventory_delete_case", case.pk)
        self.assertEqual(self.post("inventory_message", case.pk, body="New message", client_message_id=uuid4()).status_code, 409)
        self.assertEqual(self.post("inventory_restore_message", case.pk, message.pk).status_code, 409)
        self.assertFalse(InventoryMessage.objects.filter(role="assistant").exists())

    def test_deleted_first_message_no_longer_blocks_later_queue(self):
        case, first, _ = self.case()
        second = self.message(case)
        self.post("inventory_delete_message", case.pk, first.pk)
        claimed = self.claim()
        self.assertEqual(claimed["job"]["message_id"], second.pk)
        self.assertEqual([message["id"] for message in claimed["messages"]], [second.pk])

    def test_deleted_completed_staff_message_and_reply_are_absent_from_new_worker_context(self):
        case, first, job = self.case()
        self.complete(self.claim())
        self.post("inventory_delete_message", case.pk, first.pk)
        next_message = self.message(case)
        claimed = self.claim()
        self.assertEqual([message["id"] for message in claimed["messages"]], [next_message.pk])
        self.assertEqual(claimed["prior_results"], [])
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.result["workbook"]["rows"], [10])

    def test_deleted_assistant_reply_hides_prior_result_and_invalidates_processing_context(self):
        case, first, _ = self.case()
        self.complete(self.claim())
        reply = InventoryMessage.objects.get(in_reply_to=first)
        second = self.message(case)
        claim = self.claim()
        self.post("inventory_delete_message", case.pk, reply.pk)
        second.job.refresh_from_db()
        self.assertEqual(second.job.status, "failed")
        self.assertEqual(self.worker("inventory_worker_status", claim).json()["job"]["status"], "failed")
        self.assertEqual(self.worker("inventory_worker_complete", claim, body="Stale reply", result={}).status_code, 409)
        self.post("inventory_retry", second.job.pk)
        fresh = self.claim()
        self.assertNotIn(reply.pk, [message["id"] for message in fresh["messages"]])
        self.assertEqual(fresh["prior_results"], [])

    def test_restoring_history_invalidates_processing_without_repeating_completed_work(self):
        case, first, job = self.case()
        self.complete(self.claim())
        self.post("inventory_delete_message", case.pk, first.pk)
        second = self.message(case)
        claim = self.claim()
        self.post("inventory_restore_message", case.pk, first.pk)
        job.refresh_from_db()
        second.job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(second.job.status, "failed")
        self.assertEqual(self.worker("inventory_worker_status", claim).json()["job"]["status"], "failed")
        self.assertIsNone(self.claim()["job"])

    def test_completed_case_can_restore_without_requeue_and_preserves_exact_replay(self):
        case, _, job = self.case()
        claim = self.claim()
        receipt = self.complete(claim)
        self.post("inventory_delete_case", case.pk)
        self.assertTrue(self.complete(claim)["already_completed"])
        self.assertEqual(self.complete(claim)["reply_id"], receipt["reply_id"])
        self.post("inventory_restore_case", case.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertIsNone(self.claim()["job"])
        self.assertEqual(InventoryMessage.objects.filter(role="assistant").count(), 1)

    def test_message_trash_state_and_no_script_context_have_exact_shapes(self):
        case, first, _ = self.case()
        second = self.message(case)
        state = self.post("inventory_delete_message", case.pk, first.pk).json()
        self.assertEqual([message["id"] for message in state["active_messages"]], [second.pk])
        self.assertEqual([message["id"] for message in state["deleted_messages"]], [first.pk])
        item = state["trash_messages"][0]
        self.assertEqual(item["case_id"], str(case.pk))
        self.assertEqual(item["case_title"], case.title)
        self.assertEqual(item["restore_url"], reverse("inventory_restore_message", args=[case.pk, first.pk]))
        self.assertEqual(state["trash_count"], 1)

    def test_empty_snapshot_purges_cases_and_individual_messages_but_not_later_trash(self):
        case, _, job = self.case()
        claim = self.claim()
        self.complete(claim)
        active, message, pending = self.case("Keep active")
        self.post("inventory_delete_case", case.pk)
        self.post("inventory_delete_message", active.pk, message.pk)
        token = self.token()
        later, _, later_job = self.case("Trashed later")
        self.post("inventory_delete_case", later.pk)
        self.assertEqual(self.empty(token).status_code, 302)
        for record in (case, message):
            record.refresh_from_db()
            self.assertIsNotNone(record.purged_at)
            self.assertEqual(record.purged_by_id, self.staff.pk)
        later.refresh_from_db()
        active.refresh_from_db()
        self.assertIsNone(later.purged_at)
        self.assertIsNone(active.purged_at)
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.result["workbook"]["rows"], [10])
        self.assertEqual(self.worker("inventory_worker_status", claim).json()["job"]["status"], "completed")
        self.assertTrue(self.complete(claim)["already_completed"])
        self.assertEqual(self.empty(token).status_code, 302)
        self.assertEqual(InventoryJob.objects.count(), 3)

    def test_purged_items_are_not_visible_or_restorable(self):
        case, _, _ = self.case()
        active, message, _ = self.case("Keep active")
        self.post("inventory_delete_case", case.pk)
        self.post("inventory_delete_message", active.pk, message.pk)
        self.empty(self.token())
        for route in ("inventory_case", "inventory_restore_case", "inventory_delete_case"):
            response = self.client.get(reverse(route, args=[case.pk])) if route == "inventory_case" else self.post(route, case.pk)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(reverse("inventory_state"), {"case": case.pk}).status_code, 404)
        self.assertEqual(self.post("inventory_restore_message", active.pk, message.pk).status_code, 404)
        self.assertEqual(self.post("inventory_delete_message", active.pk, message.pk).status_code, 404)
        state = self.client.get(reverse("inventory_state"), {"case": active.pk}).json()
        self.assertEqual(state["trash_cases"], [])
        self.assertEqual(state["trash_messages"], [])
        self.assertEqual(state["messages"], [])
        self.assertEqual(self.client.get(reverse("inventory")).context["selected_case"]["id"], str(active.pk))

    def test_snapshot_changes_reject_entire_purge_without_partial_changes(self):
        first, _, _ = self.case()
        second, message, _ = self.case()
        self.post("inventory_delete_case", first.pk)
        self.post("inventory_delete_message", second.pk, message.pk)
        token = self.token()
        self.post("inventory_restore_message", second.pk, message.pk)
        self.post("inventory_delete_message", second.pk, message.pk)
        self.assertEqual(self.empty(token).status_code, 409)
        first.refresh_from_db()
        message.refresh_from_db()
        self.assertIsNone(first.purged_at)
        self.assertIsNone(message.purged_at)
        token = self.token()
        self.post("inventory_delete_case", second.pk)
        self.assertEqual(self.empty(token).status_code, 409)
        first.refresh_from_db()
        self.assertIsNone(first.purged_at)

    def test_empty_trash_requires_actor_bound_current_confirmation(self):
        case, _, _ = self.case()
        self.post("inventory_delete_case", case.pk)
        token = self.token()
        for payload in ({}, {"trash_token": token}, {"trash_token": "bad", "confirm_empty_trash": "yes"}):
            self.assertEqual(self.client.post(reverse("inventory_empty_trash"), payload).status_code, 400)
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 86400):
            self.assertEqual(self.empty(token).status_code, 400)
        other = get_user_model().objects.create_user("other-inventory-staff", is_staff=True)
        self.client.force_login(other)
        self.assertEqual(self.empty(token).status_code, 400)
        case.refresh_from_db()
        self.assertIsNone(case.purged_at)

    def test_case_restore_and_retrash_invalidates_old_confirmation(self):
        case, _, _ = self.case()
        self.post("inventory_delete_case", case.pk)
        token = self.token()
        self.post("inventory_restore_case", case.pk)
        self.post("inventory_delete_case", case.pk)
        self.assertEqual(self.empty(token).status_code, 409)

    def test_trash_controls_require_staff_post_and_csrf(self):
        case, message, _ = self.case()
        urls = [reverse("inventory_delete_case", args=[case.pk]), reverse("inventory_restore_case", args=[case.pk]),
            reverse("inventory_delete_message", args=[case.pk, message.pk]), reverse("inventory_restore_message", args=[case.pk, message.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405)
        secured = Client(enforce_csrf_checks=True)
        secured.force_login(self.staff)
        for url in urls + [reverse("inventory_empty_trash")]:
            self.assertEqual(secured.post(url).status_code, 403)
        anonymous, ordinary = Client(), Client()
        ordinary.force_login(get_user_model().objects.create_user("inventory-trash-member"))
        for client in (anonymous, ordinary):
            for url in urls + [reverse("inventory_empty_trash")]:
                self.assertEqual(client.post(url).status_code, 302)
        case.refresh_from_db()
        message.refresh_from_db()
        self.assertIsNone(case.deleted_at)
        self.assertIsNone(message.deleted_at)

    def test_message_cannot_be_removed_through_another_request(self):
        first, _, _ = self.case()
        _, second, _ = self.case()
        self.assertEqual(self.post("inventory_delete_message", first.pk, second.pk).status_code, 404)
        second.refresh_from_db()
        self.assertIsNone(second.deleted_at)
