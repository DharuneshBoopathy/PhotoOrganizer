"""
Burst-shot detection.

A "burst" is a sequence of photos taken within a short time window
(default: 3 seconds) that are also visually similar (near-duplicate by
perceptual hash). Cameras and phones produce these in continuous-shoot
mode — usually you only want one keeper.

We never delete; we just GROUP them and pick a recommended keeper.
The user can review keepers in Photos_By_Burst/<group>/.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

from .database import Database
from .safety import safe_copy

logger = logging.getLogger(__name__)


# Tunables
BURST_WINDOW_SEC = 3      # photos within this many seconds are candidates
PHASH_DISTANCE = 8        # max Hamming distance for "visually similar"
MIN_BURST_SIZE = 3        # need at least this many to call it a burst


def _hamming(a: str, b: str) -> int:
    """Hamming distance between two hex pHash strings."""
    if not a or not b or len(a) != len(b):
        return 999
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 999


def detect_bursts(db: Database) -> List[List[int]]:
    """
    Group media into bursts. Returns list of groups, each a list of media_ids
    sorted by capture time.
    """
    rows = db.conn.execute(
        """SELECT id, source_path, date_taken, date_file_modified,
                  perceptual_hash, file_size
           FROM media
           WHERE media_type = 'image'
           ORDER BY COALESCE(date_taken, date_file_modified)"""
    ).fetchall()

    items = []
    for r in rows:
        date_str = r["date_taken"] or r["date_file_modified"]
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str)
        except Exception:
            continue
        items.append({
            "id": r["id"],
            "path": r["source_path"],
            "dt": dt,
            "phash": r["perceptual_hash"],
            "size": r["file_size"] or 0,
        })

    items.sort(key=lambda x: x["dt"])

    bursts: List[List[dict]] = []
    current: List[dict] = []
    for it in items:
        if not current:
            current = [it]
            continue
        last = current[-1]
        gap = (it["dt"] - last["dt"]).total_seconds()
        # Same time-window AND visually similar to ANY member of current burst
        if gap <= BURST_WINDOW_SEC:
            similar = any(_hamming(it["phash"], m["phash"]) <= PHASH_DISTANCE
                          for m in current if m["phash"] and it["phash"])
            if similar or not it["phash"]:  # no phash → trust the timestamp
                current.append(it)
                continue
        # Close out current group
        if len(current) >= MIN_BURST_SIZE:
            bursts.append(current)
        current = [it]

    if len(current) >= MIN_BURST_SIZE:
        bursts.append(current)

    return [[m["id"] for m in g] for g in bursts]


def pick_keeper(db: Database, media_ids: List[int]) -> Optional[int]:
    """
    Choose the recommended keeper. Heuristic:
      1. Largest file size (proxy for sharpness/resolution)
      2. Tie-break: most face detections
      3. Tie-break: highest face quality_score average
    """
    if not media_ids:
        return None
    placeholders = ",".join("?" * len(media_ids))
    rows = db.conn.execute(
        f"""SELECT m.id, m.file_size,
                   COUNT(fd.id) AS face_count,
                   AVG(fd.quality_score) AS avg_q
            FROM media m
            LEFT JOIN face_detections fd ON fd.media_id = m.id
            WHERE m.id IN ({placeholders})
            GROUP BY m.id""",
        media_ids,
    ).fetchall()

    def score(r):
        return (r["file_size"] or 0,
                r["face_count"] or 0,
                r["avg_q"] or 0.0)

    best = max(rows, key=score)
    return best["id"]


def build_burst_folders(db: Database, output_dir: str) -> dict:
    """
    Persist detected bursts in DB and create Photos_By_Burst/<group>/
    folders. Each folder gets all members + a 'KEEPER_<filename>' marker
    pointing at the recommended one.
    """
    groups = detect_bursts(db)
    if not groups:
        logger.info("[burst] No burst groups found.")
        return {}

    base = os.path.join(output_dir, "Photos_By_Burst")
    os.makedirs(base, exist_ok=True)

    summary = {}
    for group_idx, media_ids in enumerate(groups, start=1):
        keeper = pick_keeper(db, media_ids)

        # Get capture time for folder name
        first_row = db.conn.execute(
            "SELECT date_taken, date_file_modified FROM media WHERE id=?",
            (media_ids[0],),
        ).fetchone()
        ts = first_row["date_taken"] or first_row["date_file_modified"] or ""
        try:
            dt = datetime.fromisoformat(ts)
            folder_name = f"burst_{dt.strftime('%Y-%m-%d_%H%M%S')}_{group_idx:03d}"
        except Exception:
            folder_name = f"burst_{group_idx:04d}"

        folder = os.path.join(base, folder_name)
        os.makedirs(folder, exist_ok=True)

        bg_id = db.insert_burst_group(folder_name, keeper, folder_path=folder)

        copied = 0
        keeper_basename = ""
        for mid in media_ids:
            row = db.conn.execute(
                "SELECT source_path FROM media WHERE id=?", (mid,)
            ).fetchone()
            if not row:
                continue
            src = row["source_path"]
            if not os.path.isfile(src):
                continue
            dest = os.path.join(folder, os.path.basename(src))
            ok, _ = safe_copy(src, dest, verify=True)
            if ok:
                copied += 1
                db.add_burst_member(bg_id, mid, is_keeper=(mid == keeper))
                if mid == keeper:
                    keeper_basename = os.path.basename(src)

        # Drop a tiny marker file naming the recommended keeper
        if keeper_basename:
            marker = os.path.join(folder, "_KEEPER.txt")
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(f"Recommended keeper: {keeper_basename}\n"
                            f"Group: {folder_name}\n"
                            f"Members: {len(media_ids)}\n")
            except Exception:
                pass

        summary[folder_name] = {"members": len(media_ids), "copied": copied,
                                "keeper": keeper_basename}
        logger.info(f"[burst] {folder_name}: {len(media_ids)} photos "
                    f"(keeper={keeper_basename})")

    return summary
