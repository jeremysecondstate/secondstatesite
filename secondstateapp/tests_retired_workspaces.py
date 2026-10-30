"""Retired staff workspaces stay inaccessible without disrupting the remaining site."""

from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.urls import Resolver404, resolve, reverse


class RetiredWorkspaceTests(SimpleTestCase):
    def test_retired_pages_and_worker_endpoints_have_no_routes(self):
        case_id = "a9dc8386-133b-4ee8-9027-7bf1de871480"
        paths = [
            f"/{workspace}/{suffix}"
            for workspace in ("coordinate", "inventory")
            for suffix in ("", f"{case_id}/", "state/", "api/claim/", f"api/jobs/{case_id}/complete/")
        ]
        for path in paths:
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)
                for user in (AnonymousUser(), SimpleNamespace(is_authenticated=True, is_staff=True)):
                    with self.subTest(authenticated=user.is_authenticated):
                        with patch("django.contrib.auth.middleware.get_user", return_value=user):
                            self.assertEqual(self.client.get(path).status_code, 404)
                            self.assertEqual(self.client.post(path, {}).status_code, 404)

    def test_staff_navigation_keeps_active_destinations(self):
        request = RequestFactory().get(reverse("auction_calendar"))
        request.user = SimpleNamespace(is_authenticated=True, is_staff=True, username="staff")
        html = render_to_string("base.html", request=request)

        self.assertNotIn('href="/inventory/"', html)
        self.assertNotIn('href="/coordinate/"', html)
        for name in ("gallery", "auction_calendar", "capital_dashboard", "account_profile"):
            with self.subTest(destination=name):
                self.assertIn(f'href="{reverse(name)}"', html)

    def test_public_navigation_remains_available(self):
        request = RequestFactory().get(reverse("home"))
        request.user = AnonymousUser()
        html = render_to_string("base.html", request=request)

        for name in ("home", "gallery", "about", "contact", "login"):
            with self.subTest(destination=name):
                self.assertIn(f'href="{reverse(name)}"', html)

    def test_active_calendar_and_gallery_routes_still_resolve(self):
        for name in ("gallery", "auction_calendar", "auction_calendar_inventory", "auction_research_queue"):
            with self.subTest(destination=name):
                self.assertEqual(resolve(reverse(name)).url_name, name)

    def test_retired_workspaces_are_absent_from_the_runtime_model_registry(self):
        registered = apps.get_app_config("secondstateapp").get_models()
        self.assertEqual(
            [model.__name__ for model in registered if model.__name__.startswith(("Coordinate", "Inventory"))],
            [],
        )
