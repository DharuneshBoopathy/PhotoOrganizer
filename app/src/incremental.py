"""
Incremental scan support.

The actual skip logic lives in main.py (compares path + size + mtime against DB).
This module provides:
  - Detection of file moves (same SHA-256 + same size, different path)
  - Cleanup of stale rows (paths that no longer exist on disk)
  - Cluster identity preservation across rescans
"""
import os
import logging
from typing import Dict, List, Tuple

from .database import Database

logger = logging.getLogger(__name__)


def find_moved_files(db: Database, current_paths: List[str]) -> Dict[str, str]:
    """
    Detect files that have been moved (same content, different path).
    Returns {old_path: new_path}.

    Strategy: for any current path NOT in DB, check if its SHA-256
    matches an existing DB row whose path is now missing.
    """
    from .hasher import sha256_file

    db_rows = db.conn.execute(
        "SELECT source_path, sha256, file_size FROM media"
    ).fetchall()
    by_hash = {}
    for r in db_rows:
        by_hash.setdefault(r["sha256"], []).append({
            "path": r["source_path"], "size": r["file_size"]
        })

    moved = {}
    db_paths = {r["source_path"] for r in db_rows}
    for path in current_paths:
        if path in db_paths:
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue

        # Cheap filter by size first
        candidates_by_size = [
            entry for entries in by_hash.values()
            for entry in entries if entry["size"] == size
        ]
        if not candidates_by_size:
            continue
        # Confirm by hash
        try:
            h = sha256_file(path)
        except Exception:
            continue
        for entry in by_hash.get(h, []):
            if not os.path.isfile(entry["path"]):
                moved[entry["path"]] = path
                break
    return moved


def apply_moved_paths(db: Database, moved: Dict[str, str]) -> int:
    """Update source_path in DB for moved files. Preserves cluster IDs etc."""
    if not moved:
        return 0
    n = 0
    with db.transaction() as c:
        for old, new in moved.items():
            c.execute("UPDATE media SET source_path=? WHERE source_path=?", (new, old))
            n += c.rowcount
    logger.info(f"[incremental] Updated {n} moved-file paths.")
    return n


def find_missing_files(db: Database) -> List[str]:
    """Return source paths that exist in DB but not on disk."""
    rows = db.conn.execute("SELECT source_path FROM media").fetchall()
    missing = []
    for r in rows:
        if not os.path.isfile(r["source_path"]):
            missing.append(r["source_path"])
    return missing


def report_changes(db: Database, current_paths: List[str]) -> dict:
    """Quick diff report between current scan and DB."""
    db_paths = {r["source_path"] for r in db.conn.execute(
        "SELECT source_path FROM media").fetchall()}
    current_set = set(current_paths)

    new_files = current_set - db_paths
    missing_in_disk = db_paths - current_set
    moved = find_moved_files(db, list(new_files))

    # Subtract moved-from from missing, moved-to from new
    for old, new in moved.items():
        missing_in_disk.discard(old)
        new_files.discard(new)

    return {
        "new": sorted(new_files),
        "missing": sorted(missing_in_disk),
        "moved": moved,
        "unchanged": len(db_paths) - len(missing_in_disk),
    }
