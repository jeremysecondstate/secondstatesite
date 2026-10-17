import os
import webbrowser
from functools import partial

import pandas as pd
import requests
import tkinter as tk
from docx import Document
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import scrolledtext

from catalogapp.catalog_paths import resolve_catalog_path
from catalogapp.studio_theme import STUDIO_COLORS, apply_studio_theme, studio_icon
from catalogapp.watchlist_ui import ArtistWatchlistPanel
from secondstate.artwork_dimensions import format_catalog_dimensions, normalize_dimensions
from secondstate.artwork_notes import clean_public_notes
from secondstate.environment import load_project_environment

load_project_environment()
BASE_URL = os.environ.get("SECONDSTATE_BASE_URL", "https://secondstate.art").rstrip("/")
APP_TITLE = "SECONDSTATE — Catalog workspace"
APP_MIN_W, APP_MIN_H = 1180, 820
CATALOG_API_KEY = os.environ.get("CATALOG_API_KEY", "").strip()
DEFAULT_CATALOG_SHEET = "Inventory for Fall 2026"


def api_headers(extra=None):
    headers = {"X-API-KEY": CATALOG_API_KEY}
    if extra:
        headers.update(extra)
    return headers


def raise_for_api_error(response, action):
    """Raise an error that preserves the API's useful JSON message."""

    if response.status_code < 400:
        return

    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("error") or payload.get("detail") or payload.get("message") or ""
            if isinstance(detail, dict):
                detail = detail.get("message") or str(detail)
    except ValueError:
        pass

    if not detail:
        detail = (response.text or "").strip()
    raise RuntimeError(detail or f"{action} failed with status {response.status_code}.")


class ArtCatalogApp:
    EDIT_FIELDS = [
        ("artist", "Artist"), ("title", "Title"), ("year", "Year"), ("medium", "Medium"),
        ("dimensions_text", "Image size"), ("sheet_size", "Sheet size"),
        ("catalog_number", "Literature"), ("price", "Price"),
    ]

    def __init__(self, master):
        self.master = master
        self.df = None
        self.current_results = None
        master.title(APP_TITLE)
        master.geometry("1280x860")
        master.minsize(APP_MIN_W, APP_MIN_H)
        self._style()
        master.iconphoto(True, studio_icon(master, "brand", size=16), studio_icon(master, "brand", size=32))
        self._build_ui()
        master.bind("<Alt-a>", self._open_actions_menu, add="+")
        master.bind("<F10>", self._open_actions_menu, add="+")
        master.bind_all("<Control-f>", self._search_from_shortcut)
        master.bind_all("<Control-e>", lambda _e: self.export_to_word())
        master.bind_all("<Control-d>", lambda _e: self.export_entire_database())
        master.bind_all("<Control-u>", lambda _e: self.upload_artworks())
        master.bind_all("<Control-q>", lambda _e: master.quit())
        master.after(100, self.load_excel)

    def _style(self):
        self.style = apply_studio_theme(self.master)

    def _build_ui(self):
        header = ttk.Frame(self.master, padding=(24, 18), style="Surface.TFrame")
        header.pack(fill=tk.X)
        ttk.Label(header, image=studio_icon(self.master, "brand", size=34),
                  style="Surface.TLabel").pack(side=tk.LEFT, padx=(0, 12))
        brand = ttk.Frame(header, style="Surface.TFrame")
        brand.pack(side=tk.LEFT)
        ttk.Label(brand, text="SECONDSTATE", font=("Georgia", 10, "bold"),
                  style="Brand.TLabel").pack(anchor="w")
        ttk.Label(brand, text="Catalog workspace", style="BrandSubtle.TLabel").pack(anchor="w", pady=(2, 0))
        # Keep global actions in the themed header; a native Windows menubar
        # ignores Tk's dark palette and adds a bright strip above the workspace.
        self.actions_button = ttk.Menubutton(header, text="Actions", underline=0,
                                             style="Secondary.TMenubutton", takefocus=True)
        self.actions_button.pack(side=tk.RIGHT, padx=(20, 0))
        self.actions_menu = tk.Menu(self.actions_button, tearoff=False)
        self.actions_menu.add_command(label="Upload Artwork(s)", command=self.upload_artworks, accelerator="Ctrl+U")
        self.actions_menu.add_command(label="Generate Description for Selected", command=self.generate_description_for_selected)
        self.actions_menu.add_command(label="Edit Website Listings", command=self.edit_website_listings)
        self.actions_menu.add_command(label="Delete Artwork from Website", command=self.delete_artwork)
        self.actions_button.configure(menu=self.actions_menu)
        catalog_source = ttk.Frame(header, style="Surface.TFrame")
        catalog_source.pack(side=tk.RIGHT)
        tk.Label(catalog_source, text="●", font=("Segoe UI", 7), background=STUDIO_COLORS["surface"],
                 foreground=STUDIO_COLORS["accent"]).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(catalog_source, text="Shared catalog database", style="SurfaceSubtle.TLabel").pack(side=tk.LEFT)

        footer = ttk.Frame(self.master)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Separator(footer).pack(fill=tk.X)
        self.status = ttk.Label(footer, text="Loading shared catalog database...", anchor="w", padding=(24, 10), style="Small.TLabel")
        self.status.pack(fill=tk.X)

        # Keep catalog actions with Results, leaving every other tab its full width.
        self.notebook = ttk.Notebook(self.master)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.tab_results = ttk.Frame(self.notebook, padding=(24, 22))
        tab_details = ttk.Frame(self.notebook, padding=(24, 22))
        tab_preview = ttk.Frame(self.notebook, padding=(24, 22))
        self.notebook.add(self.tab_results, text="Results", image=studio_icon(self.master, "grid"), compound=tk.LEFT)
        self.notebook.add(tab_details, text="Details", image=studio_icon(self.master, "file"), compound=tk.LEFT)
        self.notebook.add(tab_preview, text="Preview Text", image=studio_icon(self.master, "text"), compound=tk.LEFT)
        self.watchlist_panel = ArtistWatchlistPanel(
            self.notebook,
            status_callback=self._set_status,
            calendar_base_url=BASE_URL,
            calendar_api_key=CATALOG_API_KEY,
        )
        self.notebook.add(self.watchlist_panel, text="Artist Watchlist",
                          image=studio_icon(self.master, "calendar"), compound=tk.LEFT)

        self.tab_results.rowconfigure(0, weight=1)
        self.tab_results.columnconfigure(2, weight=1)
        # The concept uses a compact action rail; long action names wrap without
        # changing their words, order, handlers, or keyboard shortcuts.
        left = ttk.Frame(self.tab_results, width=212, padding=(0, 0, 18, 0))
        left.grid(row=0, column=0, sticky="ns")
        left.grid_propagate(False)
        left.pack_propagate(False)
        ttk.Separator(self.tab_results, orient=tk.VERTICAL).grid(row=0, column=1, sticky="ns")
        right = ttk.Frame(self.tab_results, padding=(25, 0, 0, 0))
        right.grid(row=0, column=2, sticky="nsew")
        self.results_content = right
        right.columnconfigure(0, weight=1)
        right.rowconfigure(4, weight=1)
        right.bind("<Configure>", self._resize_results_table)

        ttk.Label(left, text="Search by Title or Artist", style="Subtle.TLabel").pack(anchor="w")
        search_row = ttk.Frame(left)
        search_row.pack(fill=tk.X, pady=(7, 16))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var, width=13)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<Return>", self.search_catalog)
        search_hint = tk.Label(self.search_entry, text="Artist or title", anchor="w", borderwidth=0,
                               background=STUDIO_COLORS["surface"], foreground=STUDIO_COLORS["muted"],
                               font=("Segoe UI", 9))
        search_hint.place(x=9, rely=0.5, anchor="w")
        search_hint.bind("<Button-1>", lambda _event: self.search_entry.focus_set())
        def update_search_hint(*_args):
            if self.search_var.get() or self.search_entry.focus_get() == self.search_entry:
                search_hint.place_forget()
            else:
                search_hint.place(x=9, rely=0.5, anchor="w")
        self.search_var.trace_add("write", update_search_hint)
        self.search_entry.bind("<FocusIn>", update_search_hint)
        self.search_entry.bind("<FocusOut>", update_search_hint)
        ttk.Button(search_row, image=studio_icon(self.master, "search"), command=self.search_catalog,
                   style="Secondary.TButton", width=2).pack(side=tk.LEFT, padx=(5, 0))

        for text, cmd, style, icon_name in [
            ("Export Search -> Word", self.export_to_word, "Rail.TButton", "export"),
            ("Export Entire Database", self.export_entire_database, "Rail.TButton", "database"),
            ("Upload Artwork(s) to\nWebsite", self.upload_artworks, "Upload.TButton", "upload"),
            ("Generate Description for\nSelected", self.generate_description_for_selected, "Rail.TButton", "sparkles"),
            ("Edit Website Listings", self.edit_website_listings, "Rail.TButton", "edit"),
            ("Delete Artwork from\nWebsite", self.delete_artwork, "RailDanger.TButton", "trash"),
            ("Go to Your Listings", lambda: webbrowser.open(f"{BASE_URL}/artworks/"), "Rail.TButton", "external"),
            ("Display All Inventory", self.display_all_inventory, "Rail.TButton", "rows"),
        ]:
            icon_color = STUDIO_COLORS["on_accent"] if style == "Upload.TButton" else (
                STUDIO_COLORS["danger"] if style == "RailDanger.TButton" else STUDIO_COLORS["ink"]
            )
            ttk.Button(left, text=text, command=cmd, style=style, compound=tk.LEFT,
                       image=studio_icon(self.master, icon_name, color=icon_color, size=15)).pack(fill=tk.X, pady=3)

        shortcuts = ttk.Frame(left, padding=(0, 12, 0, 0))
        shortcuts.pack(fill=tk.X)
        for label, key in (("Search", "Ctrl+F"), ("Export search", "Ctrl+E"),
                           ("Export database", "Ctrl+D"), ("Upload selected", "Ctrl+U"), ("Quit", "Ctrl+Q")):
            row = ttk.Frame(shortcuts)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=label, style="Small.TLabel").pack(side=tk.LEFT)
            ttk.Label(row, text=key, style="Small.TLabel").pack(side=tk.RIGHT)

        result_heading = ttk.Frame(right)
        result_heading.grid(row=0, column=0, sticky="ew")
        ttk.Label(result_heading, text="Results", style="Header.TLabel").pack(side=tk.LEFT)
        self.results_count = ttk.Label(result_heading, text="", style="Small.TLabel")
        self.results_count.pack(side=tk.RIGHT)
        ttk.Label(right, text="Search, select, edit and upload.", style="Subtle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 18)
        )
        table_frame = ttk.Frame(right)
        table_frame.grid(row=2, column=0, sticky="ew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        cols = ("Artist", "Title", "Year", "Medium", "Catalog #")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", style="Inventory.Treeview",
                                 selectmode="extended", height=5)
        for c, width, minimum in zip(cols, (190, 240, 70, 140, 100), (140, 170, 60, 110, 95)):
            self.tree.heading(c, text=c, anchor="w", command=partial(self._sort_tree, c, False))
            self.tree.column(c, width=width, minwidth=minimum, stretch=True, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=lambda first, last: self._update_scrollbar(vsb, first, last),
                            xscrollcommand=lambda first, last: self._update_scrollbar(hsb, first, last))
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._on_select_row)
        self.results_empty = ttk.Frame(table_frame, padding=(24, 22))
        ttk.Label(self.results_empty, image=studio_icon(self.master, "search", color=STUDIO_COLORS["muted"], size=24)).pack(pady=(0, 12))
        self.results_empty_title = ttk.Label(self.results_empty, text="Your catalog, ready to explore",
                                             font=("Segoe UI Semibold", 12))
        self.results_empty_title.pack()
        self.results_empty_hint = ttk.Label(self.results_empty,
                                            text="Search by artist or title, or choose Display All Inventory.",
                                            style="Subtle.TLabel")
        self.results_empty_hint.pack(pady=(7, 0))
        self.results_empty.place(x=0, y=55, relwidth=1)

        self.selection_bar = ttk.Frame(right, style="Status.TFrame", padding=(12, 10))
        self.selection_bar.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        self.selection_summary = ttk.Label(self.selection_bar, text="No artwork selected", anchor="w",
                                           style="Status.TLabel", font=("Segoe UI", 9))
        self.selection_summary.pack(side=tk.LEFT)
        ttk.Label(self.selection_bar, text="Ctrl or Shift to select multiple", anchor="e",
                  style="Status.TLabel", foreground=STUDIO_COLORS["muted"],
                  font=("Segoe UI", 8)).pack(side=tk.RIGHT)

        self.details_text = self._build_text_tab(tab_details, "Details", "Catalog details for the selected artwork.")
        self.text_display = self._build_text_tab(tab_preview, "Preview Text", "Formatted catalog text for the current results.")

    def _open_actions_menu(self, event=None):
        # ttk menubuttons do not receive Windows' native menu mnemonic handling.
        self.actions_button.event_generate("<<Invoke>>")
        return "break"

    @staticmethod
    def _update_scrollbar(scrollbar, first, last):
        scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            scrollbar.grid_remove()
        else:
            scrollbar.grid()

    def _resize_results_table(self, event=None):
        if not hasattr(self, "tree"):
            return
        # Short results end at the selection strip, just like the concept. A
        # longer inventory uses the available height and the normal scrollbar.
        row_height = int(self.style.lookup("Inventory.Treeview", "rowheight") or 54)
        available = max(3, (self.results_content.winfo_height() - 170) // row_height)
        count = len(self.tree.get_children())
        rows = min(max(4 if count == 0 else 1, count), available)
        if int(self.tree.cget("height")) != rows:
            self.tree.configure(height=rows)

    def _update_results_presentation(self, empty_title=None, empty_hint=None):
        # Presentation is optional for unit tests that exercise catalog logic
        # without constructing the application window.
        if not hasattr(self, "results_count"):
            return
        count = len(self.tree.get_children())
        self.results_count.configure(text=f"{count:,} artwork{'s' if count != 1 else ''}" if count else "")
        if count:
            self.results_empty.place_forget()
        else:
            self.results_empty_title.configure(text=empty_title or "Your catalog, ready to explore")
            self.results_empty_hint.configure(text=empty_hint or "Search by artist or title, or choose Display All Inventory.")
            self.results_empty.place(x=0, y=55, relwidth=1)
        selected = self.tree.selection()
        summary = "Select artwork to view Details" if count else "No artwork selected"
        if selected:
            summary = f"{len(selected):,} selected"
            if len(selected) == 1:
                artist = self.tree.set(selected[0], "Artist")
                if artist:
                    summary += f" · {artist}"
        self.selection_summary.configure(text=summary)
        self._resize_results_table()

    def _build_text_tab(self, tab, title, subtitle):
        ttk.Label(tab, text=title, style="Header.TLabel").pack(anchor="w")
        ttk.Label(tab, text=subtitle, style="Subtle.TLabel").pack(anchor="w", pady=(4, 18))
        surface = ttk.Frame(tab, padding=1, style="Surface.TFrame")
        surface.pack(fill=tk.BOTH, expand=True)
        surface.rowconfigure(0, weight=1)
        surface.columnconfigure(0, weight=1)
        text = tk.Text(
            surface, wrap=tk.WORD, height=16, font=("Segoe UI", 11), background=STUDIO_COLORS["surface"],
            foreground=STUDIO_COLORS["ink"], relief=tk.FLAT, borderwidth=0, highlightthickness=1,
            highlightbackground=STUDIO_COLORS["line"], highlightcolor=STUDIO_COLORS["accent"],
            padx=22, pady=20, spacing1=3, spacing3=5, selectbackground=STUDIO_COLORS["soft"],
            selectforeground=STUDIO_COLORS["ink"],
        )
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(surface, orient=tk.VERTICAL, command=text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scrollbar.set, state=tk.DISABLED)
        return text

    def _set_status(self, text):
        self.status.config(text=text)

    def safe(self, val, fallback=""):
        return str(val).strip() if pd.notna(val) else fallback

    def _sort_tree(self, col, reverse):
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        data.sort(key=lambda t: (t[0] or "").lower(), reverse=reverse)
        for index, (_val, k) in enumerate(data):
            self.tree.move(k, "", index)
        self.tree.heading(col, command=lambda c=col: self._sort_tree(c, not reverse))

    def _selected_catalog_row(self):
        sel = self.tree.selection()
        if not sel or self.current_results is None:
            return None
        return self.current_results.loc[int(sel[0])]

    def _dimensions_from_row(self, row):
        return format_catalog_dimensions(row.get("Height"), row.get("Width"))

    @staticmethod
    def _normalize_listing_dimensions(data):
        data = dict(data)
        for field in ("dimensions_text", "sheet_size"):
            if field in data:
                data[field] = normalize_dimensions(data[field])
        return data

    def _row_to_payload(self, row, price="", catalog_description=""):
        dimensions_text, sheet_size = self._dimensions_from_row(row)
        return {
            "artist": self.safe(row.get("Artist", "")),
            "title": self.safe(row.get("Title", "")) or "Untitled",
            "year": self.safe(row.get("Year", "")),
            "medium": self.safe(row.get("Medium", "")),
            "description": clean_public_notes(self.safe(row.get("Description/Notes", ""))),
            "dimensions_text": dimensions_text,
            "sheet_size": sheet_size,
            "catalog_number": self.safe(row.get("Catalog Number", "")),
            "price": price,
            "catalog_description": catalog_description,
        }

    def _load_excel_from_path(self, path):
        preview = pd.read_excel(path, sheet_name=DEFAULT_CATALOG_SHEET, header=None, nrows=30)
        header_row = None
        for i in range(len(preview)):
            row_vals = preview.iloc[i].astype(str).str.strip().tolist()
            if "Title" in row_vals and "Artist" in row_vals:
                header_row = i
                break
        if header_row is None:
            raise ValueError(f"Could not find a header row containing both 'Title' and 'Artist' on sheet '{DEFAULT_CATALOG_SHEET}'.")
        self.df = pd.read_excel(path, sheet_name=DEFAULT_CATALOG_SHEET, header=header_row)
        self.df.columns = [str(c).strip() for c in self.df.columns]
        self._clear_results()
        self._set_status(f"Loaded: {os.path.basename(path)} — {len(self.df):,} records")

    def load_excel(self):
        try:
            self._load_excel_from_path(resolve_catalog_path())
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load Excel file:\n{e}")

    def _clear_results(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.current_results = None
        for widget in (self.details_text, self.text_display):
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            widget.configure(state=tk.DISABLED)
        self._update_results_presentation()

    def _fill_results(self, results):
        self._clear_results()
        self.current_results = results
        for idx, row in results.iterrows():
            self.tree.insert("", tk.END, iid=str(idx), values=(self.safe(row.get("Artist", "")), self.safe(row.get("Title", "")), self.safe(row.get("Year", "")), self.safe(row.get("Medium", "")), self.safe(row.get("Catalog Number", ""))))
        entries = [self.format_catalog_entry(row) for _, row in results.iterrows()]
        self.text_display.configure(state=tk.NORMAL)
        self.text_display.insert(tk.END, "\n\n".join(entries))
        self.text_display.configure(state=tk.DISABLED)
        self._update_results_presentation()

    def display_all_inventory(self):
        if self.df is None:
            messagebox.showwarning("No Catalog", "Open an Excel catalog first.")
            return
        self._fill_results(self.df)
        self._set_status(f"Showing all inventory: {len(self.df)} records.")

    def search_catalog(self, event=None):
        if self.df is None:
            messagebox.showwarning("No Catalog", "Open an Excel catalog first.")
            return
        query = self.search_var.get().lower().strip()
        if not query:
            messagebox.showwarning("Warning", "Enter a search query!")
            return
        results = self.df[self.df["Title"].astype(str).str.lower().str.contains(query, na=False) | self.df["Artist"].astype(str).str.lower().str.contains(query, na=False)]
        if results.empty:
            self._clear_results()
            self._update_results_presentation(
                empty_title="No matching artworks",
                empty_hint="Try another artist or title to search your catalog.",
            )
            self._set_status("No results found.")
            return
        self._fill_results(results)
        self._set_status(f"Found {len(results)} result(s).")

    def _search_from_shortcut(self, event=None):
        self.notebook.select(self.tab_results)
        self.search_entry.focus_set()
        if self.search_var.get().strip():
            self.search_catalog(event)
        return "break"

    def _on_select_row(self, event=None):
        self._update_results_presentation()
        row = self._selected_catalog_row()
        if row is None:
            return
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert(tk.END, self.format_catalog_entry(row))
        self.details_text.configure(state=tk.DISABLED)

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
        low = f"${int(row['Low']):,}" if pd.notna(row.get("Low")) else "N/A"
        high = f"${int(row['High']):,}" if pd.notna(row.get("High")) else "N/A"
        text = f"{artist}\n{title}, {year}\n{medium}"
        if notes:
            text += f"\n{notes}"
        text += f"\n{size_label}: {size_value}"
        if catalog_number:
            text += f"\nCatalog #: {catalog_number}"
        return text + f"\n\nEstimate: {low} - {high}"

    def _fetch_website_artworks(self):
        response = requests.get(f"{BASE_URL}/artworks/manage_json/", headers=api_headers(), timeout=25)
        response.raise_for_status()
        return response.json().get("artworks", [])

    def _generate_description(self, payload):
        response = requests.post(f"{BASE_URL}/artworks/generate_description/", json=payload, headers=api_headers({"Content-Type": "application/json"}), timeout=70)
        raise_for_api_error(response, "Generate description")
        description = response.json().get("description", "").strip()
        if not description:
            raise ValueError("Website returned an empty generated description.")
        return description

    def _generate_notes(self, payload, artwork_id=None):
        path = f"artworks/{artwork_id}/generate_notes/" if artwork_id is not None else "artworks/generate_notes/"
        response = requests.post(
            f"{BASE_URL}/{path}", json=self._normalize_listing_dimensions(payload),
            headers=api_headers({"Content-Type": "application/json"}), timeout=70,
        )
        raise_for_api_error(response, "Generate notes")
        notes = response.json().get("notes", "").strip()
        if not notes:
            raise ValueError("Website returned empty generated notes.")
        return notes

    def _upload_dialog(self, payload):
        """Review the public notes, dimensions, and description before upload."""
        dialog = tk.Toplevel(self.master)
        dialog.title(f"Review upload: {payload['title']}")
        dialog.geometry("860x760")
        dialog.minsize(760, 620)
        dialog.transient(self.master)
        dialog.grab_set()
        form = ttk.Frame(dialog, padding=16)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text=payload["title"], style="Header.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        size_fields = {}
        for row_num, (key, label) in enumerate((("dimensions_text", "Image size"), ("sheet_size", "Sheet size")), start=1):
            ttk.Label(form, text=label).grid(row=row_num, column=0, sticky="w", padx=(0, 12), pady=3)
            entry = ttk.Entry(form)
            entry.grid(row=row_num, column=1, sticky="ew", pady=3)
            entry.insert(0, payload.get(key, ""))
            size_fields[key] = entry
        ttk.Label(form, text='Inches, for example 11.5" x 14.75".', style="Subtle.TLabel").grid(row=3, column=1, sticky="w")
        ttk.Label(form, text="Notes / signature text").grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 4))
        notes_text = scrolledtext.ScrolledText(form, wrap=tk.WORD, height=5, font=("Segoe UI", 10))
        notes_text.grid(row=5, column=0, columnspan=2, sticky="nsew")
        notes_text.insert(tk.END, payload.get("description", ""))
        form.rowconfigure(5, weight=1)
        ttk.Label(form, text="Description").grid(row=7, column=0, columnspan=2, sticky="w", pady=(12, 4))
        desc_text = scrolledtext.ScrolledText(form, wrap=tk.WORD, height=10, font=("Segoe UI", 10))
        desc_text.grid(row=8, column=0, columnspan=2, sticky="nsew")
        desc_text.insert(tk.END, payload.get("catalog_description", ""))
        form.rowconfigure(8, weight=2)
        use_web = tk.BooleanVar(value=True)
        status = ttk.Label(form, text="Review the public notes and description before continuing.", style="Subtle.TLabel")
        status.grid(row=10, column=0, columnspan=2, sticky="w", pady=(10, 0))
        result = {"value": None}

        def current_payload():
            data = dict(payload)
            data.update({key: widget.get().strip() for key, widget in size_fields.items()})
            data["description"] = notes_text.get("1.0", tk.END).strip()
            data["catalog_description"] = desc_text.get("1.0", tk.END).strip()
            return self._normalize_listing_dimensions(data)

        def generate(kind):
            for button in generation_buttons:
                button.config(state=tk.DISABLED)
            try:
                status.config(text=f"Generating {kind}...")
                dialog.update_idletasks()
                data = current_payload()
                if kind == "notes":
                    generated, target = self._generate_notes(data), notes_text
                else:
                    data["use_web"] = use_web.get()
                    generated, target = self._generate_description(data), desc_text
                target.delete("1.0", tk.END)
                target.insert(tk.END, generated)
                status.config(text=f"Draft {kind} inserted. Review/edit before continuing.")
            except Exception as exc:
                messagebox.showerror(f"Generate {kind.title()} Failed", str(exc), parent=dialog)
            finally:
                for button in generation_buttons:
                    button.config(state=tk.NORMAL)

        def accept():
            result["value"] = current_payload()
            dialog.destroy()

        notes_btn = ttk.Button(form, text="Generate Notes", command=lambda: generate("notes"), style="Accent.TButton")
        notes_btn.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        description_actions = ttk.Frame(form)
        description_actions.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        desc_btn = ttk.Button(description_actions, text="Generate Description", command=lambda: generate("description"), style="Accent.TButton")
        desc_btn.pack(side=tk.LEFT)
        ttk.Checkbutton(description_actions, text="allow web search", variable=use_web).pack(side=tk.LEFT, padx=(10, 0))
        generation_buttons = (notes_btn, desc_btn)
        actions = ttk.Frame(form)
        actions.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Continue to Images", command=accept, style="Success.TButton").pack(side=tk.RIGHT)
        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=(0, 8))
        dialog.wait_window()
        return result["value"]

    def _description_dialog(self, title, payload, initial_text=""):
        dialog = tk.Toplevel(self.master)
        dialog.title(title)
        dialog.geometry("760x620")
        dialog.transient(self.master)
        dialog.grab_set()
        frm = ttk.Frame(dialog, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text=title, style="Header.TLabel").pack(anchor="w")
        text = scrolledtext.ScrolledText(frm, wrap=tk.WORD, height=18, font=("Segoe UI", 11))
        text.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        text.insert(tk.END, initial_text or payload.get("catalog_description", ""))
        use_web = tk.BooleanVar(value=True)
        status = ttk.Label(frm, text="", style="Subtle.TLabel")
        status.pack(anchor="w", pady=(8, 0))
        result = {"value": None}

        def generate():
            generate_btn.config(state=tk.DISABLED)
            try:
                working = dict(payload)
                working["catalog_description"] = text.get("1.0", tk.END).strip()
                working["use_web"] = use_web.get()
                status.config(text="Generating description...")
                dialog.update_idletasks()
                description = self._generate_description(working)
                text.delete("1.0", tk.END)
                text.insert(tk.END, description)
                status.config(text="Draft inserted. Review/edit before using it.")
            except Exception as exc:
                messagebox.showerror("Generate Description Failed", str(exc), parent=dialog)
            finally:
                generate_btn.config(state=tk.NORMAL)

        def accept():
            result["value"] = text.get("1.0", tk.END).strip()
            dialog.destroy()

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(10, 0))
        generate_btn = ttk.Button(btns, text="Generate with OpenAI", command=generate, style="Accent.TButton")
        generate_btn.pack(side=tk.LEFT)
        ttk.Checkbutton(btns, text="allow web search", variable=use_web).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(btns, text="Use Description", command=accept, style="Success.TButton").pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=(0, 8))
        dialog.wait_window()
        return result["value"]

    def generate_description_for_selected(self):
        row = self._selected_catalog_row()
        if row is None:
            messagebox.showwarning("No Selection", "Select one artwork row first.")
            return
        payload = self._row_to_payload(row)
        description = self._description_dialog(f"Description for {payload['title']}", payload)
        if description is not None:
            self.text_display.configure(state=tk.NORMAL)
            self.text_display.delete("1.0", tk.END)
            self.text_display.insert(tk.END, description)
            self.text_display.configure(state=tk.DISABLED)
            self._set_status("Generated description is shown in Preview Text. It is not saved until upload/edit save.")

    def edit_website_listings(self):
        try:
            artworks = self._fetch_website_artworks()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch artworks: {e}")
            return
        if not artworks:
            messagebox.showinfo("No Listings", "No website listings found.")
            return
        win = tk.Toplevel(self.master)
        win.title("Edit Website Listings")
        win.geometry("1180x760")
        paned = ttk.Panedwindow(win, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        left = ttk.Frame(paned, padding=8)
        right = ttk.Frame(paned, padding=8)
        paned.add(left, weight=1)
        paned.add(right, weight=2)
        ttk.Label(left, text="Website Listings", style="Header.TLabel").pack(anchor="w")
        listing_tree = ttk.Treeview(left, columns=("Artist", "Title", "Price"), show="headings")
        for col in ("Artist", "Title", "Price"):
            listing_tree.heading(col, text=col)
            listing_tree.column(col, width=140, stretch=True)
        listing_tree.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        for art in artworks:
            listing_tree.insert("", tk.END, iid=str(art.get("id")), values=(art.get("artist", ""), art.get("title", ""), art.get("price", "")))

        fields, selected = {}, {"art": None}
        is_available = tk.BooleanVar(value=True)
        form = ttk.Frame(right)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)
        row_num = 0
        ttk.Label(form, text="Edit Listing", style="Header.TLabel").grid(row=row_num, column=0, columnspan=2, sticky="w")
        row_num += 1
        for key, label in self.EDIT_FIELDS:
            ttk.Label(form, text=label).grid(row=row_num, column=0, sticky="w", padx=(0, 8), pady=3)
            entry = ttk.Entry(form)
            entry.grid(row=row_num, column=1, sticky="ew", pady=3)
            fields[key] = entry
            row_num += 1
        notes_heading = ttk.Frame(form)
        notes_heading.grid(row=row_num, column=0, sticky="nw", padx=(0, 8), pady=3)
        ttk.Label(notes_heading, text="Notes / signature text").pack(anchor="w")
        notes_btn = ttk.Button(notes_heading, text="Generate Notes", command=lambda: generate_notes(), style="Accent.TButton")
        notes_btn.pack(anchor="w", pady=(4, 0))
        notes_text = scrolledtext.ScrolledText(form, wrap=tk.WORD, height=4, font=("Segoe UI", 10))
        notes_text.grid(row=row_num, column=1, sticky="ew", pady=3)
        row_num += 1
        ttk.Label(form, text="Description").grid(row=row_num, column=0, sticky="nw", padx=(0, 8), pady=3)
        desc_text = scrolledtext.ScrolledText(form, wrap=tk.WORD, height=8, font=("Segoe UI", 10))
        desc_text.grid(row=row_num, column=1, sticky="nsew", pady=3)
        form.rowconfigure(row_num, weight=1)
        row_num += 1
        ttk.Checkbutton(form, text="Available", variable=is_available).grid(row=row_num, column=1, sticky="w")
        row_num += 1
        image_box = ttk.LabelFrame(form, text="Images")
        image_box.grid(row=row_num, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        image_list = ttk.Frame(image_box, padding=6)
        image_list.pack(fill=tk.X)
        image_status = ttk.Label(image_box, text="", style="Subtle.TLabel")
        image_status.pack(anchor="w", padx=6, pady=(0, 6))
        delete_image_vars, add_image_paths = {}, []
        status = ttk.Label(right, text="Select a listing to edit.", style="Subtle.TLabel")
        status.pack(anchor="w", pady=(8, 0))

        def payload():
            data = {key: widget.get().strip() for key, widget in fields.items()}
            data["description"] = notes_text.get("1.0", tk.END).strip()
            data["catalog_description"] = desc_text.get("1.0", tk.END).strip()
            data["is_available"] = is_available.get()
            return self._normalize_listing_dimensions(data)

        def populate(art):
            selected["art"] = art
            art = self._normalize_listing_dimensions(art)
            for key, widget in fields.items():
                widget.delete(0, tk.END)
                widget.insert(0, art.get(key, "") or "")
            notes_text.delete("1.0", tk.END)
            notes_text.insert(tk.END, art.get("description", "") or "")
            desc_text.delete("1.0", tk.END)
            desc_text.insert(tk.END, art.get("catalog_description", "") or "")
            is_available.set(bool(art.get("is_available", True)))
            add_image_paths.clear()
            for child in image_list.winfo_children():
                child.destroy()
            delete_image_vars.clear()
            for image in art.get("images", []) or []:
                var = tk.BooleanVar(value=False)
                delete_image_vars[str(image.get("id"))] = var
                ttk.Checkbutton(image_list, text=f"Delete image {image.get('id')}: {image.get('url', '')}", variable=var).pack(anchor="w", fill=tk.X)
            image_status.config(text="")
            status.config(text=f"Editing listing ID {art.get('id')}")

        def on_select(_event=None):
            sel = listing_tree.selection()
            if sel:
                art = next((a for a in artworks if str(a.get("id")) == sel[0]), None)
                if art:
                    populate(art)

        def add_images():
            paths = filedialog.askopenfilenames(title="Add images", filetypes=[("Image Files", "*.jpg *.jpeg *.png")], parent=win)
            add_image_paths.extend(paths)
            image_status.config(text=f"{len(add_image_paths)} new image(s) queued.")

        def generate():
            art = selected["art"]
            if not art:
                return
            try:
                data = payload()
                data["use_web"] = True
                response = requests.post(f"{BASE_URL}/artworks/{art.get('id')}/generate_description/", json=data, headers=api_headers({"Content-Type": "application/json"}), timeout=70)
                raise_for_api_error(response, "Generate description")
                desc_text.delete("1.0", tk.END)
                desc_text.insert(tk.END, response.json().get("description", ""))
                status.config(text="Draft inserted. Review/edit, then Save Changes.")
            except Exception as exc:
                messagebox.showerror("Generate Failed", str(exc), parent=win)

        def generate_notes():
            art = selected["art"]
            if not art:
                return
            notes_btn.config(state=tk.DISABLED)
            try:
                status.config(text="Generating notes...")
                win.update_idletasks()
                notes = self._generate_notes(payload(), artwork_id=art.get("id"))
                notes_text.delete("1.0", tk.END)
                notes_text.insert(tk.END, notes)
                status.config(text="Draft notes inserted. Review/edit, then Save Changes.")
            except Exception as exc:
                messagebox.showerror("Generate Notes Failed", str(exc), parent=win)
            finally:
                notes_btn.config(state=tk.NORMAL)

        def save():
            art = selected["art"]
            if not art:
                return
            data = payload()
            for image_id, var in delete_image_vars.items():
                if var.get():
                    data.setdefault("delete_image_ids", []).append(image_id)
            data_items = []
            for key, value in data.items():
                if isinstance(value, list):
                    data_items.extend((key, item) for item in value)
                else:
                    data_items.append((key, str(value)))
            files = []
            try:
                for i, path in enumerate(add_image_paths):
                    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
                    files.append((f"image_{i}", (os.path.basename(path), open(path, "rb"), mime)))
                response = requests.post(f"{BASE_URL}/artworks/{art.get('id')}/update_artwork/", data=data_items, files=files, headers=api_headers(), timeout=70)
                response.raise_for_status()
                updated = response.json().get("artwork", {})
                listing_tree.item(str(art.get("id")), values=(updated.get("artist", ""), updated.get("title", ""), updated.get("price", "")))
                populate(updated)
                status.config(text="Saved changes to website listing.")
            except Exception as exc:
                messagebox.showerror("Save Failed", str(exc), parent=win)
            finally:
                for _name, file_tuple in files:
                    try:
                        file_tuple[1].close()
                    except Exception:
                        pass

        listing_tree.bind("<<TreeviewSelect>>", on_select)
        buttons = ttk.Frame(right)
        buttons.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons, text="Generate Description", command=generate, style="Accent.TButton").pack(side=tk.LEFT)
        ttk.Button(buttons, text="Add Images", command=add_images).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Save Changes", command=save, style="Success.TButton").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side=tk.RIGHT)
        first = str(artworks[0].get("id"))
        listing_tree.selection_set(first)
        listing_tree.focus(first)
        populate(artworks[0])

    def export_to_word(self):
        text = self.text_display.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Nothing to Export", "Search or generate text first.")
            return
        file_path = filedialog.asksaveasfilename(defaultextension=".docx", filetypes=[("Word Document", "*.docx")])
        if not file_path:
            return
        doc = Document()
        for entry in text.split("\n\n"):
            doc.add_paragraph(entry)
        doc.save(file_path)
        self._set_status(f"Exported: {os.path.basename(file_path)}")

    def export_entire_database(self):
        if self.df is None:
            messagebox.showwarning("No Catalog", "Open an Excel catalog first.")
            return
        file_path = filedialog.asksaveasfilename(defaultextension=".docx", filetypes=[("Word Document", "*.docx")])
        if not file_path:
            return
        doc = Document()
        for _, row in self.df.iterrows():
            doc.add_paragraph(self.format_catalog_entry(row))
        doc.save(file_path)
        self._set_status(f"Exported: {os.path.basename(file_path)}")

    def delete_artwork(self):
        messagebox.showinfo("Moved", "Use Edit Website Listings for editing/images, or existing website deletion flow if needed.")

    def upload_artworks(self):
        if self.current_results is None or self.current_results.empty:
            messagebox.showwarning("Warning", "No artworks available. Search or display inventory first.")
            return
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Select one or more artworks first.")
            return
        for _, row in self.current_results.loc[[int(iid) for iid in selected_items]].iterrows():
            title = row.get("Title", "")
            price = simpledialog.askstring("Enter Sale Price", f"Enter sale price for '{title}':")
            if not price:
                continue
            data = self._row_to_payload(row, price=price)
            data = self._upload_dialog(data)
            if data is None:
                continue
            images = list(filedialog.askopenfilenames(title=f"Select image(s) for '{title}'", filetypes=[("Image Files", "*.jpg *.jpeg *.png")]))
            if not images:
                continue
            files = []
            try:
                for i, img in enumerate(images):
                    mime = "image/png" if img.lower().endswith(".png") else "image/jpeg"
                    files.append((f"image_{i}", (os.path.basename(img), open(img, "rb"), mime)))
                response = requests.post(f"{BASE_URL}/artworks/upload_artwork/", data=data, files=files, headers=api_headers(), timeout=70)
                if response.status_code == 201:
                    messagebox.showinfo("Success", f"'{title}' uploaded successfully!")
                else:
                    messagebox.showerror("Error", f"Upload failed: {response.text}")
            finally:
                for _name, file_tuple in files:
                    try:
                        file_tuple[1].close()
                    except Exception:
                        pass


def main():
    root = tk.Tk()
    ArtCatalogApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
