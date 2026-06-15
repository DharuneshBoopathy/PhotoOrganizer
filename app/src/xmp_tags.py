"""
XMP sidecar generation.

For each photo, optionally write a `<photo>.xmp` sidecar that records:
  - dc:subject  → person labels (as keywords)
  - photoshop:City / photoshop:Country
  - xmp:CreateDate
  - dc:description → location_place_name + event hints

Sidecars are NEVER written into the original photo file. They are placed
next to the original in the SOURCE folder (read-only side-effect: the
photo file is untouched, the sidecar is a separate file).

If the user does NOT want sidecars in the source dir, they can disable
this step in the GUI; sidecars then go into Photos_By_Face/_xmp/ instead.
"""
import os
import logging
import xml.sax.saxutils as saxutils
from datetime import datetime
from typing import List, Optional

from .database import Database

logger = logging.getLogger(__name__)


XMP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="PhotoOrganizer">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">
{body}
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""


def _esc(s: str) -> str:
    return saxutils.escape(s or "", {'"': "&quot;"})


def _format_subject(keywords: List[str]) -> str:
    if not keywords:
        return ""
    items = "".join(f"     <rdf:li>{_esc(k)}</rdf:li>\n" for k in keywords)
    return ("   <dc:subject>\n    <rdf:Bag>\n"
            + items
            + "    </rdf:Bag>\n   </dc:subject>")


def build_xmp_for_media(db: Database, media_id: int) -> Optional[str]:
    """Return XMP body string for one media row, or None if nothing to write."""
    row = db.conn.execute(
        """SELECT m.*, GROUP_CONCAT(fc.label, '||') AS labels
           FROM media m
           LEFT JOIN face_detections fd ON fd.media_id = m.id
           LEFT JOIN face_clusters fc ON fc.cluster_key = fd.cluster_key
                                       AND fc.label IS NOT NULL
                                       AND fc.label != ''
           WHERE m.id = ?
           GROUP BY m.id""",
        (media_id,),
    ).fetchone()
    if not row:
        return None

    keywords = []
    if row["labels"]:
        keywords = sorted({l for l in row["labels"].split("||") if l})

    parts = []
    if keywords:
        parts.append(_format_subject(keywords))

    if row["date_taken"]:
        parts.append(f"   <xmp:CreateDate>{_esc(row['date_taken'])}</xmp:CreateDate>")

    if row["location_city"]:
        parts.append(f"   <photoshop:City>{_esc(row['location_city'])}</photoshop:City>")
    if row["location_country"]:
        parts.append(f"   <photoshop:Country>{_esc(row['location_country'])}</photoshop:Country>")

    desc_bits = []
    if row["location_place_name"]:
        desc_bits.append(row["location_place_name"])
    if desc_bits:
        parts.append(f"   <dc:description>{_esc(' · '.join(desc_bits))}</dc:description>")

    if not parts:
        return None
    return XMP_TEMPLATE.format(body="\n".join(parts))


def write_xmp_sidecars(db: Database, output_dir: str,
                        in_source_dir: bool = False) -> dict:
    """
    Walk all media, write .xmp sidecars.
    in_source_dir=True → next to original photo
    in_source_dir=False → centralized in <output_dir>/Photos_By_Face/_xmp/
    """
    rows = db.conn.execute("SELECT id, source_path FROM media").fetchall()

    central = os.path.join(output_dir, "Photos_By_Face", "_xmp")
    if not in_source_dir:
        os.makedirs(central, exist_ok=True)

    written = 0
    skipped = 0
    for r in rows:
        body = build_xmp_for_media(db, r["id"])
        if not body:
            skipped += 1
            continue

        src = r["source_path"]
        if in_source_dir:
            base, _ = os.path.splitext(src)
            xmp_path = base + ".xmp"
            if not os.path.isdir(os.path.dirname(xmp_path)):
                skipped += 1
                continue
        else:
            stem = os.path.splitext(os.path.basename(src))[0]
            xmp_path = os.path.join(central, f"{stem}_{r['id']}.xmp")

        try:
            with open(xmp_path, "w", encoding="utf-8") as f:
                f.write(body)
            written += 1
        except Exception as e:
            logger.debug(f"[xmp] skipped {src}: {e}")
            skipped += 1

    logger.info(f"[xmp] wrote {written} sidecars, skipped {skipped}")
    return {"written": written, "skipped": skipped,
            "destination": "source dir" if in_source_dir else central}
