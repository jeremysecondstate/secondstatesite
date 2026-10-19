"""Rendering and frontend boundaries for case briefs and private intake."""

from pathlib import Path
import shutil
import subprocess

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class CoordinateFrontendTests(SimpleTestCase):
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
