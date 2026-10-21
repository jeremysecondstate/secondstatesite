"""Guide a local snapshot import from the user's ordinary browser."""

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlsplit
import webbrowser


SNAPSHOT_HELPER = Path(__file__).resolve().parents[1] / "scripts" / "invaluable_export_snapshot.js"


def recovery_searches(entries, selected_artists, coverage):
    """Show unfinished selected searches first, retaining completed selections."""
    selected = {name.casefold() for name in selected_artists}
    states = {item.watch_url: item for item in coverage}
    searches = []
    for entry in entries:
        if (entry.source != "Invaluable" or "\\" in entry.url
                or any(character.isspace() or ord(character) < 32 for character in entry.url)):
            continue
        try:
            parts = urlsplit(entry.url)
        except ValueError:
            continue
        if (parts.scheme != "https" or parts.netloc not in {"www.invaluable.com", "invaluable.com"}
                or parts.path.rstrip("/") != "/search" or entry.watch_label.casefold() not in selected):
            continue
        searches.append(entry)
    return sorted(searches, key=lambda entry: (
        entry.url in states and not states[entry.url].needs_recovery,
        entry.watch_label.casefold(), entry.url,
    ))


def show_browser_helper(parent, entries, *, import_snapshots):
    """Keep all browser data local until the existing normalized-lot import."""
    dialog = tk.Toplevel(parent)
    dialog.title("Sync from your usual browser")
    dialog.transient(parent.winfo_toplevel())
    dialog.resizable(True, False)
    body = ttk.Frame(dialog, padding=24)
    body.pack(fill=tk.BOTH, expand=True)
    body.columnconfigure(0, weight=1)
    ttk.Label(body, text="Use the browser where Invaluable loads", style="Heading.TLabel").grid(
        row=0, column=0, sticky="w",
    )
    ttk.Label(
        body, text=("For a whole artist list, use the SecondState Invaluable Collector extension, then More → "
                    "Import browser capture and update Calendar. Setup: docs/invaluable-collector.md.\n\n"
                    "The manual fallback below works for individual pages. Unfinished searches appear first."),
        wraplength=660,
    ).grid(row=1, column=0, sticky="ew", pady=(8, 16))
    choices = ttk.Combobox(body, state="readonly", values=[entry.watch_label for entry in entries], width=60)
    choices.grid(row=2, column=0, sticky="ew")
    choices.current(0)
    status = tk.StringVar(value="Only public lot details are saved. Your browser login stays in your browser.")

    def copy_text(value, message):
        parent.clipboard_clear()
        parent.clipboard_append(value)
        status.set(message)

    def open_search():
        url = entries[choices.current()].url
        try:
            opened = webbrowser.open_new_tab(url)
        except (OSError, webbrowser.Error):
            opened = False
        status.set(
            "Search opened. If it opens in another browser profile, use Copy artist link in your working browser."
            if opened else "The browser could not be opened. Use Copy artist link and open it in your usual browser."
        )

    def copy_helper():
        try:
            script = SNAPSHOT_HELPER.read_text(encoding="utf-8")
        except OSError:
            messagebox.showerror(
                "Snapshot helper unavailable", "The snapshot helper is missing from this installation. "
                "You can still import existing saved pages or snapshots.", parent=dialog,
            )
            return
        copy_text(script, "Helper copied. In the loaded artist search, open F12 → Console, paste it and press Enter.")

    actions = ttk.Frame(body)
    actions.grid(row=3, column=0, sticky="w", pady=(10, 16))
    ttk.Button(actions, text="Open artist search", command=open_search).pack(side=tk.LEFT)
    ttk.Button(actions, text="Copy artist link", command=lambda: copy_text(
        entries[choices.current()].url, "Artist link copied. Open it in the browser where Invaluable works.",
    )).pack(side=tk.LEFT, padx=10)
    ttk.Button(actions, text="Copy snapshot helper", command=copy_helper).pack(side=tk.LEFT)
    ttk.Label(body, text=(
        "1. Open the artist search in your usual browser and wait for the lots to load.\n\n"
        "2. Click Copy snapshot helper. In that search tab, press F12, select Console, paste the helper, "
        "and press Enter. A SecondState snapshot panel appears on the page.\n\n"
        "3. Change Sort By once. When the panel shows the artist and lot count, click Download lot snapshot. "
        "Save each results page you need; run the helper again after a full page navigation.\n\n"
        "4. Click Import snapshots and update Calendar below. Select the downloaded JSON files together. "
        "Studio imports their dated lots and uploads them automatically."
    ), wraplength=660, justify=tk.LEFT).grid(row=4, column=0, sticky="ew")
    ttk.Label(body, textvariable=status, wraplength=660, style="Subtle.TLabel").grid(
        row=5, column=0, sticky="ew", pady=(16, 0),
    )
    ttk.Label(body, text=(
        "Snapshots contain the lots loaded when you downloaded them. Missing pages keep their cached data; "
        "an import does not confirm a complete live search."
    ), wraplength=660, style="Subtle.TLabel").grid(row=6, column=0, sticky="ew", pady=(8, 16))

    def finish_import():
        dialog.destroy()
        import_snapshots()

    bottom = ttk.Frame(body)
    bottom.grid(row=7, column=0, sticky="e")
    ttk.Button(bottom, text="Close", command=dialog.destroy).pack(side=tk.LEFT, padx=(0, 12))
    ttk.Button(bottom, text="Import snapshots and update Calendar", command=finish_import).pack(side=tk.LEFT)
    dialog.grab_set()
    return dialog
