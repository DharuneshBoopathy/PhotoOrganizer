"""
Face cluster labeling — assign human-readable names to person folders.

Operations:
  1. Update DB: face_clusters.label = "Alice", manual_label = 1
  2. Rename folder: Photos_By_Face/person_0001 → Photos_By_Face/Alice
  3. Update desktop.ini InfoTip
  4. Re-emit person_summary.json with new label

All file operations are READ-ONLY on source files. Renames affect only
the folder created in the output directory.
"""
import os
import re
import shutil
import logging
from typing import Optional

from .database import Database
from .organizer import face_folder_path
from .folder_icon import (
    write_desktop_ini, apply_folder_icon_attributes, refresh_folder_icon,
    IS_WINDOWS,
)

logger = logging.getLogger(__name__)


def _sanitize_label(label: str) -> str:
    """Strip characters unsafe for Windows folder names."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", label.strip())
    cleaned = cleaned.replace("\x00", "")
    cleaned = cleaned.strip(". ")
    return cleaned[:80]


def label_person(
    db: Database,
    output_dir: str,
    cluster_key: str,
    new_label: str,
    rename_folder: bool = True,
) -> dict:
    """
    Assign or update a human label for a face cluster.
    Returns {old_path, new_path, status}.
    """
    new_label = _sanitize_label(new_label)
    if not new_label:
        return {"status": "error", "message": "Empty label"}

    cluster = db.get_cluster(cluster_key)
    if not cluster:
        return {"status": "error", "message": f"Cluster not found: {cluster_key}"}

    old_label = cluster["label"]
    old_path = face_folder_path(output_dir, cluster_key, old_label)

    # Update DB
    db.label_cluster(cluster_key, new_label, manual=True)
    logger.info(f"[labeling] {cluster_key}: '{old_label}' → '{new_label}'")

    new_path = face_folder_path(output_dir, cluster_key, new_label)

    if not rename_folder or old_path == new_path:
        _refresh_desktop_ini(new_path, new_label, cluster_key, cluster["member_count"])
        return {"status": "ok", "old_path": old_path, "new_path": new_path,
                "renamed": False}

    if not os.path.isdir(old_path):
        logger.warning(f"[labeling] Old folder missing: {old_path}")
        return {"status": "ok", "old_path": old_path, "new_path": new_path,
                "renamed": False}

    # Folder rename: clear READONLY first (Windows wouldn't allow rename otherwise)
    if IS_WINDOWS:
        try:
            import ctypes
            FILE_ATTRIBUTE_READONLY = 0x01
            attrs = ctypes.windll.kernel32.GetFileAttributesW(old_path)
            if attrs != 0xFFFFFFFF:
                ctypes.windll.kernel32.SetFileAttributesW(
                    old_path, attrs & ~FILE_ATTRIBUTE_READONLY)
        except Exception as e:
            logger.debug(f"[labeling] Could not clear READONLY: {e}")

    # If destination exists, try a numbered variant
    final_new = new_path
    n = 1
    while os.path.isdir(final_new) and final_new != old_path:
        final_new = f"{new_path}_{n}"
        n += 1

    try:
        shutil.move(old_path, final_new)
    except Exception as e:
        logger.error(f"[labeling] Rename failed {old_path} → {final_new}: {e}")
        # Restore READONLY on the old folder if it still exists
        return {"status": "error", "message": str(e)}

    db.update_cluster_paths(cluster_key, folder_path=final_new)
    _refresh_desktop_ini(final_new, new_label, cluster_key, cluster["member_count"])

    return {"status": "ok", "old_path": old_path, "new_path": final_new,
            "renamed": True}


def _refresh_desktop_ini(folder: str, label: str, cluster_key: str,
                          member_count: int) -> None:
    """Re-write desktop.ini with the updated InfoTip."""
    if not os.path.isdir(folder):
        return
    info_tip = f"{label} ({cluster_key}) — {member_count} photos"
    ini_path = write_desktop_ini(folder, "cluster_icon.ico", info_tip=info_tip)
    if ini_path:
        apply_folder_icon_attributes(folder, ini_path)
        refresh_folder_icon(folder)


def list_clusters_for_labeling(db: Database) -> list:
    """Return clusters in label-friendly form, sorted by member count desc."""
    rows = db.get_face_clusters()
    out = []
    for r in rows:
        out.append({
            "cluster_key": r["cluster_key"],
            "label": r["label"],
            "member_count": r["member_count"],
            "cohesion": r["cohesion"],
            "quality_flag": r["quality_flag"],
            "avatar_path": r["avatar_path"],
            "folder_path": r["folder_path"],
            "is_stranger": bool(r["is_stranger"] or 0),
            "manual_label": bool(r["manual_label"] or 0),
        })
    return out
