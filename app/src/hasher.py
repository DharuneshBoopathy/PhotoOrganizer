"""
Duplicate detection:
  - SHA-256 exact hash (byte-perfect duplicates)
  - pHash perceptual hash (near-duplicates, visually similar)

Never modifies any file. Read-only operations only.
"""
import hashlib
import os
from typing import Optional, List, Tuple, Dict

try:
    import imagehash
    from PIL import Image
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False


PHASH_DISTANCE_THRESHOLD = 8  # hamming distance ≤ 8 = near-duplicate


def sha256_file(path: str, chunk_size: int = 65536) -> str:
    """Compute SHA-256 of file contents. Read-only."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def phash_image(path: str) -> Optional[str]:
    """
    Compute perceptual hash of an image.
    Returns hex string or None if unsupported/error.
    """
    if not HAS_IMAGEHASH:
        return None
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            h = imagehash.phash(img, hash_size=16)
            return str(h)
    except Exception:
        return None


def phash_distance(hash1: str, hash2: str) -> int:
    """Hamming distance between two pHash hex strings."""
    if not HAS_IMAGEHASH:
        return 999
    try:
        h1 = imagehash.hex_to_hash(hash1)
        h2 = imagehash.hex_to_hash(hash2)
        return h1 - h2
    except Exception:
        return 999


def is_near_duplicate(hash1: str, hash2: str, threshold: int = PHASH_DISTANCE_THRESHOLD) -> bool:
    return phash_distance(hash1, hash2) <= threshold


def find_exact_duplicates(hash_map: Dict[str, List[int]]) -> Dict[str, List[int]]:
    """
    Given {sha256: [media_id, ...]}, return only groups with >1 entry.
    """
    return {h: ids for h, ids in hash_map.items() if len(ids) > 1}


def find_near_duplicates(
    phash_list: List[Tuple[int, str]],
    threshold: int = PHASH_DISTANCE_THRESHOLD,
) -> List[Tuple[int, int, int]]:
    """
    Compare all phash pairs. Returns list of (media_id_a, media_id_b, distance).
    O(n^2) — acceptable for photo libraries up to ~50k images.
    """
    if not HAS_IMAGEHASH:
        return []

    results = []
    hashes = []
    for media_id, hash_str in phash_list:
        try:
            hashes.append((media_id, imagehash.hex_to_hash(hash_str)))
        except Exception:
            continue

    n = len(hashes)
    for i in range(n):
        for j in range(i + 1, n):
            dist = hashes[i][1] - hashes[j][1]
            if dist <= threshold:
                results.append((hashes[i][0], hashes[j][0], dist))

    return results
