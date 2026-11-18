from io import BytesIO
import re
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from reportlab.platypus import Paragraph

from .calendar_images import store_saved_calendar_image
from .models import AuctionWatchLot, HouseProposalEntry


class ConsignmentProposalTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=temp.name))
        photo = BytesIO()
        Image.new("RGB", (80, 120), "tan").save(photo, format="JPEG")
        self.photo = store_saved_calendar_image(photo.getvalue())
        self.lot = AuctionWatchLot.objects.create(source="test", source_lot_id="1", image_url=self.photo)
        self.params = {"season": "spring-2027", "house": "swann"}
        self.workspace = reverse("calendar_consignment_proposals")
        self.pdf = reverse("calendar_consignment_proposal_pdf")
        self.staff = get_user_model().objects.create_user("proposal-staff", is_staff=True)
        self.client.force_login(self.staff)

    def add_work(self, **overrides):
        fields = dict(lot=self.lot, season="spring", year=2027, house="Swann", house_key="swann",
                      artist="María León", title="Étude", description="Swann-specific copy.",
                      dimensions="Image 7⅛ × 4½ in.", estimate_low=125, estimate_high=200)
        return HouseProposalEntry.objects.create(**{**fields, **overrides})

    def test_private_access_and_empty_selection(self):
        self.assertContains(self.client.get(self.workspace), "No proposals for")
        self.assertEqual(self.client.get(self.pdf).status_code, 404)
        self.client.logout()
        for route in (self.workspace, self.pdf):
            self.assertEqual(self.client.get(route).status_code, 302)

    def test_house_season_totals_and_pdf_scope(self):
        self.add_work()
        other_lot = AuctionWatchLot.objects.create(source="test", source_lot_id="2", won_by_us=True)
        last = self.add_work(lot=other_lot, image_url=self.photo, title="Zinnia", sort_order=10)
        self.add_work(house="Doyle", house_key="doyle", description="Other recipient copy.")
        self.add_work(season="fall", description="Different season copy.")
        page = self.client.get(self.workspace, {**self.params, "work": last.pk})
        self.assertContains(page, "Zinnia")
        self.assertContains(page, "1 work pending acquisition")
        self.assertContains(page, "Total: $250–$400")
        self.assertNotContains(page, "Other recipient copy.")
        with patch("reportlab.platypus.Paragraph", wraps=Paragraph) as paragraphs:
            response = self.client.get(self.pdf, self.params)
        contents = b"".join(response.streaming_content)
        self.assertIn("swann-spring-2027-draft.pdf", response["Content-Disposition"])
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", contents)), 2)
        self.assertIn(b"/Subtype /Image", contents)
        printed = "\n".join(call.args[0] for call in paragraphs.call_args_list)
        self.assertEqual(printed.count("Swann-specific copy."), 2)
        self.assertIn("Total: $250–$400", printed)
        self.assertNotIn("Different season", printed)
        self.assertNotIn("Other recipient", printed)
        self.assertNotIn("pending acquisition", printed)
        self.lot.won_by_us = True
        self.lot.save()
        self.assertNotIn("-draft", self.client.get(self.pdf, self.params)["Content-Disposition"])

    def test_incomplete_proposals_never_sum_missing_estimates_as_zero(self):
        self.add_work()
        self.add_work(work_key="component", title="Second work", estimate_low=None, estimate_high=None)
        page = self.client.get(self.workspace, self.params)
        self.assertContains(page, "Estimate pending")
        self.assertContains(page, "Second work — photograph, USD estimate")
        self.assertNotContains(page, "Download draft PDF")
        self.assertContains(self.client.get(self.pdf, self.params), "Needed for PDF export", status_code=422)

    def test_unsupported_or_missing_photo_cannot_create_a_partial_catalog(self):
        entry = self.add_work(image_url="https://elsewhere.example/photo.jpg")
        with patch("requests.get") as get:
            self.assertContains(self.client.get(self.pdf, self.params), "saved object photograph", status_code=422)
            get.assert_not_called()
        entry.image_url = "/media/calendar-lots/" + "0" * 64 + ".jpg"
        entry.save()
        self.assertContains(self.client.get(self.pdf, self.params), "could not be included", status_code=422)

    def test_long_text_flows_onto_additional_pages(self):
        self.add_work(description=("Long catalog paragraph with documented details. " * 140) + "End of entry.")
        response = self.client.get(self.pdf, self.params)
        data = b"".join(response.streaming_content)
        self.assertGreater(len(re.findall(rb"/Type\s*/Page\b", data)), 1)
