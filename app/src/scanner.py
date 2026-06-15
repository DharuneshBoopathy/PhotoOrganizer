"""
Recursive media file scanner. Read-only — never modifies source files.
"""
import os
import mimetypes
from typing import List, Tuple, Generator

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".cr2", ".cr3", ".nef", ".arw",
    ".dng", ".orf", ".rw2", ".pef", ".srw", ".raw",
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v",
    ".3gp", ".mts", ".m2ts", ".ts", ".webm", ".mpg", ".mpeg",
}

ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS


def get_media_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "unknown"


def scan_directory(root_dir: str, skip_hidden: bool = True) -> Generator[str, None, None]:
    """
    Yield absolute paths of all media files under root_dir.
    Never follows symlinks to avoid loops. Read-only walk.
    """
    root_dir = os.path.abspath(root_dir)
    for dirpath, dirnames, filenames in os.walk(root_dir, followlinks=False):
        if skip_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        for filename in filenames:
            if skip_hidden and filename.startswith("."):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext in ALL_MEDIA_EXTENSIONS:
                full_path = os.path.join(dirpath, filename)
                if os.path.isfile(full_path) and not os.path.islink(full_path):
                    yield full_path


def count_media(root_dir: str, skip_hidden: bool = True) -> int:
    """Count media files without loading them all into memory."""
    return sum(1 for _ in scan_directory(root_dir, skip_hidden))


def collect_media(root_dir: str, skip_hidden: bool = True) -> List[str]:
    """Return sorted list of all media file paths."""
    return sorted(scan_directory(root_dir, skip_hidden))


def get_mime_type(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"
