"""About dialog — version, license, credits."""
from __future__ import annotations

import os
import sys
import webbrowser
import tkinter as tk
from tkinter import ttk

from .version import (
    __app_name__, __version__, __publisher__,
    __copyright__, __license__, __homepage__, __bug_tracker__,
)


CREDITS_TEXT = """\
Stack:
 • InsightFace + ONNX Runtime — local face detection / embedding
 • Pillow, OpenCV, scikit-image — image I/O and processing
 • imagehash — perceptual hashing
 • scikit-learn — DBSCAN clustering
 • reverse_geocoder — local GPS → place lookup
 • SQLite — portable catalog
 • Tkinter — desktop UI
 • PyInstaller, Inno Setup — packaging
"""


class AboutDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title(f"About {__app_name__}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        body = ttk.Frame(self, padding=24)
        body.pack(fill="both", expand=True)

        # Icon
        icon_label = ttk.Label(body)
        icon_label.grid(row=0, column=0, rowspan=4, padx=(0, 16), sticky="n")
        try:
            from PIL import Image, ImageTk
            ico = self._icon_path()
            if ico and os.path.isfile(ico):
                with Image.open(ico) as im:
                    im.load()
                    im = im.convert("RGBA")
                    im.thumbnail((96, 96))
                    self._icon = ImageTk.PhotoImage(im)
                    icon_label.configure(image=self._icon)
        except Exception:
            pass

        ttk.Label(body, text=__app_name__,
                  font=("Segoe UI", 16, "bold")).grid(
            row=0, column=1, sticky="w")
        ttk.Label(body, text=f"Version {__version__}").grid(
            row=1, column=1, sticky="w")
        ttk.Label(body, text=__publisher__).grid(
            row=2, column=1, sticky="w")
        ttk.Label(body, text=f"{__copyright__}\nLicensed under the {__license__} license.",
                  foreground="#666", justify="left").grid(
            row=3, column=1, sticky="w", pady=(8, 0))

        # Tagline
        ttk.Separator(body, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(
            body,
            text=("Local-first, offline AI photo organizer.\n"
                  "Your photos and faces never leave this machine."),
            justify="left", foreground="#444",
        ).grid(row=5, column=0, columnspan=2, sticky="w")

        # Credits
        ttk.Separator(body, orient="horizontal").grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=12)
        credits = tk.Text(body, height=10, width=58, wrap="word",
                          font=("Segoe UI", 9), borderwidth=0,
                          background=self.cget("background"))
        credits.insert("1.0", CREDITS_TEXT)
        credits.config(state="disabled")
        credits.grid(row=7, column=0, columnspan=2, sticky="w")

        # Links
        links = ttk.Frame(body)
        links.grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Button(links, text="Website",
                   command=lambda: webbrowser.open(__homepage__)).pack(
            side="left", padx=(0, 6))
        ttk.Button(links, text="Report a bug",
                   command=lambda: webbrowser.open(__bug_tracker__)).pack(
            side="left", padx=6)
        ttk.Button(links, text="Open log folder",
                   command=self._open_log_folder).pack(
            side="left", padx=6)

        # Close
        ttk.Button(body, text="Close", command=self.destroy).grid(
            row=9, column=0, columnspan=2, sticky="e", pady=(16, 0))

        self._center_on_parent(parent)

    @staticmethod
    def _icon_path() -> str:
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "assets", "app_icon.ico")

    @staticmethod
    def _open_log_folder():
        appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(appdata, "PhotoOrganizer")
        if os.path.isdir(d):
            try:
                os.startfile(d)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _center_on_parent(self, parent):
        self.update_idletasks()
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
            self.geometry(f"+{max(x,0)}+{max(y,0)}")
        except Exception:
            pass
