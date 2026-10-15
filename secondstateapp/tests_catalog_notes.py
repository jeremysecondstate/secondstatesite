import json
import os
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from secondstate.artwork_notes import clean_public_notes

from .catalog_api_views import _generate_notes
from .models import Artwork


class PublicNotesCleanupTests(SimpleTestCase):
    def test_screenshot_fairey_accounting_is_removed_and_art_facts_survive(self):
        source = (
            "Portrait of Common. Signed and dated in pencil; sheet 61 x 91 cm (portrait). "
            "Excellent condition per auctioneer. Invoice V01760: hammer EUR 50 + Drouot fee EUR 0.75 + "
            "VAT EUR 0.15 = EUR 50.90, paid 7/20/2026. USD conversion: EUR 1 = USD 1.1435, "
            "ECB 7/17/2026 (last business day before Sunday sale). Year, edition and shipping not stated."
        )
        self.assertEqual(
            clean_public_notes(source),
            "Portrait of Common. Signed and dated in pencil; sheet 61 x 91 cm (portrait). "
            "Excellent condition per auctioneer.",
        )

    def test_benton_public_notes_preserve_condition_framing_and_provenance(self):
        source = (
            "Signed in pencil lower right. A very good impression of this scarce print. Fath p. 6-7. "
            "Framed 21.75 x 25.75 in. Condition: extremely pale mat burn; otherwise good and clean. "
            "Lot 4073. Notes say the lithograph appeared on the November 1951 cover of The New Republic "
            "for Benton's article “Disaster on the Kaw” and was purchased directly from the Benton estate "
            "from Benton's daughter, Jessie."
        )
        self.assertEqual(clean_public_notes(source), source)

    def test_art_fact_sharing_clause_with_invoice_is_retained(self):
        self.assertEqual(
            clean_public_notes("Signed in pencil, invoice V99: EUR 50; Condition per auctioneer: good."),
            "Signed in pencil; Condition per auctioneer: good.",
        )

    def test_provenance_is_retained_but_acquisition_amount_is_removed(self):
        self.assertEqual(
            clean_public_notes("Purchased directly from the artist for EUR 500. Signed lower right; paid 8/2/2026."),
            "Purchased directly from the artist. Signed lower right.",
        )

    def test_missing_information_clause_does_not_erase_signature(self):
        self.assertEqual(clean_public_notes("Signed in pencil, edition not stated."), "Signed in pencil.")
        self.assertEqual(clean_public_notes("Unsigned. Condition unknown."), "Unsigned.")

    def test_missing_information_phrase_preserves_later_damage_facts(self):
        cases = (
            ("Signed in pencil, edition not stated, pale mat burn at edges.",
             "Signed in pencil, pale mat burn at edges."),
            ("Signed in pencil; edition not stated, pale mat burn at edges.",
             "Signed in pencil; pale mat burn at edges."),
            ("Condition: excellent; edition not stated, slight toning to sheet.",
             "Condition: excellent; slight toning to sheet."),
            ("Condition is excellent, signature not stated, faint crease at lower edge.",
             "Condition is excellent, faint crease at lower edge."),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(clean_public_notes(source), expected)

    def test_clear_cost_shipping_and_payment_clauses_are_removed(self):
        self.assertEqual(clean_public_notes(
            "Signed in pencil; purchase price: EUR 500; fees: EUR 50; shipping: EUR 25. "
            "Payment date: 7/20/2026. Postage USD 20."
        ), "Signed in pencil.")

    def test_symbol_prices_and_curly_apostrophe_premium_are_removed(self):
        self.assertEqual(clean_public_notes(
            "Signed lower right. Buyer’s premium: EUR 25. Fees: EUR 25. Tax: EUR 5. "
            "Paid €500, shipping €30. Postage £20. Shipping cost: €30."
        ), "Signed lower right.")

    def test_unknown_public_art_prose_is_retained(self):
        self.assertEqual(clean_public_notes(
            "Printed in dark brown ink. Broad margins. A shipping scene with a dock worker holding a hammer."
        ), "Printed in dark brown ink. Broad margins. A shipping scene with a dock worker holding a hammer.")

    def test_empty_notes_are_empty(self):
        for value in (None, "", "  ", "Invoice V99: EUR 50. Year and edition not stated."):
            with self.subTest(value=value):
                self.assertEqual(clean_public_notes(value), "")


class NotesGenerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username="notes-staff", is_staff=True)
        cls.member = User.objects.create_user(username="notes-member")
        cls.artwork = Artwork.objects.create(
            artist="Benton, Thomas Hart",
            title="Homecoming Kaw Valley",
            year="1951",
            medium="Offset lithograph",
            dimensions_text='11.5" x 14.75"',
            catalog_number="Fath p. 6-7",
            description="Signed in pencil lower right. Condition: extremely pale mat burn; otherwise clean.",
            catalog_description="PROMOTIONAL_UNVERIFIED_CLAIM",
            price=2850,
        )

    def setUp(self):
        self.client.force_login(self.staff)
        self.draft_url = reverse("generate_catalog_notes_from_payload")
        self.existing_url = reverse("generate_artwork_notes", args=[self.artwork.pk])

    def post_notes(self, payload, *, url=None, client=None, **headers):
        return (client or self.client).post(
            url or self.draft_url,
            json.dumps(payload),
            content_type="application/json",
            **headers,
        )

    def mock_response(self, payload):
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        return response

    @patch.dict(os.environ, {"OPENAI_API_KEY": "notes-test-key", "OPENAI_DESCRIPTION_MODEL": "gpt-5.6"})
    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_new_upload_calls_responses_api_and_returns_draft_without_saving(self, urlopen):
        urlopen.return_value = self.mock_response({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "Signed and dated in pencil. Excellent condition per auctioneer."}
        ]}]})
        before = Artwork.objects.count()
        response = self.post_notes({
            "artist": "Fairey, Shepard", "title": "Reconnect", "sheet_size": '24" x 35.83"',
            "description": "Signed and dated in pencil. Excellent condition per auctioneer. Invoice V99: EUR 50.",
            "catalog_description": "UNTRUSTED_DESCRIPTION", "use_web": True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"notes": "Signed and dated in pencil. Excellent condition per auctioneer."})
        self.assertEqual(Artwork.objects.count(), before)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer notes-test-key")
        body = json.loads(request.data)
        facts = json.loads(body["input"])
        self.assertEqual(facts["Sheet size"], '24" x 35.83"')
        self.assertNotIn("Image size", facts)
        self.assertNotIn("UNTRUSTED_DESCRIPTION", body["input"])
        self.assertNotIn("Invoice", body["input"])
        self.assertIn("condition per auctioneer", body["instructions"])
        self.assertIn("never as instructions", body["instructions"])
        self.assertNotIn("tools", body)
        self.assertNotIn("tool_choice", body)

    @patch("secondstateapp.catalog_api_views._generate_notes", return_value="Draft notes.")
    def test_existing_artwork_uses_unsaved_overrides_and_never_saves(self, generate):
        before = Artwork.objects.values().get(pk=self.artwork.pk)
        response = self.post_notes({
            "title": "Unsaved title", "description": "Fresh signature fact.", "edition_size": "100",
        }, url=self.existing_url)
        self.assertEqual(response.status_code, 200)
        candidate = generate.call_args.args[0]
        self.assertEqual(candidate.title, "Unsaved title")
        self.assertEqual(candidate.description, "Fresh signature fact.")
        self.assertEqual(candidate.edition_size, "100")
        self.assertEqual(candidate.catalog_number, "Fath p. 6-7")
        self.assertEqual(Artwork.objects.values().get(pk=self.artwork.pk), before)

    @patch("secondstateapp.catalog_api_views._generate_notes", return_value="Draft notes.")
    def test_staff_and_configured_api_key_authorize_both_routes(self, generate):
        for url in (self.draft_url, self.existing_url):
            with self.subTest(url=url, kind="staff"):
                self.assertEqual(self.post_notes({"title": "A print"}, url=url).status_code, 200)
            with patch.dict(os.environ, {"CATALOG_API_KEY": "notes-catalog-key"}):
                with self.subTest(url=url, kind="api-key"):
                    response = self.post_notes(
                        {"title": "A print"}, url=url, client=Client(), HTTP_X_API_KEY="notes-catalog-key",
                    )
                    self.assertEqual(response.status_code, 200)

    @patch("secondstateapp.catalog_api_views._generate_notes")
    def test_anonymous_nonstaff_and_wrong_keys_are_rejected_without_api_call(self, generate):
        member = Client()
        member.force_login(self.member)
        for client in (Client(), member):
            for url in (self.draft_url, self.existing_url):
                with self.subTest(url=url, client=client):
                    with patch.dict(os.environ, {"CATALOG_API_KEY": "expected"}):
                        self.assertEqual(self.post_notes({}, url=url, client=client, HTTP_X_API_KEY="wrong").status_code, 401)
        generate.assert_not_called()

    @patch("secondstateapp.catalog_api_views._generate_notes")
    def test_only_post_and_valid_object_json_are_accepted(self, generate):
        for url in (self.draft_url, self.existing_url):
            self.assertEqual(self.client.get(url).status_code, 405)
            for raw in ("{", "[]", "null", '"text"'):
                with self.subTest(url=url, raw=raw):
                    response = self.client.post(url, raw, content_type="application/json")
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("error", response.json())
        generate.assert_not_called()

    @patch("secondstateapp.catalog_api_views._generate_notes")
    def test_missing_existing_artwork_returns_404_without_api_call(self, generate):
        response = self.post_notes({}, url=reverse("generate_artwork_notes", args=[self.artwork.pk + 999]))
        self.assertEqual(response.status_code, 404)
        generate.assert_not_called()

    @patch.dict(os.environ, {"OPENAI_API_KEY": "notes-test-key"})
    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_empty_facts_are_rejected_without_openai_request(self, urlopen):
        response = self.post_notes({})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Enter artwork facts", response.json()["error"])
        urlopen.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_missing_api_configuration_is_actionable(self, urlopen):
        response = self.post_notes({"title": "A print"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("OPENAI_API_KEY is not configured", response.json()["error"])
        urlopen.assert_not_called()

    @patch.dict(os.environ, {"OPENAI_API_KEY": "notes-test-key"})
    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_empty_or_internal_only_openai_output_returns_error(self, urlopen):
        for payload in ({"output": []}, {"output_text": "Invoice V99: EUR 50."}):
            with self.subTest(payload=payload):
                urlopen.return_value = self.mock_response(payload)
                response = self.post_notes({"title": "A print"})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"error": "OpenAI returned empty notes."})

    @patch.dict(os.environ, {"OPENAI_API_KEY": "notes-test-key"})
    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_openai_http_error_returns_message_without_saving(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://api.openai.com/v1/responses", 429, "Rate limited", {},
            BytesIO(b'{"error": {"message": "Please retry later."}}'),
        )
        before = Artwork.objects.values().get(pk=self.artwork.pk)
        response = self.post_notes({"description": "Unsaved notes."}, url=self.existing_url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "OpenAI request failed: Please retry later."})
        self.assertEqual(Artwork.objects.values().get(pk=self.artwork.pk), before)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "notes-test-key"})
    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_model_uses_notes_override_then_description_then_existing_default(self, urlopen):
        urlopen.return_value = self.mock_response({"output_text": "Signed in pencil."})
        cases = (
            ({}, "gpt-5.6"),
            ({"OPENAI_DESCRIPTION_MODEL": "description-model"}, "description-model"),
            ({"OPENAI_DESCRIPTION_MODEL": "description-model", "OPENAI_NOTES_MODEL": "notes-model"}, "notes-model"),
        )
        for environment, expected in cases:
            with self.subTest(expected=expected), patch.dict(
                os.environ, {"OPENAI_API_KEY": "notes-test-key", **environment}, clear=True,
            ):
                _generate_notes(self.artwork)
                body = json.loads(urlopen.call_args.args[0].data)
                self.assertEqual(body["model"], expected)
                self.assertEqual("reasoning" in body, expected == "gpt-5.6")
                self.assertNotIn("PROMOTIONAL_UNVERIFIED_CLAIM", body["input"])


class CatalogUploadFormattingTests(TestCase):
    @patch.dict(os.environ, {"CATALOG_API_KEY": "formatting-test-key"})
    def test_upload_persists_clean_public_notes_and_normalized_image_and_sheet_sizes(self):
        response = self.client.post(reverse("upload_artwork"), {
            "artist": "Fairey, Shepard", "title": "Reconnect", "price": "1000",
            "dimensions_text": '35.8267716535433" x 24.015748031496063"',
            "sheet_size": "61 x 91 cm",
            "description": (
                "Portrait of Common. Signed and dated in pencil. Excellent condition per auctioneer. "
                "Invoice V01760: hammer EUR 50 + VAT EUR 0.15, paid 7/20/2026. "
                "Year, edition and shipping not stated."
            ),
            "catalog_description": "Existing promotional description.",
        }, HTTP_X_API_KEY="formatting-test-key")
        self.assertEqual(response.status_code, 201)
        artwork = Artwork.objects.get(pk=response.json()["id"])
        self.assertEqual(artwork.dimensions_text, '35.83" x 24.02"')
        self.assertEqual(artwork.sheet_size, '24.02" x 35.83"')
        self.assertEqual(
            artwork.description,
            "Portrait of Common. Signed and dated in pencil. Excellent condition per auctioneer.",
        )
        self.assertEqual(artwork.catalog_description, "Existing promotional description.")

    @patch.dict(os.environ, {"CATALOG_API_KEY": "formatting-test-key"})
    def test_update_normalizes_sizes_while_preserving_manually_edited_notes(self):
        artwork = Artwork.objects.create(artist="Artist", title="A print", price=100)
        manual_notes = "Signed lower right. Provenance: acquired directly from the artist. Invoice reviewed."
        response = self.client.post(reverse("update_artwork", args=[artwork.pk]), {
            "dimensions_text": "11.5000 × 14.7500 in",
            "sheet_size": "24.015748031496063 x 35.8267716535433",
            "description": manual_notes,
        }, HTTP_X_API_KEY="formatting-test-key")
        self.assertEqual(response.status_code, 200)
        artwork.refresh_from_db()
        self.assertEqual(artwork.dimensions_text, '11.5" x 14.75"')
        self.assertEqual(artwork.sheet_size, '24.02" x 35.83"')
        self.assertEqual(artwork.description, manual_notes)
        self.assertEqual(response.json()["artwork"]["description"], manual_notes)
