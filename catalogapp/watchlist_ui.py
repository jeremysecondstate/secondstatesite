"""Tkinter Artist Watchlist panel for the internal desktop catalog app."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import webbrowser

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from catalogapp.bookmark_watchlist import (
    BookmarkEntry,
    artist_source_counts,
    folder_counts,
    load_bookmarks_file,
)
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_exports import render_calendar_preview, render_csv, render_ics, render_markdown
from catalogapp.watchlist_models import NormalizedLot, parse_lot_datetime
from catalogapp.watchlist_service import WatchlistResult, WatchlistService
from catalogapp.watchlist_sync import CalendarSyncResult, sync_watchlist_lots


DEFAULT_BOOKMARK_PATH = Path(r"I:\Shared drives\SECONDSTATE\ARTAPP\INVALUABLE-BM.html")


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
        super().__init__(master, padding=10)
        self.status_callback = status_callback or (lambda _text: None)
        self.service_factory = service_factory
        self.calendar_base_url = calendar_base_url
        self.calendar_api_key = calendar_api_key
        self.calendar_syncer = calendar_syncer or sync_watchlist_lots
        self.all_entries: list[BookmarkEntry] = []
        self.active_entries: list[BookmarkEntry] = []
        self.selected_artists: set[str] = set()
        self.folder_vars: dict[str, tk.BooleanVar] = {}
        self.current_lots: list[NormalizedLot] = []
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._lot_urls: dict[str, str] = {}
        self._settings_path = local_watchlist_directory() / "settings.json"
        self._cache_path = local_watchlist_directory() / "watchlist.sqlite3"
        self._build()
        self._load_initial_bookmarks()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        ttk.Label(self, text="Artist Watchlist", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            self,
            text=(
                "Import curated auction bookmarks, visit only selected artist URLs, and build a local agenda. "
                "Bookmark files stay on this computer; zero-AI mode is on by default."
            ),
            style="Subtle.TLabel",
            wraplength=920,
        ).grid(row=1, column=0, sticky="ew", pady=(2, 8))

        import_frame = ttk.LabelFrame(self, text="1. Curated bookmark file", padding=8)
        import_frame.grid(row=2, column=0, sticky="ew")
        import_frame.columnconfigure(1, weight=1)
        ttk.Button(import_frame, text="Import Bookmarks HTML…", command=self.import_bookmarks).grid(row=0, column=0, sticky="w")
        self.bookmark_path_var = tk.StringVar()
        ttk.Entry(import_frame, textvariable=self.bookmark_path_var, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )
        self.import_summary_var = tk.StringVar(value="No bookmark file loaded.")
        ttk.Label(import_frame, textvariable=self.import_summary_var, style="Subtle.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )

        # Keep the two data-heavy sections in a vertical paned window so the
        # artist picker or the agenda can use as much of the tab as the user
        # needs.  The nested horizontal pane does the same for folders/artists.
        workspace = tk.PanedWindow(
            self,
            orient=tk.VERTICAL,
            borderwidth=0,
            relief=tk.FLAT,
            sashwidth=8,
            sashrelief=tk.RAISED,
        )
        workspace.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        self.workspace_pane = workspace

        selection = tk.PanedWindow(
            workspace,
            orient=tk.HORIZONTAL,
            borderwidth=0,
            relief=tk.FLAT,
            sashwidth=8,
            sashrelief=tk.RAISED,
        )
        self.selection_pane = selection
        folders = ttk.LabelFrame(selection, text="Detected folders", padding=8, width=300)
        artists = ttk.LabelFrame(selection, text="Artists", padding=8)
        selection.add(folders, minsize=160, stretch="always")
        selection.add(artists, minsize=280, stretch="always")
        self.folder_controls = ttk.Frame(folders)
        self.folder_controls.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            folders,
            text="Only allowed auction domains are counted.",
            style="Subtle.TLabel",
        ).pack(anchor="w", pady=(5, 0))

        artist_search = ttk.Frame(artists)
        artist_search.pack(fill=tk.X)
        ttk.Label(artist_search, text="Filter").pack(side=tk.LEFT)
        self.artist_filter_var = tk.StringVar()
        self.artist_filter_var.trace_add("write", lambda *_args: self._fill_artist_tree())
        ttk.Entry(artist_search, textvariable=self.artist_filter_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 8))
        ttk.Button(artist_search, text="Select All", command=self._select_all_artists).pack(side=tk.LEFT)
        ttk.Button(artist_search, text="Select None", command=self._select_no_artists).pack(side=tk.LEFT, padx=(6, 0))
        artist_table = ttk.Frame(artists)
        artist_table.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        artist_table.columnconfigure(0, weight=1)
        artist_table.rowconfigure(0, weight=1)
        self.artist_tree = ttk.Treeview(
            artist_table,
            columns=("watch", "artist", "sources", "urls"),
            show="headings",
            # This is only the comfortable starting size; the pane sash can
            # still shrink the table to its configured minimum.
            height=8,
            selectmode="browse",
        )
        for key, title, width in (
            ("watch", "Watch", 55),
            ("artist", "Artist", 230),
            ("sources", "Sources", 180),
            ("urls", "URLs", 55),
        ):
            self.artist_tree.heading(key, text=title)
            self.artist_tree.column(key, width=width, stretch=key in {"artist", "sources"})
        self.artist_tree.grid(row=0, column=0, sticky="nsew")
        artist_scroll_y = ttk.Scrollbar(artist_table, orient=tk.VERTICAL, command=self.artist_tree.yview)
        artist_scroll_y.grid(row=0, column=1, sticky="ns")
        artist_scroll_x = ttk.Scrollbar(artist_table, orient=tk.HORIZONTAL, command=self.artist_tree.xview)
        artist_scroll_x.grid(row=1, column=0, sticky="ew")
        self.artist_tree.configure(
            yscrollcommand=artist_scroll_y.set,
            xscrollcommand=artist_scroll_x.set,
        )
        self.artist_tree.bind("<Double-1>", self._toggle_artist)

        results = ttk.LabelFrame(workspace, text="2. Refresh and agenda", padding=8)
        results.columnconfigure(0, weight=1)
        results.rowconfigure(1, weight=1)
        workspace.add(selection, minsize=100, stretch="always")
        workspace.add(results, minsize=140, stretch="always")
        controls = ttk.Frame(results)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        ttk.Label(controls, text="Date horizon").pack(side=tk.LEFT)
        self.horizon_var = tk.IntVar(value=7)
        horizon = ttk.Combobox(controls, textvariable=self.horizon_var, values=(3, 7, 14, 30), width=4, state="readonly")
        horizon.pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(controls, text="days").pack(side=tk.LEFT, padx=(0, 14))
        self.new_changed_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="New/changed only", variable=self.new_changed_var).pack(side=tk.LEFT)
        self.zero_ai_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Zero-AI mode", variable=self.zero_ai_var).pack(side=tk.LEFT, padx=(12, 0))
        self.refresh_button = ttk.Button(
            controls,
            text="Refresh Watchlist",
            command=self.refresh_watchlist,
            style="Accent.TButton",
        )
        self.refresh_button.pack(side=tk.RIGHT)
        self.stop_button = ttk.Button(controls, text="Stop", command=self.stop_refresh, state=tk.DISABLED)
        self.stop_button.pack(side=tk.RIGHT, padx=(0, 8))

        views = ttk.Notebook(results)
        views.grid(row=1, column=0, sticky="nsew")
        agenda_tab = ttk.Frame(views, padding=4)
        calendar_tab = ttk.Frame(views, padding=4)
        views.add(agenda_tab, text="Agenda")
        views.add(calendar_tab, text="Calendar")
        agenda_tab.columnconfigure(0, weight=1)
        agenda_tab.rowconfigure(0, weight=1)
        columns = ("time", "sale", "lot", "title", "estimate", "bid", "status")
        self.agenda_tree = ttk.Treeview(agenda_tab, columns=columns, show="tree headings", height=6)
        self.agenda_tree.heading("#0", text="Date / Artist")
        self.agenda_tree.column("#0", width=200, stretch=True)
        widths = {"time": 60, "sale": 180, "lot": 55, "title": 220, "estimate": 105, "bid": 130, "status": 70}
        for column in columns:
            heading = "Current Bid" if column == "bid" else column.replace("_", " ").title()
            self.agenda_tree.heading(column, text=heading)
            self.agenda_tree.column(column, width=widths[column], stretch=column in {"artist", "sale", "title"})
        self.agenda_tree.grid(row=0, column=0, sticky="nsew")
        agenda_scroll = ttk.Scrollbar(agenda_tab, orient=tk.VERTICAL, command=self.agenda_tree.yview)
        agenda_scroll.grid(row=0, column=1, sticky="ns")
        agenda_scroll_x = ttk.Scrollbar(agenda_tab, orient=tk.HORIZONTAL, command=self.agenda_tree.xview)
        agenda_scroll_x.grid(row=1, column=0, sticky="ew")
        self.agenda_tree.configure(
            yscrollcommand=agenda_scroll.set,
            xscrollcommand=agenda_scroll_x.set,
        )
        self.agenda_tree.tag_configure("date_group", font=("Segoe UI Semibold", 10))
        self.agenda_tree.tag_configure("artist_group", font=("Segoe UI Semibold", 10))
        self.agenda_tree.tag_configure("new", foreground="#117a37")
        self.agenda_tree.tag_configure("changed", foreground="#a05a00")
        self.agenda_tree.tag_configure("ended", foreground="#777777")
        self.agenda_tree.bind("<Double-1>", self._open_selected_lot)
        self.calendar_text = scrolledtext.ScrolledText(calendar_tab, wrap=tk.WORD, font=("Consolas", 10), height=10)
        self.calendar_text.pack(fill=tk.BOTH, expand=True)
        self.calendar_text.configure(state=tk.DISABLED)

        footer = ttk.Frame(self)
        footer.grid(row=4, column=0, sticky="ew", pady=(7, 0))
        self.metrics_var = tk.StringVar(
            value="Pages fetched: 0 · Cache hits: 0 · Changed: 0 · AI-enriched: 0 · Tokens: 0"
        )
        ttk.Label(footer, textvariable=self.metrics_var, style="Subtle.TLabel").pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.calendar_sync_button = ttk.Button(
            footer,
            text="Sync Website Calendar",
            command=self.sync_website_calendar,
            state=tk.DISABLED,
        )
        self.calendar_sync_button.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(footer, text="Export Markdown", command=lambda: self._export("md")).pack(side=tk.LEFT)
        ttk.Button(footer, text="Export CSV", command=lambda: self._export("csv")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(footer, text="Export ICS", command=lambda: self._export("ics")).pack(side=tk.LEFT, padx=(6, 0))

    def import_bookmarks(self) -> None:
        initial = Path(self.bookmark_path_var.get()) if self.bookmark_path_var.get() else None
        path = filedialog.askopenfilename(
            title="Import exported browser bookmarks",
            initialdir=str(initial.parent) if initial and initial.parent.exists() else None,
            initialfile=initial.name if initial else None,
            filetypes=[("Bookmark HTML", "*.html *.htm"), ("All Files", "*.*")],
        )
        if path:
            self.load_bookmarks(path)

    def load_bookmarks(self, path: str | Path) -> bool:
        try:
            entries = load_bookmarks_file(path)
        except Exception as exc:
            messagebox.showerror("Bookmark Import Failed", str(exc), parent=self)
            return False
        self.all_entries = entries
        self.bookmark_path_var.set(str(Path(path).resolve()))
        self._save_settings_hint()
        self._build_folder_controls()
        self._update_active_entries(select_all=True)
        return True

    def _build_folder_controls(self) -> None:
        for child in self.folder_controls.winfo_children():
            child.destroy()
        self.folder_vars.clear()
        counts = folder_counts(self.all_entries)
        for row, (folder, count) in enumerate(counts.items()):
            selected = folder.casefold() == "artists invaluable"
            var = tk.BooleanVar(value=selected)
            self.folder_vars[folder] = var
            ttk.Checkbutton(
                self.folder_controls,
                text=f"{folder} ({count})",
                variable=var,
                command=self._update_active_entries,
            ).grid(row=row, column=0, sticky="w")
        if not counts:
            ttk.Label(self.folder_controls, text="No allowed auction folders detected.", style="Subtle.TLabel").pack(anchor="w")

    def _update_active_entries(self, select_all: bool = False) -> None:
        previous_artists = set(artist_source_counts(self.active_entries))
        selected_folders = {name.casefold() for name, var in self.folder_vars.items() if var.get()}
        self.active_entries = [
            entry for entry in self.all_entries if any(part.casefold() in selected_folders for part in entry.folder_path)
        ]
        artists = set(artist_source_counts(self.active_entries))
        if select_all or not self.selected_artists:
            self.selected_artists = set(artists)
        else:
            self.selected_artists = (self.selected_artists & artists) | (artists - previous_artists)
        self._fill_artist_tree()
        source_counts: dict[str, int] = {}
        for entry in self.active_entries:
            source_counts[entry.source] = source_counts.get(entry.source, 0) + 1
        sources = ", ".join(f"{source}: {count}" for source, count in sorted(source_counts.items())) or "none"
        self.import_summary_var.set(
            f"{len(self.folder_vars)} folders detected · {len(artists)} artists selected from allowed sources ({sources})."
        )

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
        self.selected_artists = set(artist_source_counts(self.active_entries))
        self._refresh_artist_watch_marks()

    def _select_no_artists(self) -> None:
        self.selected_artists.clear()
        self._refresh_artist_watch_marks()

    def _refresh_artist_watch_marks(self) -> None:
        """Update watch marks without rebuilding the tree or losing its scroll position."""
        for item in self.artist_tree.get_children(""):
            values = list(self.artist_tree.item(item, "values"))
            if values:
                values[0] = "Yes" if item in self.selected_artists else ""
                self.artist_tree.item(item, values=values)

    def refresh_watchlist(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.active_entries:
            messagebox.showwarning("No Bookmarks", "Import a bookmark file and select at least one allowed folder.", parent=self)
            return
        if not self.selected_artists:
            messagebox.showwarning("No Artists", "Select at least one artist to refresh.", parent=self)
            return
        self.stop_event = threading.Event()
        self.refresh_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self._set_status("Starting deterministic watchlist refresh…")
        entries = list(self.active_entries)
        selected_artists = set(self.selected_artists)
        horizon_days = int(self.horizon_var.get())
        zero_ai = bool(self.zero_ai_var.get())
        new_changed_only = bool(self.new_changed_var.get())

        def run() -> None:
            try:
                local_watchlist_directory().mkdir(parents=True, exist_ok=True)
                with WatchlistCache(self._cache_path) as cache:
                    service = self.service_factory(cache) if self.service_factory else WatchlistService(cache)
                    result = service.refresh(
                        entries,
                        selected_artists=selected_artists,
                        horizon_days=horizon_days,
                        zero_ai=zero_ai,
                        new_changed_only=new_changed_only,
                        stop_event=self.stop_event,
                        progress=lambda text: self.after(0, lambda value=text: self._set_status(value)),
                    )
                sync_result = None
                sync_error = ""
                if not result.stopped and self._calendar_sync_configured():
                    self.after(0, lambda: self._set_status("Watchlist refreshed. Syncing the website calendar..."))
                    try:
                        sync_result = self.calendar_syncer(
                            result.lots,
                            base_url=self.calendar_base_url,
                            api_key=self.calendar_api_key,
                        )
                    except Exception as exc:
                        sync_error = " ".join(str(exc).split())[:500]
                self.after(
                    0,
                    lambda result=result, sync_result=sync_result, sync_error=sync_error: self._finish_refresh(
                        result,
                        sync_result=sync_result,
                        sync_error=sync_error,
                    ),
                )
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                self.after(0, lambda: self._finish_refresh_error(message))

        self.worker = threading.Thread(target=run, name="artist-watchlist-refresh", daemon=True)
        self.worker.start()

    def stop_refresh(self) -> None:
        self.stop_event.set()
        self._set_status("Stopping after the current safe fetch…")

    def _calendar_sync_configured(self) -> bool:
        return bool(self.calendar_base_url and self.calendar_api_key)

    def _set_calendar_sync_button_state(self) -> None:
        enabled = bool(self.current_lots and self._calendar_sync_configured())
        self.calendar_sync_button.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _finish_refresh(
        self,
        result: WatchlistResult,
        *,
        sync_result: CalendarSyncResult | None = None,
        sync_error: str = "",
    ) -> None:
        self.refresh_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.current_lots = result.lots
        self._set_calendar_sync_button_state()
        self.metrics_var.set(result.metrics.summary())
        self._fill_agenda()
        if result.errors:
            messagebox.showwarning("Watchlist Finished with Source Issues", "\n".join(result.errors[:8]), parent=self)
        if sync_error:
            messagebox.showwarning(
                "Website Calendar Sync Failed",
                f"The local watchlist refreshed successfully, but the website calendar did not sync.\n\n{sync_error}",
                parent=self,
            )
        label = "Watchlist refresh stopped." if result.stopped else result.metrics.summary()
        if sync_result:
            label = sync_result.summary()
        elif sync_error:
            label = "Local watchlist refreshed; website calendar sync failed. Use Sync Website Calendar to retry."
        self._set_status(label)

    def _finish_refresh_error(self, message: str) -> None:
        self.refresh_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self._set_status("Watchlist refresh failed.")
        messagebox.showerror("Watchlist Refresh Failed", message, parent=self)

    def sync_website_calendar(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.current_lots:
            messagebox.showwarning("Nothing to Sync", "Refresh the watchlist first.", parent=self)
            return
        if not self._calendar_sync_configured():
            messagebox.showwarning(
                "Calendar Sync Not Configured",
                "SECONDSTATE_BASE_URL and CATALOG_API_KEY are required.",
                parent=self,
            )
            return

        self.refresh_button.configure(state=tk.DISABLED)
        self.calendar_sync_button.configure(state=tk.DISABLED)
        self._set_status("Syncing current watchlist results to the website calendar...")
        lots = list(self.current_lots)

        def run() -> None:
            try:
                result = self.calendar_syncer(
                    lots,
                    base_url=self.calendar_base_url,
                    api_key=self.calendar_api_key,
                )
                self.after(0, lambda: self._finish_calendar_sync(result))
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                self.after(0, lambda: self._finish_calendar_sync_error(message))

        self.worker = threading.Thread(target=run, name="artist-watchlist-calendar-sync", daemon=True)
        self.worker.start()

    def _finish_calendar_sync(self, result: CalendarSyncResult) -> None:
        self.refresh_button.configure(state=tk.NORMAL)
        self._set_calendar_sync_button_state()
        self._set_status(result.summary())

    def _finish_calendar_sync_error(self, message: str) -> None:
        self.refresh_button.configure(state=tk.NORMAL)
        self._set_calendar_sync_button_state()
        self._set_status("Website calendar sync failed.")
        messagebox.showerror("Website Calendar Sync Failed", message, parent=self)

    def _fill_agenda(self) -> None:
        for item in self.agenda_tree.get_children(""):
            self.agenda_tree.delete(item)
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
            iid = f"lot-{index}"
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
                    lot.status.title(),
                ),
                tags=(lot.status,),
            )
            self._lot_urls[iid] = lot.lot_url
        self.calendar_text.configure(state=tk.NORMAL)
        self.calendar_text.delete("1.0", tk.END)
        self.calendar_text.insert(tk.END, render_calendar_preview(self.current_lots))
        self.calendar_text.configure(state=tk.DISABLED)

    def _open_selected_lot(self, _event=None) -> None:
        selected = self.agenda_tree.selection()
        if selected and self._lot_urls.get(selected[0]):
            webbrowser.open(self._lot_urls[selected[0]])

    def _export(self, kind: str) -> None:
        if not self.current_lots:
            messagebox.showwarning("Nothing to Export", "Refresh the watchlist first.", parent=self)
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
        self.status_callback(text)

    def _remembered_bookmark_path(self) -> Path | None:
        try:
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
            path = payload.get("last_bookmark_path", "")
        except (OSError, ValueError, TypeError):
            return None
        return Path(path) if path else None

    def _load_initial_bookmarks(self) -> None:
        remembered_path = self._remembered_bookmark_path()
        candidates = [DEFAULT_BOOKMARK_PATH]
        if remembered_path and remembered_path != DEFAULT_BOOKMARK_PATH:
            candidates.append(remembered_path)

        for path in candidates:
            if path.is_file() and self.load_bookmarks(path):
                return

        self.bookmark_path_var.set(str(DEFAULT_BOOKMARK_PATH))
        self.import_summary_var.set(
            "Default bookmark file is unavailable. Connect the shared drive or click Import to choose another file."
        )

    def _save_settings_hint(self) -> None:
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(
            json.dumps({"last_bookmark_path": self.bookmark_path_var.get()}, indent=2),
            encoding="utf-8",
        )
