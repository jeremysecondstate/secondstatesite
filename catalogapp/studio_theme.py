"""Shared, dependency-free Studio styling for the catalog desktop workspace."""

import sys
import tkinter as tk
from tkinter import ttk

from catalogapp.studio_assets import rounded_image, row_separator, studio_icon
from catalogapp.studio_palette import STUDIO_COLORS


def apply_studio_theme(master) -> ttk.Style:
    """Apply the same palette to the workspace, watchlist and existing dialogs."""
    colors = STUDIO_COLORS
    style = ttk.Style(master)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    master.configure(background=colors["bg"])
    master.option_add("*Toplevel.background", colors["bg"])
    master.option_add("*Menu.background", colors["surface"])
    master.option_add("*Menu.foreground", colors["ink"])
    master.option_add("*Menu.activeBackground", colors["soft"])
    master.option_add("*Menu.activeForeground", colors["ink"])
    master.option_add("*Listbox.background", colors["surface"])
    master.option_add("*Listbox.foreground", colors["ink"])
    master.option_add("*Listbox.selectBackground", colors["soft"])
    master.option_add("*Listbox.selectForeground", colors["ink"])
    master.option_add("*Text.background", colors["surface"])
    master.option_add("*Text.foreground", colors["ink"])
    master.option_add("*Text.selectBackground", colors["soft"])
    master.option_add("*Text.selectForeground", colors["ink"])
    master.option_add("*Text.insertBackground", colors["ink"])

    style.configure(".", font=("Segoe UI", 10), background=colors["bg"], foreground=colors["ink"])
    style.configure("TFrame", background=colors["bg"])
    style.configure("Surface.TFrame", background=colors["surface"])
    style.configure("Soft.TFrame", background=colors["soft"])
    style.configure("Soft.TLabel", background=colors["soft"], foreground=colors["ink"])
    style.configure("TLabel", background=colors["bg"], foreground=colors["ink"])
    style.configure("Surface.TLabel", background=colors["surface"])
    style.configure("Subtle.TLabel", foreground=colors["muted"])
    style.configure("SurfaceSubtle.TLabel", background=colors["surface"], foreground=colors["muted"])
    style.configure("Header.TLabel", font=("Segoe UI Semibold", 19))
    style.configure("Section.TLabel", font=("Segoe UI Semibold", 11))
    style.configure("SurfaceSection.TLabel", background=colors["surface"], font=("Segoe UI Semibold", 11))
    style.configure("Brand.TLabel", background=colors["surface"], font=("Georgia", 10))
    style.configure("BrandSubtle.TLabel", background=colors["surface"], foreground=colors["muted"], font=("Segoe UI", 9))
    style.configure("Small.TLabel", foreground=colors["muted"], font=("Segoe UI", 9))
    style.configure("Selection.TLabel", background=colors["soft"], foreground=colors["ink"], padding=(12, 10))
    style.configure("TSeparator", background=colors["line"], lightcolor=colors["line"], darkcolor=colors["line"])
    style.configure("TLabelframe", bordercolor=colors["line"], relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", foreground=colors["muted"], font=("Segoe UI Semibold", 10))

    style.configure(
        "TButton", background=colors["surface"], foreground=colors["ink"],
        bordercolor=colors["line"], lightcolor=colors["surface"], darkcolor=colors["surface"],
        padding=(12, 9), relief="flat", borderwidth=1, focusthickness=1,
        focuscolor=colors["accent"],
    )
    style.map(
        "TButton", background=[("disabled", colors["bg"]), ("pressed", colors["soft"]), ("active", colors["soft"])],
        foreground=[("disabled", colors["muted"])], bordercolor=[("focus", colors["accent"])],
    )
    style.configure("Secondary.TButton", padding=(12, 9))
    style.configure("Rail.TButton", anchor="w", padding=(10, 9), font=("Segoe UI", 9))
    for name in ("Accent.TButton", "Success.TButton"):
        # Keep the established names used by upload/edit dialogs.
        style.configure(
            name, background=colors["accent"], foreground=colors["on_accent"],
            bordercolor=colors["accent"], lightcolor=colors["accent"], darkcolor=colors["accent"],
            font=("Segoe UI Semibold", 10), padding=(14, 10), focuscolor=colors["on_accent"],
        )
        style.map(
            name, background=[("disabled", colors["line"]), ("pressed", colors["accent_hover"]), ("active", colors["accent_hover"])],
            foreground=[("disabled", colors["muted"]), ("!disabled", colors["on_accent"])],
            bordercolor=[("disabled", colors["line"]), ("!disabled", colors["accent"])],
        )
    style.configure("Upload.TButton", anchor="w", background=colors["accent"], foreground=colors["on_accent"],
                    bordercolor=colors["accent"], lightcolor=colors["accent"], darkcolor=colors["accent"],
                    font=("Segoe UI", 9), padding=(10, 9), focuscolor=colors["on_accent"])
    style.map("Upload.TButton", background=[("disabled", colors["line"]), ("active", colors["accent_hover"])],
              foreground=[("disabled", colors["muted"]), ("!disabled", colors["on_accent"])])
    style.configure("Danger.TButton", foreground=colors["danger"])
    style.map("Danger.TButton", background=[("disabled", colors["bg"]), ("active", colors["danger_soft"])],
              foreground=[("disabled", colors["muted"]), ("!disabled", colors["danger"])])
    style.configure("RailDanger.TButton", foreground=colors["danger"], anchor="w", font=("Segoe UI", 9), padding=(10, 9))
    style.map("RailDanger.TButton", background=[("active", colors["danger_soft"])],
              foreground=[("disabled", colors["muted"]), ("!disabled", colors["danger"])])

    style.configure("TEntry", fieldbackground=colors["surface"], foreground=colors["ink"],
                    insertcolor=colors["ink"], selectbackground=colors["soft"], selectforeground=colors["ink"], bordercolor=colors["line"],
                    lightcolor=colors["surface"], darkcolor=colors["surface"], padding=(8, 7))
    style.map("TEntry", bordercolor=[("focus", colors["accent"])],
              fieldbackground=[("disabled", colors["bg"]), ("readonly", colors["surface"])],
              foreground=[("disabled", colors["muted"]), ("readonly", colors["ink"])])
    style.configure("TCombobox", fieldbackground=colors["surface"], background=colors["surface"],
                    foreground=colors["ink"], arrowcolor=colors["muted"],
                    lightcolor=colors["surface"], darkcolor=colors["surface"],
                    bordercolor=colors["line"], padding=(7, 5), arrowsize=13)
    style.map("TCombobox", fieldbackground=[("disabled", colors["bg"]), ("readonly", colors["surface"])],
              background=[("active", colors["soft"]), ("disabled", colors["bg"])],
              foreground=[("disabled", colors["muted"]), ("readonly", colors["ink"])],
              arrowcolor=[("disabled", colors["muted"])])
    style.configure("TCheckbutton", padding=(0, 3), focuscolor=colors["accent"],
                    indicatorbackground=colors["surface"], indicatorforeground=colors["accent"],
                    indicatorcolor=colors["accent"], bordercolor=colors["line"])
    style.map("TCheckbutton", background=[("active", colors["bg"])],
              indicatorbackground=[("disabled", colors["bg"]), ("!disabled", colors["surface"])],
              foreground=[("disabled", colors["muted"])])
    style.configure("Surface.TCheckbutton", background=colors["surface"])
    style.map("Surface.TCheckbutton", background=[("active", colors["surface"])])

    style.configure("TNotebook", background=colors["surface"], borderwidth=0, tabmargins=(24, 0, 24, 8))
    style.configure("TNotebook.Tab", padding=(18, 10), background=colors["surface"],
                    borderwidth=0, foreground=colors["muted"], focuscolor=colors["accent"])
    style.map("TNotebook.Tab", background=[("selected", colors["soft"]), ("active", colors["bg"])],
              foreground=[("selected", colors["accent"]), ("active", colors["ink"])],
              padding=[("selected", (18, 10))])
    style.configure("Treeview", background=colors["surface"], fieldbackground=colors["surface"],
                    foreground=colors["ink"], bordercolor=colors["line"],
                    lightcolor=colors["line"], darkcolor=colors["line"], rowheight=28)
    style.map("Treeview", background=[("selected", colors["soft"])], foreground=[("selected", colors["ink"])])
    style.configure("Treeview.Heading", background=colors["bg"], foreground=colors["muted"],
                    bordercolor=colors["line"], lightcolor=colors["bg"], darkcolor=colors["bg"])
    style.map("Treeview.Heading", background=[("active", colors["soft"])])
    style.configure("Catalog.Treeview", background=colors["surface"], fieldbackground=colors["surface"],
                    foreground=colors["ink"], bordercolor=colors["line"], lightcolor=colors["line"],
                    darkcolor=colors["line"], borderwidth=1, relief="flat", rowheight=42, font=("Segoe UI", 10))
    style.map("Catalog.Treeview", background=[("selected", colors["soft"])], foreground=[("selected", colors["ink"])])
    style.configure("Catalog.Treeview.Heading", background=colors["bg"], foreground=colors["muted"],
                    bordercolor=colors["line"], lightcolor=colors["bg"], darkcolor=colors["bg"],
                    font=("Segoe UI Semibold", 9), padding=(10, 11), relief="flat")
    style.map("Catalog.Treeview.Heading", background=[("active", colors["soft"])])
    # Date and artist group rows need less height than inventory artwork rows.
    style.configure("Watchlist.Catalog.Treeview", rowheight=32)
    style.configure("Watchlist.Catalog.Treeview.Heading", padding=(8, 7))
    style.configure("Inventory.Treeview", background=colors["bg"], fieldbackground=colors["bg"],
                    foreground=colors["ink"], borderwidth=0, relief="flat", rowheight=54, font=("Segoe UI", 9))
    style.map("Inventory.Treeview", background=[("selected", colors["soft"])], foreground=[("selected", colors["ink"])])
    style.configure("Inventory.Treeview.Heading", background=colors["bg"], foreground=colors["muted"],
                    font=("Segoe UI", 8), padding=(8, 11), relief="flat", borderwidth=0)
    style.configure("Studio.Agenda.Treeview", background=colors["surface"], fieldbackground=colors["surface"],
                    foreground=colors["ink"], borderwidth=0, relief="flat", rowheight=50, font=("Segoe UI", 9))
    style.map("Studio.Agenda.Treeview", background=[("selected", colors["soft"])], foreground=[("selected", colors["ink"])])
    style.configure("Studio.Agenda.Treeview.Heading", background=colors["surface"], foreground=colors["muted"],
                    font=("Segoe UI", 8), padding=(8, 11), relief="flat", borderwidth=0)
    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(name, background=colors["line"], troughcolor=colors["bg"],
                        bordercolor=colors["bg"], arrowcolor=colors["muted"], arrowsize=12,
                        lightcolor=colors["line"], darkcolor=colors["line"])
        style.map(name, background=[("disabled", colors["bg"]), ("active", colors["soft"])],
                  arrowcolor=[("disabled", colors["muted"])])
    style.configure("TProgressbar", background=colors["accent"], troughcolor=colors["soft"],
                    bordercolor=colors["soft"], lightcolor=colors["accent"], darkcolor=colors["accent"])
    _rounded_elements(master, style, colors)
    if sys.platform == "win32":
        # Tk creates its native wrapper while mapping the window. Reapply when
        # restored as well, without reacting to every child widget's Map event.
        master.after_idle(lambda: _style_windows_titlebar(master))
        master.bind("<Map>", lambda event: _style_windows_titlebar(master)
                    if event.widget == master else None, add="+")
    return style


def _style_windows_titlebar(master):
    """Color the native caption, retaining Windows sizing, snapping and controls."""
    if sys.platform != "win32":
        return

    import ctypes
    from ctypes import wintypes

    try:
        # winfo_id() is Tk's client HWND, not the decorated outer window.
        # Explicit pointer-sized signatures also keep this safe on 64-bit Python.
        user32 = ctypes.WinDLL("user32")
        dwmapi = ctypes.WinDLL("dwmapi")
        get_ancestor = user32.GetAncestor
        get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
        get_ancestor.restype = wintypes.HWND
        set_attribute = dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        set_attribute.restype = ctypes.c_long
        hwnd = get_ancestor(master.winfo_id(), 2)  # GA_ROOT
        if not hwnd:
            return

        dark_mode = wintypes.BOOL(True)
        set_attribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
        # Windows 11 supports exact caption/text/border colors. Older Windows
        # versions can reject these attributes and keep their native fallback.
        for attribute, color in ((34, STUDIO_COLORS["line"]),
                                 (35, STUDIO_COLORS["surface"]),
                                 (36, STUDIO_COLORS["ink"])):
            red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
            colorref = wintypes.DWORD(red | (green << 8) | (blue << 16))
            set_attribute(hwnd, attribute, ctypes.byref(colorref), ctypes.sizeof(colorref))
    except (AttributeError, OSError, tk.TclError):
        # Cosmetic integration must never prevent the catalog from opening.
        pass


def _rounded_elements(master, style, colors):
    """Replace native bevels with the rounded, flat surfaces in the Studio concept."""
    existing = set(style.element_names())

    def element(name, normal, *states, border=10):
        if name not in existing:
            style.element_create(name, "image", normal, *states, border=border, padding=0, sticky="nsew")

    # Clam's native separator draws a bright bevel even on dark backgrounds.
    if "Studio.separator" not in existing:
        master._studio_separator_image = tk.PhotoImage(master=master, width=1, height=1)
        master._studio_separator_image.put(colors["line"], to=(0, 0, 1, 1))
        element("Studio.separator", master._studio_separator_image, border=0)
    for name in ("Horizontal.TSeparator", "Vertical.TSeparator"):
        style.layout(name, [("Studio.separator", {"sticky": "nsew"})])

    def button_layout(element_name):
        return [(element_name, {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [
                ("Button.label", {"sticky": "nsew"}),
            ]}),
        ]})]

    def button(name, fill, line, hover, foreground, background=None):
        prefix = "Studio." + name.replace(".", "_")
        background = background or colors["bg"]
        normal = rounded_image(master, fill, line, background=background)
        active = rounded_image(master, hover, line, background=background)
        focus = rounded_image(master, fill, colors["accent"], width=2, background=background)
        if fill == colors["accent"]:
            focus = rounded_image(master, fill, colors["ink"], width=2, background=background)
        disabled = rounded_image(master, colors["bg"], colors["line"], background=background)
        element(prefix, normal, ("disabled", disabled), ("focus", focus), ("pressed", active), ("active", active))
        style.layout(name, button_layout(prefix))
        style.configure(name, foreground=foreground, borderwidth=0, compound="left", space=8)

    button("TButton", colors["surface"], colors["line"], colors["soft"], colors["ink"])
    for name in ("Accent.TButton", "Success.TButton", "Upload.TButton"):
        button(name, colors["accent"], colors["accent"], colors["accent_hover"], colors["on_accent"])
    for name in ("Danger.TButton", "RailDanger.TButton"):
        button(name, colors["surface"], colors["line"], colors["danger_soft"], colors["danger"])
    button("SurfaceSecondary.TButton", colors["surface"], colors["line"], colors["soft"], colors["ink"], colors["surface"])
    button("SurfaceAccent.TButton", colors["accent"], colors["accent"], colors["accent_hover"], colors["on_accent"], colors["surface"])
    style.configure("SurfaceAccent.TButton", padding=(14, 10), font=("Segoe UI", 10))
    style.map("SurfaceAccent.TButton", foreground=[("disabled", colors["muted"]), ("!disabled", colors["on_accent"])])
    button("Quiet.TButton", colors["bg"], None, colors["soft"], colors["muted"])
    style.configure("Quiet.TButton", padding=(0, 7), font=("Segoe UI", 9))
    style.configure("Secondary.TButton", font=("Segoe UI", 10))
    element("Studio.menu_arrow", studio_icon(master, "chevron_down", colors["muted"], size=10), border=0)
    style.layout("Secondary.TMenubutton", [("Studio.SurfaceSecondary_TButton", {"sticky": "nsew", "children": [
        ("Menubutton.padding", {"sticky": "nsew", "children": [
            ("Studio.menu_arrow", {"side": "right", "sticky": ""}),
            ("Menubutton.label", {"side": "left", "sticky": "we"}),
        ]}),
    ]})])
    style.configure("Secondary.TMenubutton", background=colors["surface"], foreground=colors["muted"],
                    font=("Segoe UI", 9), padding=(10, 7), borderwidth=0, arrowsize=9)

    element("Studio.entry", rounded_image(master, colors["surface"], colors["line"]),
            ("focus", rounded_image(master, colors["surface"], colors["accent"], width=2)))
    style.layout("TEntry", [("Studio.entry", {"sticky": "nsew", "children": [
        ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]}),
    ]})])
    style.configure("TEntry", padding=(10, 10))

    for name, fill, outline in (
        ("Card.TFrame", colors["surface"], colors["line"]),
        ("Status.TFrame", colors["soft"], None),
        ("WarningStatus.TFrame", colors["warning_bg"], None),
    ):
        element_name = "Studio." + name.replace(".", "_")
        element(element_name, rounded_image(master, fill, outline, radius=10))
        style.layout(name, [(element_name, {"sticky": "nsew"})])
        style.configure(name, background=fill, borderwidth=0)
    style.configure("Status.TLabel", background=colors["soft"], foreground=colors["ink"], font=("Segoe UI", 9))
    style.configure("WarningStatus.TLabel", background=colors["warning_bg"], foreground=colors["warning"], font=("Segoe UI", 9))

    # Transparent outer margins provide the concept's space between pill tabs.
    element("Studio.tab", rounded_image(master, colors["surface"], radius=7, inset=3, background=colors["surface"]),
            ("selected", rounded_image(master, colors["soft"], radius=7, inset=3, background=colors["surface"])),
            ("active", rounded_image(master, colors["bg"], radius=7, inset=3, background=colors["surface"])), border=(12, 9, 12, 9))
    style.layout("TNotebook.Tab", [("Studio.tab", {"sticky": "nsew", "children": [
        ("Notebook.padding", {"sticky": "nsew", "children": [("Notebook.label", {"sticky": "nsew"})]}),
    ]})])
    style.configure("TNotebook", tabmargins=(21, 0, 21, 8), borderwidth=0)
    style.configure("TNotebook.Tab", padding=(19, 10), font=("Segoe UI", 10), space=8)
    style.map("TNotebook.Tab", padding=[("selected", (19, 10))])
    style.layout("TNotebook", [("Notebook.padding", {"sticky": "nsew"})])

    # Remove native heading bevels and table borders, retaining native sorting,
    # multi-selection, scrolling, and keyboard navigation.
    for name in ("Inventory.Treeview", "Studio.Agenda.Treeview"):
        fill = colors["bg"] if name == "Inventory.Treeview" else colors["surface"]
        cell_element = "Studio." + name.replace(".", "_") + "_cell"
        element(cell_element, row_separator(master, fill, colors["line"]),
                ("selected", row_separator(master, colors["soft"], colors["line"])), border=(0, 0, 0, 1))
        style.layout(name, [("Treeview.padding", {"sticky": "nsew", "children": [
            ("Treeview.treearea", {"sticky": "nsew"}),
        ]})])
        style.layout(name + ".Cell", [(cell_element, {"sticky": "nsew", "children": [
            ("Treedata.padding", {"sticky": "nsew", "children": [("Treeitem.text", {"sticky": "nsew"})]}),
        ]})])
        style.configure(name + ".Cell", padding=(5, 0))
        style.layout(name + ".Heading", [(cell_element, {"sticky": "nsew", "children": [
            ("Treeheading.padding", {"sticky": "nsew", "children": [
                ("Treeheading.image", {"side": "right", "sticky": ""}),
                ("Treeheading.text", {"sticky": "we"}),
            ]}),
        ]})])
