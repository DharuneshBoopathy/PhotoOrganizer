"""
File organization engine.
Creates the output folder structure and copies (never moves) files into it.
All write operations go through safety.safe_copy which verifies integrity.
"""
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from .safety import safe_copy
from .database import Database

logger = logging.getLogger(__name__)


def _sanitize(name: str, max_len: int = 80) -> str:
    """Strip characters unsafe for folder/file names."""
    safe = "".join(c if c.isalnum() or c in "-_. " else "_" for c in name)
    return safe.strip()[:max_len]


def date_folder_path(output_dir: str, date: Optional[datetime], media_type: str) -> str:
    """
    Build Photos_By_Date/YYYY/YYYY-MM/YYYY-MM-DD/ path.
    Falls back to Photos_By_Date/Unknown/ if date is None.
    """
    base = os.path.join(output_dir, "Photos_By_Date" if media_type == "image" else "Videos_By_Date")
    if date is None:
        return os.path.join(base, "Unknown")
    return os.path.join(base, str(date.year), date.strftime("%Y-%m"), date.strftime("%Y-%m-%d"))


def location_folder_path(output_dir: str, location_label: Optional[str]) -> Optional[str]:
    """Build Photos_By_Location/<location>/ path. Returns None if no location."""
    if not location_label:
        return None
    return os.path.join(output_dir, "Photos_By_Location", _sanitize(location_label))


def face_folder_path(output_dir: str, cluster_key: str, label: Optional[str] = None) -> str:
    """Build Photos_By_Face/<label_or_key>/ path."""
    folder_name = _sanitize(label) if label else cluster_key
    return os.path.join(output_dir, "Photos_By_Face", folder_name)


def duplicate_review_path(output_dir: str) -> str:
    return os.path.join(output_dir, "Duplicate_Review")


def _dest_filename(source_path: str, dest_dir: str) -> str:
    """Build destination path, preserving original filename."""
    return os.path.join(dest_dir, os.path.basename(source_path))


def organize_by_date(
    source_path: str,
    output_dir: str,
    date: Optional[datetime],
    media_type: str,
    session_id: str,
    db: Database,
) -> Optional[str]:
    """Copy file into date-based folder. Returns dest path or None."""
    dest_dir = date_folder_path(output_dir, date, media_type)
    dest_path = _dest_filename(source_path, dest_dir)

    success, final_path = safe_copy(source_path, dest_path, verify=True)

    if success:
        db.log_operation(session_id, "copy", source_path, final_path, "ok")
        logger.debug(f"[organizer] date copy: {source_path} → {final_path}")
        return final_path
    else:
        db.log_operation(session_id, "copy", source_path, dest_path, "error", final_path)
        logger.error(f"[organizer] date copy FAILED: {source_path} reason={final_path}")
        return None


def organize_by_location(
    source_path: str,
    output_dir: str,
    location_label: Optional[str],
    session_id: str,
    db: Database,
) -> Optional[str]:
    """Copy file into location-based folder. Returns dest path or None."""
    dest_dir = location_folder_path(output_dir, location_label)
    if dest_dir is None:
        return None

    dest_path = _dest_filename(source_path, dest_dir)
    success, final_path = safe_copy(source_path, dest_path, verify=True)

    if success:
        db.log_operation(session_id, "copy", source_path, final_path, "ok")
        return final_path
    else:
        db.log_operation(session_id, "copy", source_path, dest_path, "error", final_path)
        return None


def organize_by_face(
    source_path: str,
    output_dir: str,
    cluster_key: str,
    label: Optional[str],
    session_id: str,
    db: Database,
) -> Optional[str]:
    """Copy file into face cluster folder. Returns dest path or None."""
    dest_dir = face_folder_path(output_dir, cluster_key, label)
    dest_path = _dest_filename(source_path, dest_dir)

    success, final_path = safe_copy(source_path, dest_path, verify=True)

    if success:
        db.log_operation(session_id, "copy", source_path, final_path, "ok")
        return final_path
    else:
        db.log_operation(session_id, "copy", source_path, dest_path, "error", final_path)
        return None


def stage_duplicate_for_review(
    source_path: str,
    output_dir: str,
    dup_type: str,
    session_id: str,
    db: Database,
) -> Optional[str]:
    """
    Copy suspected duplicate into Duplicate_Review/<dup_type>/ folder.
    NEVER deletes anything. User manually reviews.
    """
    dest_dir = os.path.join(duplicate_review_path(output_dir), dup_type)
    dest_path = _dest_filename(source_path, dest_dir)

    success, final_path = safe_copy(source_path, dest_path, verify=True)

    if success:
        db.log_operation(session_id, "copy_dup_review", source_path, final_path, "ok")
        logger.info(f"[organizer] dup review: {source_path} → {final_path}")
        return final_path
    else:
        db.log_operation(session_id, "copy_dup_review", source_path, dest_path, "error", final_path)
        return None


def create_output_structure(output_dir: str):
    """Create all top-level output folders upfront."""
    folders = [
        "Photos_By_Date",
        "Videos_By_Date",
        "Photos_By_Face",
        "Photos_By_Location",
        "Duplicate_Review/exact",
        "Duplicate_Review/near",
        "Index",
        "Thumbnails",
    ]
    for folder in folders:
        os.makedirs(os.path.join(output_dir, folder), exist_ok=True)
