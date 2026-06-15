"""
Duplicate detection tests.
Run: python -m pytest tests/test_duplicates.py -v
"""
import os
import sys
import shutil
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.hasher import sha256_file, phash_image, phash_distance, is_near_duplicate, find_near_duplicates

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="organizer_dup_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_jpeg(path, color, size=(100, 100)):
    if HAS_PILLOW:
        Image.new("RGB", size, color=color).save(path, "JPEG")
    else:
        with open(path, "wb") as f:
            f.write(b"\xFF\xD8\xFF" + b"\x00" * 100)


def test_exact_duplicate_detected(tmp_dir):
    p1 = os.path.join(tmp_dir, "a.jpg")
    p2 = os.path.join(tmp_dir, "b.jpg")
    _make_jpeg(p1, (255, 0, 0))
    shutil.copy2(p1, p2)

    h1 = sha256_file(p1)
    h2 = sha256_file(p2)
    assert h1 == h2, "Exact duplicate must have identical SHA-256"


def test_different_files_different_hash(tmp_dir):
    p1 = os.path.join(tmp_dir, "a.jpg")
    p2 = os.path.join(tmp_dir, "b.jpg")
    _make_jpeg(p1, (255, 0, 0))
    _make_jpeg(p2, (0, 255, 0))

    h1 = sha256_file(p1)
    h2 = sha256_file(p2)
    assert h1 != h2, "Different images must have different SHA-256"


@pytest.mark.skipif(not HAS_PILLOW, reason="Pillow required for pHash tests")
def test_phash_identical_images(tmp_dir):
    p1 = os.path.join(tmp_dir, "a.jpg")
    p2 = os.path.join(tmp_dir, "b.jpg")
    _make_jpeg(p1, (128, 64, 32))
    shutil.copy2(p1, p2)

    h1 = phash_image(p1)
    h2 = phash_image(p2)
    assert h1 is not None
    assert h1 == h2
    assert phash_distance(h1, h2) == 0


@pytest.mark.skipif(not HAS_PILLOW, reason="Pillow required for pHash tests")
def test_phash_near_duplicate(tmp_dir):
    p1 = os.path.join(tmp_dir, "original.jpg")
    p2 = os.path.join(tmp_dir, "slightly_modified.jpg")

    _make_jpeg(p1, (100, 100, 100), size=(200, 200))

    # Modify one pixel — still visually identical
    with Image.open(p1) as img:
        px = img.load()
        px[0, 0] = (105, 100, 100)
        img.save(p2, "JPEG")

    h1 = phash_image(p1)
    h2 = phash_image(p2)
    assert h1 is not None and h2 is not None
    dist = phash_distance(h1, h2)
    assert is_near_duplicate(h1, h2), f"Near-duplicate distance {dist} should be ≤ 8"


@pytest.mark.skipif(not HAS_PILLOW, reason="Pillow required for pHash tests")
def test_phash_different_images_not_near_dup(tmp_dir):
    p1 = os.path.join(tmp_dir, "img1.jpg")
    p2 = os.path.join(tmp_dir, "img2.jpg")
    
    img1 = Image.new("RGB", (200, 200), color="white")
    for x in range(100):
        for y in range(100):
            img1.putpixel((x, y), (0, 0, 0))
    img1.save(p1, "JPEG")
    
    img2 = Image.new("RGB", (200, 200), color="white")
    for x in range(100, 200):
        for y in range(100, 200):
            img2.putpixel((x, y), (0, 0, 0))
    img2.save(p2, "JPEG")

    h1 = phash_image(p1)
    h2 = phash_image(p2)
    assert h1 is not None and h2 is not None
    assert not is_near_duplicate(h1, h2), "Completely different images should not be near-duplicates"


@pytest.mark.skipif(not HAS_PILLOW, reason="Pillow required for pHash tests")
def test_find_near_duplicates(tmp_dir):
    paths = []
    for i, color in enumerate([(100, 0, 0), (100, 0, 0), (0, 255, 0)]):
        p = os.path.join(tmp_dir, f"img_{i}.jpg")
        _make_jpeg(p, color, size=(200, 200))
        paths.append(p)

    phash_list = [(i + 1, phash_image(p)) for i, p in enumerate(paths) if phash_image(p)]
    near_dups = find_near_duplicates(phash_list)

    dup_pairs = [(a, b) for a, b, d in near_dups]
    assert (1, 2) in dup_pairs or (2, 1) in dup_pairs, "Images 1 and 2 should be near-duplicates"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
