"""
User preferences: a small JSON file under %LOCALAPPDATA%.

Why JSON, not SQLite? Preferences are tiny, text-readable (helps
support cases where a user emails a corrupted file), and atomically
writable with `os.replace`. The catalog `manifest.db` is a separate
concern — that one's per-output-folder, this one's per-user.

Schema is forward-compatible: unknown keys are preserved on load,
missing keys default sensibly. Don't break old prefs files.
"""
from __future__ import annotations

import os
import json
import logging
import tempfile
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


DEFAULT_PREFS: Dict[str, Any] = {
    # Folders
    "last_source": "",
    "last_output": "",
    "recent_sources": [],          # most-recent first, max 10
    "recent_outputs": [],

    # Pipeline toggles (mirror GUI checkboxes)
    "enable_faces": True,
    "enable_geo": True,
    "enable_icons": True,
    "enable_duplicates": True,
    "enable_timeline": False,
    "enable_strangers": False,
    "enable_relationships": False,
    "enable_incremental": False,

    # Tunables
    "face_threshold": 0.4,
    "model_dir": "",               # empty → INSIGHTFACE_HOME default

    # UI
    "first_run": True,
    "open_report_when_done": True,
    "log_level": "INFO",
    "window_geometry": "",         # "WxH+X+Y" Tk format
    "theme": "system",             # placeholder for future themes
}

RECENT_LIMIT = 10


def _prefs_dir() -> str:
    appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(appdata, "PhotoOrganizer")
    os.makedirs(d, exist_ok=True)
    return d


def _prefs_path() -> str:
    return os.path.join(_prefs_dir(), "preferences.json")


class Preferences:
    """Thin wrapper around a JSON dict with atomic writes."""

    def __init__(self, path: str | None = None):
        self.path = path or _prefs_path()
        self._data: Dict[str, Any] = dict(DEFAULT_PREFS)
        self.load()

    # ------------- I/O -------------
    def load(self) -> None:
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                # Merge: defaults + on-disk overrides (preserve unknown keys)
                self._data = {**DEFAULT_PREFS, **loaded}
        except Exception as e:
            logger.warning(f"[prefs] could not load {self.path}: {e}; "
                            "starting with defaults")
            self._data = dict(DEFAULT_PREFS)

    def save(self) -> None:
        """Atomic write via temp file + os.replace."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="prefs_", suffix=".json",
                                         dir=os.path.dirname(self.path))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, self.path)
            finally:
                if os.path.isfile(tmp):
                    try: os.remove(tmp)
                    except OSError: pass
        except Exception as e:
            logger.error(f"[prefs] save failed: {e}")

    # ------------- Mapping API -------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULT_PREFS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, **kwargs: Any) -> None:
        self._data.update(kwargs)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._data)

    # ------------- Recent-folders helpers -------------
    def push_recent(self, key: str, path: str) -> None:
        if not path:
            return
        lst: List[str] = list(self._data.get(key) or [])
        path_norm = os.path.normpath(path)
        # Remove existing entry (case-insensitive on Windows)
        lst = [p for p in lst if os.path.normpath(p).lower() != path_norm.lower()]
        lst.insert(0, path)
        self._data[key] = lst[:RECENT_LIMIT]

    def recent(self, key: str) -> List[str]:
        return list(self._data.get(key) or [])

    def clear_recent(self, key: str) -> None:
        self._data[key] = []

    # ------------- First-run flag -------------
    def mark_first_run_complete(self) -> None:
        self._data["first_run"] = False
        self.save()
