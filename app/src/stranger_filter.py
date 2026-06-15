"""
Flag clusters likely to be background people / strangers.

Rules (configurable thresholds):
  - cluster has < min_recurrence photos → stranger
  - cluster has poor cohesion AND small size → stranger
  - cluster never co-occurs with any "main" cluster → loner

Strangers are tagged in the DB and their folders are MOVED (not deleted)
under Photos_By_Face/_strangers/ for the user to review.
"""
import os
import shutil
import logging
from typing import List

from .database import Database
from .organizer import face_folder_path
from .folder_icon import IS_WINDOWS

logger = logging.getLogger(__name__)


def detect_strangers(db: Database, min_recurrence: int = 3,
                      total_photo_threshold: int = 100) -> List[str]:
    """
    Return a list of cluster_keys that look like strangers.
    Skips small libraries (< total_photo_threshold) where everyone is "rare".
    """
    total = db.count_media()
    if total < total_photo_threshold:
        logger.info(f"[strangers] Library too small ({total} photos); "
                    "skipping stranger detection.")
        return []

    strangers = []
    for c in db.get_face_clusters():
        if c["cluster_key"].startswith("unknown_"):
            continue
        if c["manual_label"]:
            # User has labeled this person — never auto-tag as stranger
            continue
        count = c["member_count"] or 0
        flag = c["quality_flag"]
        # Rule 1: too few recurrences
        if count < min_recurrence:
            strangers.append(c["cluster_key"])
            continue
        # Rule 2: small + poor cohesion = noise cluster
        if count < (min_recurrence * 2) and flag in ("poor", "suspect"):
            strangers.append(c["cluster_key"])
    return strangers


def quarantine_strangers(db: Database, output_dir: str,
                          stranger_keys: List[str]) -> dict:
    """
    Move stranger folders into Photos_By_Face/_strangers/.
    Tag them in the DB. Returns a summary dict.
    """
    if not stranger_keys:
        return {"moved": 0, "skipped": 0}

    base = os.path.join(output_dir, "Photos_By_Face", "_strangers")
    os.makedirs(base, exist_ok=True)

    moved = 0
    skipped = 0
    for ck in stranger_keys:
        cluster = db.get_cluster(ck)
        if not cluster:
            skipped += 1
            continue
        src_folder = face_folder_path(output_dir, ck, cluster["label"])
        if not os.path.isdir(src_folder):
            skipped += 1
            continue

        # Strip READONLY before moving
        if IS_WINDOWS:
            try:
                import ctypes
                FILE_ATTRIBUTE_READONLY = 0x01
                attrs = ctypes.windll.kernel32.GetFileAttributesW(src_folder)
                if attrs != 0xFFFFFFFF:
                    ctypes.windll.kernel32.SetFileAttributesW(
                        src_folder, attrs & ~FILE_ATTRIBUTE_READONLY)
            except Exception:
                pass

        dest_folder = os.path.join(base, os.path.basename(src_folder))
        n = 1
        while os.path.exists(dest_folder):
            dest_folder = os.path.join(base, f"{os.path.basename(src_folder)}_{n}")
            n += 1
        try:
            shutil.move(src_folder, dest_folder)
            db.mark_cluster_stranger(ck, True)
            db.update_cluster_paths(ck, folder_path=dest_folder)
            moved += 1
            logger.info(f"[strangers] {ck} → {dest_folder}")
        except Exception as e:
            logger.error(f"[strangers] move failed for {ck}: {e}")
            skipped += 1

    return {"moved": moved, "skipped": skipped, "destination": base}


def restore_stranger(db: Database, output_dir: str, cluster_key: str) -> bool:
    """Move a cluster back out of _strangers/. Used when the user labels it."""
    cluster = db.get_cluster(cluster_key)
    if not cluster or not cluster["is_stranger"]:
        return False

    current = cluster["folder_path"]
    if not current or not os.path.isdir(current):
        return False

    target = face_folder_path(output_dir, cluster_key, cluster["label"])
    os.makedirs(os.path.dirname(target), exist_ok=True)

    try:
        shutil.move(current, target)
        db.mark_cluster_stranger(cluster_key, False)
        db.update_cluster_paths(cluster_key, folder_path=target)
        return True
    except Exception as e:
        logger.error(f"[strangers] restore failed: {e}")
        return False
