"""Bounded briefing extraction, source provenance, and suggestions without approvals."""

from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from scripts.coordinate_brief_contract import BRIEF_SCHEMA, LOT_LIMITS, validate_brief

from .coordinate_brief import brief_state, save_brief
from .models import (
    CoordinateActivity, CoordinateBrief, CoordinateCase, CoordinateDocument, CoordinateDraft, CoordinateJob,
    CoordinateMessage, CoordinatePlan, CoordinateQuote, CoordinateResearch,
)


def fixture_brief(ref, **changes):
    return {
        "summary": "Listing details for staff review.",
        "lots": [{**{key: "" for key in LOT_LIMITS}, "label": "Synthetic lot 17", "source_refs": [ref]}],
        "plan": {"notes": "Confirm outer frame dimensions before requesting packing.", "pickup_deadline": "",
                 "deadline_basis": "", "source_refs": [ref]},
        "open_questions": ["What are the outer frame dimensions?"],
        **changes,
    }


def fixture_price(ref, **changes):
    return {"kind": "sold", "basis": "unknown", "label": "Sold", "amount": "500.00",
            "amount_high": "", "currency": "", "evidence_quote": "Sold: $500.00",
            "source_refs": [ref], **changes}


class BriefContractTests(SimpleTestCase):
    def test_schema_and_validator_require_the_same_explicit_fields_and_preserve_dimension_scope(self):
        brief = fixture_brief("https://auction.example/lot/17")
        brief["lots"][0].update(dimensions="Image: 13 x 17 inches", framed_dimensions="", framing="Listed as framed")
        original = deepcopy(brief)
        clean = validate_brief(brief)
        self.assertEqual(clean, original)
        self.assertEqual(brief, original)
        self.assertEqual(set(clean), set(BRIEF_SCHEMA["required"]) - {"shipping"})
        self.assertEqual(clean["lots"][0]["dimensions"], "Image: 13 x 17 inches")
        self.assertEqual(clean["lots"][0]["framed_dimensions"], "")
        self.assertIsNone(validate_brief(None))

    def test_unknown_fields_bad_types_and_size_limits_are_rejected(self):
        valid = fixture_brief("message:1")
        invalid = [
            {**valid, "destination": "duarte"}, {**valid, "summary": True},
            {**valid, "summary": "x" * 1201}, {**valid, "lots": valid["lots"] * 9},
            {**valid, "open_questions": ["question"] * 9},
            {**valid, "open_questions": [""]}, {**valid, "open_questions": ["x" * 301]},
            {**valid, "lots": [{**valid["lots"][0], "dimensions": "x" * 301}]},
            {**valid, "lots": [{**valid["lots"][0], "source_refs": []}]},
            {**valid, "lots": [{**valid["lots"][0], "source_refs": ["message:1"] * 2}]},
            {**valid, "lots": [{**valid["lots"][0], "source_refs": [f"message:{i}" for i in range(9)]}]},
            {**valid, "lots": [{**valid["lots"][0], "source_refs": [" message:1"]}]},
            {**valid, "lots": [{**valid["lots"][0], "source_refs": [[]]}]},
            {**valid, "plan": {**valid["plan"], "handling": "Remove the frame"}},
        ]
        missing = deepcopy(valid)
        missing["lots"][0].pop("framed_dimensions")
        invalid.append(missing)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate_brief(item)

    def test_deadline_requires_a_stated_time_timezone_basis_and_source(self):
        valid = fixture_brief("message:1")
        valid["plan"].update(pickup_deadline="2026-10-30T17:00:00-04:00", deadline_basis="Collect by October 30 at 5pm EDT.")
        self.assertEqual(validate_brief(valid)["plan"]["pickup_deadline"], "2026-10-30T17:00:00-04:00")
        for changes in (
            {"pickup_deadline": "2026-10-30"}, {"pickup_deadline": "2026-10-30T17:00:00"},
            {"deadline_basis": "Collect by October 30 EDT."},
            {"deadline_basis": "Collect by October 30 UTC-04:00."},
            {"deadline_basis": "Collect by October 30 at 5pm."},
            {"deadline_basis": ""}, {"source_refs": []},
        ):
            brief = deepcopy(valid)
            brief["plan"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_brief(brief)
        date_only = fixture_brief("message:1")
        date_only["lots"][0]["deadline_text"] = "Collect by October 30; time and zone are unstated."
        self.assertEqual(validate_brief(date_only)["plan"]["pickup_deadline"], "")

    def test_prices_preserve_unknown_currency_and_basis_and_accept_legacy_payloads(self):
        legacy = fixture_brief("message:1")
        self.assertEqual(validate_brief(legacy), legacy)
        brief = deepcopy(legacy)
        brief["lots"][0].update(prices=[fixture_price("message:1")], auction_date="2026-10-17",
                                shipping_contacts="", storage_terms="", price_notes="")
        self.assertEqual(validate_brief(brief), brief)
        self.assertIn("prices", BRIEF_SCHEMA["properties"]["lots"]["items"]["required"])
        for changes in ({"amount": "$500"}, {"amount": "NaN"}, {"amount": "-1"}, {"currency": "$"},
                        {"basis": "estimate"}, {"amount_high": "600"}, {"source_refs": ["message:2"]},
                        {"kind": "estimate", "basis": "unknown"}, {"evidence_quote": ""}):
            invalid = deepcopy(brief)
            invalid["lots"][0]["prices"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_brief(invalid)
        brief["lots"][0]["prices"] = [fixture_price("message:1", kind="estimate", basis="estimate",
                                                    label="Estimate", amount="800", amount_high="1200",
                                                    evidence_quote="Estimate: $800–$1,200")]
        self.assertEqual(validate_brief(brief), brief)


@override_settings(
    COORDINATE_DRAFT_WORKFLOW_ENABLED=True,
    COORDINATE_WORKER_TOKEN="synthetic-brief-worker-secret",
    COORDINATE_SHIPPING_PLAYBOOK="Synthetic shipping reference.",
    COORDINATE_PACKING_PLAYBOOK="Synthetic packing reference.",
)
class BriefEvidenceTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("brief-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.worker = Client(enforce_csrf_checks=True)
        self.case = CoordinateCase.objects.create(title="Synthetic brief case", created_by=self.staff)
        self.message = CoordinateMessage.objects.create(
            case=self.case, role="staff", author=self.staff,
            body="Lot 17 is framed. Collect by October 30 at 5pm EDT.", client_message_id=uuid4(),
        )
        self.job = CoordinateJob.objects.create(message=self.message)
        self.ref = f"message:{self.message.pk}"

    def research(self, *, job=None, **changes):
        job = job or self.job
        return CoordinateResearch.objects.create(
            case=job.message.case, job=job,
            **{"source_url": "https://auction.example/lot/17", "final_url": "https://auction.example/lot/17",
               "title": "Lot 17", "text": "Image dimensions: 13 x 17 inches.",
               "fetched_at": timezone.now(), "error": "", **changes},
        )

    def document(self, *, case=None, message=None, **changes):
        case = case or self.case
        message = message or self.message
        return CoordinateDocument.objects.create(
            case=case, message=message, title="Synthetic pickup instructions", byte_size=80,
            **{"kind": "text", "text": "Collect by October 30 at 5pm EDT.", "extraction_status": "ready", **changes},
        )

    def worker_post(self, name, payload, job_id=None):
        return self.worker.post(
            reverse(name, args=[job_id] if job_id else []), json.dumps(payload), content_type="application/json",
            HTTP_AUTHORIZATION="Bearer synthetic-brief-worker-secret",
        )

    def claim(self):
        response = self.worker_post("coordinate_worker_claim", {"worker_id": "manual-codex"})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["job"]

    def complete(self, claim, brief, **changes):
        return self.worker_post("coordinate_worker_complete", {
            "claim_token": claim["claim_token"], "case_id": claim["case_id"], "message_id": claim["message_id"],
            "worker_id": "manual-codex", "body": "The brief is ready for staff review.", "brief": brief, **changes,
        }, job_id=claim["id"])

    def price_source(self, **changes):
        return {"source_url": "https://auction.example/lot/17", "final_url": "https://market.example/sale/17",
                "source_kind": "public_browser", "title": "Example artist, Example artwork",
                "text": "Example artist. Example artwork. Lot 17. Auction House. October 17, 2026. Sold: $500.00",
                "error": "", "identity_match": {"artist": "Example artist", "title": "Example artwork",
                    "auction_house": "Auction House", "lot_number": "17", "auction_date": "2026-10-17", "status": "exact"},
                **changes}

    def price_brief(self, source=None, **price_changes):
        source = source or self.price_source()
        ref = source["final_url"]
        brief = fixture_brief(ref)
        brief["lots"][0].update(artist="Example artist", title="Example artwork", auction_house="Auction House",
                                lot_number="17", auction_date="2026-10-17", prices=[fixture_price(ref, **price_changes)], price_notes="")
        return brief

    def test_discovered_price_uses_opened_url_unknown_currency_and_preserves_other_failed_lot(self):
        source = self.price_source()
        brief = self.price_brief(source)
        failed = {"source_url": "https://auction.example/lot/18", "final_url": "", "text": "", "error": "Timed out."}
        saved = save_brief(self.job, brief, [source, failed])
        self.assertEqual(saved.payload["lots"][0]["prices"][0]["basis"], "unknown")
        self.assertEqual(saved.payload["lots"][0]["prices"][0]["currency"], "")
        self.assertEqual(saved.payload["lots"][0]["source_refs"], [source["final_url"]])

    def test_price_rejects_snippet_wrong_sale_wrong_lot_and_incomplete_identity(self):
        source = self.price_source()
        for kind, changes in (("search_only", {"status": "unverified"}), ("public_fetch", {"auction_date": "2024-10-17"}),
                              ("public_browser", {"lot_number": "99"}), ("public_browser", {"status": "historical"}),
                              ("public_browser", {"auction_date": ""}), ("public_browser", {"lot_number": ""}),
                              ("public", {"status": "unverified"}), ("browser", {"auction_date": ""})):
            candidate = {**source, "source_kind": kind, "identity_match": {**source["identity_match"], **changes}}
            with self.subTest(kind=kind, changes=changes), self.assertRaises(ValueError):
                save_brief(self.job, self.price_brief(), [candidate])
        self.assertFalse(CoordinateBrief.objects.exists())

    def test_price_amount_label_currency_and_basis_need_exact_evidence(self):
        source = self.price_source()
        for changes in ({"currency": "USD"}, {"amount": "450.00"}, {"basis": "hammer"},
                        {"basis": "premium_inclusive"}, {"evidence_quote": "Sold: $450.00"},
                        {"label": "Hammer price"}, {"label": "Estimate"},
                        {"kind": "invoice_total", "basis": "invoice_total"}, {"kind": "tax", "basis": "tax"},
                        {"kind": "shipping", "basis": "shipping"}, {"kind": "insurance", "basis": "insurance"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                save_brief(self.job, self.price_brief(**changes), [source])
        for kind, basis, label, quote in (
                ("sold", "hammer", "Hammer price", "Hammer price: USD 500.00"),
                ("sold", "premium_inclusive", "Sold", "Sold: USD 500.00 including buyer's premium"),
                ("estimate", "estimate", "Estimate", "Estimate: USD 500.00")):
            valid = self.price_brief(kind=kind, basis=basis, label=label, currency="USD", evidence_quote=quote)
            saved = save_brief(self.job, valid, [{**source, "text": source["text"] + "\n" + quote}])
            self.assertEqual(saved.payload["lots"][0]["prices"][0]["basis"], basis)
            CoordinateBrief.objects.all().delete()

    def test_explicit_premium_exclusion_cannot_support_premium_inclusive_price(self):
        for phrase in ("not including buyer's premium", "including buyer's premium; premium is additional"):
            quote = "Sold: USD 500.00 " + phrase
            with self.subTest(phrase=phrase), self.assertRaises(ValueError):
                save_brief(self.job, self.price_brief(basis="premium_inclusive", currency="USD", evidence_quote=quote),
                           [self.price_source(text=quote)])

    def test_estimate_amount_cannot_be_presented_as_sold_and_conflicts_require_note(self):
        source = self.price_source(text="Sold: USD 500.00. Estimate: USD 800–1,200.")
        with self.assertRaises(ValueError):
            save_brief(self.job, self.price_brief(amount="800", currency="USD",
                       evidence_quote=source["text"]), [source])
        other = self.price_source(final_url="https://other.example/sale/17", text="Sold: USD 450.00")
        brief = self.price_brief(source, currency="USD", evidence_quote="Sold: USD 500.00")
        brief["lots"][0]["source_refs"].append(other["final_url"])
        brief["lots"][0]["prices"].append(fixture_price(other["final_url"], amount="450.00", currency="USD",
                                                       evidence_quote=other["text"]))
        with self.assertRaises(ValueError):
            save_brief(self.job, brief, [source, other])
        brief["lots"][0]["price_notes"] = "Sources disagree: one says USD 500 sold and the other USD 450. Confirm before using either as the purchase amount."
        self.assertIsNotNone(save_brief(self.job, brief, [source, other]))

    def test_historical_comparison_is_separate_and_opened_enrichment_can_supply_missing_price(self):
        source = self.price_source()
        incomplete = {**source, "source_kind": "public_fetch", "text": "Artist and title only. " * 100}
        self.assertIsNotNone(save_brief(self.job, self.price_brief(), [incomplete, source]))
        CoordinateBrief.objects.all().delete()
        history = {**source, "final_url": "https://market.example/older-sale/17",
                   "identity_match": {**source["identity_match"], "auction_date": "2024-10-17", "status": "historical"}}
        brief = self.price_brief(kind="historical_comparison")
        brief["lots"][0]["prices"][0]["source_refs"] = [history["final_url"]]
        brief["lots"][0]["source_refs"].append(history["final_url"])
        self.assertIsNotNone(save_brief(self.job, brief, [incomplete, history]))

    def test_historical_unverified_and_context_pages_do_not_supply_current_artwork_facts(self):
        source = self.price_source()
        for status in ("historical", "unverified", "context"):
            record = {**source, "identity_match": {**source["identity_match"], "status": status}}
            brief = self.price_brief()
            brief["lots"][0]["prices"] = []
            with self.subTest(status=status), self.assertRaises(ValueError):
                save_brief(self.job, brief, [record])
        context = {**source, "identity_match": {"status": "context"}, "text": "Shipping contact: packer@example.test"}
        brief = fixture_brief(source["final_url"])
        brief["lots"][0].update(label="Collection information", shipping_contacts="packer@example.test")
        self.assertIsNotNone(save_brief(self.job, brief, [context]))

    def test_same_url_conflicting_observations_cannot_silently_select_old_price(self):
        source = self.price_source()
        changed = {**source, "source_kind": "public_fetch", "text": "Sold: $450.00"}
        brief = self.price_brief()
        with self.assertRaises(ValueError):
            save_brief(self.job, brief, [changed, source])
        brief["lots"][0]["price_notes"] = "The two observations of this page disagree: $450 and $500. The purchase amount remains unresolved."
        self.assertIsNotNone(save_brief(self.job, brief, [changed, source]))

    def test_current_and_previous_successful_sources_are_resolved_with_browser_provenance(self):
        source = self.research(source_kind="browser", public_error="Public fetch failed.",
                               final_url="https://www.invaluable.com/auction-lot/17")
        later = CoordinateMessage.objects.create(case=self.case, role="staff", body="Continue with the lot details.")
        next_job = CoordinateJob.objects.create(message=later)
        brief = fixture_brief(source.source_url)
        save_brief(next_job, brief, [])
        state = brief_state(self.case)
        self.assertEqual(state["sources"][source.source_url], {
            "label": "Lot 17", "url": "https://www.invaluable.com/auction-lot/17", "kind": "browser",
        })
        self.assertEqual(state["job_id"], str(next_job.pk))
        self.assertEqual(state["lots"], brief["lots"])

    def test_sources_must_be_successful_in_this_case_and_no_later_than_the_claim(self):
        failed = self.research(error="Could not load.")
        other = CoordinateCase.objects.create(title="Other", created_by=self.staff)
        other_message = CoordinateMessage.objects.create(case=other, role="staff", body="Other source")
        other_job = CoordinateJob.objects.create(message=other_message)
        foreign = self.research(job=other_job, source_url="https://other.example/lot/18")
        future_message = CoordinateMessage.objects.create(case=self.case, role="staff", body="Future source")
        future_job = CoordinateJob.objects.create(message=future_message)
        future = self.research(job=future_job, source_url="https://auction.example/lot/19")
        assistant = CoordinateMessage.objects.create(case=self.case, role="assistant", body="Unverified suggestion")
        for ref in (failed.source_url, foreign.source_url, future.source_url, f"message:{other_message.pk}",
                    f"message:{future_message.pk}", f"message:{assistant.pk}", "message:99999", "https://invented.example/lot"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                save_brief(self.job, fixture_brief(ref), [])
        self.assertFalse(CoordinateBrief.objects.exists())

    def test_current_successful_record_can_support_brief_before_source_persistence(self):
        ref = "https://auction.example/lot/17"
        save_brief(self.job, fixture_brief(ref), [{"source_url": ref, "final_url": ref,
                   "title": "Lot 17", "text": "Framed print.", "error": ""}])
        self.assertEqual(CoordinateBrief.objects.count(), 1)
        self.assertIsNone(brief_state(self.case))  # Until the caller persists its source in the same transaction.
        self.research()
        self.assertIsNotNone(brief_state(self.case))

    def test_staff_and_active_documents_are_supported_but_blank_future_and_foreign_documents_are_not(self):
        document = self.document()
        ref = f"document:{document.pk}"
        save_brief(self.job, fixture_brief(ref), [])
        self.assertEqual(brief_state(self.case)["sources"][ref]["url"], f"#coordinate-document-{document.pk}")
        CoordinateBrief.objects.all().delete()
        document.extraction_status, document.text = "no_text", ""
        document.save()
        with self.assertRaises(ValueError):
            save_brief(self.job, fixture_brief(ref), [])
        document.extraction_status, document.text = "truncated", "Readable partial instructions."
        document.save()
        self.assertIsNotNone(save_brief(self.job, fixture_brief(ref), []))
        CoordinateBrief.objects.all().delete()
        future_message = CoordinateMessage.objects.create(case=self.case, role="staff", body="Later document")
        future = self.document(message=future_message)
        other = CoordinateCase.objects.create(title="Other", created_by=self.staff)
        other_message = CoordinateMessage.objects.create(case=other, role="staff", body="Other document")
        foreign = self.document(case=other, message=other_message)
        for rejected in (future, foreign):
            with self.subTest(document=rejected.pk), self.assertRaises(ValueError):
                save_brief(self.job, fixture_brief(f"document:{rejected.pk}"), [])

    def test_resolving_document_sources_does_not_select_private_binary_originals(self):
        document = self.document(kind="pdf", original_pdf=b"synthetic-private-pdf")
        brief = fixture_brief(f"document:{document.pk}")
        with CaptureQueriesContext(connection) as captured:
            save_brief(self.job, brief, [])
            state = brief_state(self.case)
        document_queries = [item["sql"] for item in captured if "secondstateapp_coordinatedocument" in item["sql"]]
        self.assertTrue(document_queries)
        self.assertTrue(all("original_pdf" not in query for query in document_queries))
        self.assertEqual(state["sources"][f"document:{document.pk}"]["kind"], "document")

    def test_earlier_claim_never_sees_later_document_excerpt_research_or_brief(self):
        from .coordinate_shipping import coordination_state

        later = CoordinateMessage.objects.create(case=self.case, role="staff", body="Later document input")
        later_job = CoordinateJob.objects.create(message=later)
        document = self.document(message=later, text="Future document details that are outside this claim.")
        source = self.research(job=later_job, text="Future research details that are outside this claim.")
        later_brief = fixture_brief(f"document:{document.pk}", summary="Future brief outside this claim.")
        save_brief(later_job, later_brief, [])
        generated_draft = CoordinateDraft.objects.create(
            case=self.case, job=later_job, recipient="later@example.test", subject="Later generated draft",
            body="Future document details copied into a later generated draft.",
        )
        manual_draft = CoordinateDraft.objects.create(
            case=self.case, recipient="staff@example.test", subject="Manual draft",
            body="Current staff-maintained instructions.",
        )
        ui = coordination_state(self.case)
        self.assertIn("intake", ui)
        self.assertEqual(ui["intake"]["documents"][0]["id"], str(document.pk))
        self.assertEqual(ui["research"][0]["source_url"], source.source_url)
        self.assertEqual(ui["brief"]["summary"], later_brief["summary"])
        self.assertEqual({item["id"] for item in ui["drafts"]}, {str(generated_draft.pk), str(manual_draft.pk)})

        response = self.worker_post("coordinate_worker_claim", {"worker_id": "manual-codex"})
        self.assertEqual(response.status_code, 200, response.content)
        claimed = response.json()
        self.assertEqual(claimed["job"]["message_id"], self.message.pk)
        self.assertEqual(claimed["documents"], [])
        self.assertNotIn("intake", claimed["coordination"])
        self.assertEqual(claimed["coordination"]["research"], [])
        self.assertEqual(claimed["research"], [])
        self.assertIsNone(claimed["coordination"]["brief"])
        self.assertEqual([item["id"] for item in claimed["coordination"]["drafts"]], [str(manual_draft.pk)])
        self.assertNotIn("Future document details", response.content.decode())
        self.assertNotIn("Future research details", response.content.decode())
        self.assertNotIn("Future brief outside", response.content.decode())
        self.assertNotIn("Later generated draft", response.content.decode())

    def test_deadline_basis_must_match_cited_evidence_and_suggestion_does_not_change_plan_or_approval(self):
        plan = CoordinatePlan.objects.create(case=self.case, destination="duarte", handling="Keep frame", notes="Staff notes")
        quote = CoordinateQuote.objects.create(case=self.case, provider_name="Packer", provider_email="packer@example.test",
                                               amount=100, latest_amount=100, accepted=True, accepted_amount=100)
        brief = fixture_brief(self.ref)
        brief["plan"].update(pickup_deadline="2026-10-30T17:00:00-04:00", deadline_basis="Collect by October 30 at 5pm EDT.")
        saved = save_brief(self.job, brief, [])
        self.assertEqual(saved.payload["plan"]["pickup_deadline"], "2026-10-30T17:00:00-04:00")
        plan.refresh_from_db()
        quote.refresh_from_db()
        self.assertIsNone(plan.pickup_deadline)
        self.assertEqual(plan.notes, "Staff notes")
        self.assertEqual(plan.handling, "Keep frame")
        self.assertTrue(quote.accepted)
        CoordinateBrief.objects.all().delete()
        brief["plan"]["deadline_basis"] = "Collect by November 1 at 5pm EDT."
        with self.assertRaises(ValueError):
            save_brief(self.job, brief, [])

    def test_brief_is_immutable_and_completion_replay_does_not_duplicate_it(self):
        claim, brief = self.claim(), fixture_brief(self.ref)
        first = self.complete(claim, brief)
        self.assertEqual(first.status_code, 200, first.content)
        retry = self.complete(claim, brief)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertTrue(retry.json()["already_completed"])
        self.assertEqual(CoordinateBrief.objects.count(), 1)
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=self.message).count(), 1)
        changed = {**brief, "summary": "Changed summary"}
        self.assertEqual(self.complete(claim, changed).status_code, 409)
        self.assertEqual(self.complete(claim, None).status_code, 409)
        with self.assertRaises(ValueError):
            save_brief(self.job, changed, [])
        self.assertEqual(CoordinateBrief.objects.get().payload["summary"], brief["summary"])

    def test_old_public_completion_cannot_gain_a_brief_through_legacy_digest_fallback(self):
        from .coordinate_shipping import validate_worker_artifacts

        claim = self.claim()
        source = {"source_url": "https://auction.example/lot/17", "final_url": "https://auction.example/lot/17",
                  "text": "Framed print.", "title": "Lot 17", "error": "", "fetched_at": timezone.now().isoformat()}
        first = self.complete(claim, None, research=[source])
        self.assertEqual(first.status_code, 200, first.content)
        research, drafts = validate_worker_artifacts({"research": [source]})
        legacy_research = [{key: value for key, value in item.items() if key not in ("source_kind", "public_error")}
                           for item in research]
        old_digest = hashlib.sha256(json.dumps({
            "body": "The brief is ready for staff review.", "artifacts": (legacy_research, drafts),
        }, sort_keys=True, default=str).encode()).hexdigest()
        CoordinateJob.objects.filter(pk=self.job.pk).update(completion_digest=old_digest)
        self.assertEqual(self.complete(claim, fixture_brief(source["source_url"]), research=[source]).status_code, 409)
        self.assertFalse(CoordinateBrief.objects.exists())
        retry = self.complete(claim, None, research=[source])
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertTrue(retry.json()["already_completed"])

    def test_brief_completion_accepts_its_new_source_in_one_atomic_save(self):
        claim = self.claim()
        source = {"source_url": "https://auction.example/lot/17", "final_url": "https://auction.example/lot/17",
                  "text": "Framed print.", "title": "Lot 17", "error": "", "fetched_at": timezone.now().isoformat()}
        response = self.complete(claim, fixture_brief(source["source_url"]), research=[source])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CoordinateBrief.objects.count(), 1)
        self.assertEqual(CoordinateResearch.objects.count(), 1)
        self.assertEqual(brief_state(self.case)["sources"][source["source_url"]]["label"], "Lot 17")

    @override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=False)
    def test_disabled_workspace_rejects_brief_before_completing_job(self):
        claim = self.claim()
        response = self.complete(claim, fixture_brief(self.ref))
        self.assertEqual(response.status_code, 400, response.content)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "processing")
        self.assertFalse(CoordinateBrief.objects.exists())
        self.assertFalse(CoordinateMessage.objects.filter(in_reply_to=self.message).exists())

    def test_bad_source_rolls_back_the_reply_job_and_research(self):
        self.message.body += " Contact packer@example.test."
        self.message.save(update_fields=["body"])
        claim = self.claim()
        source = {"source_url": "https://auction.example/lot/17", "final_url": "https://auction.example/lot/17",
                  "text": "Framed print.", "title": "Lot 17", "error": "", "fetched_at": timezone.now().isoformat()}
        response = self.complete(claim, fixture_brief("https://unrelated.example/lot"), research=[source], drafts=[{
            "recipient": "packer@example.test", "subject": "Collection details", "body": "Please share collection details.",
        }])
        self.assertEqual(response.status_code, 400, response.content)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "processing")
        self.assertFalse(CoordinateResearch.objects.exists())
        self.assertFalse(CoordinateDraft.objects.exists())
        self.assertFalse(CoordinateBrief.objects.exists())
        self.assertFalse(CoordinateMessage.objects.filter(in_reply_to=self.message).exists())
        self.assertFalse(CoordinateActivity.objects.filter(event="research_and_drafts_saved").exists())

    def test_deleted_source_document_hides_a_later_brief_and_restoring_it_restores_visibility(self):
        document = self.document()
        later = CoordinateMessage.objects.create(case=self.case, role="staff", body="Please prepare the pickup plan.")
        job = CoordinateJob.objects.create(message=later)
        save_brief(job, fixture_brief(f"document:{document.pk}"), [])
        self.assertIsNotNone(brief_state(self.case))
        self.message.deleted_at = timezone.now()
        self.message.save(update_fields=["deleted_at"])
        self.assertIsNone(brief_state(self.case))
        self.message.deleted_at = None
        self.message.save(update_fields=["deleted_at"])
        self.assertIsNotNone(brief_state(self.case))

    def test_latest_valid_brief_hides_deleted_research_inputs_and_reply(self):
        older = save_brief(self.job, fixture_brief(self.ref), [])
        source = self.research()
        later = CoordinateMessage.objects.create(case=self.case, role="staff", body="Make a new brief.")
        job = CoordinateJob.objects.create(message=later)
        latest = save_brief(job, fixture_brief(source.source_url), [])
        self.assertEqual(brief_state(self.case)["id"], latest.pk)
        reply = CoordinateMessage.objects.create(case=self.case, role="assistant", body="Source reply", in_reply_to=self.message)
        reply.deleted_at = timezone.now()
        reply.save(update_fields=["deleted_at"])
        # The older brief's own reply and the latest brief's research evidence are hidden.
        self.assertIsNone(brief_state(self.case))
        reply.deleted_at = None
        reply.save(update_fields=["deleted_at"])
        later.deleted_at = timezone.now()
        later.save(update_fields=["deleted_at"])
        self.assertEqual(brief_state(self.case)["id"], older.pk)
        self.case.deleted_at = timezone.now()
        self.case.save(update_fields=["deleted_at"])
        self.assertIsNone(brief_state(self.case))
