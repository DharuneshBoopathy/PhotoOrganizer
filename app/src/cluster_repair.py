"""
Cluster split / merge operations.

Split: select a subset of detections from cluster X → move to new cluster Y.
Merge: collapse cluster Y into cluster X, delete Y.
After either operation:
  - Folder contents (copied photos) are reorganized
  - Avatars/icons regenerated for affected clusters
  - Cluster cohesion recomputed
"""
import os
import shutil
import logging
from typing import List, Optional, Dict

from .database import Database
from .organizer import face_folder_path
from .face_engine import bytes_to_embedding
from .identity import (
    score_all_detections_for_cluster,
    write_cluster_avatar, write_contact_sheet, write_person_summary,
    compute_cluster_cohesion,
)
from .folder_icon import install_folder_icon, refresh_association_cache, IS_WINDOWS

logger = logging.getLogger(__name__)


def merge_clusters(db: Database, output_dir: str,
                    source_key: str, target_key: str) -> dict:
    """
    Move all detections from source_key into target_key.
    Move/copy photos from source folder into target folder.
    Drop the source cluster row + its folder.
    """
    src = db.get_cluster(source_key)
    tgt = db.get_cluster(target_key)
    if not src or not tgt:
        return {"status": "error", "message": "Cluster not found"}
    if source_key == target_key:
        return {"status": "error", "message": "Cannot merge cluster into itself"}

    src_folder = face_folder_path(output_dir, source_key, src["label"])
    tgt_folder = face_folder_path(output_dir, target_key, tgt["label"])
    os.makedirs(tgt_folder, exist_ok=True)

    moved_files = 0
    if os.path.isdir(src_folder):
        _clear_readonly(src_folder)
        for fname in os.listdir(src_folder):
            if fname in ("desktop.ini", "cluster_icon.ico", "cluster_avatar.jpg",
                          "cluster_avatar_badge.png", "cluster_avatar_badge_ring.png",
                          "contact_sheet.jpg", "person_summary.json"):
                continue
            src_file = os.path.join(src_folder, fname)
            tgt_file = os.path.join(tgt_folder, fname)
            if os.path.exists(tgt_file):
                base, ext = os.path.splitext(fname)
                n = 1
                while os.path.exists(tgt_file):
                    tgt_file = os.path.join(tgt_folder, f"{base}_merged_{n}{ext}")
                    n += 1
            try:
                shutil.move(src_file, tgt_file)
                moved_files += 1
            except Exception as e:
                logger.error(f"[merge] move failed {src_file}: {e}")

    moved_dets = db.merge_clusters(source_key, target_key)

    # Try to delete source folder (now should be only metadata files left)
    if os.path.isdir(src_folder):
        try:
            for fname in os.listdir(src_folder):
                fpath = os.path.join(src_folder, fname)
                try:
                    os.remove(fpath)
                except Exception:
                    pass
            os.rmdir(src_folder)
        except Exception as e:
            logger.debug(f"[merge] could not remove {src_folder}: {e}")

    # Rebuild target's identity
    _rebuild_cluster_identity(db, output_dir, target_key)

    return {"status": "ok", "moved_detections": moved_dets,
            "moved_files": moved_files,
            "source_folder": src_folder, "target_folder": tgt_folder}


def split_cluster(db: Database, output_dir: str,
                   source_key: str, detection_ids: List[int],
                   new_label: Optional[str] = None) -> dict:
    """
    Move specified detections out of source_key into a brand-new cluster.
    Photos containing any of those detections are also copied to the new
    cluster folder (originals in source folder remain — they may still
    contain other people's faces).
    """
    if not detection_ids:
        return {"status": "error", "message": "No detections selected"}

    src = db.get_cluster(source_key)
    if not src:
        return {"status": "error", "message": f"Cluster not found: {source_key}"}

    # Allocate new cluster key
    existing = {c["cluster_key"] for c in db.get_face_clusters()}
    n = 1
    while True:
        candidate = f"person_split_{n:04d}"
        if candidate not in existing:
            new_key = candidate
            break
        n += 1

    db.split_cluster(source_key, detection_ids, new_key)
    if new_label:
        from .labeling import _sanitize_label
        db.label_cluster(new_key, _sanitize_label(new_label), manual=True)

    # Copy associated photos into the new folder
    new_folder = face_folder_path(output_dir, new_key,
                                    new_label if new_label else None)
    os.makedirs(new_folder, exist_ok=True)

    media_ids = set()
    placeholders = ",".join("?" * len(detection_ids))
    rows = db.conn.execute(
        f"""SELECT DISTINCT m.id, m.source_path FROM media m
            JOIN face_detections fd ON fd.media_id = m.id
            WHERE fd.id IN ({placeholders})""",
        detection_ids,
    ).fetchall()

    copied = 0
    for r in rows:
        src_path = r["source_path"]
        if not os.path.isfile(src_path):
            continue
        from .safety import safe_copy
        dest = os.path.join(new_folder, os.path.basename(src_path))
        ok, _ = safe_copy(src_path, dest, verify=True)
        if ok:
            copied += 1
            media_ids.add(r["id"])

    _rebuild_cluster_identity(db, output_dir, new_key)
    _rebuild_cluster_identity(db, output_dir, source_key)

    return {"status": "ok", "new_cluster": new_key, "new_folder": new_folder,
            "moved_detections": len(detection_ids), "copied_photos": copied}


def _rebuild_cluster_identity(db: Database, output_dir: str, cluster_key: str) -> None:
    """Recompute cohesion + regenerate avatar/icon/sheet/summary for one cluster."""
    cluster = db.get_cluster(cluster_key)
    if not cluster:
        return
    folder = face_folder_path(output_dir, cluster_key, cluster["label"])
    if not os.path.isdir(folder):
        return

    try:
        ranked = score_all_detections_for_cluster(db, cluster_key)
        if not ranked:
            return
        embs = [bytes_to_embedding(r["embedding"])
                for r in db.get_detections_by_cluster(cluster_key) if r["embedding"]]
        metrics = compute_cluster_cohesion(embs)
        db.update_cluster_quality(cluster_key, metrics["cohesion"], metrics["quality_flag"])

        avatar_path = write_cluster_avatar(folder, ranked, circular=True)
        write_contact_sheet(folder, ranked)
        write_person_summary(folder, cluster_key, cluster["label"],
                              cluster["member_count"], ranked, metrics, avatar_path)
        db.update_cluster_paths(cluster_key, avatar_path=avatar_path, folder_path=folder)

        badge_path = os.path.join(folder, "cluster_avatar_badge.png")
        if os.path.isfile(badge_path):
            info_tip = f"{cluster['label'] or cluster_key} — {cluster['member_count']} photos"
            install_folder_icon(folder, badge_path, info_tip=info_tip,
                                  quality_flag=metrics["quality_flag"])
        if IS_WINDOWS:
            refresh_association_cache()
    except Exception as e:
        logger.error(f"[repair] rebuild identity failed for {cluster_key}: {e}",
                      exc_info=True)


def _clear_readonly(folder: str) -> None:
    """Strip READONLY so we can mutate folder contents."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_READONLY = 0x01
        attrs = ctypes.windll.kernel32.GetFileAttributesW(folder)
        if attrs != 0xFFFFFFFF:
            ctypes.windll.kernel32.SetFileAttributesW(
                folder, attrs & ~FILE_ATTRIBUTE_READONLY)
    except Exception:
        pass
