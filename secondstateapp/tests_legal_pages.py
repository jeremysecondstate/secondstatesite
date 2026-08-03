from django.test import TestCase, override_settings
from django.urls import reverse


class LegalPageTests(TestCase):
    @override_settings(TWILIO_FROM_NUMBER="+12065550123")
    def test_sms_program_page_is_public_and_discloses_opt_in(self):
        response = self.client.get(reverse("sms_program"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "+12065550123")
        self.assertContains(response, "text <strong>START</strong>", html=True)
        self.assertContains(response, "up to one message per day")
        self.assertContains(response, "Reply <strong>STOP</strong>", html=True)
        self.assertContains(response, "Reply <strong>HELP</strong>", html=True)
        self.assertContains(response, "Consent is not a condition")

    @override_settings(TWILIO_FROM_NUMBER="")
    def test_sms_program_page_handles_closed_enrollment(self):
        response = self.client.get(reverse("sms_program"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SMS enrollment is not currently open")

    def test_privacy_policy_contains_mobile_data_language(self):
        response = self.client.get(reverse("privacy_policy"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not sell, rent, or share")
        self.assertContains(response, "mobile phone number")
        self.assertContains(response, "marketing or promotional purposes")
        self.assertContains(response, "Reply <strong>STOP</strong>", html=True)

    def test_sms_terms_contains_required_program_disclosures(self):
        response = self.client.get(reverse("sms_terms"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "up to one message per day")
        self.assertContains(response, "Message and data rates may apply")
        self.assertContains(response, "replying <strong>STOP</strong>", html=True)
        self.assertContains(response, "Reply <strong>HELP</strong>", html=True)
        self.assertContains(response, "not a condition of purchasing")

    def test_footer_links_to_all_public_compliance_pages(self):
        response = self.client.get(reverse("about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("sms_program"))
        self.assertContains(response, reverse("privacy_policy"))
        self.assertContains(response, reverse("sms_terms"))
