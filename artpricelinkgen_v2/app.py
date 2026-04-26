import math
import os
import sys
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

from artpricelinkgen_v2.artist_lookup import ArtistIdLookup
from artpricelinkgen_v2.batch import BatchProcessor
from artpricelinkgen_v2.config import *
from artpricelinkgen_v2.extraction import ImageListingExtractor
from artpricelinkgen_v2.ui_utils import blend_hex
from artpricelinkgen_v2.url_builder import ArtpriceURLBuilder
from artpricelinkgen_v2.widgets import GoldButton, HyperlinkText


class App:
    def __init__(self, master):
        self.master = master
        self.master.title(APP_TITLE)
        icon_path = Path(__file__).resolve().parent / "assets" / "app_icon.ico"
        if icon_path.exists():
            self.master.iconbitmap(str(icon_path))
        self.master.geometry("256x256")
        self.master.minsize(1120, 840)
        self.master.configure(bg=BG)

        self.lookup = ArtistIdLookup()
        self.extractor = ImageListingExtractor()
        self.last_generated_link = ""
        self.last_exported_file = None
        self.last_missing_file = None
        self.batch_input_path = ""
        self.image_input_path = ""
        self.batch_processor = BatchProcessor(self.extractor, self.lookup, self.log)
        self.daumier_img_ref = None

        self._build_fonts()
        self._build_ui()
        self._autoload_artist_ids()
        self._load_daumier_image()
        self._animate_banner(0)

    def log(self, message: str):
        stamp = time.strftime("%H:%M:%S")
        text = f"[{stamp}] {message}"
        print(text)
        sys.stdout.flush()
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _build_fonts(self):
        self.title_font = ("Baskerville", 30, "bold")
        self.section_font = ("Georgia", 15, "bold")
        self.label_font = ("Georgia", 12, "bold")
        self.body_font = ("Helvetica", 12)
        self.small_font = ("Helvetica", 10)

    def _build_ui(self):
        outer = tk.Frame(self.master, bg=BG)
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        self.banner = tk.Canvas(outer, height=24, bg=BG, highlightthickness=0)
        self.banner.pack(fill="x", pady=(0, 10))

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")

        header_left = tk.Frame(header, bg=BG)
        header_left.pack(side="left", fill="x", expand=True)

        tk.Label(header_left, text="Artprice Link Generator", bg=BG, fg=TEXT, font=self.title_font).pack(anchor="w")
        tk.Label(
            header_left,
            text="Single listing screenshot, manual entry, and batch spreadsheet Artprice link generation.",
            bg=BG,
            fg=SUBTLE,
            font=self.body_font,
        ).pack(anchor="w", pady=(4, 10))

        self.header_image_label = tk.Label(header, bg=BG)
        self.header_image_label.pack(side="right", padx=(12, 0))

        options_shell = tk.Frame(outer, bg=GOLD_SHADOW)
        options_shell.pack(fill="x", pady=(0, 14))
        options = tk.Frame(options_shell, bg=PANEL)
        options.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 3))

        tk.Label(options, text="Search Options", bg=PANEL, fg=TEXT, font=self.section_font).pack(anchor="w", padx=12, pady=(10, 0))
        opt_row = tk.Frame(options, bg=PANEL)
        opt_row.pack(fill="x", pady=(10, 0), padx=12)

        self.exact_match_var = tk.BooleanVar(value=False)
        self.all_terms_var = tk.BooleanVar(value=False)

        tk.Checkbutton(
            opt_row,
            text="Exact match",
            variable=self.exact_match_var,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            selectcolor="#fff6dc",
            font=self.body_font,
        ).pack(side="left")

        tk.Checkbutton(
            opt_row,
            text="Search all terms individually",
            variable=self.all_terms_var,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            selectcolor="#fff6dc",
            font=self.body_font,
        ).pack(side="left", padx=(18, 0))

        tk.Label(
            options,
            text="Exact match checked = plain title with exact_match 1. Search all terms individually = dashed terms with exact_match 0. Neither checked = plain title with exact_match 0.",
            bg=PANEL,
            fg=SUBTLE,
            font=self.small_font,
            wraplength=1020,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(8, 12))

        notebook_shell = tk.Frame(outer, bg=GOLD_SHADOW)
        notebook_shell.pack(fill="both", expand=True)
        notebook_frame = tk.Frame(notebook_shell, bg=PANEL)
        notebook_frame.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 3))

        style = ttk.Style(self.master)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=PANEL, borderwidth=0)
        style.configure("TNotebook.Tab", font=("Georgia", 12, "bold"), padding=(18, 10), background="#efe7d3", foreground=TEXT)
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", TEXT)])

        self.notebook = ttk.Notebook(notebook_frame)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.image_tab = tk.Frame(self.notebook, bg=PANEL)
        self.batch_tab = tk.Frame(self.notebook, bg=PANEL)
        self.manual_tab = tk.Frame(self.notebook, bg=PANEL)

        self.notebook.add(self.image_tab, text="Upload Photo of Auction Listing")
        self.notebook.add(self.batch_tab, text="Batch Spreadsheet")
        self.notebook.add(self.manual_tab, text="Search by Title / Artist Name")

        self._build_image_tab(self.image_tab)
        self._build_batch_tab(self.batch_tab)
        self._build_manual_tab(self.manual_tab)

        bottom = tk.Frame(outer, bg=BG)
        bottom.pack(fill="both", expand=False, pady=(14, 0))

        log_shell = tk.Frame(bottom, bg=GOLD_SHADOW)
        log_shell.pack(side="left", fill="both", expand=True, padx=(0, 8))
        log_panel = tk.Frame(log_shell, bg=PANEL)
        log_panel.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 3))

        tk.Label(log_panel, text="Program Log", bg=PANEL, fg=TEXT, font=self.section_font).pack(anchor="w", padx=12, pady=(10, 0))
        self.log_text = tk.Text(log_panel, height=10, bg="#fffdf9", fg=TEXT, font=("Menlo", 10), relief="flat", bd=0, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self.log_text.config(state="disabled")

        status_shell = tk.Frame(bottom, bg=GOLD_SHADOW)
        status_shell.pack(side="left", fill="both", expand=True, padx=(8, 0))
        status_panel = tk.Frame(status_shell, bg=PANEL)
        status_panel.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 3))

        tk.Label(status_panel, text="Status", bg=PANEL, fg=TEXT, font=self.section_font).pack(anchor="w", padx=12, pady=(10, 0))
        self.status_text = HyperlinkText(status_panel, height=10, bg="#fffdf9", fg=TEXT, font=self.body_font, relief="flat", bd=0, wrap="word")
        self.status_text.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self.status_text.insert("end", "Ready.\n")

    def _build_image_tab(self, parent):
        wrap = tk.Frame(parent, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(wrap, text="Upload Photo of Auction Listing", bg=PANEL, fg=TEXT, font=self.section_font).pack(anchor="w")
        tk.Label(
            wrap,
            text="Upload a screenshot/photo of the auction listing. OCR will try to read artist and title from the image.",
            bg=PANEL,
            fg=SUBTLE,
            font=self.body_font,
            wraplength=1000,
            justify="left",
        ).pack(anchor="w", pady=(6, 10))

        file_row = tk.Frame(wrap, bg=PANEL)
        file_row.pack(fill="x")
        self.image_file_var = tk.StringVar()
        tk.Entry(file_row, textvariable=self.image_file_var, font=self.body_font, relief="flat", bd=0, bg="#fffdf9", fg=TEXT).pack(side="left", fill="x", expand=True, ipady=10)
        GoldButton(file_row, "Choose Image", self.choose_image_file).pack(side="left", padx=(10, 0))

        btn_row = tk.Frame(wrap, bg=PANEL)
        btn_row.pack(fill="x", pady=(12, 0))
        GoldButton(btn_row, "Generate Link", self.generate_link_from_image).pack(side="left")
        GoldButton(btn_row, "🌐 ↗ Open Link in Browser", self.open_link).pack(side="left", padx=(10, 0))
        GoldButton(btn_row, "Copy ArtPrice URL", self.copy_link).pack(side="left", padx=(10, 0))
        GoldButton(btn_row, "Clear", self.clear_image_tab).pack(side="left", padx=(10, 0))

        data_shell = tk.Frame(wrap, bg=GOLD_SHADOW)
        data_shell.pack(fill="both", expand=True, pady=(14, 0))
        data_panel = tk.Frame(data_shell, bg=PANEL)
        data_panel.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 3))

        left = tk.Frame(data_panel, bg=PANEL)
        left.pack(side="left", fill="both", expand=True, padx=(12, 8), pady=12)
        right = tk.Frame(data_panel, bg=PANEL)
        right.pack(side="left", fill="both", expand=True, padx=(8, 12), pady=12)

        tk.Label(left, text="Extracted Data", bg=PANEL, fg=TEXT, font=self.section_font).pack(anchor="w")
        self.artist_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.artist_id_var = tk.StringVar()
        self.keyword_var = tk.StringVar()

        for label, var in [
            ("Artist", self.artist_var),
            ("Title", self.title_var),
            ("Artist ID", self.artist_id_var),
            ("Keyword", self.keyword_var),
        ]:
            row = tk.Frame(left, bg=PANEL)
            row.pack(fill="x", pady=6)
            tk.Label(row, text=label, width=12, anchor="w", bg=PANEL, fg=TEXT, font=self.label_font).pack(side="left")
            tk.Entry(row, textvariable=var, font=self.body_font, relief="flat", bd=0, bg="#fffdf9", fg=TEXT).pack(side="left", fill="x", expand=True, ipady=7)

        tk.Label(right, text="Result", bg=PANEL, fg=TEXT, font=self.section_font).pack(anchor="w")
        self.output = HyperlinkText(right, height=16, bg="#fffdf9", fg=TEXT, font=self.body_font, relief="flat", bd=0, wrap="word")
        self.output.pack(fill="both", expand=True, pady=(10, 0))

    def _build_batch_tab(self, parent):
        wrap = tk.Frame(parent, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            wrap,
            text="Choose an auction spreadsheet. Artist and Title are preferred.",
            bg=PANEL,
            fg=SUBTLE,
            font=self.body_font,
            wraplength=1040,
            justify="left",
        ).pack(anchor="w")

        row = tk.Frame(wrap, bg=PANEL)
        row.pack(fill="x", pady=(10, 10))
        self.batch_file_var = tk.StringVar()
        tk.Entry(row, textvariable=self.batch_file_var, font=self.body_font, relief="flat", bd=0, bg="#fffdf9", fg=TEXT).pack(side="left", fill="x", expand=True, ipady=10)
        GoldButton(row, "Select Auction Spreadsheet", self.choose_batch_file).pack(side="left", padx=(10, 0))

        self.generate_batch_button = GoldButton(wrap, "Generate updated spreadsheet with artprice links", self.process_batch_file)
        self.generate_batch_button.pack(anchor="w", pady=(0, 10))
        self.generate_batch_button.pack_forget()

        log_shell = tk.Frame(wrap, bg=GOLD_SHADOW)
        log_shell.pack(fill="both", expand=True)
        log_panel = tk.Frame(log_shell, bg=PANEL)
        log_panel.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 3))
        tk.Label(log_panel, text="Batch Output", bg=PANEL, fg=TEXT, font=self.section_font).pack(anchor="w", padx=12, pady=(10, 0))
        self.batch_log = tk.Text(log_panel, height=18, bg="#fffdf9", fg=TEXT, font=("Menlo", 10), relief="flat", bd=0, wrap="word")
        self.batch_log.pack(fill="both", expand=True, padx=12, pady=(8, 12))

    def _build_manual_tab(self, parent):
        wrap = tk.Frame(parent, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            wrap,
            text="Search by Title / Artist Name",
            bg=PANEL,
            fg=TEXT,
            font=self.section_font,
        ).pack(anchor="w")

        tk.Label(
            wrap,
            text="Enter artist name and artwork title manually to generate an Artprice link.",
            bg=PANEL,
            fg=SUBTLE,
            font=self.body_font,
        ).pack(anchor="w", pady=(6, 10))

        self.manual_artist_var = tk.StringVar()
        self.manual_title_var = tk.StringVar()

        row1 = tk.Frame(wrap, bg=PANEL)
        row1.pack(fill="x", pady=5)
        tk.Label(row1, text="Artist", width=12, anchor="w", bg=PANEL, fg=TEXT, font=self.label_font).pack(side="left")
        tk.Entry(row1, textvariable=self.manual_artist_var, font=self.body_font, relief="flat", bd=0, bg="#fffdf9", fg=TEXT).pack(side="left", fill="x", expand=True, ipady=8)

        row2 = tk.Frame(wrap, bg=PANEL)
        row2.pack(fill="x", pady=5)
        tk.Label(row2, text="Title", width=12, anchor="w", bg=PANEL, fg=TEXT, font=self.label_font).pack(side="left")
        tk.Entry(row2, textvariable=self.manual_title_var, font=self.body_font, relief="flat", bd=0, bg="#fffdf9", fg=TEXT).pack(side="left", fill="x", expand=True, ipady=8)

        btn_row = tk.Frame(wrap, bg=PANEL)
        btn_row.pack(fill="x", pady=(12, 0))
        GoldButton(btn_row, "Generate Link", self.generate_manual_link).pack(side="left")
        GoldButton(btn_row, "🌐 ↗ Open Link", self.open_link).pack(side="left", padx=(10, 0))
        GoldButton(btn_row, "Copy Link", self.copy_link).pack(side="left", padx=(10, 0))
        GoldButton(btn_row, "Clear", self.clear_manual_tab).pack(side="left", padx=(10, 0))

        result_shell = tk.Frame(wrap, bg=GOLD_SHADOW)
        result_shell.pack(fill="both", expand=True, pady=(16, 0))
        result_panel = tk.Frame(result_shell, bg=PANEL)
        result_panel.pack(fill="both", expand=True, padx=(0, 3), pady=(0, 3))

        tk.Label(result_panel, text="Result", bg=PANEL, fg=TEXT, font=self.section_font).pack(anchor="w", padx=12, pady=(12, 0))
        self.manual_output = HyperlinkText(
            result_panel,
            height=12,
            bg="#fffdf9",
            fg=TEXT,
            font=self.body_font,
            relief="flat",
            bd=0,
            wrap="word",
        )
        self.manual_output.pack(fill="both", expand=True, padx=12, pady=(8, 12))

    def _autoload_artist_ids(self):
        candidates = [DEFAULT_ARTIST_ID_PATH]
        base = os.path.dirname(os.path.abspath(__file__))
        candidates.extend(os.path.join(base, name) for name in FALLBACK_ARTIST_ID_FILENAMES)

        for path in candidates:
            if os.path.exists(path):
                self.lookup.load_file(path)
                self.log(f"Loaded {os.path.basename(path)} for link gen program")
                self._set_status_message(f"Loaded default artist ID file: {path}")
                return

        self.log("Default artist ID file was not found.")
        self._set_status_message("Default artist ID file was not found. Place ARTIST IDs.xlsx at the project path.")

    def _load_daumier_image(self):
        if Image is None or ImageTk is None:
            return

        img_path = None
        candidates = [DEFAULT_DAUMIER_IMAGE_PATH]
        base = os.path.dirname(os.path.abspath(__file__))
        for name in [
            "daumier_smoking_guy.png",
            "daumier_smoking_guy.jpg",
            "daumier.png",
            "daumier.jpg",
        ]:
            candidates.append(os.path.join(base, name))

        for path in candidates:
            if os.path.exists(path):
                img_path = path
                break

        if not img_path:
            return

        try:
            img = Image.open(img_path)
            img.thumbnail((240, 360))
            self.daumier_img_ref = ImageTk.PhotoImage(img)
            self.header_image_label.config(image=self.daumier_img_ref)
        except Exception as exc:
            self.log(f"Could not load Daumier image: {exc}")

    def _set_status_message(self, text, link_label=None, link_url=None):
        self.status_text.delete("1.0", "end")
        self.status_text.insert("end", text)
        if link_label and link_url:
            self.status_text.insert("end", "\n")
            self.status_text.insert_link(link_label, link_url)

    def _append_status_link(self, label, url):
        self.status_text.insert("end", "\n")
        self.status_text.insert_link(label, url)

    def _resolve_options(self):
        exact = self.exact_match_var.get()
        all_terms = self.all_terms_var.get()
        mode = ArtpriceURLBuilder.resolve_mode(exact, all_terms)
        self.log(f"Search mode resolved to: {mode}")
        return exact, all_terms

    def choose_image_file(self):
        path = filedialog.askopenfilename(
            title="Select Auction Listing Screenshot",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp")],
        )
        if not path:
            return
        self.image_input_path = path
        self.image_file_var.set(path)
        self.log(f'Listing image chosen: "{os.path.basename(path)}"')
        self._set_status_message(f"Listing image selected: {path}")

    def generate_link_from_image(self):
        if self.lookup.df is None:
            messagebox.showwarning("Missing Artist IDs", "Default artist ID file could not be loaded.")
            return

        image_path = self.image_file_var.get().strip()
        if not image_path:
            messagebox.showwarning("Missing Image", "Please choose a listing image.")
            return

        self.log(f"Image Entered: {image_path}")
        exact, all_terms = self._resolve_options()

        try:
            listing = self.extractor.extract_from_image(image_path)
            artist_id = self.lookup.lookup(listing.artist)

            self.artist_var.set(listing.artist)
            self.title_var.set(listing.title)

            keyword = ArtpriceURLBuilder.build_keyword(listing.title, exact, all_terms)

            if not artist_id:
                link = ArtpriceURLBuilder.build_url_without_artist(listing.title, exact, all_terms)
                self.artist_id_var.set("")
                self.keyword_var.set(keyword)
                self.last_generated_link = link
                self.output.delete("1.0", "end")
                self.output.insert("end", link)
                self.log(f"Missing artist ID match in single image mode: {listing.artist}")
                self.log(f"Generated fallback Artprice link without artist ID: {link}")
                self._set_status_message(
                    f"No artist ID found for: {listing.artist}. Generated fallback link without artist filter.",
                    "Open generated link in browser",
                    link,
                )
                return

            link = ArtpriceURLBuilder.build_url(artist_id, listing.title, exact, all_terms)
            self.artist_id_var.set(str(artist_id))
            self.keyword_var.set(keyword)
            self.last_generated_link = link
            self.output.delete("1.0", "end")
            self.output.insert("end", link)
            self.log(f"Single image extracted artist: {listing.artist}")
            self.log(f"Single image extracted title: {listing.title}")
            self.log(f"Generated Artprice link: {link}")
            self._set_status_message("Artprice link generated successfully.", "Open generated link in browser", link)

        except Exception as exc:
            self.log(f"Single image generation error: {exc}")
            messagebox.showerror("Error", str(exc))

    def generate_manual_link(self):
        if self.lookup.df is None:
            messagebox.showwarning("Missing Artist IDs", "Artist ID file not loaded.")
            return

        artist = self.manual_artist_var.get().strip()
        title = self.manual_title_var.get().strip()

        if not artist or not title:
            messagebox.showwarning("Missing Data", "Enter both artist and title.")
            return

        self.log(f"Manual input artist: {artist}")
        self.log(f"Manual input title: {title}")

        exact, all_terms = self._resolve_options()

        cleaned_artist = self.extractor.clean_artist_name(artist)
        cleaned_title = self.extractor.clean_title(title)

        artist_id = self.lookup.lookup(cleaned_artist)
        keyword = ArtpriceURLBuilder.build_keyword(cleaned_title, exact, all_terms)

        if not artist_id:
            link = ArtpriceURLBuilder.build_url_without_artist(cleaned_title, exact, all_terms)
            self.log(f"No artist ID found for manual entry: {cleaned_artist}")
        else:
            link = ArtpriceURLBuilder.build_url(artist_id, cleaned_title, exact, all_terms)

        self.last_generated_link = link

        self.manual_output.delete("1.0", "end")
        self.manual_output.insert("end", link)

        self._set_status_message("Manual Artprice link generated.", "Open Link", link)
        self.log(f"Manual cleaned artist: {cleaned_artist}")
        self.log(f"Manual cleaned title: {cleaned_title}")
        self.log(f"Manual keyword: {keyword}")
        self.log(f"Manual generated link: {link}")

    def choose_batch_file(self):
        path = filedialog.askopenfilename(title="Select Auction Spreadsheet", filetypes=[("Excel Workbook", "*.xlsx")])
        if not path:
            return
        self.batch_input_path = path
        self.batch_file_var.set(path)
        self.generate_batch_button.pack(anchor="w", pady=(0, 10))
        self.log(f'Auction Spreadsheet "{os.path.basename(path)}" chosen for link generations')
        self._set_status_message(f"Batch spreadsheet selected: {path}")

    def process_batch_file(self):
        if self.lookup.df is None:
            messagebox.showwarning("Missing Artist IDs", "Default artist ID file could not be loaded.")
            return

        input_path = self.batch_file_var.get().strip()
        if not input_path:
            messagebox.showwarning("Missing Spreadsheet", "Choose an XLSX file to process.")
            return

        exact, all_terms = self._resolve_options()
        self.batch_log.delete("1.0", "end")
        self.log(f"Starting batch processing for: {input_path}")

        def progress(row_num, total, status):
            line = f"Row {row_num}/{total}: {status}"
            self.batch_log.insert("end", line + "\n")
            self.batch_log.see("end")
            self.master.update_idletasks()

        try:
            output_path, missing_path, artist_col, title_col, result_df = self.batch_processor.process_workbook(
                input_path=input_path,
                exact_match=exact,
                all_terms=all_terms,
                progress_callback=progress,
            )
            self.last_exported_file = output_path
            self.last_missing_file = missing_path
            ok_count = int((result_df[STATUS_COLUMN] == "OK").sum())
            missing_count = int((result_df[STATUS_COLUMN] == UNKNOWN_ARTIST_MESSAGE).sum())
            self.log(f"Batch done. OK rows: {ok_count}. Missing artist IDs: {missing_count}.")
            if missing_path:
                self.log(f"Missing Artist Artprice IDs.xlsx exported to desktop: {missing_path}")
            self._set_status_message(
                f"Updated spreadsheet exported. Artist column: {artist_col or 'None'} | Title column: {title_col or 'None'} | OK: {ok_count} | Missing: {missing_count}",
                "Open exported spreadsheet",
                f"file://{os.path.abspath(output_path)}",
            )
            if missing_path:
                self._append_status_link("Open Missing Artist Artprice IDs.xlsx", f"file://{os.path.abspath(missing_path)}")
        except Exception as exc:
            self.log(f"Batch processing error: {exc}")
            messagebox.showerror("Batch Processing Error", str(exc))

    def open_link(self):
        if self.last_generated_link.startswith("http"):
            webbrowser.open(self.last_generated_link)
        else:
            messagebox.showinfo("Nothing to Open", "Generate a valid Artprice link first.")

    def copy_link(self):
        text = self.last_generated_link.strip()
        if not text:
            messagebox.showinfo("Nothing to Copy", "Generate a link first.")
            return
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
        self.master.update()
        self.log("Generated Artprice link copied to clipboard")
        self._set_status_message("Generated Artprice link copied to clipboard.")

    def clear_image_tab(self):
        self.image_file_var.set("")
        self.artist_var.set("")
        self.title_var.set("")
        self.artist_id_var.set("")
        self.keyword_var.set("")
        self.last_generated_link = ""
        self.output.delete("1.0", "end")
        self.log("Single image panel cleared")
        self._set_status_message("Single image panel cleared.")

    def clear_manual_tab(self):
        self.manual_artist_var.set("")
        self.manual_title_var.set("")
        self.manual_output.delete("1.0", "end")
        self.last_generated_link = ""
        self.log("Manual tab cleared")
        self._set_status_message("Manual tab cleared.")

    def _animate_banner(self, tick):
        w = max(self.banner.winfo_width(), 900)
        h = int(self.banner["height"])
        self.banner.delete("all")
        steps = 78
        pink_pass = ((tick // 28) % 3) == 2

        for i in range(steps):
            x0 = i * w / steps
            x1 = (i + 1) * w / steps + 1
            phase = (i / steps * 2 * math.pi) + tick / 8
            glow = (math.sin(phase) + 1) / 2
            base = blend_hex(GOLD_1, GOLD_4, glow)
            color = base
            if pink_pass:
                pink_mix = max(0.0, math.sin(phase + 0.8))
                if pink_mix > 0:
                    color = blend_hex(base, blend_hex(PINK_1, PINK_2, glow), min(0.28, pink_mix * 0.28))
            self.banner.create_rectangle(x0, 0, x1, h, outline="", fill=color)

        self.banner.create_line(0, h - 1, w, h - 1, fill="#d0b06a", width=1)
        self.master.after(85, lambda: self._animate_banner(tick + 1))
