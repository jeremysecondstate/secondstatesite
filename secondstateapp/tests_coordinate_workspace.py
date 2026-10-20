"""Compact case components retain their full evidence and explicit mail controls."""

from copy import deepcopy

from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class CoordinateWorkspaceRenderingTests(SimpleTestCase):
    def fixture(self):
        case_id = "11111111-1111-4111-8111-111111111111"
        base = f"/coordinate/{case_id}/"
        source = "https://auction.example/lot/17"
        state = {
            "drafts": [{
                "id": "draft-17", "recipient": "packer@example.test", "subject": "Packing quote for Lot 17",
                "body": "Please quote packing and collection for Lot 17.\nKeep the existing frame.",
                "status": "reviewed", "editable": True, "can_send": True,
                "current_digest": "saved-version", "reviewed_digest": "saved-version",
                "save_url": base + "drafts/draft-17/", "review_url": base + "drafts/draft-17/review/",
                "send_url": base + "drafts/draft-17/send/", "send_request_id": "send-once",
            }],
            "mail": {"enabled": True, "ready": True, "sender": "jeremy@secondstate.art",
                     "sync_enabled": True, "threads": [{
                         "id": "thread-17", "subject": "Collection availability",
                         "provider_email": "packer@example.test", "messages": [{
                             "id": "email-17", "direction": "inbound", "sender": "packer@example.test",
                             "recipient": "jeremy@secondstate.art", "body": "Collection is available on Friday.",
                             "source_ref": "message:17", "source_url": "https://mail.google.com/mail/u/0/#all/email-17",
                         }],
                     }]},
            "brief": {
                "summary": "Lot 17 is ready for a packing inquiry.",
                "lots": [{"lot_number": "17", "label": "Framed landscape", "artist": "Example Artist",
                          "dimensions": "8 x 10 inches", "framed_dimensions": "12 x 14 inches",
                          "release_requirements": "Present the paid invoice.", "source_refs": [source],
                          "prices": [{"label": "Sold", "amount": "500", "currency": "USD",
                                      "kind": "sold", "basis": "hammer", "evidence_quote": "Hammer USD 500",
                                      "source_refs": [source]}]}],
                "plan": {"notes": "Ask the provider to collect the framed work.", "source_refs": [source]},
                "open_questions": ["Confirm the final pickup window."],
                "sources": {source: {"label": "Auction listing", "url": source}},
            },
            "intake": {"add_url": base + "intake/", "submission_token": "upload-once", "documents": [{
                "id": "document-17", "title": "Paid invoice", "kind": "pdf", "text_excerpt": "Invoice confirms Lot 17.",
                "download_url": base + "documents/document-17/",
            }]},
            "plan": {"update_url": base + "plan/", "stage": "preparing", "destination": "duarte",
                     "handling": "Keep the existing frame.", "notes": "Staff approved destination: Duarte."},
            "quotes": [{"id": "quote-17", "provider_name": "Example Packer", "provider_email": "packer@example.test",
                        "amount": "225.00", "latest_amount": "225.00", "currency": "USD",
                        "update_url": base + "quotes/quote-17/", "accept_url": base + "quotes/quote-17/accept/"}],
            "research": [{"title": "Published pickup terms", "source_url": source,
                          "text": "Pickup requires an appointment.", "source_kind": "public_fetch"}],
            "urls": {"add_draft": base + "drafts/", "add_quote": base + "quotes/"},
        }
        return {
            "selected_case": {"id": case_id, "title": "October shipment", "status": "replied", "deleted": False},
            "coordination": state, "worker": {"email_sending_enabled": True}, "cases": [], "trash_cases": [],
            "messages": [{"id": 17, "role": "assistant", "body": "A packing inquiry is prepared for review."}],
        }

    def render(self, context=None):
        return BeautifulSoup(render_to_string("coordinate/index.html", context or self.fixture()), "html.parser")

    def test_workspace_puts_collapsed_correspondence_before_supporting_components(self):
        page = self.render()
        workspace = page.select_one("#coordinate-planning")
        panels = workspace.select("details[data-panel]")
        self.assertEqual([panel["data-panel"] for panel in panels],
                         ["drafts", "mail", "briefing", "intake", "plan", "quotes", "research"])
        for panel in panels:
            self.assertNotIn("open", panel.attrs)
            self.assertIsNotNone(panel.find("summary", recursive=False))
        self.assertIn("Case workspace", workspace.select_one("#coordinate-workspace-heading").get_text())

    def test_each_draft_has_a_compact_summary_and_complete_editable_contents(self):
        context = self.fixture()
        other = deepcopy(context["coordination"]["drafts"][0])
        other.update(id="draft-18", recipient="other@example.test", subject="Second provider inquiry")
        context["coordination"]["drafts"].append(other)
        page = self.render(context)
        cards = page.select("details.coordinate-draft")
        self.assertEqual([card["data-draft-id"] for card in cards], ["draft-17", "draft-18"])
        self.assertEqual(len({card["id"] for card in cards}), 2)
        for card, draft in zip(cards, context["coordination"]["drafts"]):
            self.assertNotIn("open", card.attrs)
            summary = card.find("summary", recursive=False)
            self.assertIn(draft["subject"], summary.get_text())
            self.assertIn(draft["recipient"], summary.get_text())
            self.assertNotIn(draft["body"], summary.get_text())
            self.assertEqual(card.select_one("input[name=recipient]")["value"], draft["recipient"])
            self.assertEqual(card.select_one("input[name=subject]")["value"], draft["subject"])
            self.assertEqual(card.select_one("textarea[name=body]").get_text(), draft["body"])
            self.assertIsNotNone(card.select_one("button.coordinate-copy-draft"))

    def test_collapsed_lots_suggestions_and_sources_keep_full_case_information(self):
        page = self.render()
        workspace = page.select_one("#coordinate-planning")
        for selector in ("details.coordinate-lot-card", "details.coordinate-suggestion",
                         "details.coordinate-open-questions", "details.coordinate-mail-thread"):
            component = workspace.select_one(selector)
            self.assertIsNotNone(component, selector)
            self.assertNotIn("open", component.attrs)
            self.assertIsNotNone(component.find("summary", recursive=False))
        lot = workspace.select_one("details.coordinate-lot-card")
        for fact in ("Example Artist", "8 x 10 inches", "12 x 14 inches", "Present the paid invoice.",
                     "Sold 500 USD", "Hammer USD 500"):
            self.assertIn(fact, lot.get_text())
        self.assertEqual(lot.select_one("a[data-source-link]")["href"], "https://auction.example/lot/17")
        self.assertIn("Ask the provider to collect the framed work.", workspace.select_one(".coordinate-suggestion").get_text())
        self.assertIsNotNone(workspace.select_one(".coordinate-suggestion [data-use-suggestion]"))
        self.assertIn("Confirm the final pickup window.", workspace.select_one(".coordinate-open-questions").get_text())
        self.assertIn("Collection is available on Friday.", workspace.select_one("[data-panel=mail]").get_text())
        self.assertIn("Invoice confirms Lot 17.", workspace.select_one("[data-panel=intake]").get_text())
        self.assertIsNotNone(workspace.select_one("[data-panel=intake] a[data-private-download]"))
        self.assertIn("Staff approved destination: Duarte.", workspace.select_one("[data-panel=plan] textarea").get_text())
        self.assertIn("Example Packer", workspace.select_one("[data-panel=quotes]").get_text())
        self.assertIn("Pickup requires an appointment.", workspace.select_one("[data-panel=research]").get_text())

    def test_component_summaries_and_bodies_escape_untrusted_text(self):
        context = self.fixture()
        unsafe = '</textarea><img src=x onerror="alert(1)"><script>source</script>'
        state = context["coordination"]
        state["drafts"][0].update(subject=unsafe, recipient='packer@example.test" autofocus="true', body=unsafe)
        state["brief"]["lots"][0].update(label=unsafe, artist=unsafe)
        state["brief"]["plan"]["notes"] = unsafe
        state["mail"]["threads"][0]["messages"][0]["body"] = unsafe
        page = self.render(context)
        workspace = page.select_one("#coordinate-planning")
        self.assertIsNone(workspace.select_one("img, [onerror], [autofocus]"))
        self.assertIsNone(workspace.select_one("script:not([type='application/json'])"))
        draft = workspace.select_one(".coordinate-draft")
        self.assertIn(unsafe, draft.find("summary", recursive=False).get_text())
        self.assertEqual(draft.select_one("textarea[name=body]").get_text(), unsafe)
        self.assertEqual(draft.select_one("input[name=recipient]")["value"], state["drafts"][0]["recipient"])
        self.assertIn(unsafe, workspace.select_one(".coordinate-lot-card").get_text())

    def test_lots_from_different_sales_can_share_a_lot_number(self):
        context = self.fixture()
        other = deepcopy(context["coordination"]["brief"]["lots"][0])
        other.update(artist="Another Artist", auction_date="2026-10-18")
        context["coordination"]["brief"]["lots"].append(other)
        page = self.render(context)
        records = page.select("details.coordinate-lot-card, details[id$='-citations']")
        ids = [record["id"] for record in records]
        self.assertEqual(len(ids), len(set(ids)))
        lots = page.select("details.coordinate-lot-card")
        self.assertNotEqual(lots[0]["data-state-key"], lots[1]["data-state-key"])

    def test_collapsed_drafts_preserve_review_binding_and_locked_delivery_controls(self):
        context = self.fixture()
        draft = context["coordination"]["drafts"][0]
        page = self.render(context)
        send = page.select_one(".coordinate-draft-send")
        self.assertEqual(send["method"], "post")
        self.assertEqual(send["data-reviewed-digest"], "saved-version")
        self.assertEqual(send.select_one("input[name=content_digest]")["value"], "saved-version")
        self.assertEqual(send.select_one("input[name=request_id]")["value"], "send-once")
        self.assertIn("Send reviewed email", send.get_text())
        draft["reviewed_digest"] = "older-version"
        self.assertIsNone(self.render(context).select_one(".coordinate-draft-send"))
        draft.update(editable=False, send_status="sent")
        page = self.render(context)
        self.assertTrue(page.select_one(".coordinate-draft-fields").has_attr("disabled"))
        self.assertIsNone(page.select_one(".coordinate-draft-review, .coordinate-draft-send"))
        self.assertIn("Start a reply draft to continue", page.select_one(".coordinate-draft").get_text())
