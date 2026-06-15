"""
Per-person identity module.
- Face quality scoring (sharpness, size, brightness, confidence)
- Representative face selection per cluster
- Contact sheet generation (top-9 best photos of that person)
- person_summary.json writer
- Cluster cohesion scoring (flags likely mis-grouped clusters)

All operations are READ-ONLY on source files. Writes go only inside
the output Photos_By_Face/ folders.
"""
import os
import json
import logging
from typing import List, Tuple, Dict, Optional

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from PIL import Image, ImageDraw, ImageFilter
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

from .database import Database
from .face_engine import bytes_to_embedding

logger = logging.getLogger(__name__)

AVATAR_SIZE = 512       # cluster_avatar.jpg square size
CONTACT_TILE = 320      # per-tile size in contact sheet
CONTACT_GRID = 3        # 3x3 = top 9 photos
QUALITY_WEIGHTS = {
    "sharpness":  0.30,   # Laplacian variance — penalizes blur
    "size":       0.20,   # bbox area
    "confidence": 0.15,   # det_score from InsightFace
    "brightness": 0.10,   # mid-range luminance preferred
    "pose":       0.15,   # frontality based on 5pt landmarks
    "eyes":       0.10,   # eye-openness proxy
}


def _coerce_int(value) -> int:
    """
    Older DB rows may have bbox stored as bytes (SQLite received numpy.int64
    without an adapter). Decode if needed.
    """
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, (bytes, bytearray)):
        # numpy.int64 → 8 little-endian bytes
        try:
            if len(value) == 8:
                return int.from_bytes(value, "little", signed=True)
            if len(value) == 4:
                return int.from_bytes(value, "little", signed=True)
        except Exception:
            pass
        try:
            return int(value.decode("utf-8"))
        except Exception:
            return 0
    return int(value)


# ────────────────────────────────────────────────────────────────────────────
# Face quality scoring
# ────────────────────────────────────────────────────────────────────────────

def compute_face_quality(
    image_bgr: np.ndarray,
    bbox: Tuple[int, int, int, int],
    confidence: float,
    landmarks: Optional[np.ndarray] = None,
) -> float:
    """
    Score a face crop on 0..1. Higher = better candidate for avatar.
    Factors: sharpness (blur), bbox size, detection confidence, brightness,
    pose frontality, eye-openness — last two require 5-point landmarks.
    """
    if image_bgr is None:
        return 0.0
    x1, y1, x2, y2 = bbox
    H, W = image_bgr.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(W, x2), min(H, y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0

    crop = image_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    sharpness = min(lap_var / 500.0, 1.0)

    area = (x2 - x1) * (y2 - y1)
    size = min(area / (256 * 256), 1.0)

    mean_b = gray.mean() / 255.0
    brightness = max(0.0, 1.0 - abs(mean_b - 0.5) * 2)

    pose, eyes = _pose_and_eye_scores(landmarks, bbox)

    score = (
        QUALITY_WEIGHTS["sharpness"]  * sharpness +
        QUALITY_WEIGHTS["size"]       * size +
        QUALITY_WEIGHTS["confidence"] * float(confidence) +
        QUALITY_WEIGHTS["brightness"] * brightness +
        QUALITY_WEIGHTS["pose"]       * pose +
        QUALITY_WEIGHTS["eyes"]       * eyes
    )
    return round(float(score), 4)


def _pose_and_eye_scores(landmarks: Optional[np.ndarray],
                          bbox: Tuple[int, int, int, int]) -> Tuple[float, float]:
    """
    From 5-point landmarks (left_eye, right_eye, nose, left_mouth, right_mouth):
      - pose score: how centered the nose is between the eyes (frontality)
      - eyes score: vertical separation between eyes (proxy for closed eyes / extreme tilt)
    Both default to 0.5 when landmarks unavailable.
    """
    if landmarks is None or len(landmarks) < 5:
        return 0.5, 0.5

    try:
        lm = np.asarray(landmarks, dtype=np.float32)
        l_eye = lm[0]
        r_eye = lm[1]
        nose  = lm[2]

        # Pose: distance of nose from eye midline (normalized by eye distance)
        eye_mid = (l_eye + r_eye) / 2.0
        eye_dist = max(np.linalg.norm(r_eye - l_eye), 1.0)
        nose_offset = abs(nose[0] - eye_mid[0]) / eye_dist
        # 0.0 offset = perfect frontal → score 1; 0.5+ offset = extreme profile → score 0
        pose = max(0.0, 1.0 - nose_offset * 2.0)

        # Eyes: vertical separation should be small (level head)
        eye_yspread = abs(l_eye[1] - r_eye[1]) / eye_dist
        eyes = max(0.0, 1.0 - eye_yspread * 4.0)

        return float(pose), float(eyes)
    except Exception:
        return 0.5, 0.5


# ────────────────────────────────────────────────────────────────────────────
# Face crop extraction
# ────────────────────────────────────────────────────────────────────────────

def extract_face_crop_bgr(
    image_bgr: np.ndarray,
    bbox: Tuple[int, int, int, int],
    margin: float = 0.35,
) -> Optional[np.ndarray]:
    """
    Return a padded square BGR crop around the face, or None if invalid.
    """
    if image_bgr is None:
        return None
    H, W = image_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return None

    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    side = int(max(w, h) * (1.0 + margin))
    half = side // 2

    nx1 = max(0, cx - half)
    ny1 = max(0, cy - half)
    nx2 = min(W, cx + half)
    ny2 = min(H, cy + half)

    crop = image_bgr[ny1:ny2, nx1:nx2]
    if crop.size == 0:
        return None
    return crop


# ────────────────────────────────────────────────────────────────────────────
# Circular badge avatar
# ────────────────────────────────────────────────────────────────────────────

def make_circular_badge(face_bgr: np.ndarray, size: int = AVATAR_SIZE,
                         border_color=(240, 240, 240), border_width: int = 6) -> "Image.Image":
    """
    Produce an RGBA PIL image of the face cropped into a circle
    with a subtle outer border. Good for Windows folder icons.
    """
    if not HAS_PILLOW or not HAS_CV2:
        raise RuntimeError("Pillow and OpenCV required for badge generation")

    h, w = face_bgr.shape[:2]
    s = max(h, w)
    # Pad to square with neutral gray
    padded = np.full((s, s, 3), 128, dtype=np.uint8)
    y0 = (s - h) // 2
    x0 = (s - w) // 2
    padded[y0:y0 + h, x0:x0 + w] = face_bgr

    padded = cv2.resize(padded, (size, size), interpolation=cv2.INTER_LANCZOS4)
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb).convert("RGBA")

    # Circular alpha mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    img.putalpha(mask)

    # Border stroke
    draw = ImageDraw.Draw(img)
    bw = border_width
    draw.ellipse(
        (bw // 2, bw // 2, size - bw // 2 - 1, size - bw // 2 - 1),
        outline=border_color, width=bw,
    )
    return img


def make_generic_silhouette(size: int = AVATAR_SIZE) -> "Image.Image":
    """Fallback avatar: neutral circle with a generic person silhouette."""
    if not HAS_PILLOW:
        raise RuntimeError("Pillow required")

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg_color = (200, 205, 215, 255)
    fg_color = (120, 125, 135, 255)

    d.ellipse((0, 0, size - 1, size - 1), fill=bg_color)

    # Head circle
    head_r = size // 6
    head_cx = size // 2
    head_cy = int(size * 0.40)
    d.ellipse(
        (head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r),
        fill=fg_color,
    )
    # Shoulders ellipse
    sh_w = int(size * 0.60)
    sh_h = int(size * 0.35)
    d.ellipse(
        (head_cx - sh_w // 2, int(size * 0.58),
         head_cx + sh_w // 2, int(size * 0.58) + sh_h),
        fill=fg_color,
    )
    return img


# ────────────────────────────────────────────────────────────────────────────
# Representative face selection
# ────────────────────────────────────────────────────────────────────────────

def score_all_detections_for_cluster(db: Database, cluster_key: str) -> List[Dict]:
    """
    Return a list of {detection_id, media_id, source_path, bbox, quality, confidence}
    sorted by quality desc. Scores are computed fresh and persisted to DB.
    """
    if not HAS_CV2:
        return []

    rows = db.get_detections_by_cluster(cluster_key)
    results = []

    for r in rows:
        src = r["media_source_path"]
        if not os.path.isfile(src):
            continue
        img = cv2.imread(src)
        if img is None:
            continue
        bbox = (_coerce_int(r["bbox_x1"]), _coerce_int(r["bbox_y1"]),
                _coerce_int(r["bbox_x2"]), _coerce_int(r["bbox_y2"]))
        # Decode landmarks BLOB (5x2 float32 = 40 bytes) if present
        landmarks = None
        try:
            lmk_blob = r["landmarks"] if "landmarks" in r.keys() else None
        except Exception:
            lmk_blob = None
        if lmk_blob:
            try:
                arr = np.frombuffer(lmk_blob, dtype=np.float32)
                if arr.size in (10, 212):  # 5pt or 106pt
                    landmarks = arr.reshape(-1, 2)
            except Exception:
                landmarks = None
        q = compute_face_quality(img, bbox, float(r["confidence"]), landmarks=landmarks)
        db.update_detection_quality(r["id"], q)
        results.append({
            "detection_id": r["id"],
            "media_id": r["media_id"],
            "source_path": src,
            "thumbnail_path": r["media_thumbnail_path"],
            "bbox": bbox,
            "confidence": float(r["confidence"]),
            "quality": q,
        })

    results.sort(key=lambda x: x["quality"], reverse=True)
    return results


# ────────────────────────────────────────────────────────────────────────────
# Avatar writer
# ────────────────────────────────────────────────────────────────────────────

def write_cluster_avatar(folder_path: str, ranked: List[Dict], circular: bool = True) -> Optional[str]:
    """
    Save cluster_avatar.jpg (square face crop) + cluster_avatar_badge.png
    (circular cutout for icon generation) into folder_path.
    Returns path to cluster_avatar.jpg, or None on total failure.
    """
    if not HAS_CV2 or not HAS_PILLOW:
        return None

    avatar_path = os.path.join(folder_path, "cluster_avatar.jpg")
    badge_path = os.path.join(folder_path, "cluster_avatar_badge.png")

    for candidate in ranked:
        img = cv2.imread(candidate["source_path"])
        if img is None:
            continue
        crop = extract_face_crop_bgr(img, candidate["bbox"], margin=0.35)
        if crop is None or crop.shape[0] < 50 or crop.shape[1] < 50:
            continue

        # Save square avatar (JPEG, no transparency)
        square = _make_square_bgr(crop, AVATAR_SIZE)
        cv2.imwrite(avatar_path, square, [cv2.IMWRITE_JPEG_QUALITY, 92])

        # Save circular badge PNG (for ICO input)
        if circular:
            badge = make_circular_badge(crop, AVATAR_SIZE)
            badge.save(badge_path, "PNG")

        return avatar_path

    # No usable face — write silhouette fallback
    logger.warning(f"[identity] No usable face for avatar in {folder_path}; using silhouette.")
    silhouette = make_generic_silhouette(AVATAR_SIZE)
    silhouette.convert("RGB").save(avatar_path, "JPEG", quality=92)
    if circular:
        silhouette.save(badge_path, "PNG")
    return avatar_path


def _make_square_bgr(crop_bgr: np.ndarray, size: int) -> np.ndarray:
    h, w = crop_bgr.shape[:2]
    s = max(h, w)
    canvas = np.full((s, s, 3), 128, dtype=np.uint8)
    canvas[(s - h) // 2:(s - h) // 2 + h, (s - w) // 2:(s - w) // 2 + w] = crop_bgr
    return cv2.resize(canvas, (size, size), interpolation=cv2.INTER_LANCZOS4)


# ────────────────────────────────────────────────────────────────────────────
# Contact sheet (top-9 photos of this person)
# ────────────────────────────────────────────────────────────────────────────

def write_contact_sheet(folder_path: str, ranked: List[Dict],
                         grid: int = CONTACT_GRID, tile: int = CONTACT_TILE) -> Optional[str]:
    """Save a grid×grid contact sheet of the best photos of this person."""
    if not HAS_PILLOW:
        return None

    max_tiles = grid * grid
    picks = ranked[:max_tiles]
    if not picks:
        return None

    sheet = Image.new("RGB", (tile * grid, tile * grid), (30, 30, 30))

    for i, c in enumerate(picks):
        src = c.get("thumbnail_path") or c.get("source_path")
        if not src or not os.path.isfile(src):
            continue
        try:
            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail((tile, tile), Image.LANCZOS)
                # Center within tile
                tx = (i % grid) * tile + (tile - im.size[0]) // 2
                ty = (i // grid) * tile + (tile - im.size[1]) // 2
                sheet.paste(im, (tx, ty))
        except Exception as e:
            logger.debug(f"[identity] contact sheet tile failed: {e}")

    out = os.path.join(folder_path, "contact_sheet.jpg")
    sheet.save(out, "JPEG", quality=85, optimize=True)
    return out


# ────────────────────────────────────────────────────────────────────────────
# person_summary.json
# ────────────────────────────────────────────────────────────────────────────

def write_person_summary(
    folder_path: str,
    cluster_key: str,
    label: Optional[str],
    member_count: int,
    ranked: List[Dict],
    quality_metrics: Dict,
    avatar_path: Optional[str],
) -> str:
    data = {
        "cluster_key": cluster_key,
        "label": label,
        "photo_count": member_count,
        "avatar_path": os.path.basename(avatar_path) if avatar_path else None,
        "representative": {
            "source_path": ranked[0]["source_path"] if ranked else None,
            "quality_score": ranked[0]["quality"] if ranked else None,
            "detection_confidence": ranked[0]["confidence"] if ranked else None,
        },
        "top_faces": [
            {
                "source_path": r["source_path"],
                "quality": r["quality"],
                "confidence": r["confidence"],
            }
            for r in ranked[:10]
        ],
        "cluster_quality": quality_metrics,
    }
    out = os.path.join(folder_path, "person_summary.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return out


# ────────────────────────────────────────────────────────────────────────────
# Cluster cohesion / quality scoring
# ────────────────────────────────────────────────────────────────────────────

def compute_cluster_cohesion(embeddings: List[np.ndarray]) -> Dict:
    """
    Measure how tight a cluster is.
    Returns dict with cohesion 0..1 (higher = tighter) + quality flag.
    """
    if len(embeddings) < 2:
        return {"cohesion": 1.0, "mean_dist": 0.0, "max_dist": 0.0,
                "member_count": len(embeddings), "quality_flag": "single"}

    M = np.vstack(embeddings).astype(np.float32)
    norms = np.linalg.norm(M, axis=1, keepdims=True)
    norms[norms == 0] = 1
    M = M / norms

    centroid = M.mean(axis=0)
    cn = np.linalg.norm(centroid)
    if cn > 0:
        centroid = centroid / cn

    sims = M @ centroid
    dists = 1.0 - sims
    mean_dist = float(dists.mean())
    max_dist = float(dists.max())
    cohesion = float(max(0.0, 1.0 - mean_dist))

    if mean_dist < 0.25:
        flag = "good"
    elif mean_dist < 0.40:
        flag = "fair"
    elif mean_dist < 0.55:
        flag = "suspect"
    else:
        flag = "poor"

    return {
        "cohesion": round(cohesion, 4),
        "mean_dist": round(mean_dist, 4),
        "max_dist": round(max_dist, 4),
        "member_count": len(embeddings),
        "quality_flag": flag,
    }


def find_ambiguous_detections(
    all_embeddings: List[Tuple[int, str, np.ndarray]],
    margin: float = 0.08,
) -> List[Dict]:
    """
    A face is ambiguous if its distance to the 2nd-nearest cluster centroid
    is very close to its distance to the 1st-nearest.
    Returns list of {detection_id, cluster_key, alt_cluster_key, margin}.
    """
    cluster_embs: Dict[str, List[np.ndarray]] = {}
    for det_id, ck, emb in all_embeddings:
        if ck and not ck.startswith("unknown_"):
            cluster_embs.setdefault(ck, []).append(emb)

    if len(cluster_embs) < 2:
        return []

    centroids = {}
    for ck, embs in cluster_embs.items():
        M = np.vstack(embs).astype(np.float32)
        norms = np.linalg.norm(M, axis=1, keepdims=True)
        norms[norms == 0] = 1
        M = M / norms
        c = M.mean(axis=0)
        cn = np.linalg.norm(c)
        if cn > 0:
            c = c / cn
        centroids[ck] = c

    ambiguous = []
    for det_id, ck, emb in all_embeddings:
        if not ck or ck.startswith("unknown_"):
            continue
        e = emb / (np.linalg.norm(emb) or 1)
        dists = [(other_ck, 1 - float(e @ c)) for other_ck, c in centroids.items()]
        dists.sort(key=lambda x: x[1])
        if len(dists) >= 2:
            nearest_ck, nearest_d = dists[0]
            alt_ck, alt_d = dists[1]
            if nearest_ck == ck and (alt_d - nearest_d) < margin:
                ambiguous.append({
                    "detection_id": det_id,
                    "cluster_key": ck,
                    "alt_cluster_key": alt_ck,
                    "margin": round(alt_d - nearest_d, 4),
                })

    return ambiguous
