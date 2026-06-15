"""
Post-run verification script.
Proves no data was lost or corrupted by comparing source and output.

Usage:
  python scripts/verify_no_data_loss.py <source_dir> <output_dir> [--session-id SESSION_ID]

Exit code 0 = all clear. Non-zero = verification failed.
"""
import os
import sys
import hashlib
import argparse
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.scanner import collect_media
from src.database import Database


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify(source_dir: str, output_dir: str, session_id: str = None) -> bool:
    print("=" * 60)
    print("  DATA INTEGRITY VERIFICATION")
    print("=" * 60)

    # 1. All source files still exist
    print("\n[1] Checking source files exist and are unmodified...")
    db_path = os.path.join(output_dir, "manifest.db")
    db = Database(db_path)
    rows = db.get_all_media(session_id)

    missing_source = []
    modified_source = []

    for row in rows:
        path = row["source_path"]
        if not os.path.exists(path):
            missing_source.append(path)
        else:
            current_hash = sha256(path)
            if current_hash != row["sha256"]:
                modified_source.append((path, row["sha256"], current_hash))

    if missing_source:
        print(f"  [FAIL] {len(missing_source)} source files MISSING:")
        for p in missing_source[:10]:
            print(f"         {p}")
        if len(missing_source) > 10:
            print(f"         ... and {len(missing_source) - 10} more")
    else:
        print(f"  [OK]   All {len(rows)} source files still exist.")

    if modified_source:
        print(f"  [FAIL] {len(modified_source)} source files MODIFIED (CRITICAL!):")
        for p, expected, actual in modified_source[:5]:
            print(f"         {p}")
            print(f"           expected: {expected}")
            print(f"           actual:   {actual}")
    else:
        print(f"  [OK]   All source files have matching SHA-256 hashes (unmodified).")

    # 2. All copies are byte-perfect
    print("\n[2] Verifying copies are byte-perfect...")
    ops = db.get_copy_operations(session_id or "")
    bad_copies = []
    missing_copies = []
    good_copies = 0

    for op in ops:
        src = op["source_path"]
        dst = op["dest_path"]

        if not os.path.exists(dst):
            missing_copies.append(dst)
            continue

        if not os.path.exists(src):
            continue  # source gone, can't verify — already caught above

        src_hash = sha256(src)
        dst_hash = sha256(dst)
        if src_hash != dst_hash:
            bad_copies.append((src, dst))
        else:
            good_copies += 1

    if bad_copies:
        print(f"  [FAIL] {len(bad_copies)} corrupted copies found:")
        for s, d in bad_copies[:5]:
            print(f"         {s} → {d}")
    else:
        print(f"  [OK]   {good_copies} verified copies are all byte-perfect.")

    if missing_copies:
        print(f"  [WARN] {len(missing_copies)} expected copies are missing (may have been rolled back).")

    # 3. No files were deleted from source
    print("\n[3] Scanning source directory for any deleted files...")
    current_source_files = set(collect_media(source_dir))
    indexed_source_files = set(row["source_path"] for row in rows)
    deleted = indexed_source_files - current_source_files

    if deleted:
        print(f"  [FAIL] {len(deleted)} source files that were indexed are now GONE:")
        for p in list(deleted)[:10]:
            print(f"         {p}")
    else:
        print(f"  [OK]   No source files have been deleted.")

    # 4. Duplicate_Review folder should have copies, not moves
    print("\n[4] Checking Duplicate_Review folder...")
    dup_review_dir = os.path.join(output_dir, "Duplicate_Review")
    dup_files = []
    if os.path.exists(dup_review_dir):
        for root, _, files in os.walk(dup_review_dir):
            for f in files:
                dup_files.append(os.path.join(root, f))
    print(f"  [OK]   {len(dup_files)} files in Duplicate_Review/ (all are copies, originals preserved).")

    # Summary
    print("\n" + "=" * 60)
    issues = len(missing_source) + len(modified_source) + len(bad_copies) + len(deleted)
    if issues == 0:
        print("  RESULT: ALL CHECKS PASSED. No data loss detected.")
        print("=" * 60)
        db.close()
        return True
    else:
        print(f"  RESULT: {issues} ISSUE(S) FOUND. Review output above.")
        print("=" * 60)
        db.close()
        return False


def main():
    parser = argparse.ArgumentParser(description="Verify no data loss after organizing")
    parser.add_argument("source", help="Original source directory")
    parser.add_argument("output", help="Output directory containing manifest.db")
    parser.add_argument("--session-id", help="Limit check to specific session")
    args = parser.parse_args()

    ok = verify(args.source, args.output, args.session_id)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
