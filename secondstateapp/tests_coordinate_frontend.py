"""Rendering and frontend boundaries for case briefs and private intake."""

from pathlib import Path
import shutil
import subprocess

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


class CoordinateNewCaseFrontendTests(TestCase):
    @override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True, COORDINATE_EMAIL_SENDING_ENABLED=True)
    def test_enabled_email_header_is_correct_without_a_selected_case(self):
        staff = get_user_model().objects.create_user("new-case-staff", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("coordinate"), {"new": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_case"])
        self.assertIsNone(response.context["coordination"])
        self.assertTrue(response.context["worker"]["email_sending_enabled"])
        self.assertContains(response, "Staff-reviewed email coordination")
        self.assertContains(response, "Email requires a separate Send reviewed email action.")
        self.assertNotContains(response, "Email not enabled")
        self.assertNotContains(response, "Email sending is not enabled.")
        # Email cannot become globally enabled when the shipping workflow is off.
        with override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=False):
            response = self.client.get(reverse("coordinate"), {"new": "1"})
            self.assertFalse(response.context["worker"]["email_sending_enabled"])
            self.assertContains(response, "Test mode · Messaging only")
            self.assertContains(response, "Email sending is not enabled.")


class CoordinateFrontendTests(SimpleTestCase):
    def mail_fixture(self, **draft_changes):
        return {"drafts": [{"id": "draft-1", "subject": "collection details", "recipient": "packer@example.test",
                            "body": "hello! could you confirm pickup?", "status": "reviewed", "current_digest": "current-version",
                            "reviewed_digest": "current-version", "can_send": True, "editable": True,
                            "send_url": "/coordinate/case/drafts/draft-1/send/", "send_request_id": "send-once",
                            "review_url": "/coordinate/case/drafts/draft-1/review/", **draft_changes}],
                "mail": {"enabled": True, "ready": True, "sender": "jeremy@secondstate.art", "threads": []},
                "quotes": [], "urls": {"add_draft": "/coordinate/case/drafts/"}}

    def test_send_is_explicit_digest_bound_and_legacy_review_never_becomes_sendable(self):
        state = self.mail_fixture()
        html = render_to_string("coordinate/mail.html", {"coordination": state})
        self.assertIn('class="coordinate-action-form coordinate-draft-send"', html)
        self.assertIn('name="content_digest" value="current-version"', html)
        self.assertIn('name="request_id" value="send-once"', html)
        self.assertIn("Send reviewed email", html)
        self.assertIn("Marking a draft reviewed never sends it", html)
        for changes in ({"status": "draft"}, {"reviewed_digest": ""}, {"reviewed_digest": "old-version"},
                        {"can_send": False}, {"editable": False, "send_status": "sent"}):
            html = render_to_string("coordinate/mail.html", {"coordination": self.mail_fixture(**changes)})
            self.assertNotIn('class="coordinate-action-form coordinate-draft-send"', html)
        html = render_to_string("coordinate/mail.html", {"coordination": self.mail_fixture(reviewed_digest="")})
        self.assertIn("Review current draft", html)
        self.assertIn("older review needs to be renewed", html)
        for changes in ({"ready": False}, {"enabled": False}):
            state = self.mail_fixture()
            state["mail"].update(changes)
            html = render_to_string("coordinate/mail.html", {"coordination": state})
            self.assertNotIn('class="coordinate-action-form coordinate-draft-send"', html)

    def test_pending_unknown_and_sent_messages_are_immutable_without_retry_controls(self):
        for status, expected in (("sending", "Sending is in progress"), ("unknown", "Do not resend it or create a duplicate"),
                                 ("sent", "Start a reply draft to continue")):
            html = render_to_string("coordinate/mail.html", {"coordination": self.mail_fixture(editable=False, send_status=status)})
            self.assertIn('class="coordinate-draft-fields coordinate-grid-form" disabled', html)
            self.assertIn(expected, html)
            self.assertNotIn('class="coordinate-action-form coordinate-draft-send"', html)
            self.assertNotIn('class="coordinate-action-form coordinate-draft-review"', html)
            self.assertNotIn("Retry send", html)

    def test_quote_test_route_identifies_actual_recipient_without_provider_send_controls(self):
        state = self.mail_fixture(editable=False, can_send=False, send_status="sent", quote_test=True,
            actual_recipient="jeremy@secondstate.art", intended_recipient="packer@example.test")
        state["outreach"] = {"mode": "test", "test_recipient": "jeremy@secondstate.art",
            "settings_url": "/coordinate/case/quote-inquiries/"}
        html = render_to_string("coordinate/mail.html", {"coordination": state})
        for expected in ("Test routing to jeremy@secondstate.art only", "Actual recipient: jeremy@secondstate.art",
                         "Intended provider: packer@example.test", "The provider was not contacted.",
                         "Initial quote tests · Other email needs review", "Review inquiry permission and destination"):
            self.assertIn(expected, html)
        self.assertNotIn('class="coordinate-action-form coordinate-draft-send"', html)
        self.assertIn('href="/coordinate/case/quote-inquiries/"', html)
        for mode, label in (("off", "Off. Correspondence uses reviewed drafts."),
                            ("live", "Initial provider inquiries authorized for this case.")):
            state["outreach"]["mode"] = mode
            self.assertIn(label, render_to_string("coordinate/mail.html", {"coordination": state}))

    def test_linked_thread_messages_are_escaped_and_reply_options_are_case_scoped(self):
        state = self.mail_fixture(thread_id="thread-case")
        state["mail"]["threads"] = [{"id": "thread-case", "subject": "Collection <details>", "participants": ["jeremy@secondstate.art", "packer@example.test"], "provider_email": "packer@example.test",
            "url": "https://mail.google.com/mail/u/0/#all/thread-case", "last_synced_at": "2026-10-19T18:00:00Z",
            "messages": [{"id": "email-case", "direction": "inbound", "sender": "packer@example.test", "recipient": "jeremy@secondstate.art",
                          "body": "<img src=x onerror=alert(1)> Collection is ready.", "sent_at": "2026-10-19T17:59:00Z",
                          "source_ref": "message:17", "source_url": "https://mail.google.com/mail/u/0/#all/message-case"}]}]
        html = render_to_string("coordinate/mail.html", {"coordination": state})
        self.assertIn('value="thread-case" selected', html)
        self.assertIn('data-panel="mail"', html)
        self.assertIn('id="coordinate-email-email-case"', html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("message:17", html)
        self.assertIn('datetime="2026-10-19T17:59:00Z"', html)
        self.assertNotIn("contenteditable", html)

    def test_price_cards_keep_estimate_sold_unknown_basis_and_history_distinct(self):
        ref = "https://market.example/sale/17"
        prices = [
            {"kind": "sold", "label": "Sold", "amount": "500.00", "currency": "", "basis": "unknown",
             "evidence_quote": "Sold: $500.00 <untrusted>", "source_refs": [ref]},
            {"kind": "estimate", "label": "Estimate", "amount": "800", "amount_high": "1200", "currency": "USD", "basis": "estimate",
             "evidence_quote": "Estimate: USD 800–1,200", "source_refs": [ref]},
            {"kind": "historical_comparison", "label": "Sold", "amount": "450", "currency": "USD", "basis": "premium_inclusive",
             "evidence_quote": "Sold: USD 450 including buyer's premium", "source_refs": [ref]},
        ]
        html = render_to_string("coordinate/briefing.html", {"coordination": {"brief": {
            "lots": [{"label": "Example artwork", "auction_date": "2026-10-17", "prices": prices,
                      "storage_terms": "Storage begins after 30 days.", "shipping_contacts": "Published Packer: packing@example.test",
                      "price_notes": "The earlier sale is a comparison, separate from this purchase.", "source_refs": [ref]}],
            "sources": {ref: {"label": "Verified corresponding listing", "url": ref}},
        }}})
        for text in ("Sold 500.00", "Currency not stated", "Price basis not stated", "Estimate 800–1200 USD",
                     "Auction estimate.", "Historical comparison — a different sale", "Includes buyer’s premium",
                     "Storage begins after 30 days.", "packing@example.test", "2026-10-17", "&lt;untrusted&gt;"):
            self.assertIn(text, html)
        self.assertNotIn("<untrusted>", html)
        self.assertIn(f'href="{ref}"', html)

    def test_case_brief_escapes_source_text_and_distinguishes_missing_details(self):
        html = render_to_string("coordinate/briefing.html", {"coordination": {"brief": {
            "summary": "<img src=x onerror=alert(1)>",
            "lots": [{"label": "Lot 17", "lot_number": "17", "artist": "Example artist",
                      "dimensions": "8 x 10 inches", "source_refs": ["message:17"]}],
            "plan": {"notes": "Review </script><script>alert(1)</script>", "pickup_deadline": ""},
            "open_questions": ["Confirm the framed dimensions."],
            "sources": {"message:17": {"label": "Staff message", "url": "#coordinate-message-17", "kind": "message"}},
        }}})
        self.assertIn('data-panel="briefing"', html)
        self.assertIn("8 x 10 inches", html)
        self.assertIn("Not provided", html)
        self.assertIn('href="#coordinate-message-17"', html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn('type="application/json"', html)
        self.assertIn("Use suggestion in plan", html)

    def test_intake_form_is_multipart_and_original_is_a_private_link(self):
        html = render_to_string("coordinate/intake.html", {"coordination": {"intake": {
            "documents": [{"id": "document-id", "title": "Invoice <sample>", "kind": "pdf",
                           "extraction_status": "no_text", "download_url": "/coordinate/case/documents/document-id/"}],
            "add_url": "/coordinate/case/intake/", "submission_token": "retry-token",
        }}})
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('name="client_message_id" value="retry-token"', html)
        self.assertIn('maxlength="24000"', html)
        self.assertIn('id="coordinate-document-document-id"', html)
        self.assertIn('href="/coordinate/case/documents/document-id/"', html)
        self.assertIn("No readable text was found", html)
        self.assertIn("Invoice &lt;sample&gt;", html)

    def test_browser_rendering_and_form_behaviors(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable; run tests_coordinate_frontend.js with Node for frontend checks.")
        result = subprocess.run([node, str(Path(__file__).with_suffix(".js"))], capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
