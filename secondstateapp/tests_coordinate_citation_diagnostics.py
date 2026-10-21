"""Precise citation repair feedback while preserving evidence validation."""

from copy import deepcopy
import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest import TestCase
from unittest.mock import patch

from scripts import coordinate_worker as worker
from scripts.coordinate_brief_contract import LOT_LIMITS, validate_brief, validate_price_evidence
from .tests_coordinate_worker import claim_payload


SOURCE = "https://packing.example/artwork"


def brief_fixture():
    return {
        "summary": "Packing research.", "lots": [],
        "plan": {"notes": "Ask about packing.", "pickup_deadline": "", "deadline_basis": "",
                 "source_refs": [SOURCE]},
        "open_questions": [],
    }


class CitationDiagnosticsTests(TestCase):
    def test_malformed_reference_names_exact_index_without_silently_repairing_it(self):
        brief = brief_fixture()
        brief["plan"]["source_refs"] = ["message:1", SOURCE + " ill-formed citation inserted here to be removed? "]
        original = deepcopy(brief)
        with self.assertRaisesRegex(ValueError, r"plan\.source_refs\[1\]: Source references must be exact"):
            validate_brief(brief)
        self.assertEqual(brief, original)

    def test_duplicate_and_invalid_price_reference_report_nested_field(self):
        brief = brief_fixture()
        brief["lots"] = [{**{key: "" for key in LOT_LIMITS}, "label": "Lot 1", "source_refs": [SOURCE, SOURCE]}]
        with self.assertRaisesRegex(ValueError, r"lots\[0\]\.source_refs\[1\]: Duplicate"):
            validate_brief(brief)
        brief["lots"][0]["source_refs"] = [SOURCE]
        brief["lots"][0]["prices"] = [{
            "kind": "sold", "basis": "unknown", "label": "Sold", "amount": "500",
            "amount_high": "", "currency": "", "evidence_quote": "Sold: $500", "source_refs": [False],
        }]
        with self.assertRaisesRegex(ValueError, r"lots\[0\]\.prices\[0\]\.source_refs\[0\]"):
            validate_brief(brief)

    def test_shipping_reference_shape_error_keeps_shipping_field_path(self):
        brief = brief_fixture()
        brief["shipping"] = {
            "working_currency": {"code": "", "basis": "unknown", "note": "", "source_refs": []},
            "quote_readiness": {"status": "not_assessed", "note": ""},
            "actions": [], "providers": [],
            "site_checks": [{"topic": "pickup", "status": "found", "note": "Pickup available.",
                             "source_refs": [SOURCE + " "]}],
        }
        with self.assertRaisesRegex(ValueError, r"shipping\.site_checks\[0\]\.source_refs\[0\]"):
            validate_brief(brief)

    def test_unknown_reference_reports_field_and_available_ids_but_never_accepts_similarity(self):
        brief = brief_fixture()
        brief["plan"]["source_refs"] = [SOURCE + " appended commentary"]
        evidence = {SOURCE: {"kind": "public", "text": "Opened source text must not be copied into diagnostics."}}
        with self.assertRaises(ValueError) as failure:
            validate_price_evidence(validate_brief(brief), evidence)
        diagnostic = str(failure.exception)
        self.assertIn("plan.source_refs[0]", diagnostic)
        self.assertIn(json.dumps(SOURCE), diagnostic)
        self.assertIn("otherwise remove the unsupported claim", diagnostic)
        self.assertNotIn(evidence[SOURCE]["text"], diagnostic)

    def test_diagnostics_remain_within_existing_repair_budget(self):
        brief = brief_fixture()
        brief["lots"] = [{**{key: "" for key in LOT_LIMITS}, "label": f"Lot {index}",
                          "source_refs": [f"https://missing.example/{index}/{ref}" for ref in range(8)]}
                         for index in range(8)]
        evidence = {f"https://available.example/{index}/" + "x" * 1800:
                    {"kind": "public", "text": "Opened content."} for index in range(50)}
        with self.assertRaises(ValueError) as failure:
            validate_price_evidence(validate_brief(brief), evidence)
        diagnostic = str(failure.exception)
        self.assertLessEqual(len(diagnostic), 4000)
        self.assertIn("lots[0].source_refs[0]", diagnostic)
        self.assertIn("additional references are unavailable", diagnostic)
        self.assertIn("Additional reference IDs", diagnostic)

    def test_existing_failed_page_evidence_is_still_rejected_with_its_location(self):
        with self.assertRaisesRegex(ValueError, r"plan\.source_refs\[0\].*readable evidence"):
            validate_price_evidence(validate_brief(brief_fixture()), {
                SOURCE: {"kind": "public", "text": "", "error": "unavailable"},
            })


class CitationRepairWorkerTests(TestCase):
    def test_existing_bounded_repair_receives_exact_field_and_allowed_reference(self):
        payload = claim_payload()
        payload.update(test_mode=False, draft_only=True, brief_enabled=True,
                       research=[{"source_url": SOURCE, "source_kind": "public", "text": "Packing available."}])
        invalid = brief_fixture()
        invalid["plan"]["source_refs"] = [SOURCE + " appended commentary"]
        corrected = brief_fixture()
        prompts = []

        def process(command, **kwargs):
            prompts.append(kwargs["input"])
            response = {"body": "Prepared for review.", "drafts": [],
                        "brief": invalid if len(prompts) == 1 else corrected}
            (Path(kwargs["cwd"]) / "response.json").write_text(json.dumps(response), encoding="utf-8")
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

        with patch.object(worker.subprocess, "run", side_effect=process), \
                patch.object(worker, "_save_generation_diagnostics"):
            result = worker.generate_reply(payload, "codex")
        self.assertEqual(len(prompts), 2)
        correction = prompts[1].split("VALIDATION CORRECTION:", 1)[1]
        self.assertIn("plan.source_refs[0]", correction)
        self.assertIn("Available reference IDs", correction)
        self.assertIn(json.dumps(SOURCE), correction)
        self.assertEqual(result["brief"], corrected)

    def test_two_invalid_attempts_still_fail_without_normalizing_unknown_reference(self):
        payload = claim_payload()
        payload.update(test_mode=False, draft_only=True, brief_enabled=True,
                       research=[{"source_url": SOURCE, "source_kind": "public", "text": "Packing available."}])
        invalid = brief_fixture()
        invalid["plan"]["source_refs"] = [SOURCE + " appended commentary"]
        calls = []

        def process(command, **kwargs):
            calls.append(kwargs)
            (Path(kwargs["cwd"]) / "response.json").write_text(json.dumps({
                "body": "Prepared for review.", "drafts": [], "brief": invalid,
            }), encoding="utf-8")
            return CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

        with patch.object(worker.subprocess, "run", side_effect=process), \
                patch.object(worker, "_save_generation_diagnostics"), \
                self.assertRaises(worker.WorkerError):
            worker.generate_reply(payload, "codex")
        self.assertEqual(len(calls), 2)
