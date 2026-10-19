"""Focused contracts for the staff conversation and authenticated worker queue."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import OperationalError, close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    CoordinateActivity,
    CoordinateCase,
    CoordinateJob,
    CoordinateMessage,
    CoordinateWorkerState,
)


SYNTHETIC_SHIPPING_PLAYBOOK = "# Synthetic shipping fixture\n\nTest mode only.\nReference ID: TEST-SHIP-001\n"
SYNTHETIC_PACKING_PLAYBOOK = "# Synthetic packing fixture\n\nAsk the test operator about handling.\nReference ID: TEST-PACK-001\n"


@override_settings(
    COORDINATE_WORKER_TOKEN="coordinate-test-token-not-a-real-secret",
    COORDINATE_SHIPPING_PLAYBOOK=SYNTHETIC_SHIPPING_PLAYBOOK,
    COORDINATE_PACKING_PLAYBOOK=SYNTHETIC_PACKING_PLAYBOOK,
)
class CoordinateTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("coordinate-staff", is_staff=True)
        self.ordinary = get_user_model().objects.create_user("coordinate-member")
        self.client.force_login(self.staff)
        self.worker = Client(enforce_csrf_checks=True)
        self.authorization = "Bearer coordinate-test-token-not-a-real-secret"

    def create_case(self, body="we won these lots!! https://example.test/lot/123", **fields):
        message_id = fields.pop("client_message_id", uuid4())
        response = self.client.post(reverse("coordinate_create"), {
            "title": "Shipping test",
            "body": body,
            "client_message_id": str(message_id),
            **fields,
        })
        self.assertIn(response.status_code, (200, 201, 302), response.content)
        message = CoordinateMessage.objects.get(client_message_id=message_id)
        return message.case, message

    def post_message(self, case, body="follow-up with another lot", **fields):
        message_id = fields.pop("client_message_id", uuid4())
        response = self.client.post(reverse("coordinate_message", args=(case.pk,)), {
            "body": body, "client_message_id": str(message_id), **fields,
        })
        self.assertIn(response.status_code, (200, 201, 302), response.content)
        return CoordinateMessage.objects.get(client_message_id=message_id)

    def worker_post(self, name, data, *, args=(), authorization=None):
        return self.worker.post(
            reverse(name, args=args),
            json.dumps(data),
            content_type="application/json",
            HTTP_AUTHORIZATION=self.authorization if authorization is None else authorization,
        )

    def claim(self, worker_id="manual-codex"):
        response = self.worker_post("coordinate_worker_claim", {"worker_id": worker_id})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def complete(self, claim, body="test mode: please share the invoice and pickup deadline.", **fields):
        job = claim["job"]
        return self.worker_post("coordinate_worker_complete", {
            "claim_token": job["claim_token"],
            "case_id": job["case_id"],
            "message_id": job["message_id"],
            "worker_id": "manual-codex",
            "body": body,
            **fields,
        }, args=(job["id"],))

    def state(self, case):
        response = self.client.get(reverse("coordinate_state"), {"case": str(case.pk)})
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def mutate(self, name, case, message=None):
        args = (case.pk, message.pk) if message else (case.pk,)
        return self.client.post(reverse(name, args=args), HTTP_ACCEPT="application/json")

    def test_all_browser_endpoints_require_active_staff(self):
        case, message = self.create_case(body="private case contents")
        inactive = get_user_model().objects.create_user("coordinate-inactive", is_staff=True, is_active=False)
        requests = (
            ("get", reverse("coordinate"), {}),
            ("get", reverse("coordinate_case", args=(case.pk,)), {}),
            ("get", reverse("coordinate_state"), {"case": str(case.pk)}),
            ("post", reverse("coordinate_create"), {"body": "unauthorized", "client_message_id": str(uuid4())}),
            ("post", reverse("coordinate_message", args=(case.pk,)), {"body": "unauthorized", "client_message_id": str(uuid4())}),
        )
        for user in (None, self.ordinary, inactive):
            client = Client()
            if user is not None:
                client.force_login(user)
            for method, endpoint, data in requests:
                with self.subTest(user=user, endpoint=endpoint):
                    response = getattr(client, method)(endpoint, data)
                    self.assertIn(response.status_code, (302, 401, 403))
                    self.assertNotIn(message.body, response.content.decode())
        self.assertEqual(CoordinateCase.objects.count(), 1)
        self.assertEqual(CoordinateMessage.objects.count(), 1)

    def test_staff_share_cases_but_selected_conversations_stay_separate(self):
        case_a, message_a = self.create_case("only case A https://example.test/a")
        case_b, message_b = self.create_case("only case B https://example.test/b")
        colleague = get_user_model().objects.create_user("coordinate-colleague", is_staff=True)
        self.client.force_login(colleague)
        data = self.state(case_a).json()
        self.assertEqual([item["body"] for item in data["messages"]], [message_a.body])
        self.assertNotIn(message_b.body, json.dumps(data["messages"]))
        reply = self.post_message(case_a, "another staff member can coordinate this case")
        self.assertEqual(reply.author, colleague)
        self.assertEqual(CoordinateMessage.objects.filter(case=case_b).count(), 1)

    def test_session_writes_require_csrf_and_bearer_does_not_bypass_them(self):
        case, _ = self.create_case()
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.staff)
        for endpoint in (reverse("coordinate_create"), reverse("coordinate_message", args=(case.pk,))):
            with self.subTest(endpoint=endpoint):
                response = browser.post(endpoint, {"body": "blocked", "client_message_id": str(uuid4())}, HTTP_AUTHORIZATION=self.authorization)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(CoordinateMessage.objects.count(), 1)

    def test_page_and_polling_data_are_not_cacheable(self):
        case, _ = self.create_case()
        for endpoint in (reverse("coordinate"), reverse("coordinate_case", args=(case.pk,)), reverse("coordinate_state")):
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint, {"case": str(case.pk)})
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_duplicate_case_submission_has_one_case_message_and_job(self):
        message_id = uuid4()
        case, message = self.create_case(client_message_id=message_id)
        duplicate_case, duplicate_message = self.create_case(client_message_id=message_id)
        self.assertEqual(duplicate_case.pk, case.pk)
        self.assertEqual(duplicate_message.pk, message.pk)
        self.assertEqual(CoordinateCase.objects.count(), 1)
        self.assertEqual(CoordinateMessage.objects.count(), 1)
        self.assertEqual(CoordinateJob.objects.count(), 1)
        response = self.client.post(reverse("coordinate_create"), {
            "body": "different contents", "client_message_id": str(message_id),
        })
        self.assertEqual(response.status_code, 409)
        message.refresh_from_db()
        self.assertIn("https://example.test/lot/123", message.body)

    def test_duplicate_followup_is_idempotent_and_cannot_cross_cases(self):
        case_a, _ = self.create_case()
        case_b, _ = self.create_case()
        message_id = uuid4()
        followup = self.post_message(case_a, "same followup", client_message_id=message_id)
        duplicate = self.post_message(case_a, "same followup", client_message_id=message_id)
        self.assertEqual(duplicate.pk, followup.pk)
        self.assertEqual(CoordinateJob.objects.filter(message=followup).count(), 1)
        for case, body in ((case_a, "different followup"), (case_b, "same followup")):
            response = self.client.post(reverse("coordinate_message", args=(case.pk,)), {
                "body": body, "client_message_id": str(message_id),
            })
            self.assertEqual(response.status_code, 409)

    def test_invalid_browser_messages_do_not_enqueue_work(self):
        for body, client_id in (("", uuid4()), ("   ", uuid4()), ("x" * 12001, uuid4()), ("valid body", "not-a-uuid")):
            with self.subTest(length=len(body), client_id=client_id):
                response = self.client.post(reverse("coordinate_create"), {
                    "body": body, "client_message_id": str(client_id),
                })
                self.assertEqual(response.status_code, 400)
        self.assertFalse(CoordinateCase.objects.exists())
        self.assertFalse(CoordinateMessage.objects.exists())
        self.assertFalse(CoordinateJob.objects.exists())

    def test_unknown_case_cannot_be_read_or_written(self):
        case_id = uuid4()
        self.assertEqual(self.client.get(reverse("coordinate_case", args=(case_id,))).status_code, 404)
        self.assertEqual(self.client.get(reverse("coordinate_state"), {"case": str(case_id)}).status_code, 404)
        response = self.client.post(reverse("coordinate_message", args=(case_id,)), {
            "body": "missing case", "client_message_id": str(uuid4()),
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CoordinateMessage.objects.exists())

    def test_every_worker_endpoint_requires_bearer_even_with_staff_session(self):
        case, message = self.create_case()
        job = CoordinateJob.objects.get(message=message)
        self.worker.force_login(self.staff)
        for endpoint, args in (("coordinate_worker_claim", ()), ("coordinate_worker_complete", (job.pk,)), ("coordinate_worker_fail", (job.pk,))):
            for header in ("", "Bearer wrong-secret", "Basic coordinate-test-token-not-a-real-secret"):
                with self.subTest(endpoint=endpoint, header=header):
                    response = self.worker_post(endpoint, {}, args=args, authorization=header)
                    self.assertEqual(response.status_code, 401)
        job.refresh_from_db()
        self.assertEqual(job.status, "queued")
        self.assertEqual(CoordinateMessage.objects.filter(case=case).count(), 1)

    @override_settings(COORDINATE_WORKER_TOKEN="")
    def test_unconfigured_worker_connection_is_unavailable(self):
        _, message = self.create_case()
        job = CoordinateJob.objects.get(message=message)
        for endpoint, args in (("coordinate_worker_claim", ()), ("coordinate_worker_complete", (job.pk,)), ("coordinate_worker_fail", (job.pk,))):
            response = self.worker_post(endpoint, {}, args=args)
            self.assertEqual(response.status_code, 503)

    def test_worker_endpoints_reject_get_and_invalid_json(self):
        _, message = self.create_case()
        job = CoordinateJob.objects.get(message=message)
        for endpoint, args in (("coordinate_worker_claim", ()), ("coordinate_worker_complete", (job.pk,)), ("coordinate_worker_fail", (job.pk,))):
            url = reverse(endpoint, args=args)
            with self.subTest(endpoint=endpoint):
                response = self.worker.get(url, HTTP_AUTHORIZATION=self.authorization)
                self.assertEqual(response.status_code, 405)
                response = self.worker.post(url, "{", content_type="application/json", HTTP_AUTHORIZATION=self.authorization)
                self.assertEqual(response.status_code, 400)

    def test_claim_loads_exact_configured_playbooks_and_current_conversation_only(self):
        case, first = self.create_case("first https://example.test/first")
        future = self.post_message(case, "future message must wait its own turn")
        other_case, other = self.create_case("another case confidential text")
        claimed = self.claim()
        self.assertTrue(claimed["test_mode"])
        self.assertEqual(str(claimed["job"]["case_id"]), str(case.pk))
        self.assertEqual(str(claimed["job"]["message_id"]), str(first.pk))
        self.assertEqual(claimed["job"]["attempt"], 1)
        self.assertEqual([item["body"] for item in claimed["messages"]], [first.body])
        self.assertNotIn(future.body, json.dumps(claimed["messages"]))
        self.assertNotIn(other.body, json.dumps(claimed["messages"]))
        self.assertEqual(claimed["playbook"]["packing"], SYNTHETIC_PACKING_PLAYBOOK)
        self.assertEqual(claimed["playbook"]["shipping"], SYNTHETIC_SHIPPING_PLAYBOOK)
        self.assertNotIn(settings.COORDINATE_WORKER_TOKEN, json.dumps(claimed))

    def test_configured_playbooks_take_precedence_over_local_files(self):
        self.create_case()
        with TemporaryDirectory(prefix="coordinate-reference-test-") as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "docs" / "coordinate-playbook.md").write_text("local shipping fixture", encoding="utf-8")
            (root / "docs" / "cardboardsandwich.md").write_text("local packing fixture", encoding="utf-8")
            with override_settings(BASE_DIR=root):
                playbook = self.claim()["playbook"]
        self.assertEqual(playbook, {"shipping": SYNTHETIC_SHIPPING_PLAYBOOK, "packing": SYNTHETIC_PACKING_PLAYBOOK})

    def test_configured_playbooks_are_read_fresh_without_local_reference_files(self):
        self.create_case("first configured reference check")
        self.create_case("second configured reference check")
        with TemporaryDirectory(prefix="coordinate-reference-test-") as temporary:
            with override_settings(BASE_DIR=Path(temporary)):
                first = self.claim()
                updated_shipping = SYNTHETIC_SHIPPING_PLAYBOOK + "Synthetic revision two.\n"
                updated_packing = SYNTHETIC_PACKING_PLAYBOOK + "Synthetic revision two.\n"
                with override_settings(
                    COORDINATE_SHIPPING_PLAYBOOK=updated_shipping,
                    COORDINATE_PACKING_PLAYBOOK=updated_packing,
                ):
                    second = self.claim()
        self.assertEqual(first["playbook"], {"shipping": SYNTHETIC_SHIPPING_PLAYBOOK, "packing": SYNTHETIC_PACKING_PLAYBOOK})
        self.assertEqual(second["playbook"], {"shipping": updated_shipping, "packing": updated_packing})

    @override_settings(COORDINATE_SHIPPING_PLAYBOOK="", COORDINATE_PACKING_PLAYBOOK="")
    def test_local_fallback_playbooks_are_read_exactly_and_fresh_each_run(self):
        self.create_case("first local reference check")
        self.create_case("second local reference check")
        with TemporaryDirectory(prefix="coordinate-reference-test-") as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            shipping_path = root / "docs" / "coordinate-playbook.md"
            packing_path = root / "docs" / "cardboardsandwich.md"
            shipping_path.write_text(SYNTHETIC_SHIPPING_PLAYBOOK, encoding="utf-8")
            packing_path.write_text(SYNTHETIC_PACKING_PLAYBOOK, encoding="utf-8")
            with override_settings(BASE_DIR=root):
                first = self.claim()
                shipping_path.write_text("Synthetic local shipping revision two.\n", encoding="utf-8")
                packing_path.write_text("Synthetic local packing revision two.\n", encoding="utf-8")
                second = self.claim()
        self.assertEqual(first["playbook"], {"shipping": SYNTHETIC_SHIPPING_PLAYBOOK, "packing": SYNTHETIC_PACKING_PLAYBOOK})
        self.assertEqual(second["playbook"], {
            "shipping": "Synthetic local shipping revision two.\n",
            "packing": "Synthetic local packing revision two.\n",
        })

    def test_missing_playbooks_fail_closed_without_claiming_or_updating_worker_health(self):
        _, message = self.create_case()
        with TemporaryDirectory(prefix="coordinate-reference-test-") as temporary:
            for shipping, packing in (("", ""), (SYNTHETIC_SHIPPING_PLAYBOOK, ""), ("", SYNTHETIC_PACKING_PLAYBOOK)):
                with self.subTest(shipping_configured=bool(shipping), packing_configured=bool(packing)):
                    with override_settings(
                        BASE_DIR=Path(temporary),
                        COORDINATE_SHIPPING_PLAYBOOK=shipping,
                        COORDINATE_PACKING_PLAYBOOK=packing,
                    ):
                        response = self.worker_post("coordinate_worker_claim", {"worker_id": "manual-codex"})
                    self.assertEqual(response.status_code, 503)
        job = CoordinateJob.objects.get(message=message)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.attempts, 0)
        self.assertIsNone(job.claim_token)
        self.assertFalse(CoordinateActivity.objects.filter(event="job_claimed").exists())
        self.assertFalse(CoordinateWorkerState.objects.filter(last_successful_check__isnull=False).exists())

    def test_overlap_does_not_claim_same_case_twice(self):
        case, first = self.create_case()
        self.post_message(case)
        claimed = self.claim()
        self.assertEqual(str(claimed["job"]["message_id"]), str(first.pk))
        self.assertIsNone(self.claim()["job"])
        self.assertEqual(CoordinateJob.objects.filter(status="processing").count(), 1)
        self.assertEqual(CoordinateJob.objects.filter(status="queued").count(), 1)

    def test_another_case_can_progress_while_first_case_is_claimed(self):
        case_a, _ = self.create_case("case A work")
        self.post_message(case_a, "case A waiting")
        case_b, _ = self.create_case("case B work")
        first = self.claim()
        second = self.claim()
        self.assertEqual(str(first["job"]["case_id"]), str(case_a.pk))
        self.assertEqual(str(second["job"]["case_id"]), str(case_b.pk))

    def test_completion_persists_reply_and_reload_history_with_waiting_status(self):
        case, message = self.create_case()
        self.assertEqual(self.state(case).json()["messages"][0]["status"], "waiting")
        claimed = self.claim()
        self.assertEqual(self.state(case).json()["messages"][0]["status"], "processing")
        response = self.complete(claimed)
        self.assertEqual(response.status_code, 200, response.content)
        reply = CoordinateMessage.objects.get(pk=response.json()["reply_id"])
        self.assertEqual(reply.case, case)
        self.assertEqual(reply.in_reply_to, message)
        self.assertEqual(reply.role, "assistant")
        message.job.refresh_from_db()
        self.assertEqual(message.job.status, "completed")
        self.assertIsNotNone(message.job.completed_at)
        data = self.state(case).json()
        self.assertEqual([item["body"] for item in data["messages"]], [message.body, reply.body])
        self.assertEqual(data["messages"][0]["status"], "replied")
        reloaded = Client()
        reloaded.force_login(self.staff)
        response = reloaded.get(reverse("coordinate_case", args=(case.pk,)))
        self.assertContains(response, "we won these lots!!")
        self.assertContains(response, reply.body)

    def test_identical_completion_retry_has_one_reply_and_no_extra_activity(self):
        _, message = self.create_case()
        claimed = self.claim()
        first = self.complete(claimed)
        self.assertEqual(first.status_code, 200, first.content)
        activity_count = CoordinateActivity.objects.count()
        second = self.complete(claimed)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(first.json()["reply_id"], second.json()["reply_id"])
        self.assertTrue(second.json()["already_completed"])
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=message).count(), 1)
        self.assertEqual(CoordinateActivity.objects.count(), activity_count)
        changed = self.complete(claimed, body="a different answer is not a retry")
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=message).count(), 1)

    def test_untrusted_staff_and_worker_text_are_escaped_in_the_conversation(self):
        case, _ = self.create_case('<img src=x onerror=alert(1)> https://example.test/lot?x=1&y=2')
        claimed = self.claim()
        response = self.complete(claimed, body='<script>alert("unsafe worker output")</script>')
        self.assertEqual(response.status_code, 200)
        page = self.client.get(reverse("coordinate_case", args=(case.pk,)))
        self.assertNotContains(page, "<img src=x")
        self.assertNotContains(page, '<script>alert("unsafe worker output")</script>')
        self.assertContains(page, "&lt;img")
        self.assertContains(page, "&lt;script&gt;")
        self.assertNotContains(page, settings.COORDINATE_WORKER_TOKEN)

    def test_next_claim_includes_prior_reply_and_followup_history(self):
        case, first = self.create_case("initial shipping request")
        claimed = self.claim()
        answer = "please confirm pickup deadline"
        self.assertEqual(self.complete(claimed, body=answer).status_code, 200)
        followup = self.post_message(case, "pickup deadline is next friday")
        next_claim = self.claim()
        self.assertEqual(str(next_claim["job"]["message_id"]), str(followup.pk))
        self.assertEqual([item["body"] for item in next_claim["messages"]], [first.body, answer, followup.body])

    def test_completion_rejects_case_message_worker_or_claim_mismatch(self):
        case_a, message_a = self.create_case()
        case_b, message_b = self.create_case()
        claimed = self.claim()
        for changes in (
            {"case_id": str(case_b.pk)},
            {"message_id": message_b.pk},
            {"worker_id": "unassigned-coordinator"},
            {"claim_token": str(uuid4())},
        ):
            with self.subTest(changes=changes):
                response = self.complete(claimed, **changes)
                self.assertEqual(response.status_code, 400 if "worker_id" in changes else 409, response.content)
        self.assertFalse(CoordinateMessage.objects.filter(role="assistant").exists())
        self.assertEqual(self.complete(claimed).status_code, 200)
        self.assertEqual(CoordinateMessage.objects.get(in_reply_to=message_a).case, case_a)

    def test_expired_claim_reclaims_work_and_rejects_old_completion(self):
        _, message = self.create_case()
        original = self.claim()
        CoordinateJob.objects.filter(message=message).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.complete(original).status_code, 409)
        reclaimed = self.claim()
        self.assertEqual(reclaimed["job"]["id"], original["job"]["id"])
        self.assertNotEqual(reclaimed["job"]["claim_token"], original["job"]["claim_token"])
        self.assertEqual(reclaimed["job"]["attempt"], 2)
        self.assertEqual(self.complete(original).status_code, 409)
        self.assertEqual(self.complete(reclaimed).status_code, 200)
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=message).count(), 1)

    def test_failure_retries_after_delay_and_does_not_skip_later_case_message(self):
        case, message = self.create_case()
        self.post_message(case, "must not overtake failed input")
        claimed = self.claim()
        response = self.worker_post("coordinate_worker_fail", {
            "claim_token": claimed["job"]["claim_token"],
            "case_id": str(case.pk),
            "message_id": message.pk,
            "worker_id": "manual-codex",
            "error": "temporary model connection issue; secret=do-not-persist-worker-output",
        }, args=(claimed["job"]["id"],))
        self.assertEqual(response.status_code, 200, response.content)
        job = CoordinateJob.objects.get(message=message)
        self.assertEqual(job.status, "retry")
        self.assertGreater(job.available_at, timezone.now())
        self.assertNotIn("do-not-persist-worker-output", job.last_error)
        self.assertNotIn("do-not-persist-worker-output", json.dumps(list(CoordinateActivity.objects.values("details"))))
        self.assertEqual(self.state(case).json()["messages"][0]["status"], "retrying")
        self.assertIsNone(self.claim()["job"])
        self.assertEqual(self.complete(claimed).status_code, 409)
        CoordinateJob.objects.filter(pk=job.pk).update(available_at=timezone.now() - timedelta(seconds=1))
        retry = self.claim()
        self.assertEqual(str(retry["job"]["message_id"]), str(message.pk))
        self.assertEqual(retry["job"]["attempt"], 2)

    def test_failure_rejects_stale_token_and_cross_case_reference(self):
        case, message = self.create_case()
        claimed = self.claim()
        for changes in ({"claim_token": str(uuid4())}, {"case_id": str(uuid4())}, {"message_id": message.pk + 1000}, {"worker_id": "other"}):
            response = self.worker_post("coordinate_worker_fail", {
                "claim_token": claimed["job"]["claim_token"],
                "case_id": str(case.pk), "message_id": message.pk,
                "worker_id": "manual-codex", "error": "test failure", **changes,
            }, args=(claimed["job"]["id"],))
            self.assertEqual(response.status_code, 400 if "worker_id" in changes else 409)
        message.job.refresh_from_db()
        self.assertEqual(message.job.status, "processing")

    def test_successful_empty_check_updates_worker_health_without_a_schedule(self):
        self.assertIsNone(self.claim()["job"])
        worker_state = CoordinateWorkerState.objects.get(pk=1)
        self.assertIsNotNone(worker_state.last_successful_check)
        response = self.client.get(reverse("coordinate_state"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["worker"]["last_successful_check"])
        self.assertFalse(response.json().get("next_scheduled_check"))

    def test_unauthorized_worker_does_not_update_successful_check(self):
        before = CoordinateWorkerState.objects.filter(pk=1).values_list("last_successful_check", flat=True).first()
        response = self.worker_post("coordinate_worker_claim", {}, authorization="Bearer incorrect")
        self.assertEqual(response.status_code, 401)
        after = CoordinateWorkerState.objects.filter(pk=1).values_list("last_successful_check", flat=True).first()
        self.assertEqual(before, after)

    def test_deletion_and_restore_endpoints_require_staff_post_and_csrf(self):
        case, message = self.create_case()
        endpoints = [
            reverse("coordinate_delete_case", args=(case.pk,)),
            reverse("coordinate_restore_case", args=(case.pk,)),
            reverse("coordinate_delete_message", args=(case.pk, message.pk)),
            reverse("coordinate_restore_message", args=(case.pk, message.pk)),
        ]
        for user in (None, self.ordinary):
            browser = Client()
            if user:
                browser.force_login(user)
            for endpoint in endpoints:
                with self.subTest(endpoint=endpoint, user=user):
                    self.assertIn(browser.post(endpoint).status_code, (302, 403))
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.staff)
        for endpoint in endpoints:
            self.assertEqual(self.client.get(endpoint).status_code, 405)
            self.assertEqual(protected.post(endpoint, HTTP_AUTHORIZATION=self.authorization).status_code, 403)
        message.refresh_from_db()
        case.refresh_from_db()
        self.assertIsNone(message.deleted_at)
        self.assertIsNone(case.deleted_at)

    def test_message_delete_is_reversible_tombstone_with_audit_and_no_worker_reply(self):
        body = "private text to remove from visible context"
        case, message = self.create_case(body)
        claimed = self.claim()
        response = self.mutate("coordinate_delete_message", case, message)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        row = response.json()["messages"][0]
        self.assertTrue(row["deleted"])
        self.assertEqual(row["body"], "")
        self.assertEqual(row["status"], "deleted")
        self.assertNotIn(body, response.content.decode())
        self.assertEqual(row["restore_url"], reverse("coordinate_restore_message", args=(case.pk, message.pk)))
        message.refresh_from_db()
        self.assertEqual(message.body, body)
        self.assertEqual(message.deleted_by, self.staff)
        job = CoordinateJob.objects.get(message=message)
        self.assertEqual(job.status, "cancelled")
        self.assertIsNone(job.claim_token)
        self.assertIsNone(job.lease_expires_at)
        self.assertEqual(self.complete(claimed).status_code, 409)
        self.assertIsNone(self.claim()["job"])
        self.assertEqual(self.mutate("coordinate_delete_message", case, message).status_code, 200)
        self.assertEqual(CoordinateActivity.objects.filter(event="message_deleted").count(), 1)
        self.assertEqual(CoordinateMessage.objects.count(), 1)

    def test_deleted_message_restore_requeues_with_new_claim_and_rejects_old_claim(self):
        case, message = self.create_case()
        old_claim = self.claim()
        self.mutate("coordinate_delete_message", case, message)
        restored = self.mutate("coordinate_restore_message", case, message)
        self.assertEqual(restored.status_code, 200)
        self.assertFalse(restored.json()["messages"][0]["deleted"])
        self.assertEqual(restored.json()["messages"][0]["body"], message.body)
        message.refresh_from_db()
        self.assertIsNone(message.deleted_at)
        self.assertIsNone(message.deleted_by)
        self.assertEqual(self.complete(old_claim).status_code, 409)
        new_claim = self.claim()
        self.assertEqual(new_claim["job"]["id"], old_claim["job"]["id"])
        self.assertNotEqual(new_claim["job"]["claim_token"], old_claim["job"]["claim_token"])
        self.assertEqual(self.complete(new_claim).status_code, 200)
        self.assertEqual(self.mutate("coordinate_restore_message", case, message).status_code, 200)
        self.assertEqual(CoordinateActivity.objects.filter(event="message_restored").count(), 1)
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=message).count(), 1)

    def test_message_mutations_are_bound_to_the_selected_case(self):
        case_a, message_a = self.create_case("case A")
        case_b, message_b = self.create_case("case B")
        for name in ("coordinate_delete_message", "coordinate_restore_message"):
            self.assertEqual(self.mutate(name, case_b, message_a).status_code, 404)
        self.assertEqual(CoordinateMessage.objects.filter(deleted_at__isnull=False).count(), 0)
        self.assertEqual(CoordinateMessage.objects.filter(case=case_a).get().pk, message_a.pk)
        self.assertEqual(CoordinateMessage.objects.filter(case=case_b).get().pk, message_b.pk)

    def test_deleting_history_invalidates_later_claim_and_excludes_deleted_exchange(self):
        case, first = self.create_case("old context to remove")
        self.assertEqual(self.complete(self.claim(), body="old generated reply").status_code, 200)
        followup = self.post_message(case, "current request")
        stale = self.claim()
        self.mutate("coordinate_delete_message", case, first)
        self.assertEqual(self.complete(stale).status_code, 409)
        fresh = self.claim()
        self.assertEqual(fresh["job"]["message_id"], followup.pk)
        self.assertNotEqual(fresh["job"]["claim_token"], stale["job"]["claim_token"])
        self.assertEqual([item["body"] for item in fresh["messages"]], [followup.body])
        self.assertEqual(CoordinateMessage.objects.get(in_reply_to=first).body, "old generated reply")
        self.mutate("coordinate_restore_message", case, first)
        self.assertEqual(self.complete(fresh).status_code, 409)
        restored_context = self.claim()
        self.assertEqual([item["body"] for item in restored_context["messages"]], [first.body, "old generated reply", followup.body])

    def test_deleted_oldest_message_does_not_block_later_live_message(self):
        case, first = self.create_case("delete oldest pending input")
        later = self.post_message(case, "keep this input")
        self.mutate("coordinate_delete_message", case, first)
        claimed = self.claim()
        self.assertEqual(claimed["job"]["message_id"], later.pk)
        self.assertEqual([item["body"] for item in claimed["messages"]], [later.body])
        self.mutate("coordinate_restore_message", case, first)
        self.assertEqual(self.complete(claimed).status_code, 409)
        self.assertEqual(self.claim()["job"]["message_id"], first.pk)

    def test_deleting_and_restoring_completed_reply_never_regenerates_it(self):
        case, message = self.create_case()
        claim = self.claim()
        self.assertEqual(self.complete(claim).status_code, 200)
        reply = CoordinateMessage.objects.get(in_reply_to=message)
        self.mutate("coordinate_delete_message", case, reply)
        self.assertTrue(self.state(case).json()["messages"][1]["deleted"])
        self.assertEqual(self.complete(claim).status_code, 409)
        self.assertIsNone(self.claim()["job"])
        self.mutate("coordinate_restore_message", case, reply)
        self.assertFalse(self.state(case).json()["messages"][1]["deleted"])
        self.assertIsNone(self.claim()["job"])
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=message).count(), 1)
        self.assertEqual(CoordinateJob.objects.get(message=message).status, "completed")

    def test_deleted_input_is_not_exposed_through_an_automatically_derived_case_title(self):
        case, message = self.create_case("sensitive first line\nmore details", title="")
        self.assertEqual(case.title, "sensitive first line")
        response = self.mutate("coordinate_delete_message", case, message)
        self.assertNotIn("sensitive first line", response.content.decode())
        self.assertEqual(response.json()["selected_case"]["title"], "Untitled case")
        self.post_message(case, "remaining active input")
        self.assertNotIn("sensitive first line", json.dumps(self.claim()))
        self.mutate("coordinate_restore_message", case, message)
        case.refresh_from_db()
        self.assertEqual(case.title, "sensitive first line")

    def test_case_trash_redacts_conversation_cancels_work_and_is_idempotent(self):
        case, first = self.create_case("case contents must disappear")
        self.post_message(case, "another message in trashed case")
        old_claim = self.claim()
        response = self.mutate("coordinate_delete_case", case)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["cases"], [])
        self.assertEqual(data["trash_cases"][0]["id"], str(case.pk))
        self.assertTrue(data["selected_case"]["deleted"])
        self.assertTrue(all(row["deleted"] and row["body"] == "" for row in data["messages"]))
        self.assertEqual(self.client.get(reverse("coordinate_case", args=(case.pk,))).status_code, 200)
        self.assertNotIn(first.body, self.state(case).content.decode())
        self.assertIsNone(self.claim()["job"])
        self.assertEqual(self.complete(old_claim).status_code, 409)
        self.assertEqual(set(CoordinateJob.objects.values_list("status", flat=True)), {"cancelled"})
        case.refresh_from_db()
        self.assertEqual(case.deleted_by, self.staff)
        self.assertEqual(self.mutate("coordinate_delete_case", case).status_code, 200)
        self.assertEqual(CoordinateActivity.objects.filter(event="case_deleted").count(), 1)
        self.assertEqual(CoordinateMessage.objects.count(), 2)

    def test_case_restore_preserves_individual_deletions_and_historical_replies(self):
        case, completed = self.create_case("already answered")
        self.assertEqual(self.complete(self.claim()).status_code, 200)
        removed = self.post_message(case, "keep individually deleted")
        self.mutate("coordinate_delete_message", case, removed)
        pending = self.post_message(case, "resume this input after restoring case")
        old_claim = self.claim()
        self.mutate("coordinate_delete_case", case)
        restored = self.mutate("coordinate_restore_case", case)
        self.assertEqual(restored.status_code, 200)
        self.assertFalse(restored.json()["selected_case"]["deleted"])
        self.assertEqual(restored.json()["trash_cases"], [])
        removed.refresh_from_db()
        self.assertIsNotNone(removed.deleted_at)
        self.assertEqual(CoordinateJob.objects.get(message=removed).status, "cancelled")
        self.assertEqual(CoordinateJob.objects.get(message=completed).status, "completed")
        self.assertEqual(self.complete(old_claim).status_code, 409)
        new_claim = self.claim()
        self.assertEqual(new_claim["job"]["message_id"], pending.pk)
        self.assertNotEqual(new_claim["job"]["claim_token"], old_claim["job"]["claim_token"])
        self.assertNotIn(removed.body, json.dumps(new_claim))
        self.assertEqual(self.mutate("coordinate_restore_case", case).status_code, 200)
        self.assertEqual(CoordinateActivity.objects.filter(event="case_restored").count(), 1)

    def test_trashed_case_rejects_message_writes_and_individual_restore(self):
        case, message = self.create_case()
        self.mutate("coordinate_delete_message", case, message)
        self.mutate("coordinate_delete_case", case)
        for name in ("coordinate_delete_message", "coordinate_restore_message"):
            self.assertEqual(self.mutate(name, case, message).status_code, 409)
        response = self.client.post(reverse("coordinate_message", args=(case.pk,)), {
            "body": "cannot add to trash", "client_message_id": str(uuid4()),
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(CoordinateMessage.objects.count(), 1)

    def test_duplicate_submission_cannot_resurrect_deleted_message_or_case(self):
        case, message = self.create_case()
        self.mutate("coordinate_delete_message", case, message)
        payload = {"body": message.body, "client_message_id": str(message.client_message_id)}
        self.assertEqual(self.client.post(reverse("coordinate_create"), payload).status_code, 409)
        self.assertEqual(self.client.post(reverse("coordinate_message", args=(case.pk,)), payload).status_code, 409)
        self.mutate("coordinate_restore_message", case, message)
        self.mutate("coordinate_delete_case", case)
        self.assertEqual(self.client.post(reverse("coordinate_create"), payload).status_code, 409)
        self.assertEqual(CoordinateCase.objects.count(), 1)
        self.assertEqual(CoordinateMessage.objects.count(), 1)


@override_settings(
    COORDINATE_WORKER_TOKEN="coordinate-test-token-not-a-real-secret",
    COORDINATE_SHIPPING_PLAYBOOK=SYNTHETIC_SHIPPING_PLAYBOOK,
    COORDINATE_PACKING_PLAYBOOK=SYNTHETIC_PACKING_PLAYBOOK,
)
class CoordinateConcurrencyTests(TransactionTestCase):
    """Exercise the database arbiter with separate connections, not sequential clients."""

    def setUp(self):
        staff = get_user_model().objects.create_user("coordinate-concurrent", is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(reverse("coordinate_create"), {
            "title": "Concurrency test", "body": "one pending message",
            "client_message_id": str(uuid4()),
        })
        self.assertIn(response.status_code, (200, 201, 302))
        self.message = CoordinateMessage.objects.get(body="one pending message")

    def concurrent_posts(self, url, payload, *, other_staff_url=None, retry_conflicts=True):
        barrier = Barrier(2)

        def post(index):
            close_old_connections()
            staff_request = index == 1 and other_staff_url is not None
            client = Client(enforce_csrf_checks=not staff_request)
            if staff_request:
                client.cookies = self.client.cookies.copy()
            request_url = other_staff_url if staff_request else url
            barrier.wait(timeout=10)
            try:
                for attempt in range(20):
                    try:
                        response = client.post(
                            request_url, json.dumps(payload), content_type="application/json",
                            HTTP_AUTHORIZATION="Bearer coordinate-test-token-not-a-real-secret",
                            HTTP_ACCEPT="application/json",
                        )
                    except OperationalError as exc:
                        # SQLite shared-memory test databases cannot wait on locks.
                        # PostgreSQL uses its conditional UPDATE normally. A retried
                        # request must still converge without another saved reply.
                        if "locked" not in str(exc).lower():
                            raise
                        time.sleep(0.01 * (index + 1) * (attempt + 1))
                        continue
                    if response.status_code == 503 or (retry_conflicts and response.status_code == 409):
                        time.sleep(0.01 * (index + 1))
                        continue
                    return response.status_code, response.json()
                raise AssertionError("Concurrent request did not converge after transient locks")
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(post, index) for index in range(2)]
            return [future.result(timeout=20) for future in futures]

    def test_simultaneous_claims_have_one_claimant(self):
        responses = self.concurrent_posts(reverse("coordinate_worker_claim"), {"worker_id": "manual-codex"})
        self.assertTrue(all(status == 200 for status, _ in responses), responses)
        claims = [data["job"] for _, data in responses if data["job"] is not None]
        self.assertEqual(len(claims), 1, responses)
        job = CoordinateJob.objects.get(message=self.message)
        self.assertEqual(job.status, "processing")
        self.assertEqual(job.attempts, 1)
        self.assertEqual(CoordinateActivity.objects.filter(event="job_claimed", job=job).count(), 1)

    def test_simultaneous_completions_save_one_reply_and_activity(self):
        response = self.client.post(
            reverse("coordinate_worker_claim"), json.dumps({"worker_id": "manual-codex"}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer coordinate-test-token-not-a-real-secret",
        )
        self.assertEqual(response.status_code, 200, response.content)
        job = response.json()["job"]
        responses = self.concurrent_posts(reverse("coordinate_worker_complete", args=(job["id"],)), {
            "claim_token": job["claim_token"], "case_id": job["case_id"],
            "message_id": job["message_id"], "worker_id": "manual-codex",
            "body": "one persisted test response",
        })
        self.assertTrue(all(status == 200 for status, _ in responses), responses)
        self.assertEqual(responses[0][1]["reply_id"], responses[1][1]["reply_id"])
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=self.message).count(), 1)
        self.assertEqual(CoordinateActivity.objects.filter(event="reply_saved", job_id=job["id"]).count(), 1)

    def test_message_deletion_racing_claim_cannot_leave_claimed_deleted_work(self):
        responses = self.concurrent_posts(
            reverse("coordinate_worker_claim"), {"worker_id": "manual-codex"},
            other_staff_url=reverse("coordinate_delete_message", args=(self.message.case_id, self.message.pk)),
            retry_conflicts=False,
        )
        self.assertEqual([status for status, _ in responses], [200, 200])
        self.message.refresh_from_db()
        self.assertIsNotNone(self.message.deleted_at)
        job = CoordinateJob.objects.get(message=self.message)
        self.assertEqual(job.status, "cancelled")
        self.assertIsNone(job.claim_token)
        self.assertFalse(CoordinateMessage.objects.filter(in_reply_to=self.message).exists())
        claim = responses[0][1]["job"]
        if claim:
            response = self.client.post(
                reverse("coordinate_worker_complete", args=(claim["id"],)),
                json.dumps({**claim, "worker_id": "manual-codex", "body": "must not save after deletion"}),
                content_type="application/json", HTTP_AUTHORIZATION="Bearer coordinate-test-token-not-a-real-secret",
            )
            self.assertEqual(response.status_code, 409)

    def test_case_deletion_racing_completion_never_saves_a_reply_after_deletion(self):
        response = self.client.post(
            reverse("coordinate_worker_claim"), json.dumps({"worker_id": "manual-codex"}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer coordinate-test-token-not-a-real-secret",
        )
        self.assertEqual(response.status_code, 200)
        job = response.json()["job"]
        payload = {
            "claim_token": job["claim_token"], "case_id": job["case_id"],
            "message_id": job["message_id"], "worker_id": "manual-codex", "body": "racing response",
        }
        responses = self.concurrent_posts(
            reverse("coordinate_worker_complete", args=(job["id"],)), payload,
            other_staff_url=reverse("coordinate_delete_case", args=(self.message.case_id,)),
            retry_conflicts=False,
        )
        self.assertIn(responses[0][0], (200, 409), responses)
        self.assertEqual(responses[1][0], 200, responses)
        case = CoordinateCase.objects.get(pk=self.message.case_id)
        self.assertIsNotNone(case.deleted_at)
        replies = CoordinateMessage.objects.filter(in_reply_to=self.message)
        self.assertLessEqual(replies.count(), 1)
        if replies.exists():
            self.assertLessEqual(replies.get().created_at, case.deleted_at)
        saved_job = CoordinateJob.objects.get(pk=job["id"])
        self.assertIn(saved_job.status, ("cancelled", "completed"))
        self.assertIsNone(saved_job.claim_token)
        retry = self.client.post(
            reverse("coordinate_worker_complete", args=(job["id"],)), json.dumps(payload),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer coordinate-test-token-not-a-real-secret",
        )
        self.assertEqual(retry.status_code, 409)
