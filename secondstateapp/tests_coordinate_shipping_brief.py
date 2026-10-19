"""Shipping proposals preserve evidence boundaries and do not approve actions."""
from copy import deepcopy

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from scripts.coordinate_brief_contract import BRIEF_SCHEMA, brief_source_refs, validate_brief, validate_price_evidence
from .coordinate_brief import brief_state, save_brief
from .models import CoordinateBrief, CoordinateCase, CoordinateJob, CoordinateMessage, CoordinatePlan, CoordinateResearch
from .tests_coordinate_brief import fixture_brief, fixture_price


URL = "https://house.example/shipping"
CONTACT = "Example Packers\npacking@example.test"
CAPABILITY = "Example Packers provides packing, crating and shipping for fine art."
TEXT = "Pickup: Scottsdale, Arizona 85251.\n" + CONTACT + "\n" + CAPABILITY + "\nCollect within seven days."


def shipping_fixture(ref=URL):
    return {
        "working_currency": {"code": "USD", "basis": "inferred", "note": "Working USD inferred from the Arizona pickup location.", "source_refs": [ref]},
        "quote_readiness": {"status": "conditional_ready", "note": "Request conditional quotes using both stated size scenarios."},
        "actions": [{"owner": "provider", "stage": "quote", "text": "Confirm packing suitability and quote both dimension scenarios.", "source_refs": [ref]},
                    {"owner": "staff", "stage": "release", "text": "Confirm the release is authorized before collection.", "source_refs": []}],
        "providers": [{"name": "Example Packers", "email": "packing@example.test", "service_type": "full_service",
                       "published_capability": CAPABILITY, "contact_quote": CONTACT, "source_refs": [ref]}],
        "site_checks": [{"topic": "pickup", "status": "found", "note": "Collect within seven days.", "source_refs": [ref]},
                        {"topic": "storage", "status": "not_found_in_checked_pages", "note": "No storage rate found in the checked page excerpt.", "source_refs": [ref]},
                        {"topic": "third_party_release", "status": "not_checked", "note": "Release terms remain to be checked.", "source_refs": []}],
    }


def source_fixture(ref=URL, **changes):
    return {"source_url": "https://house.example/lot/17", "final_url": ref, "title": "House shipping",
            "source_kind": "public_browser", "error": "", "text": TEXT,
            "identity_match": {"status": "context", "auction_house": "Example House"}, "attempts": [], **changes}


def evidence_for(*sources):
    evidence = {}
    for source in sources:
        ref = source.get("final_url") or source["source_url"]
        evidence.setdefault(ref, {"observations": []})["observations"].append({
            "kind": source["source_kind"], "text": source["text"], "error": source.get("error", ""),
            "identity_match": source.get("identity_match", {}), "attempts": source.get("attempts", []),
        })
    return evidence


class ShippingBriefContractTests(SimpleTestCase):
    def setUp(self):
        self.brief = fixture_brief(URL, shipping=shipping_fixture())
        self.evidence = evidence_for(source_fixture())

    def validate(self, brief=None, evidence=None):
        clean = validate_brief(brief or self.brief)
        validate_price_evidence(clean, evidence or self.evidence)
        return clean

    def test_new_strict_schema_requires_shipping_but_legacy_payload_stays_unchanged(self):
        old = fixture_brief(URL)
        self.assertEqual(validate_brief(old), old)
        self.assertNotIn("shipping", validate_brief(old))
        self.assertIn("shipping", BRIEF_SCHEMA["required"])
        self.assertEqual(self.validate(), self.brief)
        self.assertIn(URL, brief_source_refs(self.brief))

    def test_inferred_working_usd_does_not_change_unknown_sale_currency_or_block_quotes(self):
        lot_url = "https://house.example/lot/17"
        source = source_fixture(lot_url, text="Example Artist. Example Work. Sold: $500.00", identity_match={
            "status": "exact", "artist": "Example Artist", "title": "Example Work", "auction_house": "Example House",
            "auction_date": "2026-10-17", "lot_number": "17"})
        brief = deepcopy(self.brief)
        brief["lots"][0].update(artist="Example Artist", title="Example Work", auction_house="Example House",
            auction_date="2026-10-17", lot_number="17", prices=[fixture_price(lot_url)], source_refs=[lot_url])
        clean = self.validate(brief, evidence_for(source_fixture(), source))
        self.assertEqual(clean["shipping"]["working_currency"]["code"], "USD")
        self.assertEqual(clean["lots"][0]["prices"][0]["currency"], "")
        self.assertEqual(clean["shipping"]["quote_readiness"]["status"], "conditional_ready")
        brief["lots"][0]["prices"][0]["currency"] = "USD"
        with self.assertRaises(ValueError):
            self.validate(brief, evidence_for(source_fixture(), source))

    def test_working_currency_requires_its_separate_supported_basis(self):
        invalid = deepcopy(self.brief)
        for changes in ({"basis": "source"}, {"basis": "staff"}, {"code": "CAD"}, {"source_refs": []}, {"note": ""}):
            invalid["shipping"]["working_currency"] = {**self.brief["shipping"]["working_currency"], **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(invalid)
        with self.assertRaises(ValueError):
            self.validate(evidence=evidence_for(source_fixture(text=TEXT.replace("Scottsdale, Arizona 85251", "Toronto, Canada"))))
        source = source_fixture(text=TEXT + "\nQuotes in USD.")
        invalid["shipping"]["working_currency"] = {"code": "USD", "basis": "source", "note": "Published quote currency.", "source_refs": [URL]}
        self.validate(invalid, evidence_for(source))

    def test_provider_contact_and_capability_require_current_opened_exact_wording(self):
        for source in (source_fixture(source_kind="search_only"), source_fixture(error="Timed out"),
                       source_fixture(identity_match={"status": "historical"}), source_fixture(identity_match={"status": "unverified"})):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.validate(evidence=evidence_for(source))
        for changes in ({"email": "other@example.test"}, {"name": "Different Packers"},
                        {"contact_quote": "Example Packers packing@example.test — invented wording"},
                        {"published_capability": "We guarantee safe insured delivery."},
                        {"service_type": "parcel_shipping"}):
            brief = deepcopy(self.brief)
            brief["shipping"]["providers"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(brief)
        # Adjacent lines in a house's recommended-provider list remain usable.
        self.validate()
        brief = deepcopy(self.brief)
        brief["shipping"]["providers"][0].update(published_capability="", service_type="unknown")
        self.validate(brief)
        brief["shipping"]["providers"][0].update(published_capability="Other Packers provides packing and shipping.")
        with self.assertRaises(ValueError):
            self.validate(brief, evidence_for(source_fixture(text=TEXT + "\nOther Packers provides packing and shipping.")))

    def test_site_checks_are_scoped_and_failed_launch_cannot_claim_failed_page_access(self):
        failed_url = "https://house.example/storage"
        failed = source_fixture(failed_url, error="Timed out", text="", attempts=[{
            "method": "public_browser", "status": "timeout"}])
        brief = deepcopy(self.brief)
        brief["shipping"]["site_checks"] = [{"topic": "storage", "status": "access_failed", "note": "Storage page timed out.", "source_refs": [failed_url]}]
        self.validate(brief, evidence_for(source_fixture(), failed))
        failed["attempts"] = [{"method": "browser_launch", "status": "tool_unavailable"}]
        with self.assertRaises(ValueError):
            self.validate(brief, evidence_for(source_fixture(), failed))
        failed["attempts"] = [{"method": "public_browser", "status": "timeout"}]
        brief["shipping"]["site_checks"][0]["status"] = "not_found_in_checked_pages"
        with self.assertRaises(ValueError):
            self.validate(brief, evidence_for(source_fixture(), failed))
        brief = deepcopy(self.brief)
        brief["shipping"]["site_checks"][0]["note"] = "Storage is free for a year."
        with self.assertRaises(ValueError):
            self.validate(brief)

    def test_provider_repair_paths_preserve_valid_contact_without_merging_alias_capability(self):
        brief = deepcopy(self.brief)
        alias = deepcopy(brief["shipping"]["providers"][0])
        alias.update(name="Example Packers #267", contact_quote="Example Packers #267\npacking@example.test")
        brief["shipping"]["providers"].append(alias)
        evidence = evidence_for(source_fixture(text=TEXT + "\n" + alias["contact_quote"]))
        with self.assertRaisesRegex(ValueError, r"shipping\.providers\[1\]\.published_capability") as error:
            self.validate(brief, evidence)
        self.assertIn('published_capability="" and service_type="unknown"', str(error.exception))
        # The verified contact remains useful without borrowing an alias's capability.
        alias.update(published_capability="", service_type="unknown")
        self.validate(brief, evidence)
        alias["contact_quote"] = CONTACT
        with self.assertRaisesRegex(ValueError, r"shipping\.providers\[1\]\.contact_quote") as error:
            self.validate(brief, evidence)
        self.assertIn("omit this provider", str(error.exception))
        self.assertNotIn(alias["email"], str(error.exception))

    def test_summarized_site_check_has_actionable_path_and_can_be_omitted_independently(self):
        brief = deepcopy(self.brief)
        brief["shipping"]["site_checks"][1].update(status="found", note="Collect in seven days.")
        with self.assertRaisesRegex(ValueError, r"shipping\.site_checks\[1\]\.note") as error:
            self.validate(brief)
        self.assertIn("shipping_research_notes.detail is a summary, not a quote", str(error.exception))
        brief["shipping"]["site_checks"].pop(1)
        cleaned = self.validate(brief)
        self.assertEqual(cleaned["lots"], self.brief["lots"])
        self.assertEqual(cleaned["shipping"]["providers"], self.brief["shipping"]["providers"])

    def test_found_note_must_entirely_match_source_not_contain_a_quote_with_commentary(self):
        for note in ('"Collect within seven days."',
                     'Pickup terms: "Collect within seven days."',
                     "Collect within seven days. Exact pickup time remains to confirm.",
                     "Collect within seven days. Pickup: Scottsdale, Arizona 85251."):
            brief = deepcopy(self.brief)
            brief["shipping"]["site_checks"][0]["note"] = note
            with self.subTest(note=note), self.assertRaises(ValueError) as error:
                self.validate(brief)
            self.assertIn("Entire note must be one exact contiguous excerpt", str(error.exception))
            self.assertIn("without added quotation marks", str(error.exception))
        self.validate()

    def test_shipping_reference_repair_identifies_record_and_reference_index(self):
        historical_url = "https://provider.example/old-services"
        historical = source_fixture(historical_url, identity_match={"status": "historical"})
        brief = deepcopy(self.brief)
        brief["shipping"]["providers"][0]["source_refs"].append(historical_url)
        with self.assertRaisesRegex(ValueError, r"shipping\.providers\[0\]\.source_refs\[1\]"):
            self.validate(brief, evidence_for(source_fixture(), historical))

    def test_all_invalid_shipping_entries_are_reported_in_one_bounded_correction(self):
        brief = deepcopy(self.brief)
        brief["shipping"]["working_currency"]["basis"] = "source"
        brief["shipping"]["providers"][0]["contact_quote"] = "Unsupported provider contact."
        brief["shipping"]["site_checks"] = [
            {"topic": topic, "status": "found", "note": "A summary that does not quote the source.", "source_refs": [URL]}
            for topic in ("pickup", "storage", "third_party_release", "house_recommended", "nearby_ups", "fine_art_packers")
        ]
        with self.assertRaises(ValueError) as error:
            self.validate(brief)
        diagnostic = str(error.exception)
        self.assertIn("shipping.working_currency.source_refs:", diagnostic)
        self.assertIn("shipping.providers[0].contact_quote:", diagnostic)
        for index in range(6):
            self.assertIn(f"shipping.site_checks[{index}].note:", diagnostic)
        self.assertLessEqual(len(diagnostic), 4000)
        # Correcting the first entry alone never accepts the remaining claims.
        brief["shipping"]["working_currency"]["basis"] = "inferred"
        with self.assertRaises(ValueError) as error:
            self.validate(brief)
        self.assertNotIn("shipping.working_currency", str(error.exception))
        self.assertIn("shipping.site_checks[5].note:", str(error.exception))

    def test_shipping_diagnostic_bound_retains_every_maximum_entry_path(self):
        brief = deepcopy(self.brief)
        historical_url = "https://provider.example/old-services"
        historical = source_fixture(historical_url, identity_match={"status": "historical"})
        brief["shipping"]["working_currency"]["source_refs"] = [historical_url]
        brief["shipping"]["actions"] = [
            {"owner": "provider", "stage": "quote", "text": "Confirm handling suitability.", "source_refs": [historical_url]}
            for _ in range(8)
        ]
        brief["shipping"]["providers"] = [
            {**self.brief["shipping"]["providers"][0], "name": f"Unsupported provider {index}"}
            for index in range(6)
        ]
        brief["shipping"]["site_checks"] = [
            {"topic": "pickup", "status": "found", "note": "Unsupported pickup summary.", "source_refs": [URL]}
            for _ in range(8)
        ]
        with self.assertRaises(ValueError) as error:
            self.validate(brief, evidence_for(source_fixture(), historical))
        diagnostic = str(error.exception)
        self.assertLessEqual(len(diagnostic), 4000)
        self.assertIn("shipping.working_currency.source_refs[0]:", diagnostic)
        for field, count, suffix in (("actions", 8, "source_refs[0]"), ("providers", 6, "contact_quote"), ("site_checks", 8, "note")):
            for index in range(count):
                self.assertIn(f"shipping.{field}[{index}].{suffix}:", diagnostic)

    def test_failed_observations_only_support_scoped_access_checks_not_lots_or_prices(self):
        failed = source_fixture(error="Unavailable", text=TEXT)
        with self.assertRaises(ValueError):
            self.validate(evidence=evidence_for(failed))
        brief = deepcopy(self.brief)
        brief["lots"][0]["source_refs"] = ["https://unrelated.example/"]
        with self.assertRaises(ValueError):
            self.validate(brief)

    def test_shipping_bounds_unknown_fields_and_classifications_fail_closed(self):
        for mutate in (lambda shipping: shipping["providers"].append(deepcopy(shipping["providers"][0])),
                       lambda shipping: shipping.update(actions=shipping["actions"] * 5),
                       lambda shipping: shipping["providers"][0].update(email="bad@-host.test"),
                       lambda shipping: shipping["actions"][0].update(stage="payment"),
                       lambda shipping: shipping["quote_readiness"].update(status="approved"),
                       lambda shipping: shipping.update(sent=True)):
            brief = deepcopy(self.brief)
            mutate(brief["shipping"])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.validate(brief)


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True)
class ShippingBriefPersistenceTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("shipping-brief-staff", is_staff=True)
        self.case = CoordinateCase.objects.create(title="Shipping brief", created_by=self.staff)
        self.message = CoordinateMessage.objects.create(case=self.case, role="staff", author=self.staff, body="Prepare conditional shipping quotes.")
        self.job = CoordinateJob.objects.create(message=self.message)
        self.source = CoordinateResearch.objects.create(case=self.case, job=self.job, fetched_at=timezone.now(), **source_fixture())

    def test_shipping_is_durable_cited_and_never_mutates_saved_plan(self):
        brief = fixture_brief(URL, shipping=shipping_fixture())
        saved = save_brief(self.job, brief)
        self.assertEqual(saved.payload, brief)
        state = brief_state(self.case)
        self.assertEqual(state["shipping"], brief["shipping"])
        self.assertEqual(state["sources"][URL]["url"], URL)
        self.assertFalse(CoordinatePlan.objects.exists())
        self.message.deleted_at = timezone.now()
        self.message.save(update_fields=["deleted_at"])
        self.assertIsNone(brief_state(self.case))

    def test_future_provider_sources_do_not_enter_earlier_job(self):
        later = CoordinateMessage.objects.create(case=self.case, role="staff", author=self.staff, body="Later research")
        later_job = CoordinateJob.objects.create(message=later)
        future_url = "https://provider.example/contact"
        CoordinateResearch.objects.create(case=self.case, job=later_job, fetched_at=timezone.now(), **source_fixture(future_url))
        brief = fixture_brief(URL, shipping=shipping_fixture())
        brief["shipping"]["providers"][0]["source_refs"] = [future_url]
        with self.assertRaises(ValueError):
            save_brief(self.job, brief)
        self.assertFalse(CoordinateBrief.objects.exists())

    def test_saved_failed_attempt_can_be_cited_only_as_a_site_access_failure(self):
        url = "https://house.example/terms"
        CoordinateResearch.objects.create(case=self.case, job=self.job, fetched_at=timezone.now(),
            **source_fixture(url, text="", error="Timed out", attempts=[{"method": "public_fetch", "status": "timeout"}]))
        brief = fixture_brief(URL, shipping=shipping_fixture())
        brief["shipping"]["site_checks"] = [{"topic": "storage", "status": "access_failed", "note": "Terms page timed out.", "source_refs": [url]}]
        save_brief(self.job, brief)
        self.assertIn(url, brief_state(self.case)["sources"])
