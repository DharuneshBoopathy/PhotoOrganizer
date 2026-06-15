"""
Settings / Preferences window.

All knobs live in `Preferences` (preferences.py). This window is a
direct view into that JSON: read on open, write on Save.
"""
from __future__ import annotations

import os
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .preferences import Preferences

logger = logging.getLogger(__name__)


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent, prefs: Preferences, on_apply=None):
        super().__init__(parent)
        self.prefs = prefs
        self.on_apply = on_apply
        self.title("Settings")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        nb = ttk.Notebook(self, padding=8)
        nb.pack(fill="both", expand=True)

        nb.add(self._build_general(nb), text="General")
        nb.add(self._build_pipeline(nb), text="Pipeline")
        nb.add(self._build_advanced(nb), text="Advanced")

        # Buttons
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel",
                    command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="Save",
                    command=self._on_save).pack(side="right")
        ttk.Button(bar, text="Reset to defaults",
                    command=self._on_reset).pack(side="left")

    # ---------- Tabs ----------
    def _build_general(self, parent):
        f = ttk.Frame(parent, padding=12)
        self.var_open_report = tk.BooleanVar(
            value=self.prefs.get("open_report_when_done", True))
        ttk.Checkbutton(
            f, text="Open report.html automatically when a run finishes",
            variable=self.var_open_report).pack(anchor="w", pady=4)

        ttk.Label(f, text="Log level:").pack(anchor="w", pady=(12, 2))
        self.var_log_level = tk.StringVar(value=self.prefs.get("log_level", "INFO"))
        ttk.Combobox(f, textvariable=self.var_log_level,
                      values=("DEBUG", "INFO", "WARNING", "ERROR"),
                      state="readonly", width=12).pack(anchor="w")

        clear_frame = ttk.Frame(f)
        clear_frame.pack(anchor="w", pady=(16, 0))
        ttk.Button(clear_frame, text="Clear recent folders",
                    command=self._clear_recents).pack(side="left")
        ttk.Label(
            clear_frame,
            text=f" ({len(self.prefs.recent('recent_sources'))} sources, "
                 f"{len(self.prefs.recent('recent_outputs'))} outputs)",
            foreground="#666").pack(side="left")
        return f

    def _build_pipeline(self, parent):
        f = ttk.Frame(parent, padding=12)
        rows = [
            ("Detect faces", "enable_faces"),
            ("Geo-locate (reverse-geocode GPS)", "enable_geo"),
            ("Install Windows folder icons", "enable_icons"),
            ("Find duplicates", "enable_duplicates"),
            ("Build per-person timelines", "enable_timeline"),
            ("Quarantine stranger clusters", "enable_strangers"),
            ("Build co-occurrence relationships", "enable_relationships"),
            ("Use incremental rescan (skip already-processed)", "enable_incremental"),
        ]
        self.pipeline_vars = {}
        for label, key in rows:
            v = tk.BooleanVar(value=bool(self.prefs.get(key, False)))
            self.pipeline_vars[key] = v
            ttk.Checkbutton(f, text=label, variable=v).pack(anchor="w", pady=2)

        # Face threshold
        sub = ttk.Frame(f)
        sub.pack(anchor="w", pady=(12, 0))
        ttk.Label(sub, text="Face cluster strictness (0.30 strict, 0.50 loose):").pack(
            side="left")
        self.var_threshold = tk.DoubleVar(
            value=float(self.prefs.get("face_threshold", 0.4)))
        ttk.Spinbox(sub, from_=0.20, to=0.80, increment=0.05,
                     width=6, textvariable=self.var_threshold).pack(
            side="left", padx=8)
        return f

    def _build_advanced(self, parent):
        f = ttk.Frame(parent, padding=12)

        ttk.Label(f, text="InsightFace model directory:").pack(anchor="w")
        ttk.Label(
            f,
            text="Leave blank to use the bundled location under %LOCALAPPDATA%.",
            foreground="#666",
        ).pack(anchor="w")
        row = ttk.Frame(f); row.pack(fill="x", pady=4)
        self.var_model_dir = tk.StringVar(value=self.prefs.get("model_dir", ""))
        ttk.Entry(row, textvariable=self.var_model_dir).pack(
            side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…",
                    command=self._browse_model_dir).pack(side="left", padx=4)

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=12)

        ttk.Label(f, text="App data folder:").pack(anchor="w")
        appdata = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "PhotoOrganizer")
        ttk.Label(f, text=appdata, foreground="#666").pack(anchor="w")
        ttk.Button(f, text="Open app data folder",
                    command=lambda: self._open(appdata)).pack(anchor="w", pady=4)

        return f

    # ---------- Actions ----------
    def _browse_model_dir(self):
        d = filedialog.askdirectory(parent=self, title="InsightFace model directory")
        if d:
            self.var_model_dir.set(d)

    def _clear_recents(self):
        if messagebox.askyesno("Clear recent folders",
                                 "Forget the recent source / output folders?",
                                 parent=self):
            self.prefs.clear_recent("recent_sources")
            self.prefs.clear_recent("recent_outputs")
            self.prefs.save()
            messagebox.showinfo("Cleared", "Recent folders cleared.", parent=self)

    @staticmethod
    def _open(path):
        if os.path.isdir(path):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _on_reset(self):
        if not messagebox.askyesno(
            "Reset to defaults",
            "Reset all settings to their default values? "
            "(Recent folders are preserved.)",
            parent=self,
        ):
            return
        from .preferences import DEFAULT_PREFS
        for k, v in DEFAULT_PREFS.items():
            if k.startswith("recent_") or k == "first_run":
                continue
            self.prefs.set(k, v)
        self.prefs.save()
        messagebox.showinfo("Reset", "Defaults restored. "
                                       "Reopen Settings to see them.", parent=self)
        self.destroy()

    def _on_save(self):
        self.prefs.set("open_report_when_done", bool(self.var_open_report.get()))
        self.prefs.set("log_level", self.var_log_level.get())
        self.prefs.set("face_threshold", float(self.var_threshold.get()))
        self.prefs.set("model_dir", self.var_model_dir.get().strip())
        for key, var in self.pipeline_vars.items():
            self.prefs.set(key, bool(var.get()))
        self.prefs.save()
        if callable(self.on_apply):
            try:
                self.on_apply()
            except Exception as e:
                logger.error(f"[settings] on_apply failed: {e}")
        self.destroy()
