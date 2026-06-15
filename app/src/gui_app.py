"""
Photo Organizer — main desktop window.

Production layout:

  Menubar:    File  |  Tools  |  Help
  ───────────────────────────────────────────────────────
  Folders     [ source picker | recent ▾ ]
              [ output picker | recent ▾ ]
  Options     [ face / geo / icons / dupes / timeline / strangers / inc ]
  Actions     [ START ] [ Cancel ] [ Open output ] [ Open report ] [ Label people ]
  Progress    Stage label + determinate bar
  Activity    Color-coded log box (DEBUG/INFO/WARN/ERROR)
  Statusbar   Hint text + version

Pipeline runs on a worker thread; events flow back through a Queue.
Preferences (recent folders, toggles, threshold, model dir) are persisted
to %LOCALAPPDATA%\\PhotoOrganizer\\preferences.json.
"""
from __future__ import annotations

import os
import sys
import queue
import logging
import threading
import webbrowser

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .gui_log import QueueLogHandler, emit_progress, emit_done, emit_error
from .main import run_pipeline, PipelineCancelled
from .preferences import Preferences
from .version import __app_name__, __version__, __homepage__, __bug_tracker__

logger = logging.getLogger(__name__)

APP_TITLE = __app_name__


class OrganizerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(820, 640)

        self.prefs = Preferences()
        self._restore_geometry()

        self.event_q: queue.Queue = queue.Queue()
        self.cancel_event: threading.Event = threading.Event()
        self.worker = None
        self.is_running = False

        self._build_menubar()
        self._setup_logging()
        self._build_ui()
        self._restore_form_from_prefs()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._save_geometry_debounced)
        self._geometry_timer = None
        self.after(100, self._drain_queue)

        # First-run wizard (deferred until window has rendered)
        if self.prefs.get("first_run", True):
            self.after(200, self._show_welcome_wizard)

    # ====================== Menubar ======================
    def _build_menubar(self):
        bar = tk.Menu(self)

        m_file = tk.Menu(bar, tearoff=0)
        m_file.add_command(label="Open output folder…",
                            command=self._open_output)
        m_file.add_command(label="Open report.html",
                            command=self._open_report)
        m_file.add_separator()
        m_file.add_command(label="Settings…",
                            command=self._open_settings)
        m_file.add_separator()
        m_file.add_command(label="Exit", command=self._on_close)
        bar.add_cascade(label="File", menu=m_file)

        m_tools = tk.Menu(bar, tearoff=0)
        m_tools.add_command(label="Label people…",
                             command=self._open_labeling)
        m_tools.add_command(label="Open log file",
                             command=self._open_log_file)
        m_tools.add_command(label="Open crash reports",
                             command=self._open_crash_dir)
        bar.add_cascade(label="Tools", menu=m_tools)

        m_help = tk.Menu(bar, tearoff=0)
        m_help.add_command(label="Online documentation",
                            command=lambda: webbrowser.open(__homepage__))
        m_help.add_command(label="Report a bug",
                            command=lambda: webbrowser.open(__bug_tracker__))
        m_help.add_separator()
        m_help.add_command(label="About…", command=self._open_about)
        bar.add_cascade(label="Help", menu=m_help)

        self.config(menu=bar)

    # ====================== UI ======================
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # Header
        header = ttk.Frame(self)
        header.pack(fill="x", **pad)
        ttk.Label(header, text=APP_TITLE,
                   font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(header,
                   text="local · offline · no data leaves this machine",
                   foreground="#666").pack(side="right")

        # Folder pickers + recents
        folders = ttk.LabelFrame(self, text="Folders")
        folders.pack(fill="x", **pad)

        self.var_source = tk.StringVar()
        self.var_output = tk.StringVar()

        for row, (label, var, browse_fn, recent_key) in enumerate([
            ("Source folder:", self.var_source, self._browse_source, "recent_sources"),
            ("Output folder:", self.var_output, self._browse_output, "recent_outputs"),
        ]):
            ttk.Label(folders, text=label).grid(
                row=row, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(folders, textvariable=var).grid(
                row=row, column=1, sticky="ew", padx=4, pady=4)
            ttk.Button(folders, text="Browse…", command=browse_fn).grid(
                row=row, column=2, padx=4, pady=4)
            mb = ttk.Menubutton(folders, text="Recent ▾",
                                  direction="below", width=10)
            mb.menu = tk.Menu(mb, tearoff=0)
            mb["menu"] = mb.menu
            self._populate_recent_menu(mb.menu, recent_key, var)
            mb.grid(row=row, column=3, padx=4, pady=4)
            setattr(self, f"_recent_btn_{recent_key}", mb)
        folders.columnconfigure(1, weight=1)

        # Options
        opts = ttk.LabelFrame(self, text="Options")
        opts.pack(fill="x", **pad)

        self.var_faces = tk.BooleanVar()
        self.var_geo = tk.BooleanVar()
        self.var_icons = tk.BooleanVar()
        self.var_dupes = tk.BooleanVar()
        self.var_timeline = tk.BooleanVar()
        self.var_strangers = tk.BooleanVar()
        self.var_incremental = tk.BooleanVar()
        self.var_relationships = tk.BooleanVar()

        opt_grid = [
            ("Detect faces", self.var_faces),
            ("Geo-locate", self.var_geo),
            ("Folder icons", self.var_icons),
            ("Find duplicates", self.var_dupes),
            ("Build timelines", self.var_timeline),
            ("Quarantine strangers", self.var_strangers),
            ("Incremental rescan", self.var_incremental),
            ("Build relationships", self.var_relationships),
        ]
        for i, (txt, var) in enumerate(opt_grid):
            ttk.Checkbutton(opts, text=txt, variable=var).grid(
                row=i // 4, column=i % 4, sticky="w", padx=8, pady=4)

        # Action buttons
        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        self.btn_start = ttk.Button(actions, text="START",
                                      command=self._on_start)
        self.btn_start.pack(side="left", padx=4)
        self.btn_cancel = ttk.Button(actions, text="Cancel",
                                      command=self._on_cancel,
                                      state="disabled")
        self.btn_cancel.pack(side="left", padx=4)
        ttk.Button(actions, text="Open output",
                    command=self._open_output).pack(side="left", padx=4)
        ttk.Button(actions, text="Open report",
                    command=self._open_report).pack(side="left", padx=4)
        ttk.Button(actions, text="Label people…",
                    command=self._open_labeling).pack(side="left", padx=4)

        # Progress
        prog_frame = ttk.Frame(self)
        prog_frame.pack(fill="x", **pad)
        self.var_stage = tk.StringVar(value="Idle")
        ttk.Label(prog_frame, textvariable=self.var_stage).pack(anchor="w")
        self.progress = ttk.Progressbar(prog_frame, mode="determinate")
        self.progress.pack(fill="x", pady=4)

        # Log box
        log_frame = ttk.LabelFrame(self, text="Activity log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_widget = tk.Text(log_frame, height=14, wrap="none",
                                    bg="#1a1a1d", fg="#e0e0e0",
                                    insertbackground="#fff",
                                    font=("Consolas", 9))
        self.log_widget.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame, orient="vertical",
                                command=self.log_widget.yview)
        scroll.pack(side="right", fill="y")
        self.log_widget.config(yscrollcommand=scroll.set, state="disabled")
        self.log_widget.tag_config("INFO", foreground="#a3d4ff")
        self.log_widget.tag_config("WARNING", foreground="#ffd166")
        self.log_widget.tag_config("ERROR", foreground="#ff6b6b")
        self.log_widget.tag_config("CRITICAL", foreground="#ff6b6b",
                                    font=("Consolas", 9, "bold"))
        self.log_widget.tag_config("DEBUG", foreground="#888")

        # Status bar
        bar = ttk.Frame(self, relief="sunken", padding=(8, 2))
        bar.pack(side="bottom", fill="x")
        self.var_status = tk.StringVar(value="Ready.")
        ttk.Label(bar, textvariable=self.var_status).pack(side="left")
        ttk.Label(bar, text=f"v{__version__}",
                   foreground="#666").pack(side="right")

    # ====================== Recents ======================
    def _populate_recent_menu(self, menu: tk.Menu, prefs_key: str, var: tk.StringVar):
        menu.delete(0, "end")
        items = self.prefs.recent(prefs_key)
        if not items:
            menu.add_command(label="(none yet)", state="disabled")
            return
        for path in items:
            display = path if len(path) <= 80 else "…" + path[-80:]
            menu.add_command(label=display,
                              command=lambda p=path, v=var: v.set(p))
        menu.add_separator()
        menu.add_command(label="Clear list",
                          command=lambda k=prefs_key: self._clear_recents(k))

    def _refresh_recents(self):
        for key in ("recent_sources", "recent_outputs"):
            mb = getattr(self, f"_recent_btn_{key}", None)
            if mb is not None:
                var = self.var_source if key == "recent_sources" else self.var_output
                self._populate_recent_menu(mb.menu, key, var)

    def _clear_recents(self, prefs_key: str):
        self.prefs.clear_recent(prefs_key)
        self.prefs.save()
        self._refresh_recents()

    # ====================== Logging ======================
    def _setup_logging(self):
        root = logging.getLogger()
        level_name = self.prefs.get("log_level", "INFO")
        level = getattr(logging, level_name, logging.INFO)
        root.setLevel(level)
        handler = QueueLogHandler(self.event_q)
        handler.setLevel(level)
        # Replace any prior queue handler (hot reload safety)
        for h in list(root.handlers):
            if isinstance(h, QueueLogHandler):
                root.removeHandler(h)
        root.addHandler(handler)

    def _apply_log_level_change(self):
        level_name = self.prefs.get("log_level", "INFO")
        level = getattr(logging, level_name, logging.INFO)
        logging.getLogger().setLevel(level)
        for h in logging.getLogger().handlers:
            if isinstance(h, QueueLogHandler):
                h.setLevel(level)

    # ====================== Pickers ======================
    def _browse_source(self):
        d = filedialog.askdirectory(title="Choose source photo folder",
                                     initialdir=self.var_source.get() or "")
        if d:
            self.var_source.set(d)
            if not self.var_output.get():
                self.var_output.set(os.path.join(d, "Organized"))

    def _browse_output(self):
        d = filedialog.askdirectory(title="Choose output folder",
                                     initialdir=self.var_output.get() or "")
        if d:
            self.var_output.set(d)

    # ====================== Pipeline run ======================
    def _on_start(self):
        if self.is_running:
            return
        source = self.var_source.get().strip()
        output = self.var_output.get().strip()
        if not source or not os.path.isdir(source):
            messagebox.showerror(APP_TITLE, "Pick a valid source folder.")
            return
        if not output:
            messagebox.showerror(APP_TITLE, "Pick an output folder.")
            return
        if os.path.normpath(source).lower() == os.path.normpath(output).lower():
            messagebox.showerror(
                APP_TITLE,
                "Source and output cannot be the same folder.\n\n"
                "Pick a separate output location to keep originals safe.",
            )
            return
        os.makedirs(output, exist_ok=True)

        # Persist current selection
        self._save_form_to_prefs()
        self._refresh_recents()

        self.cancel_event = threading.Event()
        self.is_running = True
        self.btn_start.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.var_status.set("Working…")
        self._append_log("INFO", f"=== Starting pipeline on {source} ===")

        self.worker = threading.Thread(
            target=self._run_pipeline_thread,
            args=(source, output),
            daemon=True,
        )
        self.worker.start()

    def _on_cancel(self):
        if not self.is_running:
            return
        if not messagebox.askyesno(APP_TITLE,
                                    "Cancel the running operation?"):
            return
        self.cancel_event.set()
        self.var_status.set("Cancelling…")
        self.btn_cancel.config(state="disabled")

    def _run_pipeline_thread(self, source: str, output: str):
        def progress_cb(stage: str, current: int, total: int, message: str = ""):
            emit_progress(self.event_q, stage, current, total, message)

        # Apply prefs that affect the pipeline
        model_dir = self.prefs.get("model_dir", "") or None
        face_threshold = float(self.prefs.get("face_threshold", 0.4))

        try:
            summary = run_pipeline(
                source_dir=source,
                output_dir=output,
                enable_faces=self.var_faces.get(),
                enable_location=self.var_geo.get(),
                enable_icons=self.var_icons.get(),
                enable_duplicates=self.var_dupes.get(),
                enable_timeline=self.var_timeline.get(),
                enable_strangers=self.var_strangers.get(),
                incremental=self.var_incremental.get(),
                face_threshold=face_threshold,
                model_dir=model_dir,
                progress_callback=progress_cb,
                cancel_event=self.cancel_event,
            )

            # Optional: relationships
            if self.var_relationships.get() and not self.cancel_event.is_set():
                try:
                    from .database import Database
                    from .relationships import build_relationship_folders
                    progress_cb("relationships", 0, 1, "computing co-occurrences…")
                    db = Database(os.path.join(output, "manifest.db"))
                    rel = build_relationship_folders(db, output, min_count=2)
                    db.close()
                    summary = {**(summary or {}), "relationships": rel}
                except Exception as e:
                    logger.error(f"[relationships] {e}", exc_info=True)

            # Always: build root report
            try:
                from .database import Database
                from .report import build_report
                db = Database(os.path.join(output, "manifest.db"))
                build_report(db, output)
                db.close()
            except Exception as e:
                logger.error(f"[report] {e}", exc_info=True)

            emit_done(self.event_q, "ok", summary or {})
        except PipelineCancelled:
            emit_done(self.event_q, "cancelled", {})
        except Exception as e:
            logger.exception("[pipeline] fatal error")
            emit_error(self.event_q, str(e))

    # ====================== Event drain ======================
    def _drain_queue(self):
        try:
            while True:
                ev = self.event_q.get_nowait()
                self._handle_event(ev)
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)

    def _handle_event(self, ev: dict):
        t = ev.get("type")
        if t == "log":
            self._append_log(ev.get("level", "INFO"), ev.get("msg", ""))
        elif t == "progress":
            stage = ev.get("stage", "")
            cur = int(ev.get("current") or 0)
            tot = int(ev.get("total") or 0)
            msg = ev.get("message") or ""
            label = stage if not msg else f"{stage} — {msg}"
            self.var_stage.set(label)
            if tot > 0:
                self.progress.config(mode="determinate", maximum=tot, value=cur)
            else:
                self.progress.config(mode="indeterminate")
                self.progress.start(50)
        elif t == "done":
            self.is_running = False
            self.progress.stop()
            self.btn_start.config(state="normal")
            self.btn_cancel.config(state="disabled")
            status = ev.get("status", "ok")
            if status == "ok":
                self.var_stage.set("Done.")
                self.var_status.set("Pipeline finished.")
                self._append_log("INFO", "=== Pipeline finished ===")
                if self.prefs.get("open_report_when_done", True):
                    self._open_report(silent=True)
            elif status == "cancelled":
                self.var_stage.set("Cancelled.")
                self.var_status.set("Operation cancelled.")
                self._append_log("WARNING", "=== Cancelled by user ===")
            else:
                self.var_stage.set("Done with errors.")
                self.var_status.set("See log.")
        elif t == "error":
            self.is_running = False
            self.progress.stop()
            self.btn_start.config(state="normal")
            self.btn_cancel.config(state="disabled")
            self.var_stage.set("Failed.")
            self.var_status.set("Pipeline failed.")
            self._append_log("ERROR", ev.get("error", "Unknown error"))
            messagebox.showerror(APP_TITLE,
                                  f"Pipeline failed:\n\n{ev.get('error', '')}")

    def _append_log(self, level: str, msg: str):
        tag = level if level in ("INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL") else "INFO"
        self.log_widget.config(state="normal")
        self.log_widget.insert("end", msg + "\n", tag)
        self.log_widget.see("end")
        self.log_widget.config(state="disabled")

    # ====================== Form ↔ prefs ======================
    def _restore_form_from_prefs(self):
        self.var_source.set(self.prefs.get("last_source", ""))
        self.var_output.set(self.prefs.get("last_output", ""))
        self.var_faces.set(self.prefs.get("enable_faces", True))
        self.var_geo.set(self.prefs.get("enable_geo", True))
        self.var_icons.set(self.prefs.get("enable_icons", True))
        self.var_dupes.set(self.prefs.get("enable_duplicates", True))
        self.var_timeline.set(self.prefs.get("enable_timeline", False))
        self.var_strangers.set(self.prefs.get("enable_strangers", False))
        self.var_incremental.set(self.prefs.get("enable_incremental", False))
        self.var_relationships.set(self.prefs.get("enable_relationships", False))

    def _save_form_to_prefs(self):
        src = self.var_source.get().strip()
        out = self.var_output.get().strip()
        if src:
            self.prefs.set("last_source", src)
            self.prefs.push_recent("recent_sources", src)
        if out:
            self.prefs.set("last_output", out)
            self.prefs.push_recent("recent_outputs", out)
        self.prefs.update(
            enable_faces=bool(self.var_faces.get()),
            enable_geo=bool(self.var_geo.get()),
            enable_icons=bool(self.var_icons.get()),
            enable_duplicates=bool(self.var_dupes.get()),
            enable_timeline=bool(self.var_timeline.get()),
            enable_strangers=bool(self.var_strangers.get()),
            enable_incremental=bool(self.var_incremental.get()),
            enable_relationships=bool(self.var_relationships.get()),
        )
        self.prefs.save()

    # ====================== Geometry ======================
    def _restore_geometry(self):
        g = self.prefs.get("window_geometry", "")
        if g:
            try:
                self.geometry(g)
                return
            except Exception:
                pass
        self.geometry("960x720")

    def _save_geometry_debounced(self, _event=None):
        if self._geometry_timer is not None:
            try: self.after_cancel(self._geometry_timer)
            except Exception: pass
        self._geometry_timer = self.after(800, self._save_geometry)

    def _save_geometry(self):
        try:
            self.prefs.set("window_geometry", self.geometry())
            self.prefs.save()
        except Exception:
            pass

    # ====================== Window helpers ======================
    def _open_output(self):
        out = self.var_output.get().strip()
        if out and os.path.isdir(out):
            try:
                os.startfile(out)  # type: ignore[attr-defined]
            except Exception:
                webbrowser.open("file:///" + out.replace("\\", "/"))
        else:
            messagebox.showinfo(APP_TITLE, "No output folder set yet.")

    def _open_report(self, silent: bool = False):
        out = self.var_output.get().strip()
        if not out:
            if not silent:
                messagebox.showinfo(APP_TITLE, "No output folder set yet.")
            return
        report = os.path.join(out, "report.html")
        if os.path.isfile(report):
            webbrowser.open("file:///" + report.replace("\\", "/"))
        elif not silent:
            messagebox.showinfo(APP_TITLE,
                                  "Run the pipeline first to generate report.html.")

    def _open_labeling(self):
        out = self.var_output.get().strip()
        if not out or not os.path.isdir(out):
            messagebox.showerror(APP_TITLE,
                                  "Pick / create the output folder first.")
            return
        try:
            from .labeling_ui import LabelingWindow
            LabelingWindow(self, out)
        except Exception as e:
            messagebox.showerror(APP_TITLE,
                                  f"Could not open labeling window:\n{e}")

    def _open_about(self):
        try:
            from .about_dialog import AboutDialog
            AboutDialog(self)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not open About: {e}")

    def _open_settings(self):
        try:
            from .settings_window import SettingsWindow
            SettingsWindow(self, self.prefs, on_apply=self._on_settings_applied)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not open Settings: {e}")

    def _on_settings_applied(self):
        self._restore_form_from_prefs()
        self._apply_log_level_change()

    def _open_log_file(self):
        appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(appdata, "PhotoOrganizer", "app.log")
        if os.path.isfile(path):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception:
                webbrowser.open("file:///" + path.replace("\\", "/"))
        else:
            messagebox.showinfo(APP_TITLE, "No log file yet.")

    def _open_crash_dir(self):
        appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(appdata, "PhotoOrganizer", "crash_reports")
        if os.path.isdir(d):
            try:
                os.startfile(d)  # type: ignore[attr-defined]
            except Exception:
                pass
        else:
            messagebox.showinfo(APP_TITLE,
                                  "No crash reports folder yet (good news).")

    def _show_welcome_wizard(self):
        try:
            from .welcome_wizard import WelcomeWizard
            wiz = WelcomeWizard(self, self.prefs)
            self.wait_window(wiz)
            self._restore_form_from_prefs()
            self._refresh_recents()
        except Exception as e:
            logger.error(f"[wizard] failed: {e}", exc_info=True)

    # ====================== Lifecycle ======================
    def _on_close(self):
        if self.is_running:
            if not messagebox.askyesno(
                APP_TITLE,
                "A pipeline is running. Cancel and quit?"
            ):
                return
            self.cancel_event.set()
        self._save_geometry()
        self._save_form_to_prefs()
        self.destroy()


def main():
    app = OrganizerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
