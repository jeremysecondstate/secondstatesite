"""Inventory queue, permissions, exact purchase identity and retry receipts."""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuctionWatchLot, InventoryCase, InventoryClaimRequest, InventoryJob, InventoryMessage


@override_settings(COORDINATE_WORKER_TOKEN="inventory-test-secret", INVENTORY_WORKER_TOKEN="")
class InventoryTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("inventory-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.worker = Client(enforce_csrf_checks=True)

    def create(self, body="We won Example Auctions October 20, lots 7 and 107.", token=None):
        token = token or uuid4()
        response = self.client.post(reverse("inventory_create"), {"body": body, "title": "Example Auctions acquisitions", "client_message_id": str(token)}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return InventoryMessage.objects.get(client_message_id=token)

    def worker_post(self, name, data=None, job_id=None, token="inventory-test-secret"):
        return self.worker.post(reverse(name, args=[job_id] if job_id else []), json.dumps({"worker_id": "inventory-codex", **(data or {})}), content_type="application/json", HTTP_AUTHORIZATION="Bearer " + token)

    def claim(self, request_id=None):
        response = self.worker_post("inventory_worker_claim", {"request_id": str(request_id or uuid4())})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def bound(self, claim, **extra):
        return {key: claim["job"][key] for key in ("claim_token", "case_id", "message_id")} | extra

    def complete(self, claim, **extra):
        return self.worker_post("inventory_worker_complete", self.bound(claim, body="Added the verified lots; freight remains pending.", result={"workbook": {"path": "SUPREME.xlsx", "sheet": "Inventory for Fall 2026", "rows": [41, 42]}, "sources": [{"url": "https://example.com/lot/7", "title": "Example Auctions lot 7"}], "pending_fields": ["Freight: awaiting invoice"]}, **extra), claim["job"]["id"])

    def lot(self, number="7", **kwargs):
        return AuctionWatchLot.objects.create(source="example", source_lot_id="example-20261020-" + number, lot_number=number,
            auction_house="Example Auctions", sale_title="Prints & Multiples", artist="Artist", title="Artwork",
            event_at=datetime(2026, 10, 20, tzinfo=dt_timezone.utc), is_all_day=True,
            lot_url="https://example.com/lot/" + number, **kwargs)

    def test_browser_endpoints_require_active_staff_and_csrf(self):
        message = self.create("Private inventory request")
        for user in (None, get_user_model().objects.create_user("member"), get_user_model().objects.create_user("inactive", is_staff=True, is_active=False)):
            client = Client()
            if user:
                client.force_login(user)
            for url in (reverse("inventory"), reverse("inventory_case", args=[message.case_id]), reverse("inventory_state") + "?case=" + str(message.case_id)):
                response = client.get(url)
                self.assertIn(response.status_code, (302, 403))
                self.assertNotIn(b"Private inventory request", response.content)
        secured = Client(enforce_csrf_checks=True)
        secured.force_login(self.staff)
        response = secured.post(reverse("inventory_create"), {"body": "CSRF attempt", "client_message_id": str(uuid4())})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(InventoryCase.objects.count(), 1)

    def test_worker_authentication_and_dedicated_token(self):
        self.assertEqual(self.worker_post("inventory_worker_claim", token="wrong").status_code, 401)
        self.assertEqual(self.worker_post("inventory_worker_claim", {"worker_id": "manual-codex"}).status_code, 400)
        with override_settings(INVENTORY_WORKER_TOKEN="dedicated"):
            self.assertEqual(self.worker_post("inventory_worker_claim").status_code, 401)
            self.assertEqual(self.worker_post("inventory_worker_claim", token="dedicated").status_code, 200)
        with override_settings(COORDINATE_WORKER_TOKEN=""):
            self.assertEqual(self.worker_post("inventory_worker_claim").status_code, 503)

    def test_staff_submission_is_idempotent_and_conflicts_are_rejected(self):
        token = uuid4()
        first = self.create(token=token)
        again = self.create(token=token)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(InventoryCase.objects.count(), 1)
        response = self.client.post(reverse("inventory_create"), {"body": "different", "client_message_id": str(token)})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(InventoryJob.objects.count(), 1)

    def test_queue_fifo_and_only_one_claim_for_each_case(self):
        first = self.create()
        self.client.post(reverse("inventory_message", args=[first.case_id]), {"body": "Please include the invoice", "client_message_id": str(uuid4())})
        claim = self.claim()
        self.assertEqual(claim["job"]["message_id"], first.pk)
        self.assertIsNone(self.claim()["job"])
        self.assertEqual(self.complete(claim).status_code, 200)
        next_claim = self.claim()
        self.assertNotEqual(next_claim["job"]["message_id"], first.pk)
        self.assertEqual(next_claim["prior_results"][0]["result"]["workbook"]["rows"], [41, 42])
        self.assertEqual([m["role"] for m in next_claim["messages"]], ["staff", "staff", "assistant"])

    def test_claim_receipt_survives_lost_response(self):
        self.create()
        request_id = uuid4()
        first = self.claim(request_id)
        replay = self.claim(request_id)
        self.assertEqual(first, replay)
        self.assertEqual(InventoryJob.objects.get().attempts, 1)
        self.assertEqual(InventoryClaimRequest.objects.count(), 1)

    def test_idle_receipt_stays_idle_when_new_work_arrives(self):
        request_id = uuid4()
        self.assertIsNone(self.claim(request_id)["job"])
        self.create()
        self.assertIsNone(self.claim(request_id)["job"])
        self.assertIsNotNone(self.claim()["job"])

    def test_expired_claim_reclaim_and_old_status_never_disclose_new_token(self):
        self.create()
        request_id = uuid4()
        first = self.claim(request_id)
        InventoryJob.objects.update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.claim(request_id)["job"]["status"], "expired")
        self.assertEqual(self.complete(first).status_code, 409)
        second = self.claim()
        self.assertNotEqual(first["job"]["claim_token"], second["job"]["claim_token"])
        replay = self.claim(request_id)
        self.assertEqual(replay["job"]["status"], "superseded")
        self.assertEqual(replay["job"]["claim_token"], first["job"]["claim_token"])
        status = self.worker_post("inventory_worker_status", self.bound(first), first["job"]["id"])
        self.assertEqual(status.json()["job"]["status"], "superseded")
        self.assertNotIn(second["job"]["claim_token"], status.content.decode())
        self.assertEqual(self.complete(first).status_code, 409)

    def test_completion_is_idempotent_and_different_receipt_conflicts(self):
        self.create()
        claim = self.claim()
        self.assertFalse(self.complete(claim).json()["already_completed"])
        self.assertTrue(self.complete(claim).json()["already_completed"])
        self.assertEqual(InventoryMessage.objects.filter(role="assistant").count(), 1)
        response = self.worker_post("inventory_worker_complete", self.bound(claim, body="Different response", result={}), claim["job"]["id"])
        self.assertEqual(response.status_code, 409)
        status = self.worker_post("inventory_worker_status", self.bound(claim), claim["job"]["id"]).json()
        self.assertEqual(status["job"]["status"], "completed")
        self.assertEqual(status["result"]["workbook"]["rows"], [41, 42])

    def test_result_validation_rejects_unknown_fields_unsafe_links_and_invalid_rows(self):
        self.create()
        claim = self.claim()
        for result in ({"command": "unexpected"}, {"sources": [{"url": "javascript:alert(1)"}]}, {"sources": [{"url": "https://user:password@example.com/"}]}, {"workbook": {"rows": [True]}}, {"pending_fields": "missing"}):
            response = self.worker_post("inventory_worker_complete", self.bound(claim, body="reply", result=result), claim["job"]["id"])
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(InventoryMessage.objects.filter(role="assistant").count(), 0)

    def test_purchase_action_requires_exact_identity_is_atomic_and_idempotent(self):
        self.create()
        first, second = self.lot(), self.lot("107")
        claim = self.claim()
        found = self.worker_post("inventory_worker_search", {"auction_house": "Example Auctions", "sale_date": "2026-10-20", "lot_numbers": ["7", "107"]}).json()["lots"]
        self.assertEqual(len(found), 2)
        invalid = [dict(item) for item in found]
        invalid[1]["sale_date"] = "2025-10-20"
        response = self.worker_post("inventory_worker_purchases", self.bound(claim, lots=invalid), claim["job"]["id"])
        self.assertEqual(response.status_code, 409)
        self.assertFalse(AuctionWatchLot.objects.filter(won_by_us=True).exists())
        for _ in range(2):
            response = self.worker_post("inventory_worker_purchases", self.bound(claim, lots=found), claim["job"]["id"])
            self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()["purchase_lot_ids"]), {first.pk, second.pk})
        self.assertEqual(AuctionWatchLot.objects.filter(won_by_us=True).count(), 2)
        self.complete(claim)
        self.assertEqual(self.worker_post("inventory_worker_purchases", self.bound(claim, lots=found), claim["job"]["id"]).status_code, 409)

    def test_purchase_rejects_other_claim_and_missing_identity(self):
        self.create()
        self.lot()
        claim = self.claim()
        found = self.worker_post("inventory_worker_search", {"auction_house": "Example Auctions"}).json()["lots"]
        invalid = self.bound(claim, lots=found)
        invalid["claim_token"] = str(uuid4())
        self.assertEqual(self.worker_post("inventory_worker_purchases", invalid, claim["job"]["id"]).status_code, 409)
        del found[0]["lot_url"]
        self.assertEqual(self.worker_post("inventory_worker_purchases", self.bound(claim, lots=found), claim["job"]["id"]).status_code, 400)

    def test_failed_job_waits_for_staff_retry_and_retains_purchase_receipt(self):
        message = self.create()
        claim = self.claim()
        InventoryJob.objects.update(purchase_lot_ids=[7])
        response = self.worker_post("inventory_worker_fail", self.bound(claim, error="Workbook is locked. Close it and retry."), claim["job"]["id"])
        self.assertEqual(response.json()["status"], "failed")
        self.assertIsNone(self.claim()["job"])
        self.client.post(reverse("inventory_retry", args=[claim["job"]["id"]]))
        retried = self.claim()
        self.assertEqual(retried["job"]["message_id"], message.pk)
        self.assertEqual(retried["job"]["purchase_lot_ids"], [7])
        old = self.worker_post("inventory_worker_status", self.bound(claim), claim["job"]["id"])
        self.assertEqual(old.json()["job"]["status"], "superseded")

    def test_claim_history_is_bounded_and_includes_current_message(self):
        first = self.create("A" * 12000)
        first.job.status = "completed"
        first.job.save(update_fields=["status"])
        for index in range(20):
            InventoryMessage.objects.create(case=first.case, role="staff", body=str(index) + "B" * 11990)
        current = InventoryMessage.objects.create(case=first.case, role="staff", body="The current task")
        InventoryJob.objects.create(message=current)
        claim = self.claim()
        self.assertLessEqual(sum(len(m["body"]) for m in claim["messages"]), 96000)
        self.assertEqual(claim["messages"][-1]["id"], current.pk)

    def test_current_request_survives_many_later_created_earlier_replies(self):
        first = self.create("Earlier request")
        first.job.status = "completed"
        first.job.save(update_fields=["status"])
        earlier = [InventoryMessage.objects.create(case=first.case, role="staff", body="Earlier " + str(i)) for i in range(12)]
        current = InventoryMessage.objects.create(case=first.case, role="staff", body="The current queued request")
        InventoryJob.objects.create(message=current)
        for message in earlier:
            InventoryMessage.objects.create(case=first.case, role="assistant", body="X" * 12000, in_reply_to=message)
        claim = self.claim()
        self.assertIn(current.pk, [item["id"] for item in claim["messages"]])
        self.assertLessEqual(sum(len(item["body"]) for item in claim["messages"]), 96000)

    def test_staff_page_renders_navigation_receipt_and_escaped_message(self):
        message = self.create('<script>alert("no")</script>')
        claim = self.claim()
        self.complete(claim)
        response = self.client.get(reverse("inventory_case", args=[message.case_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/inventory/"')
        self.assertContains(response, "Inventory for Fall 2026")
        self.assertContains(response, "Freight: awaiting invoice")
        self.assertNotContains(response, '<script>alert("no")</script>')
        self.assertContains(response, "&lt;script&gt;")
