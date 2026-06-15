"""
Co-occurrence relationships between people.

For each pair of clusters that appear together in N+ photos, create a
Photos_By_Relationship/<A>_and_<B>/ folder with copies of those photos
(byte-perfect verified). Also writes a relationships.html viewer.
"""
import os
import re
import html
import logging
from typing import Dict, List, Tuple
from collections import defaultdict

from .database import Database
from .safety import safe_copy

logger = logging.getLogger(__name__)


def _clean(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00]', "_", (name or "").strip())[:60]


def compute_co_occurrences(db: Database, min_count: int = 2) -> Dict[Tuple[str, str], List[int]]:
    """
    Returns {(cluster_a, cluster_b): [media_id, ...]} for clusters that
    co-occur in min_count or more photos. Keys sorted alphabetically.
    """
    rows = db.conn.execute(
        """SELECT fd.media_id, fd.cluster_key
           FROM face_detections fd
           WHERE fd.cluster_key IS NOT NULL
             AND fd.cluster_key NOT LIKE 'unknown_%'"""
    ).fetchall()

    # media_id → set of cluster_keys
    by_media = defaultdict(set)
    for r in rows:
        by_media[r["media_id"]].add(r["cluster_key"])

    pairs = defaultdict(list)
    for media_id, clusters in by_media.items():
        if len(clusters) < 2:
            continue
        cl = sorted(clusters)
        for i in range(len(cl)):
            for j in range(i + 1, len(cl)):
                pairs[(cl[i], cl[j])].append(media_id)

    return {p: ids for p, ids in pairs.items() if len(ids) >= min_count}


def build_relationship_folders(db: Database, output_dir: str,
                                 min_count: int = 2) -> dict:
    """
    Build Photos_By_Relationship/<A>_and_<B>/ folders.
    Uses cluster labels when available, falls back to cluster_key.
    Returns {pair: count} for created folders.
    """
    pairs = compute_co_occurrences(db, min_count=min_count)
    if not pairs:
        logger.info("[relationships] No co-occurring pairs found.")
        return {}

    # Map cluster keys → display names (label or key)
    clusters = {c["cluster_key"]: c["label"] or c["cluster_key"]
                for c in db.get_face_clusters()}

    base = os.path.join(output_dir, "Photos_By_Relationship")
    os.makedirs(base, exist_ok=True)

    summary = {}
    for (a, b), media_ids in pairs.items():
        if a.startswith("unknown_") or b.startswith("unknown_"):
            continue
        name_a = _clean(clusters.get(a, a))
        name_b = _clean(clusters.get(b, b))
        # Sort names so we get a stable folder name
        n1, n2 = sorted([name_a, name_b])
        folder = os.path.join(base, f"{n1}_and_{n2}")
        os.makedirs(folder, exist_ok=True)

        # Copy photos
        copied = 0
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

        db.upsert_relationship(a, b, len(media_ids), folder_path=folder)
        summary[f"{n1} & {n2}"] = copied
        logger.info(f"[relationships] {n1} & {n2}: {copied} photos")

    _write_relationships_html(db, output_dir, base, summary)
    return summary


def _write_relationships_html(db: Database, output_dir: str,
                                base: str, summary: dict) -> None:
    """Self-contained HTML viewer of all relationships."""
    rels = db.get_relationships(min_count=2)
    rows_html = []
    for r in rels:
        a, b, count, folder = r["cluster_a"], r["cluster_b"], r["co_count"], r["folder_path"]
        rel_folder = os.path.relpath(folder, base) if folder else ""
        rows_html.append(
            f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td>"
            f"<td>{count}</td>"
            f"<td><a href='{html.escape(rel_folder)}'>{html.escape(rel_folder)}</a></td></tr>"
        )

    page = f"""<!doctype html><html><head>
<meta charset="utf-8"><title>Relationships</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#fafafa;color:#222}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{border:1px solid #ddd;padding:8px}}
 th{{background:#eee;text-align:left}}
 a{{color:#1976d2;text-decoration:none}}
</style></head><body>
<h1>Co-occurrence relationships</h1>
<p>Pairs of people who appear together in 2+ photos.</p>
<table>
<tr><th>Person A</th><th>Person B</th><th>Photos</th><th>Folder</th></tr>
{''.join(rows_html)}
</table>
</body></html>
"""
    out = os.path.join(base, "relationships.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    logger.info(f"[relationships] HTML viewer: {out}")
