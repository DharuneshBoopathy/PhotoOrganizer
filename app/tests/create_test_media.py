"""
Creates synthetic test media files (images + a video placeholder)
in a temp directory for safe testing without touching real photos.

Run: python tests/create_test_media.py
"""
import os
import sys
import shutil
import struct
import hashlib
import tempfile
from datetime import datetime, timedelta

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    print("[WARNING] Pillow not installed — creating raw JPEG stubs instead.")

TEST_DIR = os.path.join(os.path.dirname(__file__), "..", "test_data", "source")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "test_data", "output")


def make_image_with_exif(path: str, date: datetime, color: tuple, label: str):
    """Create a simple colored JPEG with text and embedded EXIF date."""
    if not HAS_PILLOW:
        _make_stub_jpeg(path)
        return

    img = Image.new("RGB", (640, 480), color=color)
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), label, fill=(255, 255, 255))
    draw.text((20, 50), date.strftime("%Y-%m-%d %H:%M:%S"), fill=(255, 255, 255))

    # Save with EXIF date via piexif if available
    try:
        import piexif
        exif_dict = {
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: date.strftime("%Y:%m:%d %H:%M:%S").encode(),
                piexif.ExifIFD.DateTimeDigitized: date.strftime("%Y:%m:%d %H:%M:%S").encode(),
            }
        }
        exif_bytes = piexif.dump(exif_dict)
        img.save(path, "JPEG", exif=exif_bytes, quality=85)
    except ImportError:
        img.save(path, "JPEG", quality=85)


def _make_stub_jpeg(path: str):
    """Minimal valid JPEG header for stub files."""
    stub = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10,
                  0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
                  0x01, 0x00, 0x00, 0x01, 0x00, 0x01,
                  0x00, 0x00, 0xFF, 0xD9])
    with open(path, "wb") as f:
        f.write(stub)


def make_duplicate(source: str, dest: str):
    """Byte-perfect copy to simulate exact duplicate."""
    shutil.copy2(source, dest)


def make_near_duplicate(source: str, dest: str):
    """Slightly-modified copy to simulate near-duplicate."""
    if not HAS_PILLOW:
        shutil.copy2(source, dest)
        return
    with Image.open(source) as img:
        pixels = img.load()
        w, h = img.size
        # Flip one pixel
        if w > 1 and h > 1:
            r, g, b = pixels[0, 0]
            pixels[0, 0] = (min(r + 5, 255), g, b)
        img.save(dest, "JPEG", quality=85)


def create_test_dataset():
    os.makedirs(TEST_DIR, exist_ok=True)
    os.makedirs(os.path.join(TEST_DIR, "vacation_2023"), exist_ok=True)
    os.makedirs(os.path.join(TEST_DIR, "family_2024"), exist_ok=True)
    os.makedirs(os.path.join(TEST_DIR, "duplicates"), exist_ok=True)

    base_date = datetime(2023, 7, 15, 10, 0, 0)

    # 5 vacation photos (different dates)
    for i in range(5):
        d = base_date + timedelta(days=i, hours=i * 2)
        path = os.path.join(TEST_DIR, "vacation_2023", f"vacation_{i:02d}.jpg")
        make_image_with_exif(path, d, (50 + i * 30, 100, 150), f"Vacation photo {i}")
        print(f"  Created: {path}")

    # 3 family photos
    fam_date = datetime(2024, 1, 5, 14, 30, 0)
    for i in range(3):
        d = fam_date + timedelta(hours=i)
        path = os.path.join(TEST_DIR, "family_2024", f"family_{i:02d}.jpg")
        make_image_with_exif(path, d, (200, 50 + i * 40, 100), f"Family photo {i}")
        print(f"  Created: {path}")

    # Exact duplicate of vacation_00
    src = os.path.join(TEST_DIR, "vacation_2023", "vacation_00.jpg")
    dup_exact = os.path.join(TEST_DIR, "duplicates", "vacation_00_EXACT_DUP.jpg")
    make_duplicate(src, dup_exact)
    print(f"  Created exact duplicate: {dup_exact}")

    # Near-duplicate of vacation_01
    src2 = os.path.join(TEST_DIR, "vacation_2023", "vacation_01.jpg")
    dup_near = os.path.join(TEST_DIR, "duplicates", "vacation_01_NEAR_DUP.jpg")
    make_near_duplicate(src2, dup_near)
    print(f"  Created near-duplicate: {dup_near}")

    # PNG file
    if HAS_PILLOW:
        png_path = os.path.join(TEST_DIR, "screenshot.png")
        img = Image.new("RGB", (1920, 1080), color=(30, 30, 50))
        draw = ImageDraw.Draw(img)
        draw.text((100, 100), "Screenshot 2024-03-01", fill=(200, 200, 200))
        img.save(png_path, "PNG")
        print(f"  Created: {png_path}")

    total = len([f for _, _, files in os.walk(TEST_DIR) for f in files])
    print(f"\nTest dataset ready: {TEST_DIR}")
    print(f"Total files: {total}")
    print(f"\nTo run the organizer on this test data:")
    print(f"  python -m src.cli organize {TEST_DIR} {OUTPUT_DIR}")


if __name__ == "__main__":
    print("Creating test media dataset...")
    create_test_dataset()
