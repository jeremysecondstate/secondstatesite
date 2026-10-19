"""Persist distinct evidence scopes without promoting context to lot evidence."""
import hashlib
import importlib
import json
from types import SimpleNamespace

from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings

from scripts.coordinate_evidence import research_identity_key
from . import tests_coordinate_browser_sources as browser_fixtures
from . import tests_coordinate_discovery as discovery_fixtures
from .coordinate_shipping import research_state
from .models import CoordinateMessage, CoordinateResearch


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True,
    COORDINATE_WORKER_TOKEN="synthetic-browser-worker-secret",
    COORDINATE_SHIPPING_PLAYBOOK="Synthetic policy.", COORDINATE_PACKING_PLAYBOOK="Synthetic packing.")
class ObservationIdentityPersistenceTests(TestCase):
    setUp = browser_fixtures.BrowserSourcePersistenceTests.setUp
    worker_post = browser_fixtures.BrowserSourcePersistenceTests.worker_post
    claim = browser_fixtures.BrowserSourcePersistenceTests.claim
    complete = browser_fixtures.BrowserSourcePersistenceTests.complete

    def records(self):
        listing = discovery_fixtures.discovered_record(text="Synthetic Artist. Synthetic Title. Lot 17. Sold: USD 500.")
        context = {**listing, "identity_match": {"status": "context", "auction_house": "Synthetic Auction"},
                   "text": "Collection terms: collect within seven days. Insurance examples use USD 450.",
                   "match_reason": "Published collection terms displayed on the same lot page."}
        return listing, context

    def test_same_page_listing_and_context_complete_once_as_separate_records(self):
        listing, context = self.records()
        claim = self.claim()
        duplicate = self.complete(claim, listing, research=[listing, {**listing, "text": "Different excerpt, same exact observation."}])
        self.assertEqual(duplicate.status_code, 400, duplicate.content)
        self.assertFalse(CoordinateResearch.objects.exists())
        response = self.complete(claim, listing, research=[listing, context])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(self.complete(claim, listing, research=[listing, context]).json()["already_completed"])
        saved = list(CoordinateResearch.objects.order_by("id"))
        self.assertEqual(len(saved), 2)
        self.assertEqual([item.text for item in saved], [listing["text"], context["text"]])
        self.assertEqual([item.identity_match["status"] for item in saved], ["exact", "context"])
        self.assertEqual(len({item.observation_key for item in saved}), 2)
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=self.message).count(), 1)
        self.assertEqual(len(research_state(self.case)), 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CoordinateResearch.objects.create(case=self.case, job=self.job, **context)
        self.assertEqual(CoordinateResearch.objects.count(), 2)

    def test_database_identity_and_update_fields_preserve_scope_uniqueness(self):
        listing, context = self.records()
        exact = CoordinateResearch.objects.create(case=self.case, job=self.job, **listing)
        terms = CoordinateResearch.objects.create(case=self.case, job=self.job, **context)
        exact.identity_match = context["identity_match"]
        with self.assertRaises(IntegrityError), transaction.atomic():
            exact.save(update_fields=["identity_match"])
        exact.refresh_from_db()
        self.assertEqual(exact.identity_match["status"], "exact")
        terms.identity_match = {"status": "historical"}
        terms.save(update_fields=["identity_match"])
        terms.refresh_from_db()
        expected = hashlib.sha256(json.dumps(research_identity_key({**context, "identity_match": terms.identity_match}),
                                            ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(terms.observation_key, expected)

    def test_data_migration_rekeys_legacy_and_v2_rows_without_changing_evidence(self):
        listing, _ = self.records()
        legacy = {**listing, "source_kind": "browser", "identity_match": {}, "text": "Original legacy excerpt."}
        records = [CoordinateResearch.objects.create(case=self.case, job=self.job, **item) for item in (listing, legacy)]
        previous = []
        for record in records:
            record.refresh_from_db()
            old = hashlib.sha256(json.dumps([record.source_url, record.final_url, record.source_kind],
                                           ensure_ascii=True).encode()).hexdigest()
            CoordinateResearch.objects.filter(pk=record.pk).update(observation_key=old)
            previous.append((record.pk, record.text, record.identity_match, record.fetched_at))
        migration = importlib.import_module("secondstateapp.migrations.0042_coordinate_observation_status")
        migration.observation_keys(apps, SimpleNamespace(connection=connection))
        for identifier, text, identity, fetched_at in previous:
            record = CoordinateResearch.objects.get(pk=identifier)
            expected = hashlib.sha256(json.dumps(research_identity_key({"source_url": record.source_url,
                "final_url": record.final_url, "source_kind": record.source_kind, "identity_match": identity}),
                ensure_ascii=True).encode()).hexdigest()
            self.assertEqual(record.observation_key, expected)
            self.assertEqual((record.text, record.identity_match, record.fetched_at), (text, identity, fetched_at))
