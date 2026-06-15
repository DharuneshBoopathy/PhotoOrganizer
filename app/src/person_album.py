"""
Per-person album generation.

For a single cluster, build a self-contained HTML "album" with:
  - Hero header (avatar + name + photo count + date range)
  - Tabs: All / Best / Solo / With <other person>
  - Date-grouped grids
  - Click-to-open native files

The album lives at Photos_By_Face/<person>/album.html and references
images by relative paths into the same folder, so the album works
even when the user copies the folder to another machine.
"""
import os
import html
import logging
from datetime import datetime
from typing import List, Dict, Optional
from collections import defaultdict

from .database import Database
from .organizer import face_folder_path

logger = logging.getLogger(__name__)


def build_album_for_cluster(db: Database, output_dir: str,
                              cluster_key: str) -> Optional[str]:
    """Generate album.html for one person."""
    cluster = db.get_cluster(cluster_key)
    if not cluster:
        return None
    folder = face_folder_path(output_dir, cluster_key, cluster["label"])
    if not os.path.isdir(folder):
        return None

    media_rows = db.media_with_cluster(cluster_key)
    if not media_rows:
        return None

    label = cluster["label"] or cluster_key

    # For each photo, what other clusters appear in it?
    media_ids = [r["id"] for r in media_rows]
    co_clusters = _co_clusters_for_media(db, media_ids, exclude=cluster_key)

    # Map cluster_key → display name
    other_names = {c["cluster_key"]: c["label"] or c["cluster_key"]
                   for c in db.get_face_clusters()
                   if c["cluster_key"] != cluster_key}

    # Sections
    by_date = defaultdict(list)
    solo = []
    with_others = defaultdict(list)
    best = []
    for r in media_rows:
        date_str = r["date_taken"] or r["date_file_modified"] or ""
        try:
            dt = datetime.fromisoformat(date_str)
            date_key = dt.strftime("%Y-%m")
        except Exception:
            dt = None
            date_key = "Unknown"
        rel_src = _relpath(r["source_path"], folder)
        thumb = r["thumbnail_path"]
        rel_thumb = _relpath(thumb, folder) if thumb else rel_src
        item = {
            "src": rel_src,
            "thumb": rel_thumb,
            "date": date_key,
            "dt": dt,
            "id": r["id"],
        }
        by_date[date_key].append(item)
        co = co_clusters.get(r["id"], set())
        if not co:
            solo.append(item)
        else:
            for ck in co:
                with_others[ck].append(item)

    # Best = top by face quality
    best_rows = db.conn.execute(
        """SELECT m.id, m.source_path, m.thumbnail_path,
                  fd.quality_score, m.date_taken, m.date_file_modified
           FROM face_detections fd
           JOIN media m ON m.id = fd.media_id
           WHERE fd.cluster_key = ?
           ORDER BY fd.quality_score DESC NULLS LAST
           LIMIT 24""",
        (cluster_key,),
    ).fetchall()
    for r in best_rows:
        thumb = r["thumbnail_path"]
        rel_src = _relpath(r["source_path"], folder)
        rel_thumb = _relpath(thumb, folder) if thumb else rel_src
        best.append({"src": rel_src, "thumb": rel_thumb})

    # Build HTML
    avatar_path = os.path.join(folder, "cluster_avatar.jpg")
    avatar_rel = "cluster_avatar.jpg" if os.path.isfile(avatar_path) else ""

    dates_with_data = [v[0]["dt"] for v in by_date.values() if v and v[0]["dt"]]
    if dates_with_data:
        dates_with_data.sort()
        date_range = f"{dates_with_data[0].year}–{dates_with_data[-1].year}"
    else:
        date_range = ""

    page = _render_album_html(
        label=label,
        cluster_key=cluster_key,
        photo_count=len(media_rows),
        date_range=date_range,
        avatar_rel=avatar_rel,
        by_date=by_date,
        solo=solo,
        with_others=with_others,
        other_names=other_names,
        best=best,
    )

    out_path = os.path.join(folder, "album.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


def build_albums_all(db: Database, output_dir: str) -> dict:
    """Build album.html for every cluster."""
    summary = {}
    for c in db.get_face_clusters():
        if c["cluster_key"].startswith("unknown_"):
            continue
        out = build_album_for_cluster(db, output_dir, c["cluster_key"])
        if out:
            summary[c["cluster_key"]] = out
    return summary


def _co_clusters_for_media(db: Database, media_ids: List[int],
                             exclude: str) -> Dict[int, set]:
    """For each media_id, return the set of other cluster_keys present."""
    if not media_ids:
        return {}
    placeholders = ",".join("?" * len(media_ids))
    rows = db.conn.execute(
        f"""SELECT media_id, cluster_key FROM face_detections
            WHERE media_id IN ({placeholders})
              AND cluster_key IS NOT NULL
              AND cluster_key NOT LIKE 'unknown_%'""",
        media_ids,
    ).fetchall()
    out = defaultdict(set)
    for r in rows:
        if r["cluster_key"] != exclude:
            out[r["media_id"]].add(r["cluster_key"])
    return out


def _relpath(target: Optional[str], base: str) -> str:
    if not target:
        return ""
    try:
        return os.path.relpath(target, base).replace("\\", "/")
    except Exception:
        return target.replace("\\", "/")


def _render_album_html(label, cluster_key, photo_count, date_range,
                        avatar_rel, by_date, solo, with_others,
                        other_names, best) -> str:
    safe_label = html.escape(label)

    def cell(item):
        src = html.escape(item["src"])
        thumb = html.escape(item["thumb"])
        return f'<a href="{src}" target="_blank"><img src="{thumb}" loading="lazy" alt=""></a>'

    # All-photos section, grouped by month
    all_html_parts = []
    for k in sorted(by_date.keys()):
        cells = "".join(cell(i) for i in by_date[k])
        all_html_parts.append(f"<h3>{html.escape(k)}</h3><div class='grid'>{cells}</div>")
    all_html = "".join(all_html_parts) or "<p>No photos.</p>"

    best_html = "<div class='grid'>" + "".join(cell(i) for i in best) + "</div>" \
        if best else "<p>No best picks yet.</p>"

    solo_html = "<div class='grid'>" + "".join(cell(i) for i in solo) + "</div>" \
        if solo else "<p>No solo photos.</p>"

    # With-others sections (one tab per relationship, top 5 only to avoid bloat)
    rel_pairs = sorted(with_others.items(), key=lambda kv: -len(kv[1]))[:5]
    rel_tabs_btns = []
    rel_tabs_panes = []
    for ck, items in rel_pairs:
        name = html.escape(other_names.get(ck, ck))
        tab_id = f"with_{html.escape(ck)}"
        rel_tabs_btns.append(
            f'<button class="tabbtn" data-tab="{tab_id}">With {name} ({len(items)})</button>'
        )
        cells = "".join(cell(i) for i in items)
        rel_tabs_panes.append(
            f'<div class="pane" id="{tab_id}"><div class="grid">{cells}</div></div>'
        )

    avatar_img = f'<img class="avatar" src="{html.escape(avatar_rel)}" alt="">' \
        if avatar_rel else ""

    return f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>{safe_label} — Album</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#0e0e10;color:#eee}}
 header{{display:flex;align-items:center;gap:24px;padding:32px;background:#1a1a1d;
        border-bottom:1px solid #2a2a2e}}
 .avatar{{width:128px;height:128px;border-radius:50%;object-fit:cover;
         box-shadow:0 4px 16px rgba(0,0,0,.5)}}
 h1{{margin:0;font-size:32px}}
 .meta{{color:#aaa;margin-top:6px}}
 nav{{position:sticky;top:0;background:#0e0e10;border-bottom:1px solid #2a2a2e;
      padding:8px 32px;display:flex;gap:8px;flex-wrap:wrap;z-index:10}}
 .tabbtn{{background:#1f1f23;border:1px solid #2a2a2e;color:#eee;
         padding:8px 16px;border-radius:6px;cursor:pointer;font:inherit}}
 .tabbtn:hover{{background:#2a2a2e}}
 .tabbtn.active{{background:#1976d2;border-color:#1976d2}}
 main{{padding:24px 32px}}
 .pane{{display:none}}
 .pane.active{{display:block}}
 h3{{border-bottom:1px solid #2a2a2e;padding-bottom:6px;margin-top:24px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}}
 .grid img{{width:100%;height:180px;object-fit:cover;border-radius:6px;
           cursor:pointer;background:#1a1a1d}}
 .grid img:hover{{outline:2px solid #1976d2}}
</style>
</head><body>
<header>
  {avatar_img}
  <div>
    <h1>{safe_label}</h1>
    <div class="meta">{photo_count} photos · {html.escape(date_range)} · cluster {html.escape(cluster_key)}</div>
  </div>
</header>
<nav>
  <button class="tabbtn active" data-tab="all">All</button>
  <button class="tabbtn" data-tab="best">Best</button>
  <button class="tabbtn" data-tab="solo">Solo ({len(solo)})</button>
  {''.join(rel_tabs_btns)}
</nav>
<main>
  <div class="pane active" id="all">{all_html}</div>
  <div class="pane" id="best">{best_html}</div>
  <div class="pane" id="solo">{solo_html}</div>
  {''.join(rel_tabs_panes)}
</main>
<script>
 const btns=document.querySelectorAll('.tabbtn');
 const panes=document.querySelectorAll('.pane');
 btns.forEach(b=>b.addEventListener('click',()=>{{
   btns.forEach(x=>x.classList.remove('active'));
   panes.forEach(x=>x.classList.remove('active'));
   b.classList.add('active');
   document.getElementById(b.dataset.tab).classList.add('active');
 }}));
</script>
</body></html>
"""
