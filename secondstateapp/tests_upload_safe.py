"""Smoke-test notes for upload_safe_views.

Manual check:
1. Upload an artwork with multiple images through the desktop catalog app.
2. Confirm /artworks/upload_artwork/ returns 201 when the artwork row is created.
3. If an image raises during ArtworkImage creation, the JSON response should include
   warnings while still preserving the artwork record.
"""
