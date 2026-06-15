"""
Thumbnail generation. Writes only to the output Thumbnails/ directory.
Source files are never touched.
"""
import os
import hashlib
from typing import Optional

try:
    from PIL import Image, ImageOps
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


THUMB_SIZE = (320, 320)
THUMB_QUALITY = 80


def _thumb_filename(source_path: str) -> str:
    """Deterministic thumbnail filename based on source path hash."""
    h = hashlib.sha256(source_path.encode()).hexdigest()[:16]
    return f"{h}.jpg"


def generate_image_thumbnail(source_path: str, thumb_dir: str) -> Optional[str]:
    """
    Create JPEG thumbnail of an image in thumb_dir.
    Returns the thumbnail path, or None on failure.
    """
    if not HAS_PILLOW:
        return None

    os.makedirs(thumb_dir, exist_ok=True)
    dest = os.path.join(thumb_dir, _thumb_filename(source_path))

    if os.path.exists(dest):
        return dest  # already generated

    try:
        with Image.open(source_path) as img:
            img = ImageOps.exif_transpose(img)  # correct orientation
            img = img.convert("RGB")
            img.thumbnail(THUMB_SIZE, Image.LANCZOS)
            img.save(dest, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return dest
    except Exception:
        return None


def generate_video_thumbnail(source_path: str, thumb_dir: str) -> Optional[str]:
    """
    Extract a frame from a video and save as JPEG thumbnail.
    Returns thumbnail path, or None on failure.
    """
    if not HAS_CV2:
        return None

    os.makedirs(thumb_dir, exist_ok=True)
    dest = os.path.join(thumb_dir, _thumb_filename(source_path))

    if os.path.exists(dest):
        return dest

    try:
        cap = cv2.VideoCapture(source_path)
        if not cap.isOpened():
            return None

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        target_frame = max(0, min(total_frames // 4, total_frames - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return None

        h, w = frame.shape[:2]
        scale = min(THUMB_SIZE[0] / w, THUMB_SIZE[1] / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        cv2.imwrite(dest, resized, [cv2.IMWRITE_JPEG_QUALITY, THUMB_QUALITY])
        return dest
    except Exception:
        return None


def generate_thumbnail(source_path: str, thumb_dir: str, media_type: str) -> Optional[str]:
    """Dispatch to image or video thumbnail generator."""
    if media_type == "image":
        return generate_image_thumbnail(source_path, thumb_dir)
    else:
        return generate_video_thumbnail(source_path, thumb_dir)
