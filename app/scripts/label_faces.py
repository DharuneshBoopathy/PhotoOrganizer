"""
Interactive face labeling tool.
Lists all face clusters and lets you assign person names.
After labeling, re-run the organizer to rename Photos_By_Face folders.

Usage:
  python scripts/label_faces.py <output_dir>
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database import Database
from src.organizer import face_folder_path
from src.safety import safe_copy


def relabel_face_folder(output_dir: str, cluster_key: str, old_label: str, new_label: str):
    """Rename Photos_By_Face/<old> → Photos_By_Face/<new>."""
    old_dir = face_folder_path(output_dir, cluster_key, old_label)
    new_dir = face_folder_path(output_dir, cluster_key, new_label)

    if not os.path.exists(old_dir):
        print(f"  Folder not found: {old_dir}")
        return

    if os.path.exists(new_dir):
        print(f"  Target already exists: {new_dir}")
        return

    os.rename(old_dir, new_dir)
    print(f"  Renamed: {old_dir} → {new_dir}")


def main():
    parser = argparse.ArgumentParser(description="Label face clusters interactively")
    parser.add_argument("output", help="Output directory containing manifest.db")
    args = parser.parse_args()

    db_path = os.path.join(args.output, "manifest.db")
    if not os.path.exists(db_path):
        print(f"[ERROR] No manifest.db found at: {db_path}")
        sys.exit(1)

    db = Database(db_path)
    clusters = db.get_face_clusters()

    if not clusters:
        print("No face clusters found. Run organize first.")
        db.close()
        return

    print(f"\nFound {len(clusters)} face clusters:\n")
    print(f"  {'#':<4} {'Cluster Key':<20} {'Current Label':<25} {'Photos':>8}")
    print("  " + "-" * 60)
    for i, c in enumerate(clusters):
        label = c["label"] or "(unlabeled)"
        print(f"  {i+1:<4} {c['cluster_key']:<20} {label:<25} {c['member_count']:>8}")

    print("\nAssign names (format: cluster_key=Person Name). Press Enter to finish.\n")

    while True:
        line = input("  > ").strip()
        if not line:
            break
        if "=" not in line:
            print("    Format: person_0001=Alice Smith")
            continue
        key, name = line.split("=", 1)
        key = key.strip()
        name = name.strip()

        existing = next((c for c in clusters if c["cluster_key"] == key), None)
        if not existing:
            print(f"    Cluster key '{key}' not found.")
            continue

        old_label = existing["label"]
        db.label_face_cluster(key, name)
        relabel_face_folder(args.output, key, old_label, name)
        print(f"    {key} → {name}")

    db.close()
    print("\nDone. Face clusters labeled.")


if __name__ == "__main__":
    main()
