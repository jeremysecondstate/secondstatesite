"""Tkinter Artist Watchlist panel for the internal desktop catalog app."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import timezone
import json
import os
from pathlib import Path
import threading
import webbrowser

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from catalogapp.artprice_artist_links import ArtpriceMatchResult, load_artprice_artist_links
from catalogapp.bookmark_watchlist import (
    BookmarkEntry,
    artist_source_counts,
    folder_counts,
    load_bookmarks_file,
)
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_browser import (
    INVALUABLE_SIGN_IN_LOT, InvaluableBrowserFetcher, InvaluablePublicBrowserFetcher, connect_invaluable,
)
from catalogapp.watchlist_chrome import chrome_profiles, open_invaluable_in_chrome
from catalogapp.watchlist_fetch import HttpPageFetcher, WatchlistStopped
from catalogapp.watchlist_exports import render_calendar_preview, render_csv, render_ics, render_markdown
from catalogapp.watchlist_models import NormalizedLot, parse_lot_datetime
from catalogapp.watchlist_invaluable_pages import import_saved_invaluable_pages
from catalogapp.watchlist_saved_pages import import_saved_heritage_pages
from catalogapp.watchlist_sold_pages import import_saved_sold_pages
from catalogapp.watchlist_service import WatchlistResult, WatchlistService
from catalogapp.watchlist_sync import CalendarSyncResult, sync_watchlist_lots
from catalogapp.studio_theme import STUDIO_COLORS, studio_icon
from secondstate import environment


DEFAULT_BOOKMARK_PATH = Path(r"I:\Shared drives\SECONDSTATE\ARTAPP\INVALUABLE-BM.html")
PROJECT_BOOKMARK_PATH = Path(__file__).resolve().parents[1] / "docs" / "ARTIST-LINKZ.html"


def local_watchlist_directory() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".secondstate"))
    return root / "SecondState" / "ArtistWatchlist"


class ArtistWatchlistPanel(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        status_callback=None,
        service_factory=None,
        calendar_base_url: str = "",
        calendar_api_key: str = "",
        calendar_syncer=None,
    ) -> None:
        super().__init__(master, padding=(24, 24))
        self.status_callback = status_callback or (lambda _text: None)
        self.service_factory = service_factory
        self.calendar_base_url = calendar_base_url
        self.calendar_api_key = calendar_api_key
        self.calendar_syncer = calendar_syncer or sync_watchlist_lots
        self.all_entries: list[BookmarkEntry] = []
        self.active_entries: list[BookmarkEntry] = []
        self.artist_artprice_links: dict[str, str] = {}
        self.artprice_match_result = ArtpriceMatchResult({}, (), (), 0)
        self.selected_artists: set[str] = set()
        self.folder_vars: dict[str, tk.BooleanVar] = {}
        self.current_lots: list[NormalizedLot] = []
        self.fallback_lot_keys: set[str] = set()
        self.source_refresh_errors: list[str] = []
        self._sync_details_text = ""
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._lot_urls: dict[str, str] = {}
        self._settings_path = local_watchlist_directory() / "settings.json"
        self._cache_path = local_watchlist_directory() / "watchlist.sqlite3"
        self._invaluable_profile_directory = local_watchlist_directory() / "invaluable-browser"
        self._build()
        self._load_initial_bookmarks()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        self._busy = False
        self._selection_controls = []
        self._icons = {
            name: studio_icon(self, name, size=28 if name.startswith("step") else 16,
                              color={"sync": STUDIO_COLORS["on_accent"], "file": STUDIO_COLORS["accent"],
                                     "check": STUDIO_COLORS["accent"], "alert": STUDIO_COLORS["warning"]}.get(name))
            for name in ("file", "folder", "sync", "step1", "step2", "check", "alert")
        }

        ttk.Label(self, text="Artist Watchlist", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            self, text="Import your bookmarks. Sync your calendar.", style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 20))

        workflow = ttk.Frame(self, padding=(20, 18), style="Card.TFrame")
        workflow.grid(row=2, column=0, sticky="ew")
        workflow.columnconfigure(3, weight=1)
        ttk.Label(workflow, image=self._icons["step1"], style="Surface.TLabel").grid(
            row=0, column=0, rowspan=2, padx=(0, 16),
        )
        self.bookmark_path_var = tk.StringVar()
        self.bookmark_filename_var = tk.StringVar(value="Choose your bookmarks")
        ttk.Label(workflow, textvariable=self.bookmark_filename_var, image=self._icons["file"],
                  compound=tk.LEFT, padding=(0, 0, 8, 0), style="Surface.TLabel").grid(
            row=0, column=1, sticky="w",
        )
        self.import_summary_var = tk.StringVar(value="Import an HTML bookmark file to get started.")
        ttk.Label(workflow, textvariable=self.import_summary_var, style="SurfaceSubtle.TLabel").grid(
            row=1, column=1, sticky="w", pady=(4, 0),
        )
        self.import_bookmarks_button = ttk.Button(
            workflow, text="Import Bookmarks HTML", image=self._icons["folder"], compound=tk.LEFT,
            command=self.import_bookmarks, style="SurfaceSecondary.TButton",
        )
        self.import_bookmarks_button.grid(row=0, column=2, rowspan=2, padx=(16, 20))
        ttk.Separator(workflow, orient=tk.VERTICAL).grid(row=0, column=4, rowspan=2, sticky="ns", padx=(20, 20))
        ttk.Label(workflow, image=self._icons["step2"], style="Surface.TLabel").grid(
            row=0, column=5, rowspan=2, padx=(0, 12),
        )
        self.sync_to_calendar_button = ttk.Button(
            workflow, text="Sync to Calendar", image=self._icons["sync"], compound=tk.LEFT,
            command=self.sync_to_calendar, style="SurfaceAccent.TButton",
        )
        self.sync_to_calendar_button.grid(row=0, column=6, rowspan=2)
        # Existing completion handlers and integrations retain their controller names.
        self.refresh_button = self.sync_to_calendar_button
        self.calendar_sync_button = self.sync_to_calendar_button

        self.review_button = ttk.Button(
            self, text="▸  Review imported artists", command=self._toggle_review, style="Quiet.TButton",
        )
        self.review_button.grid(row=3, column=0, sticky="w", pady=(14, 12))
        self.review_frame = ttk.Frame(self, padding=16, style="Card.TFrame")
        # The review occupies the same flexible workspace as the agenda. It
        # must not push the sync status or calendar below smaller windows.
        self.review_frame.grid(row=5, column=0, sticky="nsew")
        self.review_frame.columnconfigure(1, weight=1)
        self.review_frame.rowconfigure(0, weight=1)
        folders = ttk.Frame(self.review_frame, style="Surface.TFrame")
        folders.grid(row=0, column=0, sticky="nsew", padx=(0, 22))
        ttk.Label(folders, text="Folders", style="Surface.TLabel").pack(anchor="w", pady=(0, 6))
        self.folder_controls = ttk.Frame(folders, style="Surface.TFrame")
        self.folder_controls.pack(fill=tk.BOTH, expand=True)
        artists = ttk.Frame(self.review_frame, style="Surface.TFrame")
        artists.grid(row=0, column=1, sticky="nsew")
        artists.columnconfigure(0, weight=1)
        artists.rowconfigure(1, weight=1)
        artist_search = ttk.Frame(artists, style="Surface.TFrame")
        artist_search.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(artist_search, text="Artists / sales", style="Surface.TLabel").pack(side=tk.LEFT)
        self.artist_filter_var = tk.StringVar()
        self.artist_filter_var.trace_add("write", lambda *_args: self._fill_artist_tree())
        search = ttk.Entry(artist_search, textvariable=self.artist_filter_var, width=20)
        search.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 8))
        self._selection_controls.append((search, tk.NORMAL))
        for label, callback in (("Select all", self._select_all_artists), ("Select none", self._select_no_artists)):
            button = ttk.Button(artist_search, text=label, command=callback, style="SurfaceSecondary.TButton")
            button.pack(side=tk.LEFT, padx=(4, 0))
            self._selection_controls.append((button, tk.NORMAL))
        artist_table = ttk.Frame(artists, style="Surface.TFrame")
        artist_table.grid(row=1, column=0, sticky="nsew")
        artist_table.columnconfigure(0, weight=1)
        artist_table.rowconfigure(0, weight=1)
        self.artist_tree = ttk.Treeview(
            artist_table, columns=("watch", "artist", "sources", "urls"), show="headings",
            height=5, selectmode="browse", style="Watchlist.Catalog.Treeview",
        )
        for key, title, width in (
            ("watch", "Watch", 60), ("artist", "Artist / sale", 230),
            ("sources", "Sources", 180), ("urls", "URLs", 55),
        ):
            self.artist_tree.heading(key, text=title)
            self.artist_tree.column(key, width=width, stretch=key in {"artist", "sources"})
        self.artist_tree.grid(row=0, column=0, sticky="nsew")
        artist_scroll_y = ttk.Scrollbar(artist_table, orient=tk.VERTICAL, command=self.artist_tree.yview)
        artist_scroll_y.grid(row=0, column=1, sticky="ns")
        self.artist_tree.configure(yscrollcommand=artist_scroll_y.set)
        self.artist_tree.bind("<Double-1>", self._toggle_artist)
        ttk.Label(
            artists, text="Double-click an artist to include or exclude them.", style="SurfaceSubtle.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))
        options = ttk.Frame(self.review_frame, style="Surface.TFrame")
        options.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Label(options, text="Look ahead", style="Surface.TLabel").pack(side=tk.LEFT)
        self.horizon_var = tk.IntVar(value=30)
        horizon = ttk.Combobox(options, textvariable=self.horizon_var, values=(3, 7, 14, 30), width=4, state="readonly")
        horizon.pack(side=tk.LEFT, padx=(8, 6))
        self._selection_controls.append((horizon, "readonly"))
        ttk.Label(options, text="days", style="SurfaceSubtle.TLabel").pack(side=tk.LEFT)
        ttk.Label(
            options, text="Bookmark files stay on this computer. No AI processing.", style="SurfaceSubtle.TLabel",
        ).pack(side=tk.RIGHT)
        self.review_frame.grid_remove()
        self.new_changed_var = tk.BooleanVar(value=False)
        self.zero_ai_var = tk.BooleanVar(value=True)
        # Retained for the dormant legacy browser integration; the Studio sync
        # never reads these preferences or launches that integration.
        saved = self._read_settings()
        self.invaluable_session_var = tk.BooleanVar(value=saved.get("invaluable_session_enabled") is True)
        profile = saved.get("invaluable_chrome_profile")
        self.chrome_profile_choices = {"Saved profile": profile}
        self.chrome_profile_var = tk.StringVar(value="Saved profile")
        self.chrome_open_status_var = tk.StringVar()
        self.invaluable_connection_status_var = tk.StringVar()

        results = ttk.Frame(self, padding=(16, 16), style="Card.TFrame")
        self.results_frame = results
        results.grid(row=5, column=0, sticky="nsew")
        results.columnconfigure(0, weight=1)
        results.rowconfigure(1, weight=1)
        table_header = ttk.Frame(results, style="Surface.TFrame")
        table_header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.results_title_var = tk.StringVar(value="Upcoming lots")
        ttk.Label(table_header, textvariable=self.results_title_var, style="Surface.TLabel", font=("Segoe UI Semibold", 12)).pack(side=tk.LEFT)
        self.lot_summary_var = tk.StringVar(value="Next 30 days")
        self.more_button = ttk.Menubutton(table_header, text="More", style="Secondary.TMenubutton")
        self.more_menu = tk.Menu(self.more_button, tearoff=False)
        self.more_button.configure(menu=self.more_menu)
        self.more_menu.add_command(label="Upcoming lots", command=lambda: self._show_lot_view("upcoming"))
        self.more_menu.add_command(label="Detailed agenda", command=lambda: self._show_lot_view("agenda"))
        self.more_menu.add_command(label="Calendar preview", command=lambda: self._show_lot_view("calendar"))
        self.more_menu.add_separator()
        self.more_menu.add_command(label="Import saved Invaluable pages…", command=self.import_saved_invaluable_pages)
        self.more_menu.add_command(label="Import saved Heritage pages…", command=self.import_saved_heritage_pages)
        self.more_menu.add_command(label="Import saved sold results…", command=self.import_saved_sold_results)
        self.more_menu.add_separator()
        for label, kind in (("Export Markdown…", "md"), ("Export CSV…", "csv"), ("Export calendar file…", "ics")):
            self.more_menu.add_command(label=label, command=lambda kind=kind: self._export(kind))
        self.more_button.pack(side=tk.RIGHT)
        ttk.Label(table_header, textvariable=self.lot_summary_var, style="SurfaceSubtle.TLabel").pack(
            side=tk.RIGHT, padx=(14, 18),
        )

        views = ttk.Frame(results, style="Surface.TFrame")
        views.grid(row=1, column=0, sticky="nsew")
        views.columnconfigure(0, weight=1)
        views.rowconfigure(0, weight=1)
        upcoming_tab = ttk.Frame(views, style="Surface.TFrame")
        agenda_tab = ttk.Frame(views, style="Surface.TFrame")
        calendar_tab = ttk.Frame(views, style="Surface.TFrame")
        self._lot_views = {"upcoming": upcoming_tab, "agenda": agenda_tab, "calendar": calendar_tab}
        self._active_lot_view = "upcoming"
        for view in self._lot_views.values():
            view.grid(row=0, column=0, sticky="nsew")
            view.grid_remove()
        upcoming_tab.grid()
        upcoming_tab.columnconfigure(0, weight=1)
        upcoming_tab.rowconfigure(0, weight=1)
        self.upcoming_tree = ttk.Treeview(
            upcoming_tab, columns=("date", "artist", "title", "lot", "estimate"), show="headings",
            height=5, selectmode="browse", style="Studio.Agenda.Treeview",
        )
        for key, title, width, minimum in (
            ("date", "Date", 100, 90), ("artist", "Artist", 190, 130),
            ("title", "Artwork", 280, 140), ("lot", "Lot", 70, 50), ("estimate", "Estimate", 140, 110),
        ):
            self.upcoming_tree.heading(key, text=title, anchor=tk.W)
            self.upcoming_tree.column(key, width=width, minwidth=minimum, stretch=key in {"artist", "title"}, anchor=tk.W)
        self.upcoming_tree.grid(row=0, column=0, sticky="nsew")
        upcoming_scroll = ttk.Scrollbar(upcoming_tab, orient=tk.VERTICAL, command=self.upcoming_tree.yview)
        upcoming_scroll.grid(row=0, column=1, sticky="ns")

        def scroll_upcoming(first, last):
            upcoming_scroll.set(first, last)
            if float(first) <= 0.0 and float(last) >= 1.0:
                upcoming_scroll.grid_remove()
            else:
                upcoming_scroll.grid()

        self.upcoming_tree.configure(yscrollcommand=scroll_upcoming)
        self.upcoming_tree.tag_configure("cached", foreground=STUDIO_COLORS["muted"])
        self.upcoming_tree.tag_configure("ended", foreground=STUDIO_COLORS["muted"])
        self.upcoming_tree.bind("<<TreeviewSelect>>", self._show_selected_lot_details)
        self.upcoming_tree.bind("<Double-1>", self._open_selected_lot)
        self.lot_detail_var = tk.StringVar(value="Select a lot for sale details. Double-click to open it.")
        detail = ttk.Label(
            upcoming_tab, textvariable=self.lot_detail_var, style="SurfaceSubtle.TLabel", padding=(4, 8, 4, 0),
            wraplength=900,
        )
        detail.grid(row=1, column=0, sticky="ew")
        detail.bind("<Configure>", lambda event: detail.configure(wraplength=max(200, event.width - 8)))
        agenda_tab.columnconfigure(0, weight=1)
        agenda_tab.rowconfigure(0, weight=1)
        columns = ("time", "sale", "lot", "title", "estimate", "bid", "status")
        self.agenda_tree = ttk.Treeview(
            agenda_tab, columns=columns, show="tree headings", height=8, style="Watchlist.Catalog.Treeview",
        )
        self.agenda_tree.heading("#0", text="Date / Artist")
        self.agenda_tree.column("#0", width=200, stretch=True)
        widths = {"time": 65, "sale": 200, "lot": 65, "title": 250, "estimate": 130, "bid": 170, "status": 95}
        for column in columns:
            heading = "Current bid / sold" if column == "bid" else column.replace("_", " ").title()
            self.agenda_tree.heading(column, text=heading)
            self.agenda_tree.column(column, width=widths[column], stretch=column in {"sale", "title"})
        self.agenda_tree.grid(row=0, column=0, sticky="nsew")
        agenda_scroll = ttk.Scrollbar(agenda_tab, orient=tk.VERTICAL, command=self.agenda_tree.yview)
        agenda_scroll.grid(row=0, column=1, sticky="ns")
        agenda_scroll_x = ttk.Scrollbar(agenda_tab, orient=tk.HORIZONTAL, command=self.agenda_tree.xview)
        agenda_scroll_x.grid(row=1, column=0, sticky="ew")
        self.agenda_tree.configure(yscrollcommand=agenda_scroll.set, xscrollcommand=agenda_scroll_x.set)
        self.agenda_tree.tag_configure("date_group", font=("Segoe UI Semibold", 10))
        self.agenda_tree.tag_configure("artist_group", font=("Segoe UI Semibold", 10))
        self.agenda_tree.tag_configure("new", foreground=STUDIO_COLORS["success"])
        self.agenda_tree.tag_configure("changed", foreground=STUDIO_COLORS["warning"])
        self.agenda_tree.tag_configure("ended", foreground=STUDIO_COLORS["muted"])
        self.agenda_tree.tag_configure("cached", foreground=STUDIO_COLORS["muted"])
        self.agenda_tree.bind("<Double-1>", self._open_selected_lot)
        self.calendar_text = scrolledtext.ScrolledText(
            calendar_tab, wrap=tk.WORD, font=("Segoe UI", 10), height=10,
            background=STUDIO_COLORS["surface"], foreground=STUDIO_COLORS["ink"], relief=tk.FLAT, borderwidth=0,
        )
        # ScrolledText creates a classic Windows scrollbar; replace it with
        # the themed scrollbar so the secondary calendar stays dark as well.
        self.calendar_text.frame.configure(background=STUDIO_COLORS["surface"])
        self.calendar_text.vbar.destroy()
        self.calendar_text.vbar = ttk.Scrollbar(
            self.calendar_text.frame, orient=tk.VERTICAL, command=self.calendar_text.yview,
        )
        self.calendar_text.vbar.pack(side=tk.RIGHT, fill=tk.Y, before=self.calendar_text._w)
        self.calendar_text.configure(yscrollcommand=self.calendar_text.vbar.set)
        self.calendar_text.pack(fill=tk.BOTH, expand=True)
        self.calendar_text.configure(state=tk.DISABLED)
        self.empty_state = ttk.Label(
            upcoming_tab, text="Your upcoming lots will appear here.\nImport your bookmarks, then sync to Calendar.",
            style="SurfaceSubtle.TLabel", justify=tk.CENTER, padding=24,
        )
        self.empty_state.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        footer = ttk.Frame(self, padding=(16, 12), style="Status.TFrame")
        self.status_banner = footer
        footer.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(1, weight=1)
        self.status_icon = ttk.Label(footer, image=self._icons["check"], style="Status.TLabel")
        self.status_icon.grid(row=0, column=0, sticky="nw", padx=(0, 10), pady=1)
        self.status_title_var = tk.StringVar(value="Ready to sync")
        self.status_title_label = ttk.Label(footer, textvariable=self.status_title_var, style="Status.TLabel")
        self.status_title_label.grid(row=0, column=1, sticky="w")
        self.sync_status_var = tk.StringVar(value="Import your bookmarks to get started. Upcoming lots will be checked when you sync.")
        status = ttk.Label(footer, textvariable=self.sync_status_var, style="Status.TLabel", wraplength=900)
        self.status_message_label = status
        status.grid(row=1, column=1, sticky="ew", pady=(3, 0))
        status.bind("<Configure>", lambda event: status.configure(wraplength=max(200, event.width)))
        footer_actions = ttk.Frame(footer, style="Status.TFrame")
        self.status_actions = footer_actions
        footer_actions.grid(row=2, column=1, sticky="e", pady=(8, 0))
        self.stop_button = ttk.Button(footer_actions, text="Stop", command=self.stop_refresh, style="Secondary.TButton")
        self.stop_button.grid(row=0, column=0, padx=(12, 0))
        self.stop_button.grid_remove()
        self.sync_details_button = ttk.Button(
            footer_actions, text="Sync details", command=self.show_sync_details, style="Secondary.TButton",
        )
        self.sync_details_button.grid(row=0, column=1, padx=(12, 0))
        self.sync_details_button.grid_remove()
        self.retry_browser_button = ttk.Button(
            footer_actions, text="Retry with browser", command=self.retry_with_browser, style="Secondary.TButton",
        )
        self.retry_browser_button.grid(row=0, column=2, padx=(12, 0))
        self.retry_browser_button.grid_remove()
        self.import_invaluable_button = ttk.Button(
            footer_actions, text="Import saved Invaluable pages…", command=self.import_saved_invaluable_pages,
            style="Secondary.TButton",
        )
        self.import_invaluable_button.grid(row=0, column=3, padx=(12, 0))
        self.import_invaluable_button.grid_remove()
        # Metrics remain available to the controller and exports without making
        # implementation counters part of the everyday workflow.
        self.metrics_var = tk.StringVar()

    def _toggle_review(self) -> None:
        if self.review_frame.winfo_manager():
            self.review_frame.grid_remove()
            self.results_frame.grid()
            self._update_review_label()
        else:
            self.results_frame.grid_remove()
            self.review_frame.grid()
            self.review_button.configure(text="Done reviewing artists")

    def _update_review_label(self) -> None:
        button = self.__dict__.get("review_button")
        review = self.__dict__.get("review_frame")
        if button is not None and (review is None or not review.winfo_manager()):
            count = len(artist_source_counts(self.active_entries))
            button.configure(text=f"▸  Review {count} imported artists" if count else "▸  Review imported artists")

    def _show_lot_view(self, name: str) -> None:
        """Keep the routine table simple while retaining the full agenda and calendar."""
        for view in self._lot_views.values():
            view.grid_remove()
        self._lot_views[name].grid()
        self._active_lot_view = name
        self.results_title_var.set({
            "upcoming": "Upcoming lots", "agenda": "Detailed agenda", "calendar": "Calendar preview",
        }[name])

    def _is_busy(self) -> bool:
        return bool(self.__dict__.get("_busy") or (self.worker and self.worker.is_alive()))

    def _set_stop_available(self, available: bool) -> None:
        self.stop_button.configure(state=tk.NORMAL if available else tk.DISABLED)
        if self.__dict__.get("sync_to_calendar_button") is not None:
            if available:
                self.stop_button.grid()
            else:
                self.stop_button.grid_remove()

    def import_bookmarks(self) -> None:
        if self._is_busy():
            return
        initial = Path(self.bookmark_path_var.get()) if self.bookmark_path_var.get() else None
        path = filedialog.askopenfilename(
            title="Import exported browser bookmarks",
            initialdir=str(initial.parent) if initial and initial.parent.exists() else None,
            initialfile=initial.name if initial else None,
            filetypes=[("Bookmark HTML", "*.html *.htm"), ("All Files", "*.*")],
        )
        if path:
            if self.load_bookmarks(path):
                self._set_status("Bookmarks imported. Click Sync to Calendar when you’re ready.")

    def load_bookmarks(self, path: str | Path, *, preserve_selection: bool = False) -> bool:
        selected_folders = (
            {name.casefold() for name, var in self.folder_vars.items() if var.get()}
            if preserve_selection else None
        )
        try:
            entries = load_bookmarks_file(path)
            artprice_matches = load_artprice_artist_links(
                path,
                {entry.artist for entry in entries if entry.artist},
            )
        except Exception as exc:
            messagebox.showerror("Bookmark Import Failed", str(exc), parent=self)
            return False
        self.all_entries = entries
        self.artist_artprice_links = dict(artprice_matches.links_by_artist)
        self.artprice_match_result = artprice_matches
        self.bookmark_path_var.set(str(Path(path).resolve()))
        filename = self.__dict__.get("bookmark_filename_var")
        if filename is not None:
            filename.set(Path(path).name)
        self._save_settings_hint()
        self._build_folder_controls(selected_folders=selected_folders)
        self._update_active_entries(select_all=not preserve_selection)
        return True

    def _build_folder_controls(self, *, selected_folders: set[str] | None = None) -> None:
        for child in self.folder_controls.winfo_children():
            child.destroy()
        self.folder_vars.clear()
        counts = folder_counts(self.all_entries)
        has_invaluable_folder = any(folder.casefold() == "artists invaluable" for folder in counts)
        for row, (folder, count) in enumerate(counts.items()):
            selected = (
                folder.casefold() in selected_folders if selected_folders is not None
                else folder.casefold() == "artists invaluable" or not has_invaluable_folder
            )
            var = tk.BooleanVar(value=selected)
            self.folder_vars[folder] = var
            ttk.Checkbutton(
                self.folder_controls,
                text=f"{folder} ({count})",
                variable=var,
                style="Surface.TCheckbutton",
                command=self._update_active_entries,
            ).grid(row=row, column=0, sticky="w")
        if not counts:
            ttk.Label(self.folder_controls, text="No allowed auction folders detected.", style="SurfaceSubtle.TLabel").pack(anchor="w")

    def _update_active_entries(self, select_all: bool = False) -> None:
        previous_artists = set(artist_source_counts(self.active_entries))
        selected_folders = {name.casefold() for name, var in self.folder_vars.items() if var.get()}
        self.active_entries = [
            entry for entry in self.all_entries
            if any(part.casefold() in selected_folders for part in (entry.folder_path or ("Unfiled",)))
        ]
        artists = set(artist_source_counts(self.active_entries))
        if select_all:
            self.selected_artists = set(artists)
        else:
            self.selected_artists = (self.selected_artists & artists) | (artists - previous_artists)
        self._fill_artist_tree()
        source_counts: dict[str, int] = {}
        for entry in self.active_entries:
            source_counts[entry.source] = source_counts.get(entry.source, 0) + 1
        sources = ", ".join(sorted(source_counts)) or "No auction sources"
        self.import_summary_var.set(f"{len(artists)} artists · {sources}")
        self._update_review_label()

    def _fill_artist_tree(self) -> None:
        for item in self.artist_tree.get_children(""):
            self.artist_tree.delete(item)
        query = self.artist_filter_var.get().strip().casefold()
        for artist, sources in artist_source_counts(self.active_entries).items():
            if query and query not in artist.casefold():
                continue
            source_label = ", ".join(f"{source} ({count})" for source, count in sorted(sources.items()))
            self.artist_tree.insert(
                "",
                tk.END,
                iid=artist,
                values=("Yes" if artist in self.selected_artists else "", artist, source_label, sum(sources.values())),
            )

    def _toggle_artist(self, event=None) -> None:
        if self._is_busy():
            return
        item = self.artist_tree.identify_row(event.y) if event else self.artist_tree.focus()
        if not item:
            return
        if item in self.selected_artists:
            self.selected_artists.remove(item)
        else:
            self.selected_artists.add(item)
        self._refresh_artist_watch_marks()
        self.artist_tree.selection_set(item)
        self.artist_tree.focus(item)

    def _select_all_artists(self) -> None:
        if self._is_busy():
            return
        self.selected_artists = set(artist_source_counts(self.active_entries))
        self._refresh_artist_watch_marks()

    def _select_no_artists(self) -> None:
        if self._is_busy():
            return
        self.selected_artists.clear()
        self._refresh_artist_watch_marks()

    def _refresh_artist_watch_marks(self) -> None:
        """Update watch marks without rebuilding the tree or losing its scroll position."""
        for item in self.artist_tree.get_children(""):
            values = list(self.artist_tree.item(item, "values"))
            if values:
                values[0] = "Yes" if item in self.selected_artists else ""
                self.artist_tree.item(item, values=values)

    def _set_invaluable_connection_status(self, text: str) -> None:
        label = self.__dict__.get("invaluable_connection_status_var")
        if label is not None:
            label.set(text)
        self._set_status(text)

    def open_regular_chrome(self) -> None:
        selected = self.agenda_tree.selection()
        url = self._lot_urls.get(selected[0], INVALUABLE_SIGN_IN_LOT) if selected else INVALUABLE_SIGN_IN_LOT
        profile = self.chrome_profile_choices.get(self.chrome_profile_var.get())
        try:
            open_invaluable_in_chrome(url, profile_directory=profile)
        except (ValueError, RuntimeError) as exc:
            message = str(exc)
            self.chrome_open_status_var.set(message)
            self._set_status(message)
            messagebox.showwarning("Open Invaluable in Chrome", message, parent=self)
            return
        self._save_settings_hint()
        message = "Opened in your chosen Chrome profile. This does not connect automatic price refreshes."
        self.chrome_open_status_var.set(message)
        self._set_status(message)

    def connect_invaluable(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.stop_event = threading.Event()
        self.refresh_button.configure(state=tk.DISABLED)
        self._set_import_buttons_state(tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self._set_invaluable_connection_status("Opening Chrome for Invaluable sign-in…")

        def run() -> None:
            try:
                connected = connect_invaluable(
                    self._invaluable_profile_directory,
                    stop_event=self.stop_event,
                    progress=lambda text: self.after(0, lambda value=text: self._set_invaluable_connection_status(value)),
                )
                self.after(0, lambda: self._finish_invaluable_connection(connected))
            except WatchlistStopped:
                self.after(0, lambda: self._finish_invaluable_connection(False))
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                self.after(0, lambda message=message: self._finish_invaluable_connection(False, message))

        self.worker = threading.Thread(target=run, name="invaluable-sign-in", daemon=True)
        self.worker.start()

    def _finish_invaluable_connection(self, connected: bool, error: str = "") -> None:
        self.refresh_button.configure(state=tk.NORMAL)
        self._set_import_buttons_state(tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.worker = None
        if connected:
            self.invaluable_session_var.set(True)
            self._save_settings_hint()
            self._set_invaluable_connection_status("Invaluable connected. Your saved login is ready for refreshes.")
            if self.active_entries and self.selected_artists:
                self.refresh_watchlist()
            else:
                self._set_invaluable_connection_status("Invaluable connected. Select artists, then click Refresh Watchlist.")
        else:
            self._set_invaluable_connection_status(
                "Invaluable connection not completed. " + (error or "Sign-in was cancelled or timed out; click Connect Invaluable to try again.")
            )
            if error:
                messagebox.showwarning("Invaluable Connection", error, parent=self)

    def refresh_watchlist(self) -> None:
        """Legacy refresh entry point retained for the dormant browser integration."""
        self._start_refresh(use_saved_login=True)

    def sync_to_calendar(self) -> None:
        """Re-read bookmarks, fetch selected watches, then sync the resulting lots."""
        self._sync_from_bookmarks(use_browser=False)

    def retry_with_browser(self) -> None:
        """Explicitly retry Invaluable in a separate, visible browser session."""
        self._sync_from_bookmarks(use_browser=True)

    def _sync_from_bookmarks(self, *, use_browser: bool) -> None:
        if self._is_busy():
            return
        path = self.bookmark_path_var.get().strip()
        if not path:
            messagebox.showwarning("No Bookmarks", "Import a bookmark HTML file first.", parent=self)
            return
        # Reading again is essential: the HTML may have changed since import.
        # Existing exclusions survive; new artists in selected folders are added.
        if not self.load_bookmarks(path, preserve_selection=True):
            self._set_status("Bookmarks could not be read. Choose the file again with Import Bookmarks HTML.")
            return
        review_frame = self.__dict__.get("review_frame")
        if review_frame is not None and review_frame.winfo_manager():
            self._toggle_review()
        self._start_refresh(use_saved_login=False, use_browser=use_browser)

    def _start_refresh(self, *, use_saved_login: bool, use_browser: bool = False) -> None:
        if self._is_busy():
            return
        if not self.active_entries:
            messagebox.showwarning("No Bookmarks", "Import a bookmark file and select at least one allowed folder.", parent=self)
            return
        if not self.selected_artists:
            messagebox.showwarning("No Selection", "Open Review imported artists and select at least one artist or sale.", parent=self)
            return
        self.stop_event = threading.Event()
        self.refresh_button.configure(state=tk.DISABLED)
        self._set_import_buttons_state(tk.DISABLED)
        self._set_stop_available(True)
        self._set_status(
            "Opening browser to retrieve Invaluable lots…" if use_browser
            else "Checking your bookmarked artists for upcoming lots…"
        )
        entries = list(self.active_entries)
        selected_artists = set(self.selected_artists)
        horizon_days = int(self.horizon_var.get())
        use_legacy_options = use_saved_login and not use_browser
        zero_ai = bool(self.zero_ai_var.get()) if use_legacy_options else True
        new_changed_only = bool(self.new_changed_var.get()) if use_legacy_options else False
        selected_invaluable = any(
            entry.source == "Invaluable" and entry.watch_label in selected_artists for entry in entries
        )
        use_invaluable_session = use_legacy_options and bool(self.invaluable_session_var.get()) and selected_invaluable

        def run() -> None:
            try:
                local_watchlist_directory().mkdir(parents=True, exist_ok=True)
                with ExitStack() as resources:
                    cache = resources.enter_context(WatchlistCache(self._cache_path))
                    if self.service_factory:
                        service = self.service_factory(cache)
                    else:
                        browser = None
                        if use_browser and selected_invaluable:
                            browser = InvaluablePublicBrowserFetcher(
                                local_watchlist_directory() / "invaluable-public-browser",
                                stop_event=self.stop_event, headless=False,
                                progress=lambda text: self.after(0, lambda value=text: self._set_status(value)),
                            )
                            resources.callback(browser.close)
                        elif use_invaluable_session:
                            browser = InvaluableBrowserFetcher(
                                self._invaluable_profile_directory, stop_event=self.stop_event,
                            )
                            resources.callback(browser.close)
                        if use_legacy_options:
                            service = WatchlistService(cache, invaluable_fetcher=browser)
                        else:
                            # Only the explicit retry uses a browser; saved login
                            # and legacy Playwright settings remain dormant.
                            fetcher = HttpPageFetcher(stop_event=self.stop_event)
                            resources.callback(fetcher.session.close)
                            service = WatchlistService(cache, fetcher=fetcher, invaluable_fetcher=browser)
                    result = service.refresh(
                        entries,
                        selected_artists=selected_artists,
                        horizon_days=horizon_days,
                        zero_ai=zero_ai,
                        new_changed_only=new_changed_only,
                        stop_event=self.stop_event,
                        progress=lambda text: self.after(0, lambda value=text: self._set_status(value)),
                    )
                self._sync_and_finish_result(result)
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                self.after(0, lambda message=message: self._finish_refresh_error(message))

        self.worker = threading.Thread(target=run, name="artist-watchlist-refresh", daemon=True)
        self.worker.start()

    def import_saved_heritage_pages(self) -> None:
        if self._is_busy():
            return
        chosen = [
            entry for entry in self.active_entries
            if entry.source == "Heritage" and entry.is_sale and entry.watch_label in self.selected_artists
        ]
        if len(chosen) != 1:
            messagebox.showwarning(
                "Select One Heritage Sale",
                "Enable the Heritage folder and select exactly one Heritage sale to import. "
                "Other sources can remain selected.",
                parent=self,
            )
            return
        paths = filedialog.askopenfilenames(
            title=f"Import saved results for {chosen[0].watch_label}",
            filetypes=[("Saved HTML pages", "*.html *.htm"), ("All Files", "*.*")],
            parent=self,
        )
        if not paths:
            return
        entry = chosen[0]
        previous_lots = list(self.current_lots)
        previous_fallback_keys = set(self.fallback_lot_keys)
        horizon_days = int(self.horizon_var.get())
        new_changed_only = bool(self.new_changed_var.get())
        self.stop_event = threading.Event()
        self.refresh_button.configure(state=tk.DISABLED)
        self._set_import_buttons_state(tk.DISABLED)
        self._set_status(f"Importing saved Heritage results for {entry.watch_label}…")

        def run() -> None:
            try:
                local_watchlist_directory().mkdir(parents=True, exist_ok=True)
                with WatchlistCache(self._cache_path) as cache:
                    result = import_saved_heritage_pages(
                        paths,
                        entry,
                        cache,
                        horizon_days=horizon_days,
                        new_changed_only=new_changed_only,
                    )
                merged = {lot.cache_key: lot for lot in previous_lots}
                result.fallback_lot_keys.update(
                    previous_fallback_keys.difference(lot.cache_key for lot in result.lots)
                )
                merged.update({lot.cache_key: lot for lot in result.lots})
                result.lots = sorted(
                    merged.values(),
                    key=lambda lot: (lot.relevant_at or "9999", lot.artist_watchlist_name.casefold(), lot.lot_number),
                )
                self._sync_and_finish_result(result, preserve_source_errors=True)
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                self.after(0, lambda message=message: self._finish_refresh_error(message))

        self.worker = threading.Thread(target=run, name="heritage-saved-page-import", daemon=True)
        self.worker.start()

    def import_saved_invaluable_pages(self) -> None:
        """Import readable search snapshots and upload their normalized lots."""
        if self._is_busy():
            return
        path = self.bookmark_path_var.get().strip()
        if not path:
            messagebox.showwarning("No Bookmarks", "Import a bookmark HTML file first.", parent=self)
            return
        if not self.load_bookmarks(path, preserve_selection=True):
            self._set_status("Bookmarks could not be read. Choose the file again with Import Bookmarks HTML.")
            return
        chosen = [
            entry for entry in self.active_entries
            if entry.source == "Invaluable" and entry.watch_label in self.selected_artists
        ]
        if not chosen:
            messagebox.showwarning(
                "Select Invaluable Artists",
                "Open Review imported artists and select the Invaluable artists whose upcoming pages you saved.",
                parent=self,
            )
            return
        paths = filedialog.askopenfilenames(
            title="Import saved Invaluable upcoming search pages",
            filetypes=[("Saved Invaluable pages", "*.html *.htm *.json"), ("All Files", "*.*")],
            parent=self,
        )
        if not paths:
            return
        previous_lots = list(self.current_lots)
        previous_fallback_keys = set(self.fallback_lot_keys)
        horizon_days = int(self.horizon_var.get())
        self.stop_event = threading.Event()
        self.refresh_button.configure(state=tk.DISABLED)
        self._set_import_buttons_state(tk.DISABLED)
        self._set_status("Importing saved Invaluable upcoming lots…")

        def run() -> None:
            try:
                local_watchlist_directory().mkdir(parents=True, exist_ok=True)
                with WatchlistCache(self._cache_path) as cache:
                    result = import_saved_invaluable_pages(
                        paths, entries=chosen, cache=cache, horizon_days=horizon_days,
                        new_changed_only=False,
                    )
                merged = {lot.cache_key: lot for lot in previous_lots}
                # The importer returns cached lots too. Only lots observed in
                # the imported snapshot lose their previous fallback label.
                observed_keys = {lot.cache_key for lot in result.lots} - result.fallback_lot_keys
                result.fallback_lot_keys.update(previous_fallback_keys - observed_keys)
                merged.update({lot.cache_key: lot for lot in result.lots})
                result.lots = sorted(
                    merged.values(),
                    key=lambda lot: (lot.relevant_at or "9999", lot.artist_watchlist_name.casefold(), lot.lot_number),
                )
                self._sync_and_finish_result(result, preserve_source_errors=True)
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                self.after(0, lambda message=message: self._finish_refresh_error(message))

        self.worker = threading.Thread(target=run, name="invaluable-saved-page-import", daemon=True)
        self.worker.start()

    def _set_import_buttons_state(self, state) -> None:
        self._busy = state == tk.DISABLED
        for name in (
            "import_saved_button", "import_sold_button", "connect_invaluable_button", "invaluable_session_check",
            "import_bookmarks_button", "review_button", "more_button",
        ):
            button = self.__dict__.get(name)
            if button is not None:
                button.configure(state=state)
        for control, normal_state in self.__dict__.get("_selection_controls", []):
            control.configure(state=tk.DISABLED if self._busy else normal_state)
        folders = self.__dict__.get("folder_controls")
        if folders is not None:
            for control in folders.winfo_children():
                if isinstance(control, ttk.Checkbutton):
                    control.configure(state=state)
        self._update_browser_retry_button()

    def _has_invaluable_source_issue(self) -> bool:
        return any("invaluable" in error.casefold() for error in self.source_refresh_errors)

    def _update_browser_retry_button(self) -> None:
        for name in ("retry_browser_button", "import_invaluable_button"):
            button = self.__dict__.get(name)
            if button is None:
                continue
            if self._has_invaluable_source_issue():
                button.grid()
                button.configure(state=tk.DISABLED if self.__dict__.get("_busy") else tk.NORMAL)
            else:
                button.grid_remove()

    def import_saved_sold_results(self) -> None:
        if self._is_busy():
            return
        chosen = [entry for entry in self.active_entries
                  if entry.source == "Invaluable" and entry.watch_label in self.selected_artists]
        if not chosen:
            messagebox.showwarning(
                "Select Invaluable Artists",
                "Select the Invaluable artists whose watched lots you want to update. "
                "Save each sold lot page as HTML from your signed-in browser, then import it here.",
                parent=self,
            )
            return
        paths = filedialog.askopenfilenames(
            title="Import saved Invaluable sold lot pages",
            filetypes=[("Saved HTML pages", "*.html *.htm"), ("All Files", "*.*")], parent=self,
        )
        if not paths:
            return
        previous_lots = list(self.current_lots)
        previous_fallback_keys = set(self.fallback_lot_keys)
        self.stop_event = threading.Event()
        self.refresh_button.configure(state=tk.DISABLED)
        self._set_import_buttons_state(tk.DISABLED)
        self._set_status("Importing posted Invaluable sold results…")

        def run() -> None:
            try:
                local_watchlist_directory().mkdir(parents=True, exist_ok=True)
                with WatchlistCache(self._cache_path) as cache:
                    result = import_saved_sold_pages(paths, entries=chosen, cache=cache)
                merged = {lot.cache_key: lot for lot in previous_lots}
                result.fallback_lot_keys.update(
                    previous_fallback_keys.difference(lot.cache_key for lot in result.lots)
                )
                merged.update({lot.cache_key: lot for lot in result.lots})
                result.lots = sorted(
                    merged.values(),
                    key=lambda lot: (lot.relevant_at or "9999", lot.artist_watchlist_name.casefold(), lot.lot_number),
                )
                self._sync_and_finish_result(result, preserve_source_errors=True)
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                self.after(0, lambda message=message: self._finish_refresh_error(message))

        self.worker = threading.Thread(target=run, name="invaluable-sold-page-import", daemon=True)
        self.worker.start()

    def _sync_and_finish_result(self, result: WatchlistResult, *, preserve_source_errors: bool = False) -> None:
        """Run calendar sync on the worker for either a refresh or a saved import."""

        if preserve_source_errors:
            # Importing a snapshot does not verify live access for other watches.
            result.errors = list(dict.fromkeys([*self.source_refresh_errors, *result.errors]))
        stop_event = self.__dict__.get("stop_event")
        if stop_event is not None and stop_event.is_set():
            result.stopped = True
        sync_result = None
        sync_error = ""
        sync_setup_message = ""
        if not result.stopped and result.lots:
            if self._calendar_sync_configured():
                self.after(0, lambda: self._set_status("Watchlist updated. Syncing the website calendar..."))
                self.after(0, lambda: self._set_stop_available(False))
                try:
                    sync_result = self.calendar_syncer(
                        result.lots,
                        base_url=self.calendar_base_url,
                        api_key=self.calendar_api_key,
                        artist_artprice_links=self.artist_artprice_links,
                    )
                except Exception as exc:
                    sync_error = " ".join(str(exc).split())[:500]
            else:
                sync_setup_message = self._calendar_sync_setup_message()
        self.after(
            0,
            lambda result=result, sync_result=sync_result, sync_error=sync_error,
            sync_setup_message=sync_setup_message: self._finish_refresh(
                result,
                sync_result=sync_result,
                sync_error=sync_error,
                sync_setup_message=sync_setup_message,
            ),
        )

    def stop_refresh(self) -> None:
        self.stop_event.set()
        self._set_status("Stopping after the current safe fetch…")

    def _calendar_sync_configured(self) -> bool:
        # A user can add missing credentials to .env and retry without restarting.
        # Explicitly supplied settings and existing environment values still win.
        environment.load_project_environment()
        self.calendar_base_url = (
            self.calendar_base_url or os.environ.get("SECONDSTATE_BASE_URL", "")
        ).strip().rstrip("/")
        self.calendar_api_key = (
            self.calendar_api_key or os.environ.get("CATALOG_API_KEY", "")
        ).strip()
        return bool(self.calendar_base_url and self.calendar_api_key)

    def _calendar_sync_setup_message(self) -> str:
        missing = []
        if not self.calendar_base_url:
            missing.append("SECONDSTATE_BASE_URL")
        if not self.calendar_api_key:
            missing.append("CATALOG_API_KEY")
        return (
            f"The local lots are ready, but website calendar sync needs {' and '.join(missing)}.\n\n"
            f"Add the missing setting(s) to:\n{environment.PROJECT_ROOT / '.env'}\n\n"
            "Use SECONDSTATE_BASE_URL=https://secondstate.art and the same CATALOG_API_KEY "
            "configured on the website. Then click Sync to Calendar again; "
            "the app reloads this file automatically."
        )

    def _set_calendar_sync_button_state(self) -> None:
        # Keep setup instructions reachable even when credentials are missing.
        # The Studio button starts from bookmarks, even if no lots exist yet.
        enabled = self.__dict__.get("sync_to_calendar_button") is not None or bool(self.current_lots)
        self.calendar_sync_button.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _finish_refresh(
        self,
        result: WatchlistResult,
        *,
        sync_result: CalendarSyncResult | None = None,
        sync_error: str = "",
        sync_setup_message: str = "",
    ) -> None:
        self.refresh_button.configure(state=tk.NORMAL)
        self._set_import_buttons_state(tk.NORMAL)
        self._set_stop_available(False)
        self.worker = None
        self.current_lots = result.lots
        self.fallback_lot_keys = set(result.fallback_lot_keys)
        self.source_refresh_errors = list(result.errors)
        self._set_calendar_sync_button_state()
        self.metrics_var.set(result.metrics.summary())
        self._fill_agenda()
        label = (
            "Calendar sync stopped. Click Sync to Calendar to try again." if result.stopped
            else "No upcoming lots found for the selected artists."
        )
        if sync_result:
            label = self._calendar_sync_summary(sync_result)
        elif sync_error:
            label = (
                "Website calendar sync incomplete; some updates may already be saved. "
                "See the sync message for the next step."
            )
        elif sync_setup_message:
            label = "Local lots ready; website calendar not synced. Add the missing .env settings, then click Sync to Calendar."
        elif result.errors and not result.stopped:
            label = "Live source refresh incomplete; website calendar was not synced."
        report = [label]
        if sync_result:
            report.append(
                "These are website upload counts. Updated means an existing calendar record was received; "
                "ended includes previously ended or sold lots. Neither count means the source changed today."
            )
        report.extend(text for text in (sync_error, sync_setup_message, self._source_refresh_details()) if text)
        if result.notices:
            report.append("Import notes:\n" + "\n".join(result.notices))
        self._set_sync_details("\n\n".join(report))
        # Update before opening modal dialogs so the underlying window cannot
        # remain stuck on the earlier 'Syncing...' progress message.
        self._set_status(label)
        if result.errors:
            if sync_result:
                sync_message = sync_result.summary()
            elif sync_error:
                sync_message = (
                    "Website calendar sync is incomplete; some updates may already be saved.\n"
                    + sync_error
                )
            else:
                sync_message = "The website calendar was not synced."
            self._show_source_refresh_warning(sync_message)
        if result.notices:
            messagebox.showinfo("Watchlist Import Notes", "\n".join(result.notices[:8]), parent=self)
        if sync_error:
            messagebox.showwarning(
                "Website Calendar Sync Incomplete",
                "Local lots were retained. Some lot details or earlier batches may already be saved "
                f"on the website, but sync did not finish.\n\n{sync_error}",
                parent=self,
            )
        if sync_setup_message:
            messagebox.showwarning("Calendar Sync Not Configured", sync_setup_message, parent=self)

    def _finish_refresh_error(self, message: str) -> None:
        self.refresh_button.configure(state=tk.NORMAL)
        self._set_import_buttons_state(tk.NORMAL)
        self._set_stop_available(False)
        self.worker = None
        self._set_sync_details("Calendar sync could not finish.\n\n" + message + "\n\n" + self._source_refresh_details())
        self._set_status("Calendar sync could not finish. Your previous local results are still available; try Sync to Calendar again.")
        messagebox.showerror("Calendar Sync Failed", message, parent=self)

    def sync_website_calendar(self) -> None:
        """Legacy upload-only entry point; Studio uses sync_to_calendar instead."""
        if self._is_busy():
            return
        if not self.current_lots:
            messagebox.showwarning("Nothing to Sync", "Use Sync to Calendar to retrieve upcoming lots first.", parent=self)
            return
        if not self._calendar_sync_configured():
            self._set_status("Website calendar not synced: missing .env settings. See the setup instructions.")
            messagebox.showwarning(
                "Calendar Sync Not Configured",
                self._calendar_sync_setup_message(),
                parent=self,
            )
            return

        self.refresh_button.configure(state=tk.DISABLED)
        self._set_import_buttons_state(tk.DISABLED)
        self.calendar_sync_button.configure(state=tk.DISABLED)
        self._set_status("Syncing current watchlist results to the website calendar...")
        lots = list(self.current_lots)

        def run() -> None:
            try:
                result = self.calendar_syncer(
                    lots,
                    base_url=self.calendar_base_url,
                    api_key=self.calendar_api_key,
                    artist_artprice_links=self.artist_artprice_links,
                )
                self.after(0, lambda: self._finish_calendar_sync(result))
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                self.after(0, lambda: self._finish_calendar_sync_error(message))

        self.worker = threading.Thread(target=run, name="artist-watchlist-calendar-sync", daemon=True)
        self.worker.start()

    def _finish_calendar_sync(self, result: CalendarSyncResult) -> None:
        self.refresh_button.configure(state=tk.NORMAL)
        self._set_import_buttons_state(tk.NORMAL)
        self.worker = None
        self._set_calendar_sync_button_state()
        label = self._calendar_sync_summary(result)
        self._set_sync_details(
            label + "\n\nThese are website upload counts. Updated means an existing calendar record was received; "
            "ended includes previously ended or sold lots. Neither count means the source changed today.\n\n"
            + self._source_refresh_details()
        )
        self._set_status(label)
        if self.source_refresh_errors:
            self._show_source_refresh_warning(result.summary())

    def _calendar_sync_summary(self, result: CalendarSyncResult) -> str:
        label = result.summary()
        if self.fallback_lot_keys:
            label += f" Includes {len(self.fallback_lot_keys)} cached lots; live data was not verified."
        if self.source_refresh_errors:
            label += (
                " Live source refresh remains incomplete; retry with browser or import saved Invaluable pages."
                if self._has_invaluable_source_issue()
                else " Live source refresh remains incomplete; try Sync to Calendar after source access is restored."
            )
            cause = " ".join(self.source_refresh_errors[0].split())
            label += "\nSource: " + (cause[:177] + "…" if len(cause) > 180 else cause)
            label += " See Sync details."
        return label

    def _source_refresh_details(self) -> str:
        parts = []
        if self.fallback_lot_keys:
            parts.append(
                f"{len(self.fallback_lot_keys)} cached lots were retained; their live data was not verified. "
                "Uploading them does not refresh their bids, availability, or sold results."
            )
            observations = []
            for lot in self.current_lots:
                if lot.cache_key not in self.fallback_lot_keys:
                    continue
                try:
                    observed, _ = parse_lot_datetime(lot.last_seen_at)
                except (ValueError, TypeError, AttributeError):
                    observed = None
                if observed is not None:
                    observations.append(observed.astimezone(timezone.utc))
            if observations:
                earliest, latest = min(observations), max(observations)
                parts.append(
                    f"Cached observations: earliest {earliest:%Y-%m-%d %H:%M UTC}; "
                    f"latest {latest:%Y-%m-%d %H:%M UTC}."
                )
            unknown = len(self.fallback_lot_keys) - len(observations)
            if unknown:
                parts.append(f"Last observation time unavailable for {unknown} cached lots.")
        if self.source_refresh_errors:
            parts.append("Live source refresh issues:\n" + "\n\n".join(self.source_refresh_errors))
            if any("HTTP 202" in error for error in self.source_refresh_errors):
                parts.append("An HTTP 202 access page is not auction data.")
            if self._has_invaluable_source_issue():
                parts.append(
                    "For Invaluable, click Retry with browser to retrieve the selected artists in a separate, "
                    "visible browser and sync the results. Keep that browser open while it loads. "
                    "If Invaluable shows an access screen, check it in the opened browser; the app waits for "
                    "readable auction data. Access is not guaranteed. Stop cancels the retry and keeps cached lots. "
                    "This retry does not use your usual Chrome profile or the old saved-login setting."
                )
                parts.append(
                    "To add fresh Invaluable lots from your usual browser, load the selected artists' upcoming "
                    "search results and use Import saved Invaluable pages (also under More). Import HTML pages "
                    "that retain full sale dates, or supported JSON search snapshots. "
                    "Imported lots sync to the calendar automatically; missing pages keep their cached data. "
                    "Saved pages do not verify live access, and their bids reflect when they were saved."
                )
            parts.append(
                "Next steps: open the affected auction bookmark in your usual browser to check access, "
                "then retry Sync to Calendar when the source is available. Browser sign-in does not connect "
                "the app's automatic refresh to that session. "
                "Artists with no retrieved or cached lots cannot appear on the calendar yet. "
                "For saved Heritage catalogs or Invaluable upcoming/sold pages, use the matching import under More."
            )
        return "\n\n".join(parts)

    def _set_sync_details(self, text: str) -> None:
        self._sync_details_text = text.strip()
        self._update_browser_retry_button()
        button = self.__dict__.get("sync_details_button")
        if button is not None:
            if self._sync_details_text:
                button.grid()
            else:
                button.grid_remove()

    def show_sync_details(self) -> None:
        if not self._sync_details_text:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Last sync details")
        dialog.geometry("820x520")
        dialog.transient(self.winfo_toplevel())
        body = scrolledtext.ScrolledText(dialog, wrap=tk.WORD, font=("Segoe UI", 10), padx=16, pady=16)
        body.frame.configure(background=STUDIO_COLORS["surface"])
        body.vbar.destroy()
        body.vbar = ttk.Scrollbar(body.frame, orient=tk.VERTICAL, command=body.yview)
        body.vbar.pack(side=tk.RIGHT, fill=tk.Y, before=body._w)
        body.configure(yscrollcommand=body.vbar.set)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(12, 0))
        body.insert("1.0", self._sync_details_text)
        body.configure(state=tk.DISABLED)
        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(anchor="e", padx=12, pady=12)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _show_source_refresh_warning(self, sync_message: str) -> None:
        cached_message = (
            f"\nThe local results include {len(self.fallback_lot_keys)} cached lots whose live data was not verified."
            if self.fallback_lot_keys else ""
        )
        retry_guidance = (
            "Use Retry with browser, or load upcoming results in your usual browser and use "
            "Import saved Invaluable pages to add those lots to Calendar. "
            if self._has_invaluable_source_issue()
            else "Retry Sync to Calendar after source access is restored. "
        )
        cause = " ".join(self.source_refresh_errors[0].split()) if self.source_refresh_errors else ""
        if len(cause) > 260:
            cause = cause[:257] + "…"
        missing = []
        for error in self.source_refresh_errors:
            text = " ".join(error.split())
            position = text.casefold().find("no cached lots")
            if position < 0:
                continue
            # Long source messages can put the missing-artist list after the
            # cause. Keep that list visible even when the cause is shortened.
            if position > 160:
                text = text[position:]
            missing.append(text)
        missing_summary = " ".join(text for text in dict.fromkeys(missing) if text not in cause)
        if len(missing_summary) > 300:
            missing_summary = missing_summary[:297] + "…"
        if missing_summary:
            cause += "\n\n" + missing_summary
        missing_guidance = (
            "Artists without retrieved or cached lots cannot appear on the calendar yet. "
            "After source access is restored, use Sync to Calendar. " if missing else ""
        )
        messagebox.showwarning(
            "Live Source Refresh Incomplete",
            "Some auction sources could not be refreshed live.\n\n"
            f"{sync_message}{cached_message}\n\n"
            + cause
            + "\n\n" + retry_guidance
            + missing_guidance
            + "Use Sync details for the full report, missing artists, and cached observation times.",
            parent=self,
        )

    def _finish_calendar_sync_error(self, message: str) -> None:
        self.refresh_button.configure(state=tk.NORMAL)
        self._set_import_buttons_state(tk.NORMAL)
        self.worker = None
        self._set_calendar_sync_button_state()
        self._set_sync_details(
            "Website calendar sync incomplete; some updates may already be saved.\n\n" + message
            + "\n\n" + self._source_refresh_details()
        )
        self._set_status("Website calendar sync incomplete; some updates may already be saved. See the sync message for the next step.")
        messagebox.showerror(
            "Website Calendar Sync Incomplete",
            "Some lot details or earlier batches may already be saved on the website, "
            f"but sync did not finish.\n\n{message}",
            parent=self,
        )

    def _fill_agenda(self) -> None:
        empty_state = self.__dict__.get("empty_state")
        if empty_state is not None:
            if self.current_lots:
                empty_state.place_forget()
            else:
                message = (
                    "No lots could be retrieved from the selected sources.\nSee the sync status below."
                    if self.source_refresh_errors else "No upcoming lots found for the selected artists."
                )
                empty_state.configure(text=message)
                empty_state.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        lot_summary = self.__dict__.get("lot_summary_var")
        if lot_summary is not None:
            lot_summary.set(f"Next {self.horizon_var.get()} days · {len(self.current_lots)} lots")
        for item in self.agenda_tree.get_children(""):
            self.agenda_tree.delete(item)
        upcoming = self.__dict__.get("upcoming_tree")
        if upcoming is not None:
            for item in upcoming.get_children(""):
                upcoming.delete(item)
            self.lot_detail_var.set("Select a lot for sale details. Double-click to open it.")
        self._lots_by_iid = {}
        self._lot_urls.clear()
        date_nodes: dict[str, str] = {}
        artist_nodes: dict[tuple[str, str], str] = {}
        for index, lot in enumerate(self.current_lots):
            parsed, all_day = parse_lot_datetime(lot.relevant_at)
            date_label = parsed.date().isoformat() if parsed else "Date unverified"
            time_label = "All day" if parsed and all_day else parsed.strftime("%H:%M") if parsed else ""
            date_parent = date_nodes.get(date_label)
            if not date_parent:
                date_parent = f"date-{len(date_nodes)}"
                date_nodes[date_label] = date_parent
                self.agenda_tree.insert("", tk.END, iid=date_parent, text=date_label, open=True, tags=("date_group",))
            artist = lot.artist_watchlist_name or lot.artist or "Unknown artist"
            artist_key = (date_label, artist)
            artist_parent = artist_nodes.get(artist_key)
            if not artist_parent:
                artist_parent = f"artist-{len(artist_nodes)}"
                artist_nodes[artist_key] = artist_parent
                self.agenda_tree.insert(
                    date_parent,
                    tk.END,
                    iid=artist_parent,
                    text=artist,
                    open=True,
                    tags=("artist_group",),
                )
            estimate = ""
            if lot.estimate_low is not None or lot.estimate_high is not None:
                estimate = f"{lot.estimate_low or '?'}–{lot.estimate_high or '?'} {lot.currency}".strip()
            bid = lot.bid_label
            display_status = "cached" if lot.cache_key in self.fallback_lot_keys else lot.status
            iid = f"lot-{index}"
            if upcoming is not None:
                upcoming.insert(
                    "", tk.END, iid=iid,
                    values=(
                        f"{parsed.day} {parsed.strftime('%b')}" if parsed else "Unverified",
                        artist, lot.title, lot.lot_number, self._compact_estimate(lot),
                    ),
                    tags=(display_status,),
                )
            self._lots_by_iid[iid] = lot
            self.agenda_tree.insert(
                artist_parent,
                tk.END,
                iid=iid,
                values=(
                    time_label,
                    " — ".join(value for value in (lot.auction_house, lot.sale_title) if value) or lot.source,
                    lot.lot_number,
                    lot.title,
                    estimate,
                    bid,
                    display_status.title(),
                ),
                tags=(display_status,),
            )
            self._lot_urls[iid] = lot.lot_url
        self.calendar_text.configure(state=tk.NORMAL)
        self.calendar_text.delete("1.0", tk.END)
        self.calendar_text.insert(tk.END, render_calendar_preview(self.current_lots))
        self.calendar_text.configure(state=tk.DISABLED)

    def _open_selected_lot(self, _event=None) -> None:
        tree = _event.widget if _event is not None else (
            self.__dict__.get("upcoming_tree") if self.__dict__.get("_active_lot_view") == "upcoming"
            else self.agenda_tree
        )
        selected = tree.selection()
        if selected and self._lot_urls.get(selected[0]):
            webbrowser.open(self._lot_urls[selected[0]])

    @staticmethod
    def _compact_estimate(lot: NormalizedLot) -> str:
        if lot.estimate_low is None and lot.estimate_high is None:
            return "—"

        def amount(value):
            return f"{value:,.2f}".rstrip("0").rstrip(".") if value is not None else "?"

        value = f"{amount(lot.estimate_low)}–{amount(lot.estimate_high)}"
        currency = (lot.currency or "").upper()
        symbol = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency)
        return f"{symbol}{value}" if symbol else f"{value} {currency}".strip()

    def _show_selected_lot_details(self, _event=None) -> None:
        selected = self.upcoming_tree.selection()
        lot = self.__dict__.get("_lots_by_iid", {}).get(selected[0]) if selected else None
        if lot is None:
            return
        parsed, all_day = parse_lot_datetime(lot.relevant_at)
        date = parsed.strftime("%d %b %Y") if parsed else "Date unverified"
        if parsed and not all_day:
            date += f" at {parsed.strftime('%H:%M')}"
        status = "Cached · live data not verified" if lot.cache_key in self.fallback_lot_keys else lot.status.title()
        sale = " — ".join(value for value in (lot.auction_house, lot.sale_title) if value) or lot.source
        self.lot_detail_var.set("  ·  ".join(value for value in (date, sale, lot.bid_label, status) if value))

    def _export(self, kind: str) -> None:
        if not self.current_lots:
            messagebox.showwarning("Nothing to Export", "Use Sync to Calendar to retrieve upcoming lots first.", parent=self)
            return
        config = {
            "md": ("Markdown", ".md", render_markdown),
            "csv": ("CSV", ".csv", render_csv),
            "ics": ("Calendar", ".ics", render_ics),
        }[kind]
        label, extension, renderer = config
        path = filedialog.asksaveasfilename(
            title=f"Export Artist Watchlist {label}",
            defaultextension=extension,
            initialfile=f"artist-watchlist{extension}",
            filetypes=[(label, f"*{extension}"), ("All Files", "*.*")],
            parent=self,
        )
        if not path:
            return
        Path(path).write_text(renderer(self.current_lots), encoding="utf-8", newline="")
        self._set_status(f"Exported {Path(path).name}.")

    def _set_status(self, text: str) -> None:
        inline_status = self.__dict__.get("sync_status_var")
        if inline_status is not None:
            inline_status.set(text)
        title = self.__dict__.get("status_title_var")
        if title is not None:
            lower = text.casefold()
            warning = any(word in lower for word in (
                "incomplete", "could not", "couldn’t", "not synced", "not verified", "missing", "failed",
            ))
            if "website calendar synced" in lower and self.source_refresh_errors:
                heading = "Calendar updated; source refresh incomplete"
            elif "website calendar synced" in lower and self.fallback_lot_keys:
                heading = "Calendar updated with cached lots"
            elif warning:
                heading = "Sync needs attention"
            elif "stopped" in lower or "stopping" in lower:
                heading = "Calendar sync stopped" if "stopped" in lower else "Stopping sync"
            elif self.__dict__.get("_busy"):
                heading = "Syncing your calendar"
            elif "calendar synced" in lower:
                heading = "Calendar updated"
            elif "no upcoming lots" in lower:
                heading = "No upcoming lots"
            elif "exported" in lower:
                heading = "Export complete"
            else:
                heading = "Ready to sync"
            title.set(heading)
            prefix = "WarningStatus" if warning else "Status"
            self.status_banner.configure(style=f"{prefix}.TFrame")
            actions = self.__dict__.get("status_actions")
            if actions is not None:
                actions.configure(style=f"{prefix}.TFrame")
            self.status_title_label.configure(style=f"{prefix}.TLabel")
            self.status_message_label.configure(style=f"{prefix}.TLabel")
            self.status_icon.configure(style=f"{prefix}.TLabel", image=self._icons["alert" if warning else "check"])
        self.status_callback(text)

    def _read_settings(self) -> dict:
        try:
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _remembered_bookmark_path(self) -> Path | None:
        path = self._read_settings().get("last_bookmark_path", "")
        return Path(path) if path else None

    def _load_initial_bookmarks(self) -> None:
        remembered_path = self._remembered_bookmark_path()
        candidates = list(dict.fromkeys(
            path for path in (remembered_path, PROJECT_BOOKMARK_PATH, DEFAULT_BOOKMARK_PATH) if path
        ))

        for path in candidates:
            if path.is_file() and self.load_bookmarks(path):
                self._set_status("Your bookmark file is loaded. Upcoming lots will be checked when you sync.")
                return

        self.bookmark_path_var.set("")
        self.import_summary_var.set(
            "No bookmark file is available. Click Import Bookmarks HTML to choose one."
        )

    def _save_settings_hint(self) -> None:
        payload = self._read_settings()
        payload["last_bookmark_path"] = self.bookmark_path_var.get()
        session_var = self.__dict__.get("invaluable_session_var")
        if session_var is not None:
            payload["invaluable_session_enabled"] = bool(session_var.get())
        chrome_profile_var = self.__dict__.get("chrome_profile_var")
        if chrome_profile_var is not None:
            payload["invaluable_chrome_profile"] = self.chrome_profile_choices.get(chrome_profile_var.get())
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
