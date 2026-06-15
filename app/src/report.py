"""
Top-level report.html — a single dashboard the user opens after a run.

Layout:
  - Hero with totals (photos / people / clusters / duplicates)
  - People grid: avatar + name + count, click → person album
  - Recent activity panel
  - Links to subsections (Photos_By_Date, Photos_By_Location, etc.)

The report is purely informational — it never mutates anything.
"""
import os
import html
import logging
from datetime import datetime
from typing import Optional

from .database import Database
from .organizer import face_folder_path
from .search import stats_summary

logger = logging.getLogger(__name__)


def build_report(db: Database, output_dir: str) -> str:
    """Generate report.html at the root of output_dir. Returns its path."""
    stats = stats_summary(db)
    clusters = db.get_face_clusters()

    # Sort: labeled first, then by count desc
    def sort_key(c):
        return (0 if c["label"] else 1, -(c["member_count"] or 0))

    clusters_sorted = sorted(
        [c for c in clusters
         if not c["cluster_key"].startswith("unknown_")
         and not c["is_stranger"]],
        key=sort_key,
    )

    cards = []
    for c in clusters_sorted:
        ck = c["cluster_key"]
        label = c["label"] or ck
        folder = face_folder_path(output_dir, ck, c["label"])
        avatar = os.path.join(folder, "cluster_avatar.jpg")
        album = os.path.join(folder, "album.html")

        rel_avatar = _relpath(avatar, output_dir) if os.path.isfile(avatar) else ""
        rel_album = _relpath(album, output_dir) if os.path.isfile(album) else \
                    _relpath(folder, output_dir)

        flag = c["quality_flag"] or "good"
        flag_color = {"good": "#4caf50", "fair": "#ffb300",
                      "suspect": "#ff7043", "poor": "#e53935"}.get(flag, "#888")

        avatar_html = (
            f'<img src="{html.escape(rel_avatar)}" alt="">'
            if rel_avatar else
            '<div class="placeholder">?</div>'
        )

        cards.append(f"""
<a class="card" href="{html.escape(rel_album)}">
  <div class="avatar-wrap">{avatar_html}
    <span class="quality-dot" style="background:{flag_color}" title="{flag}"></span>
  </div>
  <div class="name">{html.escape(label)}</div>
  <div class="count">{c['member_count'] or 0} photos</div>
</a>
""")

    # Strangers
    stranger_count = stats["strangers"]
    stranger_link = ""
    if stranger_count:
        stranger_link = (
            f'<a class="subdir" href="Photos_By_Face/_strangers/">'
            f'⚠ {stranger_count} stranger clusters quarantined</a>'
        )

    subdir_links = []
    for sd in ["Photos_By_Date", "Photos_By_Location", "Photos_By_Event",
               "Photos_By_Face", "Photos_By_Relationship", "Photos_By_Burst",
               "_Duplicates"]:
        if os.path.isdir(os.path.join(output_dir, sd)):
            subdir_links.append(
                f'<a class="subdir" href="{sd}/">{sd.replace("_", " ").strip()}</a>'
            )

    earliest = stats["earliest"] or "?"
    latest = stats["latest"] or "?"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    page = f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Photo Library Report</title>
<style>
 *{{box-sizing:border-box}}
 body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#0e0e10;color:#eee}}
 header{{padding:32px;background:linear-gradient(135deg,#1976d2,#0d47a1);color:white}}
 header h1{{margin:0;font-size:36px}}
 header .sub{{opacity:.85;margin-top:8px}}
 .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
        gap:12px;padding:20px 32px;background:#1a1a1d}}
 .stat{{padding:16px;background:#222226;border-radius:8px}}
 .stat .n{{font-size:28px;font-weight:600}}
 .stat .l{{color:#aaa;font-size:13px;text-transform:uppercase;letter-spacing:.5px}}
 main{{padding:24px 32px}}
 h2{{border-bottom:1px solid #2a2a2e;padding-bottom:8px;margin-top:32px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px;margin-top:16px}}
 .card{{display:block;padding:16px;background:#1a1a1d;border:1px solid #2a2a2e;
        border-radius:8px;text-decoration:none;color:inherit;text-align:center;
        transition:transform .15s,border-color .15s}}
 .card:hover{{transform:translateY(-2px);border-color:#1976d2}}
 .avatar-wrap{{position:relative;width:96px;height:96px;margin:0 auto 12px}}
 .avatar-wrap img{{width:96px;height:96px;border-radius:50%;object-fit:cover}}
 .placeholder{{width:96px;height:96px;border-radius:50%;background:#333;
              display:flex;align-items:center;justify-content:center;
              font-size:32px;color:#666}}
 .quality-dot{{position:absolute;right:4px;bottom:4px;width:16px;height:16px;
              border-radius:50%;border:2px solid #1a1a1d}}
 .name{{font-weight:600;margin-bottom:4px}}
 .count{{color:#aaa;font-size:13px}}
 .subdir{{display:inline-block;margin:8px 12px 8px 0;padding:8px 16px;
         background:#1f1f23;border:1px solid #2a2a2e;border-radius:6px;
         color:#1976d2;text-decoration:none}}
 .subdir:hover{{background:#2a2a2e}}
 footer{{padding:24px 32px;color:#666;font-size:12px;text-align:center}}
</style>
</head><body>
<header>
  <h1>Photo Library Report</h1>
  <div class="sub">Generated {html.escape(generated)} · {html.escape(earliest)} → {html.escape(latest)}</div>
</header>
<div class="stats">
  <div class="stat"><div class="n">{stats['total_media']:,}</div><div class="l">Total media</div></div>
  <div class="stat"><div class="n">{stats['images']:,}</div><div class="l">Images</div></div>
  <div class="stat"><div class="n">{stats['videos']:,}</div><div class="l">Videos</div></div>
  <div class="stat"><div class="n">{stats['clusters']:,}</div><div class="l">People clusters</div></div>
  <div class="stat"><div class="n">{stats['labeled_people']:,}</div><div class="l">Labeled</div></div>
  <div class="stat"><div class="n">{stats['exact_duplicates']:,}</div><div class="l">Exact duplicates</div></div>
  <div class="stat"><div class="n">{stats['near_duplicates']:,}</div><div class="l">Near duplicates</div></div>
  <div class="stat"><div class="n">{stats['geotagged']:,}</div><div class="l">Geotagged</div></div>
</div>
<main>
  <h2>Subdirectories</h2>
  <div>{''.join(subdir_links)}</div>
  {f'<p>{stranger_link}</p>' if stranger_link else ''}

  <h2>People ({len(clusters_sorted)})</h2>
  <div class="grid">
    {''.join(cards)}
  </div>
</main>
<footer>Photo Organizer · all data stays on this machine</footer>
</body></html>
"""

    out = os.path.join(output_dir, "report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    logger.info(f"[report] written: {out}")
    return out


def _relpath(target: str, base: str) -> str:
    try:
        return os.path.relpath(target, base).replace("\\", "/")
    except Exception:
        return target.replace("\\", "/")
