"""Saved image delivery and compatibility with the deployed calendar API."""

import json
from unittest import TestCase
from unittest.mock import Mock

from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_sync import CalendarSyncError, sync_watchlist_lots


def image_lot(number, pixels="image-pixels"):
    return NormalizedLot(
        source="Heritage", source_lot_id=f"8280-{number}", artist="Test Artist",
        artist_watchlist_name="Test Artist", title="Print", saved_image_base64=pixels,
        lot_url=f"https://fineart.ha.com/itm/print/a/8280-{number}.s",
    )


def accepting_session():
    session = Mock()

    def post(_endpoint, **kwargs):
        records = kwargs["json"]["lots"]
        response = Mock(status_code=200)
        response.json.return_value = {
            "ok": True, "received": len(records), "created": 0,
            "updated": len(records), "ended": 0,
            "images_received": sum(bool(record.get("saved_image_base64")) for record in records),
        }
        return response

    session.post.side_effect = post
    return session


class SavedImageSyncTests(TestCase):
    def test_empty_saved_image_preserves_existing_lot_hash_shape(self):
        lot = image_lot(65001, "")
        self.assertNotIn("saved_image_base64", lot.visible_content())
        original_hash = lot.content_hash
        lot.saved_image_base64 = "normalized-pixels"
        self.assertNotEqual(lot.calculate_content_hash(), original_hash)

    def test_sync_confirms_saved_images_and_excludes_private_fields(self):
        session = accepting_session()
        lot = image_lot(65001)
        lot.ambiguities = ["private parser detail"]
        result = sync_watchlist_lots([lot], base_url="https://secondstate.art", api_key="test", session=session)
        self.assertEqual(result.images_received, 1)
        self.assertIn("1 saved artwork images synced", result.summary())
        record = session.post.call_args.kwargs["json"]["lots"][0]
        self.assertEqual(record["saved_image_base64"], "image-pixels")
        self.assertNotIn("ambiguities", record)
        self.assertNotIn("content_hash", record)

    def test_older_server_cannot_silently_claim_image_success(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True, "received": 1, "created": 0, "updated": 1}
        session.post.return_value = response
        with self.assertRaisesRegex(CalendarSyncError, "Deploy the website's saved-image update"):
            sync_watchlist_lots([image_lot(65001)], base_url="https://secondstate.art", api_key="test", session=session)

    def test_large_catalog_is_batched_and_counts_are_combined(self):
        session = accepting_session()
        lots = [image_lot(number, "a" * 600_000) for number in range(5)]
        result = sync_watchlist_lots(
            lots, base_url="https://secondstate.art", api_key="test", session=session,
            artist_artprice_links={"Test Artist": "https://www.artprice.com/artist/1/test"},
        )
        self.assertEqual(result.received, 5)
        self.assertEqual(result.images_received, 5)
        self.assertGreater(session.post.call_count, 1)
        records = []
        for index, call in enumerate(session.post.call_args_list):
            payload = call.kwargs["json"]
            self.assertLess(len(json.dumps(payload).encode("utf-8")), 1_800_000)
            self.assertEqual(len(payload["artist_links"]), 1 if index == 0 else 0)
            records.extend(payload["lots"])
        self.assertEqual([record["source_lot_id"] for record in records], [lot.source_lot_id for lot in lots])

    def test_invalid_or_incomplete_confirmation_is_an_error(self):
        for received in (0, "not-a-number"):
            with self.subTest(received=received):
                session = Mock()
                response = Mock(status_code=200)
                response.json.return_value = {"ok": True, "received": received}
                session.post.return_value = response
                with self.assertRaises(CalendarSyncError):
                    sync_watchlist_lots([image_lot(65001)], base_url="https://secondstate.art", api_key="test", session=session)

    def test_oversized_single_record_rejected_before_network(self):
        session = accepting_session()
        with self.assertRaisesRegex(CalendarSyncError, "too large"):
            sync_watchlist_lots([image_lot(65001, "a" * 1_800_000)], base_url="https://secondstate.art", api_key="test", session=session)
        session.post.assert_not_called()
