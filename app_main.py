"""
Entry point for the bundled .exe.

Responsibilities, in order:
  1. Parse minimal CLI flags (--version, --help, --reset-prefs, --safe-mode)
  2. Set up %LOCALAPPDATA%\\PhotoOrganizer\\
  3. Configure rotating log file + console handler
  4. Tell InsightFace to use a per-user model dir
  5. Install global crash handler
  6. Acquire single-instance lock
  7. Launch the Tkinter GUI

Run as:
    python app_main.py
    PhotoOrganizer.exe
    PhotoOrganizer.exe --version
    PhotoOrganizer.exe --reset-prefs
"""
from __future__ import annotations

import os
import sys
import argparse
import logging
import logging.handlers
import socket
import traceback


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _resource_path(*parts: str) -> str:
    """Path that resolves both in-source and inside a PyInstaller bundle."""
    if _is_frozen():
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def _setup_app_data_dir() -> str:
    appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(appdata, "PhotoOrganizer")
    os.makedirs(d, exist_ok=True)
    return d


def _setup_logging(app_data: str) -> str:
    """Rotating file handler (5 MB × 3) + stderr."""
    log_path = os.path.join(app_data, "app.log")
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Clear any handlers that might persist on re-entry
    for h in list(root.handlers):
        root.removeHandler(h)

    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter(fmt))
    root.addHandler(sh)

    # Tame noisy third-party loggers
    for noisy in ("PIL", "urllib3", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_path


def _ensure_models_dir(app_data: str) -> str:
    """Per-user InsightFace cache so the model survives app reinstalls."""
    models = os.path.join(app_data, "models")
    os.makedirs(models, exist_ok=True)
    os.environ.setdefault("INSIGHTFACE_HOME", models)
    return models


# ---------- Single-instance lock --------------------------------------------
# We bind to a loopback port; if it's already taken, another instance owns it.
# Why not a lock file? File locks are flaky after a crash; a port releases
# automatically when the holding process exits.
_INSTANCE_PORT = 47291
_instance_socket: socket.socket | None = None


def _acquire_single_instance_lock() -> bool:
    global _instance_socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", _INSTANCE_PORT))
        s.listen(1)
        _instance_socket = s
        return True
    except OSError:
        return False


def _show_already_running_dialog() -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        messagebox.showinfo(
            "Photo Organizer",
            "Photo Organizer is already running.\n\n"
            "Look for it in your taskbar or system tray.",
        )
        r.destroy()
    except Exception:
        sys.stderr.write(
            "Photo Organizer is already running.\n"
        )


# ---------- CLI -------------------------------------------------------------
def _parse_args(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="PhotoOrganizer",
        description="Photo Organizer — local, offline photo organizer.",
        add_help=True,
    )
    p.add_argument("--version", action="store_true",
                    help="Print version and exit")
    p.add_argument("--reset-prefs", action="store_true",
                    help="Erase saved preferences before launching")
    p.add_argument("--safe-mode", action="store_true",
                    help="Skip the welcome wizard and load default UI state")
    p.add_argument("--cli", action="store_true",
                    help="Drop into the command-line interface")
    return p.parse_known_args(argv)[0]


def _print_version() -> None:
    try:
        from src.version import __app_name__, __version__
    except Exception:
        from src import version as _v  # type: ignore[no-redef]
        __app_name__, __version__ = _v.__app_name__, _v.__version__
    sys.stdout.write(f"{__app_name__} {__version__}\n")


def _reset_prefs(app_data: str) -> None:
    path = os.path.join(app_data, "preferences.json")
    if os.path.isfile(path):
        try:
            os.remove(path)
            sys.stdout.write(f"Removed {path}\n")
        except OSError as e:
            sys.stderr.write(f"Could not remove {path}: {e}\n")


# ---------- Main ------------------------------------------------------------
def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    args = _parse_args(argv)

    if not _is_frozen():
        root = os.path.dirname(os.path.abspath(__file__))
        app_dir = os.path.join(root, "app")
        if os.path.isdir(app_dir):
            sys.path.insert(0, app_dir)
        sys.path.insert(0, root)

    if args.version:
        _print_version()
        return 0

    app_data = _setup_app_data_dir()
    log_path = _setup_logging(app_data)
    _ensure_models_dir(app_data)

    log = logging.getLogger("app_main")
    log.info("=" * 60)

    try:
        from src.version import __app_name__, __version__
        from src import error_handler
        error_handler.install()

        log.info(f"{__app_name__} {__version__} starting "
                  f"(frozen={_is_frozen()})")
        log.info(f"AppData: {app_data}  Log: {log_path}")

        if args.reset_prefs:
            _reset_prefs(app_data)

        # CLI mode
        if args.cli:
            from src.cli import main as cli_main
            sys.argv = ["photo-organizer"] + argv[argv.index("--cli") + 1:] \
                if "--cli" in argv else ["photo-organizer"]
            return cli_main() or 0

        # Single-instance check
        if not _acquire_single_instance_lock():
            log.warning("Another instance is already running.")
            _show_already_running_dialog()
            return 0

        # Safe mode = treat as fresh UI w/o running first-run wizard
        if args.safe_mode:
            from src.preferences import Preferences
            p = Preferences()
            p.set("first_run", False)
            p.save()

        from src.gui_app import OrganizerApp
        app = OrganizerApp()

        # App icon (if assets/app_icon.ico is bundled)
        ico = _resource_path("assets", "app_icon.ico")
        if os.path.isfile(ico):
            try:
                app.iconbitmap(ico)
            except Exception as e:
                log.debug(f"app icon: {e}")

        app.mainloop()
        return 0

    except Exception:
        log.exception("Fatal error in main()")
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw()
            messagebox.showerror(
                "Photo Organizer — Fatal error",
                "Sorry, something went wrong on startup.\n\n"
                + traceback.format_exc()[-2000:]
                + f"\n\nLog: {log_path}",
            )
            r.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
