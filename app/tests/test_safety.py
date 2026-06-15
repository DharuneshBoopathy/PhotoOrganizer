"""
Safety tests: verify no source files are modified and all copies are verified.
Run: python -m pytest tests/test_safety.py -v
"""
import os
import sys
import shutil
import hashlib
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.safety import safe_copy, verify_copy, preflight_check, SafetyError, SourceFileGuard


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


@pytest.fixture
def tmp_dirs():
    src_dir = tempfile.mkdtemp(prefix="organizer_test_src_")
    dst_dir = tempfile.mkdtemp(prefix="organizer_test_dst_")
    yield src_dir, dst_dir
    shutil.rmtree(src_dir, ignore_errors=True)
    shutil.rmtree(dst_dir, ignore_errors=True)


def test_safe_copy_preserves_source(tmp_dirs):
    src_dir, dst_dir = tmp_dirs
    src = os.path.join(src_dir, "photo.jpg")
    with open(src, "wb") as f:
        f.write(b"FAKE_JPEG_DATA_" * 100)

    original_hash = sha256(src)
    ok, dest = safe_copy(src, os.path.join(dst_dir, "photo.jpg"), verify=True)

    assert ok, "safe_copy must succeed"
    assert os.path.exists(dest), "destination must exist"
    assert sha256(src) == original_hash, "SOURCE MODIFIED — SAFETY VIOLATION"


def test_safe_copy_integrity(tmp_dirs):
    src_dir, dst_dir = tmp_dirs
    src = os.path.join(src_dir, "photo.jpg")
    with open(src, "wb") as f:
        f.write(b"\xFF\xD8\xFF" + os.urandom(1024))

    ok, dest = safe_copy(src, os.path.join(dst_dir, "photo.jpg"), verify=True)
    assert ok
    assert verify_copy(src, dest), "Copy must be byte-perfect"


def test_safe_copy_no_overwrite(tmp_dirs):
    src_dir, dst_dir = tmp_dirs
    src = os.path.join(src_dir, "photo.jpg")
    with open(src, "wb") as f:
        f.write(b"DATA_A" * 50)

    dest_path = os.path.join(dst_dir, "photo.jpg")

    # Pre-create destination with DIFFERENT content
    with open(dest_path, "wb") as f:
        f.write(b"DATA_B" * 50)

    ok, final_dest = safe_copy(src, dest_path, verify=True)
    assert ok
    assert final_dest != dest_path, "Must not overwrite existing file"
    assert os.path.exists(dest_path), "Original destination must still exist"
    assert open(dest_path, "rb").read() == b"DATA_B" * 50, "Original destination must be unchanged"


def test_preflight_rejects_nested_output(tmp_dirs):
    src_dir, _ = tmp_dirs
    nested_output = os.path.join(src_dir, "output")
    with pytest.raises(SafetyError):
        preflight_check(src_dir, nested_output)


def test_preflight_rejects_missing_source():
    with pytest.raises(SafetyError):
        preflight_check("/nonexistent/path/12345", "/tmp/out")


def test_source_file_guard(tmp_dirs):
    src_dir, _ = tmp_dirs
    path = os.path.join(src_dir, "test.jpg")
    with open(path, "wb") as f:
        f.write(b"ORIGINAL_DATA")

    # Guard should pass when file is unchanged
    with SourceFileGuard(path):
        pass  # nothing happens

    # Guard should raise when file is modified
    with pytest.raises(SafetyError):
        with SourceFileGuard(path):
            with open(path, "wb") as f:
                f.write(b"MODIFIED_DATA")


def test_no_source_deletion(tmp_dirs):
    src_dir, dst_dir = tmp_dirs
    files = []
    for i in range(5):
        p = os.path.join(src_dir, f"photo_{i}.jpg")
        with open(p, "wb") as f:
            f.write(f"DATA_{i}".encode() * 100)
        files.append(p)

    # Copy all files
    for p in files:
        safe_copy(p, os.path.join(dst_dir, os.path.basename(p)), verify=True)

    # All source files must still exist and be unchanged
    for p in files:
        assert os.path.exists(p), f"Source file deleted: {p}"
        content = open(p, "rb").read()
        assert len(content) > 0, f"Source file emptied: {p}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
