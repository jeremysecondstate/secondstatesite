"""Rendering and frontend boundaries for case briefs and private intake."""

from pathlib import Path
import shutil
import subprocess

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class CoordinateFrontendTests(SimpleTestCase):
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
