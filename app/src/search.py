"""
Search across the catalog.

Supports:
  - by person (cluster_key or label, partial match)
  - by date range (YYYY-MM-DD to YYYY-MM-DD)
  - by location (city/country/place_name LIKE)
  - by filename / path substring
  - combinations (AND across criteria)

All queries are read-only — they never mutate the DB.
Returns a list of media rows (sqlite3.Row).
"""
import logging
from typing import List, Optional
from datetime import datetime

from .database import Database

logger = logging.getLogger(__name__)


def search_media(
    db: Database,
    person: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    filename: Optional[str] = None,
    media_type: Optional[str] = None,
    limit: int = 500,
) -> List[dict]:
    """
    Returns list of dicts with media + (optional) cluster info.
    All filters AND-combined; pass None to skip a filter.
    """
    sql_parts = ["SELECT DISTINCT m.* FROM media m"]
    where = []
    args = []

    if person:
        sql_parts.append("LEFT JOIN face_detections fd ON fd.media_id = m.id")
        sql_parts.append("LEFT JOIN face_clusters fc ON fc.cluster_key = fd.cluster_key")
        where.append("(fd.cluster_key = ? OR fc.label LIKE ?)")
        args.extend([person, f"%{person}%"])

    if date_from:
        where.append("COALESCE(m.date_taken, m.date_file_modified) >= ?")
        args.append(date_from)
    if date_to:
        where.append("COALESCE(m.date_taken, m.date_file_modified) <= ?")
        args.append(date_to + "T23:59:59" if len(date_to) == 10 else date_to)

    if location:
        like = f"%{location}%"
        where.append("(m.location_city LIKE ? OR m.location_country LIKE ? "
                     "OR m.location_place_name LIKE ?)")
        args.extend([like, like, like])

    if filename:
        where.append("m.source_path LIKE ?")
        args.append(f"%{filename}%")

    if media_type:
        where.append("m.media_type = ?")
        args.append(media_type)

    if where:
        sql_parts.append("WHERE " + " AND ".join(where))

    sql_parts.append("ORDER BY COALESCE(m.date_taken, m.date_file_modified) DESC")
    sql_parts.append(f"LIMIT {int(limit)}")

    sql = " ".join(sql_parts)
    rows = db.conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def search_clusters(db: Database, query: str) -> List[dict]:
    """Find clusters by partial label or cluster_key match."""
    if not query:
        return [dict(r) for r in db.get_face_clusters()]
    rows = db.conn.execute(
        """SELECT * FROM face_clusters
           WHERE cluster_key LIKE ? OR label LIKE ?
           ORDER BY member_count DESC""",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    return [dict(r) for r in rows]


def stats_summary(db: Database) -> dict:
    """One-shot dashboard numbers."""
    total = db.count_media()
    images = db.conn.execute(
        "SELECT COUNT(*) FROM media WHERE media_type='image'"
    ).fetchone()[0]
    videos = db.conn.execute(
        "SELECT COUNT(*) FROM media WHERE media_type='video'"
    ).fetchone()[0]
    clusters = db.conn.execute(
        "SELECT COUNT(*) FROM face_clusters WHERE cluster_key NOT LIKE 'unknown_%'"
    ).fetchone()[0]
    labeled = db.conn.execute(
        "SELECT COUNT(*) FROM face_clusters WHERE label IS NOT NULL AND label != ''"
    ).fetchone()[0]
    strangers = db.conn.execute(
        "SELECT COUNT(*) FROM face_clusters WHERE is_stranger=1"
    ).fetchone()[0]
    duplicates = db.conn.execute(
        "SELECT COUNT(*) FROM duplicates WHERE status='exact'"
    ).fetchone()[0]
    near_dupes = db.conn.execute(
        "SELECT COUNT(*) FROM duplicates WHERE status='near'"
    ).fetchone()[0]
    geo = db.conn.execute(
        "SELECT COUNT(*) FROM media WHERE gps_latitude IS NOT NULL"
    ).fetchone()[0]

    earliest = db.conn.execute(
        "SELECT MIN(COALESCE(date_taken, date_file_modified)) FROM media"
    ).fetchone()[0]
    latest = db.conn.execute(
        "SELECT MAX(COALESCE(date_taken, date_file_modified)) FROM media"
    ).fetchone()[0]

    return {
        "total_media": total,
        "images": images,
        "videos": videos,
        "clusters": clusters,
        "labeled_people": labeled,
        "strangers": strangers,
        "exact_duplicates": duplicates,
        "near_duplicates": near_dupes,
        "geotagged": geo,
        "earliest": earliest,
        "latest": latest,
    }
