"""
Timeline generation per person.

For each cluster: produce timeline.jpg (chronological grid) and
optional timeline.html viewer that shows photos in date order.
"""
import os
import logging
from datetime import datetime
from typing import List, Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

from .database import Database
from .organizer import face_folder_path

logger = logging.getLogger(__name__)


TILE = 200          # per-photo tile size in timeline.jpg
TILES_PER_ROW = 6   # 6 photos per row
MAX_PHOTOS = 60     # cap so the image stays a reasonable size
HEADER_H = 32


def build_timeline_for_cluster(db: Database, output_dir: str, cluster_key: str) -> Optional[str]:
    """Generate Photos_By_Face/<person>/timeline.jpg for one cluster."""
    if not HAS_PILLOW:
        return None

    cluster = db.get_cluster(cluster_key)
    if not cluster:
        return None

    folder = face_folder_path(output_dir, cluster_key, cluster["label"])
    if not os.path.isdir(folder):
        return None

    media_rows = db.media_with_cluster(cluster_key)
    items = []
    for r in media_rows:
        if r["media_type"] != "image":
            continue
        date_str = r["date_taken"] or r["date_file_modified"]
        try:
            dt = datetime.fromisoformat(date_str) if date_str else None
        except Exception:
            dt = None
        thumb = r["thumbnail_path"]
        src = thumb if (thumb and os.path.isfile(thumb)) else r["source_path"]
        if os.path.isfile(src):
            items.append((dt or datetime.min, src))

    if not items:
        return None

    items.sort(key=lambda x: x[0])
    items = items[:MAX_PHOTOS]

    n = len(items)
    rows = (n + TILES_PER_ROW - 1) // TILES_PER_ROW
    W = TILE * TILES_PER_ROW
    H = TILE * rows + HEADER_H

    canvas = Image.new("RGB", (W, H), (28, 28, 28))
    draw = ImageDraw.Draw(canvas)

    # Header
    label = cluster["label"] or cluster_key
    title = f"{label}  —  {n} photos  —  {items[0][0].year}–{items[-1][0].year}" \
        if items[0][0].year > 1 else f"{label} — {n} photos"
    font = _load_font(20)
    draw.text((12, 6), title, fill=(220, 220, 220), font=font)

    for i, (dt, src) in enumerate(items):
        try:
            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail((TILE, TILE), Image.LANCZOS)
                tx = (i % TILES_PER_ROW) * TILE + (TILE - im.size[0]) // 2
                ty = HEADER_H + (i // TILES_PER_ROW) * TILE + (TILE - im.size[1]) // 2
                canvas.paste(im, (tx, ty))
        except Exception as e:
            logger.debug(f"[timeline] tile failed: {e}")

    out_path = os.path.join(folder, "timeline.jpg")
    canvas.save(out_path, "JPEG", quality=85, optimize=True)

    _write_timeline_html(folder, label, items)
    return out_path


def _write_timeline_html(folder: str, label: str, items: list) -> None:
    """Simple HTML viewer that lists photos chronologically with date headers."""
    grouped: dict = {}
    for dt, path in items:
        key = dt.strftime("%Y-%m") if dt and dt.year > 1 else "Unknown"
        grouped.setdefault(key, []).append(path)

    sections = []
    for k in sorted(grouped.keys()):
        cells = []
        for path in grouped[k]:
            rel = os.path.relpath(path, folder).replace("\\", "/")
            cells.append(f'<a href="{rel}"><img src="{rel}" loading="lazy"></a>')
        sections.append(f"<h3>{k}</h3><div class='grid'>{''.join(cells)}</div>")

    page = f"""<!doctype html><html><head>
<meta charset="utf-8"><title>{label} — Timeline</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#111;color:#eee}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}}
 .grid img{{width:100%;height:180px;object-fit:cover;border-radius:4px;cursor:pointer}}
 h3{{border-bottom:1px solid #333;padding-bottom:4px;margin-top:32px}}
</style></head><body>
<h1>{label}</h1>
{''.join(sections)}
</body></html>
"""
    with open(os.path.join(folder, "timeline.html"), "w", encoding="utf-8") as f:
        f.write(page)


def build_timelines_all(db: Database, output_dir: str) -> dict:
    """Build timelines for every cluster."""
    summary = {}
    for c in db.get_face_clusters():
        out = build_timeline_for_cluster(db, output_dir, c["cluster_key"])
        summary[c["cluster_key"]] = out
    return summary


def _load_font(size: int):
    if not HAS_PILLOW:
        return None
    for path in ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()
