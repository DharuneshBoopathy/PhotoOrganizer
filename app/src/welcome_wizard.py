"""
First-run welcome wizard.

A 3-step modal:
  1. Welcome / privacy promise (offline, no telemetry)
  2. Pick where you want photos organized
  3. Set the default behavior toggles

When complete, prefs.first_run is set to False and the main window
opens with the chosen defaults.

Skippable: the user can hit "Skip" at any step. Defaults are sane.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog

from .preferences import Preferences
from .version import __app_name__, __version__


class WelcomeWizard(tk.Toplevel):
    def __init__(self, parent, prefs: Preferences):
        super().__init__(parent)
        self.prefs = prefs
        self.title(f"Welcome to {__app_name__}")
        self.geometry("640x440")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.completed = False

        # State
        self.var_source = tk.StringVar(value=prefs.get("last_source", ""))
        self.var_output = tk.StringVar(value=prefs.get("last_output", ""))
        self.var_faces = tk.BooleanVar(value=prefs.get("enable_faces", True))
        self.var_geo = tk.BooleanVar(value=prefs.get("enable_geo", True))
        self.var_dupes = tk.BooleanVar(value=prefs.get("enable_duplicates", True))
        self.var_icons = tk.BooleanVar(value=prefs.get("enable_icons", True))

        # Container
        self.container = ttk.Frame(self, padding=24)
        self.container.pack(fill="both", expand=True)

        # Bottom bar
        bottom = ttk.Frame(self, padding=(16, 0, 16, 16))
        bottom.pack(fill="x")
        self.btn_skip = ttk.Button(bottom, text="Skip", command=self._on_skip)
        self.btn_skip.pack(side="left")
        self.btn_back = ttk.Button(bottom, text="< Back",
                                     command=self._on_back, state="disabled")
        self.btn_back.pack(side="right", padx=(6, 0))
        self.btn_next = ttk.Button(bottom, text="Next >",
                                     command=self._on_next)
        self.btn_next.pack(side="right")

        # Pages
        self.pages = [self._page_welcome,
                      self._page_folders,
                      self._page_options,
                      self._page_done]
        self.idx = 0
        self._render()

    # ----------------------------- Pages -----------------------------
    def _render(self):
        for w in self.container.winfo_children():
            w.destroy()
        self.pages[self.idx]()

        self.btn_back.config(state=("normal" if self.idx > 0 else "disabled"))
        if self.idx == len(self.pages) - 1:
            self.btn_next.config(text="Finish")
            self.btn_skip.config(state="disabled")
        else:
            self.btn_next.config(text="Next >")
            self.btn_skip.config(state="normal")

    def _page_welcome(self):
        ttk.Label(
            self.container,
            text=f"Welcome to {__app_name__}",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            self.container,
            text=f"Version {__version__}",
            foreground="#666",
        ).pack(anchor="w", pady=(0, 16))

        msg = (
            "This app organizes your photo and video library by date, location, "
            "and faces — entirely on this computer.\n\n"
            "What it does:\n"
            "  • Sorts originals into Photos_By_Date / By_Location / By_Face folders\n"
            "  • Detects duplicates (exact + visually similar)\n"
            "  • Groups photos of the same person together\n"
            "  • Generates a top-level report you can browse offline\n\n"
            "What it does NOT do:\n"
            "  • Upload anything to the cloud\n"
            "  • Phone home, send analytics, or call any external service\n"
            "  • Modify, move, or delete your original files\n\n"
            "Your photos stay private. Always."
        )
        tk.Label(self.container, text=msg, justify="left",
                  wraplength=560, anchor="w").pack(anchor="w")

    def _page_folders(self):
        ttk.Label(self.container, text="Pick your folders",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(self.container,
                   text="You can change these later. The output folder is "
                        "where the organized copies will live.",
                   foreground="#666").pack(anchor="w", pady=(0, 12))

        ttk.Label(self.container, text="Source (your photo library):").pack(anchor="w")
        row = ttk.Frame(self.container); row.pack(fill="x", pady=4)
        ttk.Entry(row, textvariable=self.var_source).pack(side="left", fill="x",
                                                            expand=True)
        ttk.Button(row, text="Browse…",
                    command=self._pick_source).pack(side="left", padx=4)

        ttk.Label(self.container, text="Output (organized copy):").pack(
            anchor="w", pady=(12, 0))
        row = ttk.Frame(self.container); row.pack(fill="x", pady=4)
        ttk.Entry(row, textvariable=self.var_output).pack(side="left", fill="x",
                                                            expand=True)
        ttk.Button(row, text="Browse…",
                    command=self._pick_output).pack(side="left", padx=4)

        ttk.Label(
            self.container,
            text=("Tip: pick a different drive for the output if you have one "
                  "— it's safer and faster."),
            foreground="#666",
        ).pack(anchor="w", pady=(12, 0))

    def _page_options(self):
        ttk.Label(self.container, text="What should we do by default?",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            self.container,
            text="You can change these any time from Settings.",
            foreground="#666",
        ).pack(anchor="w", pady=(0, 12))

        rows = [
            ("Detect faces and group people",
                self.var_faces,
                "Slowest step. Uses InsightFace locally."),
            ("Build location folders from GPS",
                self.var_geo,
                "Reverse-geocode lookup uses a bundled offline dataset."),
            ("Find exact + near-duplicate photos",
                self.var_dupes,
                "Duplicates go to a review folder — never deleted automatically."),
            ("Set Windows folder icons for each person",
                self.var_icons,
                "Each person gets a folder icon showing their best face."),
        ]
        for label, var, hint in rows:
            ttk.Checkbutton(self.container, text=label, variable=var).pack(
                anchor="w", pady=(8, 0))
            ttk.Label(self.container, text=hint, foreground="#666").pack(
                anchor="w", padx=(24, 0))

    def _page_done(self):
        ttk.Label(self.container, text="You're all set",
                  font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            self.container,
            text=("Click Finish to open the main window. "
                  "The first run will download the InsightFace model "
                  "(~280 MB) the first time you organize photos with "
                  "face detection enabled."),
            wraplength=560, justify="left",
        ).pack(anchor="w", pady=(12, 0))
        ttk.Label(
            self.container,
            text=("Need help? Open Help → About inside the app for a "
                  "link to documentation and the bug tracker."),
            wraplength=560, foreground="#666", justify="left",
        ).pack(anchor="w", pady=(12, 0))

    # ----------------------------- Pickers -----------------------------
    def _pick_source(self):
        d = filedialog.askdirectory(parent=self, title="Choose your photo source folder")
        if d:
            self.var_source.set(d)
            if not self.var_output.get():
                self.var_output.set(os.path.join(d, "Organized"))

    def _pick_output(self):
        d = filedialog.askdirectory(parent=self, title="Choose the output folder")
        if d:
            self.var_output.set(d)

    # ----------------------------- Nav -----------------------------
    def _on_back(self):
        if self.idx > 0:
            self.idx -= 1
            self._render()

    def _on_next(self):
        if self.idx < len(self.pages) - 1:
            self.idx += 1
            self._render()
        else:
            self._save_and_close(completed=True)

    def _on_skip(self):
        self._save_and_close(completed=False)

    def _save_and_close(self, completed: bool):
        # Save folders + toggles even if skipped, so partial progress is kept
        if self.var_source.get():
            self.prefs.set("last_source", self.var_source.get())
            self.prefs.push_recent("recent_sources", self.var_source.get())
        if self.var_output.get():
            self.prefs.set("last_output", self.var_output.get())
            self.prefs.push_recent("recent_outputs", self.var_output.get())
        self.prefs.update(
            enable_faces=bool(self.var_faces.get()),
            enable_geo=bool(self.var_geo.get()),
            enable_duplicates=bool(self.var_dupes.get()),
            enable_icons=bool(self.var_icons.get()),
        )
        self.prefs.mark_first_run_complete()
        self.completed = completed
        self.destroy()
