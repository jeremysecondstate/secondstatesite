import tkinter as tk
import webbrowser

from artpricelinkgen_v2.config import GOLD_3, GOLD_4, GOLD_SHADOW, LINK_BLUE, TEXT


class HyperlinkText(tk.Text):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.config(cursor="arrow")
        self.tag_configure("link", foreground=LINK_BLUE, underline=True)
        self.links = {}

    def insert_link(self, label: str, url: str):
        start = self.index("end-1c")
        self.insert("end", label)
        end = self.index("end-1c")
        tag = f"link_{len(self.links)}"
        self.links[tag] = url
        self.tag_add("link", start, end)
        self.tag_add(tag, start, end)
        self.tag_bind(tag, "<Enter>", lambda e: self.config(cursor="hand2"))
        self.tag_bind(tag, "<Leave>", lambda e: self.config(cursor="arrow"))
        self.tag_bind(tag, "<Button-1>", lambda e, t=tag: webbrowser.open(self.links[t]))


class GoldButton(tk.Frame):
    def __init__(self, parent, text, command, width=None):
        super().__init__(parent, bg=GOLD_SHADOW, highlightthickness=0, bd=0)
        self.button = tk.Button(
            self,
            text=text,
            command=command,
            bg=GOLD_3,
            fg=TEXT,
            activebackground=GOLD_4,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=14,
            pady=10,
            font=("Georgia", 11, "bold"),
            cursor="hand2",
            width=width,
        )
        self.button.pack(padx=(0, 2), pady=(0, 2))
