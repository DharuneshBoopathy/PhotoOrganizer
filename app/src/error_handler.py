"""
Global crash handling.

Hooks `sys.excepthook` (and `threading.excepthook`) so any uncaught
exception from anywhere in the app:
  1. lands in `app.log` with a full traceback
  2. is also written verbatim to a per-incident file
     `%LOCALAPPDATA%\\PhotoOrganizer\\crash_reports\\crash_<ts>.txt`
  3. shows the user a friendly Tk dialog with one click to open the
     report and one click to copy it.

This is opt-in via `install()`. Safe to import at any time; it does
no work until install() is called.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
import logging
import tempfile
import platform
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _crash_dir() -> str:
    appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(appdata, "PhotoOrganizer", "crash_reports")
    os.makedirs(d, exist_ok=True)
    return d


def _format_report(exc_type, exc, tb) -> str:
    try:
        from .version import __app_name__, __version__
    except Exception:
        __app_name__, __version__ = "Photo Organizer", "?"

    lines = []
    lines.append("=" * 72)
    lines.append(f"{__app_name__} crash report")
    lines.append(f"Version : {__version__}")
    lines.append(f"When    : {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Python  : {platform.python_version()} "
                  f"({'frozen' if getattr(sys, 'frozen', False) else 'source'})")
    lines.append(f"OS      : {platform.platform()}")
    lines.append("")
    lines.append("Traceback:")
    lines.append("".join(traceback.format_exception(exc_type, exc, tb)))
    return "\n".join(lines)


def write_report(exc_type, exc, tb) -> str:
    """Persist a crash report. Returns path."""
    text = _format_report(exc_type, exc, tb)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(_crash_dir(), f"crash_{ts}.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        # Last-ditch fallback: stash in temp dir
        path = os.path.join(tempfile.gettempdir(), f"pbfo_crash_{ts}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + f"\n\n[note: primary crash dir unavailable: {e}]")
        except Exception:
            pass
    return path


def show_dialog(report_path: str, summary: str) -> None:
    """Best-effort Tk error dialog. Falls back to stderr."""
    try:
        import tkinter as tk
        from tkinter import scrolledtext

        try:
            with open(report_path, "r", encoding="utf-8") as f:
                body = f.read()
        except Exception:
            body = summary

        try:
            from .version import __app_name__
        except Exception:
            __app_name__ = "Photo Organizer"

        root = tk.Tk()
        root.title(f"{__app_name__} — Unexpected error")
        try:
            root.iconbitmap(_app_icon_path())
        except Exception:
            pass
        root.geometry("680x440")

        tk.Label(
            root,
            text="Sorry — the app hit an unexpected error.",
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(16, 4))

        tk.Label(
            root,
            text=("A crash report was saved. You can copy it or open the "
                  "folder to attach it to a bug report."),
            anchor="w", justify="left", wraplength=640,
        ).pack(fill="x", padx=16)

        txt = scrolledtext.ScrolledText(root, wrap="word",
                                          font=("Consolas", 9))
        txt.pack(fill="both", expand=True, padx=16, pady=12)
        txt.insert("1.0", body)
        txt.config(state="disabled")

        btns = tk.Frame(root)
        btns.pack(fill="x", padx=16, pady=(0, 12))

        def copy_to_clipboard():
            root.clipboard_clear()
            root.clipboard_append(body)
            root.update()

        def open_folder():
            try:
                os.startfile(os.path.dirname(report_path))  # type: ignore[attr-defined]
            except Exception:
                pass

        tk.Button(btns, text="Copy report",
                   command=copy_to_clipboard).pack(side="left")
        tk.Button(btns, text="Open report folder",
                   command=open_folder).pack(side="left", padx=8)
        tk.Button(btns, text="Close", command=root.destroy).pack(side="right")

        root.mainloop()
    except Exception as e:
        # Tk itself broken (rare). Spit to stderr at minimum.
        sys.stderr.write(
            f"\n*** {summary}\n*** Crash report: {report_path}\n"
            f"*** (could not show GUI dialog: {e})\n"
        )


def _app_icon_path() -> str:
    """Resolve the app icon path for both source + frozen runs."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "app_icon.ico")


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logger.critical("Uncaught exception",
                     exc_info=(exc_type, exc, tb))
    path = write_report(exc_type, exc, tb)
    summary = f"{exc_type.__name__}: {exc}"
    show_dialog(path, summary)


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:  # py 3.8+
    if issubclass(args.exc_type, SystemExit):
        return
    _excepthook(args.exc_type, args.exc_value, args.exc_traceback)


def install() -> None:
    """Wire up sys.excepthook + threading.excepthook."""
    sys.excepthook = _excepthook
    try:
        threading.excepthook = _thread_excepthook  # type: ignore[assignment]
    except Exception:
        pass
    logger.debug("[crash] global handlers installed")
