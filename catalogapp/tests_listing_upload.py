"""Uploader regressions; all network requests and AI generation are mocked."""

import unittest
from unittest.mock import Mock, mock_open, patch

import tkinter as tk
from tkinter import ttk

import pandas as pd

from catalogapp import catalogapp_inv_ui as ui
from catalogapp.catalogapp_inv_ui_clean import ArtCatalogAppClean


def response(payload, status=200, text=""):
    result = Mock(status_code=status, text=text)
    result.json.return_value = payload
    return result


class GenerationRequestTests(unittest.TestCase):
    def setUp(self):
        self.app = ui.ArtCatalogApp.__new__(ui.ArtCatalogApp)

    def test_generate_notes_uses_draft_or_existing_route_and_normalized_sizes(self):
        for artwork_id, suffix in ((None, "/artworks/generate_notes/"), (108, "/artworks/108/generate_notes/")):
            with self.subTest(artwork_id=artwork_id), patch.object(ui.requests, "post", return_value=response({"notes": " Signed in pencil. "})) as post:
                data = {"title": "Reconnect", "description": "Signed in pencil.", "dimensions_text": '35.8267716535433" x 24.015748031496063"'}
                self.assertEqual(self.app._generate_notes(data, artwork_id), "Signed in pencil.")
                args, kwargs = post.call_args
                self.assertTrue(args[0].endswith(suffix))
                self.assertEqual(kwargs["json"]["dimensions_text"], '35.83" x 24.02"')
                self.assertEqual(kwargs["json"]["description"], data["description"])
                self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
                self.assertEqual(kwargs["timeout"], 70)
                self.assertNotEqual(data["dimensions_text"], kwargs["json"]["dimensions_text"])

    def test_generate_notes_reports_api_error_and_rejects_empty_draft(self):
        with patch.object(ui.requests, "post", return_value=response({"error": "OpenAI is unavailable."}, status=503)):
            with self.assertRaisesRegex(RuntimeError, "OpenAI is unavailable"):
                self.app._generate_notes({})
        with patch.object(ui.requests, "post", return_value=response({"notes": "  "})):
            with self.assertRaisesRegex(ValueError, "empty generated notes"):
                self.app._generate_notes({})

    def test_api_error_retains_nested_details_and_non_json_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "Useful reason"):
            ui.raise_for_api_error(response({"detail": {"message": "Useful reason"}}, status=400), "Generate notes")
        failure = response(None, status=502, text="Upstream gateway unavailable")
        failure.json.side_effect = ValueError("not JSON")
        with self.assertRaisesRegex(RuntimeError, "Upstream gateway unavailable"):
            ui.raise_for_api_error(failure, "Generate notes")

    def test_catalog_payload_cleans_accounting_and_formats_dimensions(self):
        row = pd.Series({
            "Artist": "Fairey, Shepard", "Title": "Reconnect", "Height": 35.8267716535433,
            "Width": 24.015748031496063,
            "Description/Notes": "Signed and dated in pencil. Excellent condition per auctioneer. Invoice V01760: hammer EUR 50 + Drouot fee EUR 0.75. USD conversion: EUR 1 = USD 1.1435. Year, edition and shipping not stated.",
        })
        data = self.app._row_to_payload(row, price="1000.00")
        self.assertEqual(data["dimensions_text"], '35.83" x 24.02"')
        self.assertEqual(data["description"], "Signed and dated in pencil. Excellent condition per auctioneer.")
        self.assertEqual(data["price"], "1000.00")


class UploaderDialogTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        # Construct only the app instance; __init__ schedules a shared-drive read.
        self.app = ui.ArtCatalogApp.__new__(ui.ArtCatalogApp)
        self.app.master = self.root
        self.post = self.enterContext(patch.object(ui.requests, "post", side_effect=AssertionError("Unexpected network write")))
        self.enterContext(patch.object(ui.requests, "get", side_effect=AssertionError("Unexpected network read")))
        self.errors = self.enterContext(patch.object(ui.messagebox, "showerror"))

    def tearDown(self):
        if hasattr(self, "root"):
            self.root.destroy()

    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from UploaderDialogTests.descendants(child)

    def button(self, widget, label):
        return next(item for item in self.descendants(widget) if isinstance(item, ttk.Button) and item.cget("text") == label)

    def texts(self, widget):
        return [item for item in self.descendants(widget) if isinstance(item, tk.Text)]

    def test_upload_generators_use_current_fields_and_continue_keeps_reviewed_drafts(self):
        notes_generator = Mock(return_value="Generated public notes.")
        description_generator = Mock(return_value="Generated description.")
        self.app._generate_notes = notes_generator
        self.app._generate_description = description_generator
        failures = []

        def interact():
            dialog = next(item for item in self.root.winfo_children() if isinstance(item, tk.Toplevel))
            try:
                entries = [item for item in self.descendants(dialog) if isinstance(item, ttk.Entry)]
                notes, description = self.texts(dialog)
                entries[0].delete(0, tk.END)
                entries[0].insert(0, "61 x 91 cm")
                notes.delete("1.0", tk.END)
                notes.insert("1.0", "Current unsaved signature.")
                self.button(dialog, "Generate Notes").invoke()
                self.assertEqual(notes_generator.call_args.args[0]["description"], "Current unsaved signature.")
                self.assertEqual(notes_generator.call_args.args[0]["dimensions_text"], '24.02" x 35.83"')
                self.button(dialog, "Generate Description").invoke()
                self.assertEqual(description_generator.call_args.args[0]["description"], "Generated public notes.")
                self.assertTrue(description_generator.call_args.args[0]["use_web"])
                self.assertEqual(description.get("1.0", tk.END).strip(), "Generated description.")
                notes.insert(tk.END, " Reviewed by gallery.")
                self.post.assert_not_called()
                self.button(dialog, "Continue to Images").invoke()
            except BaseException as exc:
                failures.append(exc)
                dialog.destroy()

        self.root.after(20, interact)
        result = self.app._upload_dialog({"title": "Reconnect", "description": "Original notes.", "catalog_description": "", "dimensions_text": "", "sheet_size": ""})
        if failures:
            raise failures[0]
        self.assertEqual(result["description"], "Generated public notes. Reviewed by gallery.")
        self.assertEqual(result["catalog_description"], "Generated description.")
        self.assertEqual(result["dimensions_text"], '24.02" x 35.83"')
        self.errors.assert_not_called()

    def test_upload_cancel_discards_generated_drafts(self):
        self.app._generate_notes = Mock(return_value="Draft only.")

        def interact():
            dialog = next(item for item in self.root.winfo_children() if isinstance(item, tk.Toplevel))
            self.button(dialog, "Generate Notes").invoke()
            self.button(dialog, "Cancel").invoke()

        self.root.after(20, interact)
        self.assertIsNone(self.app._upload_dialog({"title": "Test"}))
        self.post.assert_not_called()

    def test_upload_posts_reviewed_notes_and_description_with_selected_images(self):
        self.app.current_results = pd.DataFrame([{"Title": "Reconnect", "Artist": "Fairey, Shepard", "Height": 35.8267716535433, "Width": 24.015748031496063}], index=[3])
        self.app.tree = Mock()
        self.app.tree.selection.return_value = ["3"]
        reviewed = {"title": "Reconnect", "description": "Reviewed public notes.", "catalog_description": "Reviewed description.", "dimensions_text": '35.83" x 24.02"', "sheet_size": "", "price": "1000"}
        self.app._upload_dialog = Mock(return_value=reviewed)
        self.post.side_effect = None
        self.post.return_value = response({}, status=201)
        opened = mock_open(read_data=b"image")
        with patch.object(ui.simpledialog, "askstring", return_value="1000"), patch.object(ui.filedialog, "askopenfilenames", return_value=["selected.jpg"]), patch.object(ui.messagebox, "showinfo"), patch("builtins.open", opened):
            self.app.upload_artworks()
        self.post.assert_called_once()
        args, kwargs = self.post.call_args
        self.assertTrue(args[0].endswith("/artworks/upload_artwork/"))
        self.assertEqual(kwargs["data"], reviewed)
        self.assertEqual(kwargs["files"][0][0], "image_0")
        self.assertEqual(kwargs["files"][0][1][0], "selected.jpg")
        opened().close.assert_called_once()
        self.errors.assert_not_called()

    def test_both_editors_generate_from_unsaved_fields_and_save_only_explicitly(self):
        for app_type in (ui.ArtCatalogApp, ArtCatalogAppClean):
            with self.subTest(app_type=app_type.__name__):
                app = app_type.__new__(app_type)
                app.master = self.root
                artwork = {"id": 108, "artist": "Fairey, Shepard", "title": "Reconnect", "description": "Old notes.", "dimensions_text": '35.8267716535433" x 24.015748031496063"', "images": []}
                app._fetch_website_artworks = Mock(return_value=[artwork])
                app._generate_notes = Mock(return_value="Signed in pencil. Excellent condition.")
                app.edit_website_listings()
                win = next(item for item in self.root.winfo_children() if isinstance(item, tk.Toplevel))
                entries = [item for item in self.descendants(win) if isinstance(item, ttk.Entry)]
                fields = dict(zip((key for key, _label in app.EDIT_FIELDS), entries))
                notes, _description = self.texts(win)
                self.assertEqual(fields["dimensions_text"].get(), '35.83" x 24.02"')
                fields["title"].delete(0, tk.END)
                fields["title"].insert(0, "Reconnect edited")
                notes.delete("1.0", tk.END)
                notes.insert("1.0", "Unsigned current draft.")
                self.button(win, "Generate Notes").invoke()
                app._generate_notes.assert_called_once()
                args, kwargs = app._generate_notes.call_args
                self.assertEqual(args[0]["title"], "Reconnect edited")
                self.assertEqual(args[0]["description"], "Unsigned current draft.")
                self.assertEqual(kwargs["artwork_id"], 108)
                self.assertEqual(notes.get("1.0", tk.END).strip(), "Signed in pencil. Excellent condition.")
                self.assertEqual(artwork["description"], "Old notes.")
                self.post.assert_not_called()
                self.post.side_effect = None
                self.post.return_value = response({"artwork": dict(artwork, title="Reconnect edited", description="Reviewed notes.")})
                notes.delete("1.0", tk.END)
                notes.insert("1.0", "Reviewed notes.")
                self.button(win, "Save Changes").invoke()
                self.post.assert_called_once()
                args, kwargs = self.post.call_args
                self.assertTrue(args[0].endswith("/artworks/108/update_artwork/"))
                saved = dict(kwargs["data"])
                self.assertEqual(saved["description"], "Reviewed notes.")
                self.assertEqual(saved["title"], "Reconnect edited")
                self.assertEqual(saved["dimensions_text"], '35.83" x 24.02"')
                self.errors.assert_not_called()
                self.post.reset_mock()
                self.post.side_effect = AssertionError("Unexpected network write")
                win.destroy()


if __name__ == "__main__":
    unittest.main()
