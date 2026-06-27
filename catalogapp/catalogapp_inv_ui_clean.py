try:
    from catalogapp.catalogapp_inv_ui_delete import ArtCatalogAppWithDelete
except ImportError:
    from catalogapp_inv_ui_delete import ArtCatalogAppWithDelete

import tkinter as tk

import pandas as pd


class ArtCatalogAppClean(ArtCatalogAppWithDelete):
    def _is_repeated_header_row(self, row):
        artist = str(row.get("Artist", "")).strip().lower()
        title = str(row.get("Title", "")).strip().lower()
        low = str(row.get("Low", "")).strip().lower()
        high = str(row.get("High", "")).strip().lower()
        return (artist == "artist" and title == "title") or low == "low" or high == "high"

    def _fill_results(self, results):
        clean_results = results[~results.apply(self._is_repeated_header_row, axis=1)]
        super()._fill_results(clean_results)

    def _format_money(self, value):
        if not pd.notna(value):
            return "N/A"
        text = str(value).replace("$", "").replace(",", "").strip()
        try:
            return f"${int(float(text)):,}"
        except (TypeError, ValueError):
            return "N/A"

    def format_catalog_entry(self, row):
        artist = self.safe(row.get("Artist", "")).upper() or "UNKNOWN ARTIST"
        title = self.safe(row.get("Title", "")) or "Untitled"
        year = self.safe(row.get("Year", ""), "Unknown Year")
        medium = self.safe(row.get("Medium", ""), "Unknown Medium")
        notes = self.safe(row.get("Description/Notes", ""))
        dimensions_text, sheet_size = self._dimensions_from_row(row)
        size_label = "Sheet Size" if sheet_size else "Image Size"
        size_value = sheet_size or dimensions_text
        catalog_number = self.safe(row.get("Catalog Number", ""), "N/A")
        low = self._format_money(row.get("Low"))
        high = self._format_money(row.get("High"))
        text = f"{artist}\n{title}, {year}\n{medium}"
        if notes:
            text += f"\n{notes}"
        text += f"\n{size_label}: {size_value}"
        if catalog_number:
            text += f"\nCatalog #: {catalog_number}"
        return text + f"\n\nEstimate: {low} - {high}"


def main():
    root = tk.Tk()
    ArtCatalogAppClean(root)
    root.mainloop()


if __name__ == "__main__":
    main()
