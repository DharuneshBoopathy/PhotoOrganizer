"""
Read-only metadata extraction: EXIF, GPS, timestamps.
Never writes to source files.
"""
import os
import struct
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

try:
    import exifread
    HAS_EXIFREAD = True
except ImportError:
    HAS_EXIFREAD = False

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


EXIF_DATE_FORMATS = [
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
]


def _parse_date(raw: str) -> Optional[datetime]:
    raw = str(raw).strip()
    for fmt in EXIF_DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _rational_to_float(value) -> float:
    """Convert EXIF rational (num/denom or IFDRational) to float."""
    try:
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            return float(value.numerator) / float(value.denominator) if value.denominator else 0.0
        if hasattr(value, "num") and hasattr(value, "den"):
            return float(value.num) / float(value.den) if value.den else 0.0
        return float(value)
    except Exception:
        return 0.0


def _dms_to_decimal(dms_values, ref: str) -> Optional[float]:
    """Convert degrees/minutes/seconds + ref to decimal degrees."""
    try:
        degrees = _rational_to_float(dms_values[0])
        minutes = _rational_to_float(dms_values[1])
        seconds = _rational_to_float(dms_values[2])
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if ref.upper() in ("S", "W"):
            decimal = -decimal
        return decimal
    except Exception:
        return None


def extract_gps_pillow(exif_data: Dict) -> Tuple[Optional[float], Optional[float]]:
    """Extract GPS from Pillow _getexif() dict."""
    if exif_data is None:
        return None, None
    gps_info = {}
    for tag_id, value in exif_data.items():
        tag_name = TAGS.get(tag_id, tag_id)
        if tag_name == "GPSInfo":
            for gps_tag_id, gps_value in value.items():
                gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                gps_info[gps_tag] = gps_value
            break

    if not gps_info:
        return None, None

    try:
        lat = _dms_to_decimal(gps_info.get("GPSLatitude"), gps_info.get("GPSLatitudeRef", "N"))
        lon = _dms_to_decimal(gps_info.get("GPSLongitude"), gps_info.get("GPSLongitudeRef", "E"))
        return lat, lon
    except Exception:
        return None, None


def extract_metadata_image(path: str) -> Dict[str, Any]:
    """Extract all useful metadata from an image file."""
    meta: Dict[str, Any] = {
        "date_taken": None,
        "gps_lat": None,
        "gps_lon": None,
        "width": None,
        "height": None,
    }

    # ── Pillow EXIF ───────────────────────────────────────────────────────────
    if HAS_PILLOW:
        try:
            with Image.open(path) as img:
                meta["width"], meta["height"] = img.size
                exif_raw = img._getexif() if hasattr(img, "_getexif") else None
                if exif_raw:
                    for tag_id, value in exif_raw.items():
                        tag = TAGS.get(tag_id, "")
                        if tag == "DateTimeOriginal" and not meta["date_taken"]:
                            meta["date_taken"] = _parse_date(str(value))
                        elif tag == "DateTime" and not meta["date_taken"]:
                            meta["date_taken"] = _parse_date(str(value))
                    lat, lon = extract_gps_pillow(exif_raw)
                    meta["gps_lat"] = lat
                    meta["gps_lon"] = lon
        except Exception:
            pass

    # ── exifread fallback for date ────────────────────────────────────────────
    if HAS_EXIFREAD and meta["date_taken"] is None:
        try:
            with open(path, "rb") as f:
                tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
            raw = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
            if raw:
                meta["date_taken"] = _parse_date(str(raw.values))
        except Exception:
            pass

    # ── File system fallback ──────────────────────────────────────────────────
    if meta["date_taken"] is None:
        try:
            ts = os.path.getmtime(path)
            meta["date_taken"] = datetime.fromtimestamp(ts)
            meta["date_source"] = "file_mtime"
        except Exception:
            meta["date_taken"] = datetime.now()
            meta["date_source"] = "now_fallback"
    else:
        meta["date_source"] = "exif"

    return meta


def extract_metadata_video(path: str) -> Dict[str, Any]:
    """Extract metadata from a video file using OpenCV."""
    meta: Dict[str, Any] = {
        "date_taken": None,
        "gps_lat": None,
        "gps_lon": None,
        "width": None,
        "height": None,
        "duration_sec": None,
    }

    if HAS_CV2:
        try:
            cap = cv2.VideoCapture(path)
            if cap.isOpened():
                meta["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                meta["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if fps and fps > 0 and frame_count > 0:
                    meta["duration_sec"] = frame_count / fps
            cap.release()
        except Exception:
            pass

    # Fall back to file mtime
    try:
        ts = os.path.getmtime(path)
        meta["date_taken"] = datetime.fromtimestamp(ts)
        meta["date_source"] = "file_mtime"
    except Exception:
        meta["date_taken"] = datetime.now()
        meta["date_source"] = "now_fallback"

    return meta


def extract_metadata(path: str, media_type: str) -> Dict[str, Any]:
    """Dispatch to image or video extractor."""
    if media_type == "image":
        return extract_metadata_image(path)
    else:
        return extract_metadata_video(path)


def format_gps_label(lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    """
    Format GPS coords as a location label.
    Tries reverse_geocoder (local dataset); falls back to coordinate string.
    """
    if lat is None or lon is None:
        return None

    try:
        import reverse_geocoder as rg
        results = rg.search([(lat, lon)], verbose=False)
        if results:
            r = results[0]
            parts = [r.get("name", ""), r.get("admin1", ""), r.get("cc", "")]
            label = "_".join(p for p in parts if p)
            # Sanitize for folder name
            label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
            return label[:80]
    except Exception:
        pass

    # Coordinate fallback (still useful for folder grouping)
    lat_str = f"{'N' if lat >= 0 else 'S'}{abs(lat):.2f}"
    lon_str = f"{'E' if lon >= 0 else 'W'}{abs(lon):.2f}"
    return f"{lat_str}_{lon_str}"
