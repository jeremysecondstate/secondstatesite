# Safer catalog upload behavior

The desktop catalog app uses `/artworks/upload_artwork/` to create live listings.

This branch routes that endpoint through `upload_safe_views.upload_artwork`, which creates the artwork row first and then records image-save warnings without turning the whole upload into a false failure after the listing already exists.
