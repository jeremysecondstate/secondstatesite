"""One preparation stage preserves existing plans, approvals, and reminders."""
from datetime import timedelta
import importlib
import re
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .coordinate_shipping import coordination_state, enqueue_due_reviews
from .models import CoordinateActivity, CoordinateCase, CoordinateDraft, CoordinateJob, CoordinatePlan, CoordinateQuote


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True)
class CoordinatePreparationStageTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("stage-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.case = CoordinateCase.objects.create(title="Synthetic shipment", created_by=self.staff)
        self.plan_fields = {"destination": "duarte", "handling": "Keep the existing frame", "notes": "Saved private notes"}

    def save_plan(self, stage):
        return self.client.post(reverse("coordinate_plan", args=[self.case.pk]),
            {"stage": stage, **self.plan_fields}, HTTP_ACCEPT="application/json")

    def test_new_plan_and_rendered_options_use_one_preparation_stage(self):
        self.assertEqual(CoordinatePlan().stage, "preparing")
        self.assertEqual(coordination_state(self.case)["plan"]["stage"], "preparing")
        response = self.client.get(reverse("coordinate_case", args=[self.case.pk]))
        self.assertEqual(response.status_code, 200)
        options = re.search(r'<select id="coordinate-plan-stage"[^>]*>(.*?)</select>',
                            response.content.decode(), re.S).group(1)
        self.assertEqual(re.findall(r'<option value="([^"]+)"', options),
                         ["preparing", "ready", "pickup", "transit", "received", "on_hold"])
        self.assertIn('value="preparing" selected>Preparing shipment', options)
        self.assertNotIn("Gathering details", options)
        self.assertNotIn("Collecting quotes", options)

    def test_legacy_submissions_canonicalize_without_clearing_quote_or_draft_review(self):
        CoordinatePlan.objects.create(case=self.case, **self.plan_fields)
        quote = CoordinateQuote.objects.create(case=self.case, provider_name="Synthetic provider",
            provider_email="provider@example.test", amount="100", latest_amount="100", accepted=True,
            accepted_amount="100", accepted_destination="duarte", accepted_handling=self.plan_fields["handling"])
        reviewed_at = timezone.now()
        draft = CoordinateDraft.objects.create(case=self.case, quote=quote, recipient=quote.provider_email,
            subject="Collection", body="Please confirm collection.", status="reviewed", reviewed_by=self.staff,
            reviewed_at=reviewed_at, reviewed_digest="a" * 64)
        for legacy in ("gathering", "quotes"):
            with self.subTest(legacy=legacy):
                response = self.save_plan(legacy)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["coordination"]["plan"]["stage"], "preparing")
                self.assertEqual(CoordinatePlan.objects.get(case=self.case).stage, "preparing")
                quote.refresh_from_db()
                draft.refresh_from_db()
                self.assertTrue(quote.accepted)
                self.assertEqual((draft.status, draft.reviewed_at, draft.reviewed_digest),
                                 ("reviewed", reviewed_at, "a" * 64))
        for stage in ("ready", "pickup", "transit", "received", "on_hold", "preparing"):
            self.assertEqual(self.save_plan(stage).status_code, 200)
            self.assertEqual(CoordinatePlan.objects.get(case=self.case).stage, stage)
        self.assertEqual(self.save_plan("arbitrary-stage").status_code, 400)
        self.assertEqual(CoordinatePlan.objects.get(case=self.case).stage, "preparing")

    def test_preparation_deadlines_remind_once_and_later_stages_keep_existing_rules(self):
        for stage, expected in (("preparing", 1), ("ready", 1), ("pickup", 0), ("transit", 0),
                                ("received", 0), ("on_hold", 0), ("gathering", 1), ("quotes", 1)):
            with self.subTest(stage=stage):
                case = CoordinateCase.objects.create(title=stage, created_by=self.staff)
                plan = CoordinatePlan.objects.create(case=case, pickup_deadline=timezone.now() + timedelta(hours=6))
                # Simulate a legacy row written by the old process during rollout.
                CoordinatePlan.objects.filter(pk=plan.pk).update(stage=stage)
                if stage in ("gathering", "quotes"):
                    self.assertEqual(coordination_state(case)["plan"]["stage"], "preparing")
                enqueue_due_reviews()
                enqueue_due_reviews()
                self.assertEqual(CoordinateJob.objects.filter(message__case=case).count(), expected)
                self.assertEqual(CoordinateActivity.objects.filter(case=case, event="pickup_deadline_review_queued").count(), expected)
                if stage in ("gathering", "quotes"):
                    plan.refresh_from_db()
                    self.assertEqual(plan.stage, "preparing")

    def test_stage_migration_preserves_plan_content_and_original_stage_audit(self):
        before = {}
        for stage in ("gathering", "quotes", "ready", "received"):
            case = CoordinateCase.objects.create(title=stage, created_by=self.staff)
            plan = CoordinatePlan.objects.create(case=case, **self.plan_fields,
                pickup_deadline=timezone.now() + timedelta(days=3), deadline_reminded_at=timezone.now(),
                tracking_number="TRACK-17", tracking_url="https://carrier.example/17")
            CoordinatePlan.objects.filter(pk=plan.pk).update(stage=stage)
            before[case.pk] = CoordinatePlan.objects.values().get(pk=case.pk)
        migration = importlib.import_module("secondstateapp.migrations.0043_coordinate_preparing_stage")
        migration.consolidate_preparation(apps, SimpleNamespace(connection=connection))
        migration.consolidate_preparation(apps, SimpleNamespace(connection=connection))
        for case_id, original in before.items():
            saved = CoordinatePlan.objects.values().get(pk=case_id)
            expected = "preparing" if original["stage"] in ("gathering", "quotes") else original["stage"]
            self.assertEqual(saved, {**original, "stage": expected})
            events = CoordinateActivity.objects.filter(case_id=case_id, event="shipping_stage_consolidated")
            if original["stage"] in ("gathering", "quotes"):
                self.assertEqual(events.count(), 1)
                self.assertEqual(events.get().details, {"previous_stage": original["stage"], "stage": "preparing"})
            else:
                self.assertFalse(events.exists())
