"""Shipping brief rendering keeps planning assumptions and source facts distinct."""
import re

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class ShippingBriefRenderingTests(SimpleTestCase):
    def fixture(self):
        source = "https://auction.example/terms"
        contact = "https://packer.example/services"
        return {"summary": "Preparation is underway.", "lots": [], "plan": {},
            "open_questions": ["Confirm the final pickup window."],
            "sources": {source: {"label": "Auction terms", "url": source},
                        contact: {"label": "Provider services", "url": contact},
                        "message:17": {"label": "Staff destination", "url": "#coordinate-message-17"}},
            "shipping": {
                "working_currency": {"code": "USD", "basis": "inferred", "note": "A planning assumption from the US sale context.", "source_refs": [source]},
                "quote_readiness": {"status": "conditional_ready", "note": "An initial inquiry can include the known dimensions and location."},
                "actions": [
                    {"owner": "provider", "stage": "quote", "text": "Confirm packing and transport scope.", "source_refs": [contact]},
                    {"owner": "auction_house", "stage": "release", "text": "Confirm third-party release requirements.", "source_refs": [source]},
                    {"owner": "staff", "stage": "booking", "text": "Choose the destination before approving a booking.", "source_refs": ["message:17"]}],
                "providers": [{"name": "Example Packer", "email": "packing@example.test", "service_type": "fine_art_transport",
                    "published_capability": "We transport framed artwork.", "contact_quote": "Example Packer: packing@example.test", "source_refs": [contact]}],
                "site_checks": [{"topic": "storage", "status": "not_found_in_checked_pages",
                    "note": "The opened terms page did not specify a storage charge.", "source_refs": [source]}]}}

    def render(self, brief):
        return render_to_string("coordinate/briefing.html", {"coordination": {"brief": brief}})

    def test_readiness_and_owner_stage_actions_are_clear_without_action_controls(self):
        brief = self.fixture()
        html = self.render(brief)
        for expected in ("Shipping preparation", "Ready for an initial quote request", "Actions and owners",
                         "Shipping provider", "Auction house", "SecondState", "For the quote request",
                         "Before release", "Before booking", "Additional details to resolve"):
            self.assertIn(expected, html)
        for item in brief["shipping"]["actions"]:
            self.assertIn(item["text"], html)
        self.assertNotIn("Still to confirm", html)
        section = html.split('class="coordinate-shipping-brief"', 1)[1].split('class="coordinate-lot-grid"', 1)[0]
        self.assertNotIn("<form", section)
        self.assertNotIn("<button", section)
        self.assertIn('href="#coordinate-message-17"', section)
        for status, label in (("needs_destination", "Destination needed for a firm quote"),
                              ("needs_public_research", "Public research still needed"), ("not_assessed", "Not yet assessed")):
            brief["shipping"]["quote_readiness"]["status"] = status
            self.assertIn(label, self.render(brief))

    def test_working_currency_inference_does_not_fill_source_price_currency(self):
        brief = self.fixture()
        brief["lots"] = [{"label": "Example lot", "prices": [{"label": "Sold", "amount": "500",
            "currency": "", "basis": "unknown", "kind": "sold", "source_refs": ["https://auction.example/terms"],
            "evidence_quote": "Sold: $500"}], "source_refs": ["https://auction.example/terms"]}]
        html = self.render(brief)
        self.assertIn("Inferred for planning", html)
        self.assertIn("This planning assumption does not change the currency shown in price evidence.", html)
        price_section = html.split('class="coordinate-lot-prices"', 1)[1].split("</section>", 1)[0]
        self.assertIn("Sold 500", price_section)
        self.assertIn("Currency not stated.", price_section)
        self.assertNotIn("Sold 500 USD", price_section)
        for basis, label in (("source", "Source-stated"), ("staff", "Staff-provided"), ("unknown", "Unconfirmed")):
            brief["shipping"]["working_currency"]["basis"] = basis
            html = self.render(brief)
            self.assertIn(label, html)
            self.assertNotIn("Inferred for planning", html)

    def test_provider_capability_and_contact_quotes_keep_their_own_citations(self):
        brief = self.fixture()
        html = self.render(brief)
        self.assertIn("Provider options &amp; published capabilities", html)
        article = re.search(r'<article class="coordinate-provider-option">(.*?)</article>', html, re.S).group(1)
        for expected in ("Example Packer", "packing@example.test", "Fine art transport",
                         "We transport framed artwork.", "Published contact wording", "Example Packer: packing@example.test"):
            self.assertIn(expected, article)
        self.assertIn('href="https://packer.example/services"', article)
        self.assertNotIn('href="https://auction.example/terms"', article)
        brief["shipping"]["providers"][0].update(email="", service_type="unknown", published_capability="", contact_quote="")
        html = self.render(brief)
        self.assertIn("Service type unconfirmed", html)
        self.assertIn("Published capability not established.", html)
        self.assertNotIn("Published contact wording", html)

    def test_site_check_statuses_are_scoped_and_untrusted_wording_is_escaped(self):
        brief = self.fixture()
        check = brief["shipping"]["site_checks"][0]
        for status, label in (("found", "Published information found"),
                              ("not_found_in_checked_pages", "Not found in the checked pages"),
                              ("access_failed", "Access attempt failed"), ("not_checked", "Not checked yet")):
            check["status"] = status
            self.assertIn(label, self.render(brief))
        check.update(topic="third_party_release", note="<script>private source wording</script>")
        provider = brief["shipping"]["providers"][0]
        provider.update(name="<img src=x onerror=alert(1)>", published_capability="<b>packing</b>", contact_quote="<script>contact</script>")
        brief["shipping"]["actions"][0]["text"] = "<script>action</script>"
        html = self.render(brief)
        for expected in ("Third-party release", "&lt;script&gt;private source wording&lt;/script&gt;",
                         "&lt;img src=x onerror=alert(1)&gt;", "&lt;b&gt;packing&lt;/b&gt;",
                         "&lt;script&gt;contact&lt;/script&gt;", "&lt;script&gt;action&lt;/script&gt;"):
            self.assertIn(expected, html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)

    def test_legacy_briefs_keep_questions_without_invented_shipping_assessment(self):
        brief = self.fixture()
        del brief["shipping"]
        html = self.render(brief)
        self.assertIn("Still to confirm", html)
        self.assertIn("Confirm the final pickup window.", html)
        self.assertNotIn("Shipping preparation", html)
        self.assertNotIn("Quote readiness", html)
        self.assertNotIn("Working currency", html)
