"""Shared utilities."""
import os
import uuid
import logging
import sys
from datetime import datetime


def setup_logging(log_dir: str, session_id: str, verbose: bool = False) -> str:
    """Configure logging to both console and a session log file."""
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"session_{session_id}.log")

    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes //= 1024
    return f"{size_bytes:.1f} TB"


def progress_bar_str(current: int, total: int, width: int = 30) -> str:
    if total == 0:
        return "[" + "=" * width + "] 100%"
    filled = int(width * current / total)
    bar = "=" * filled + "-" * (width - filled)
    pct = 100 * current // total
    return f"[{bar}] {pct}% ({current}/{total})"
