"""
Rollback script — deletes all COPIES made by a session.
Source files are NEVER touched.

Usage:
  python scripts/rollback.py <output_dir> <session_id> [--dry-run]
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database import Database
from src.safety import rollback_session


def main():
    parser = argparse.ArgumentParser(description="Roll back an organize session")
    parser.add_argument("output", help="Output directory containing manifest.db")
    parser.add_argument("session_id", help="Session ID to roll back")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    args = parser.parse_args()

    db_path = os.path.join(args.output, "manifest.db")
    if not os.path.exists(db_path):
        print(f"[ERROR] No manifest.db found at: {db_path}")
        sys.exit(1)

    db = Database(db_path)
    session = db.get_session(args.session_id)
    if not session:
        print(f"[ERROR] Session not found: {args.session_id}")
        db.close()
        sys.exit(1)

    print(f"Session: {args.session_id}")
    print(f"Source:  {session['source_dir']}")
    print(f"Output:  {session['output_dir']}")
    print(f"Status:  {session['status']}")
    print(f"Files:   {session['total_files']}")

    if not args.dry_run:
        confirm = input("\nThis will delete all COPIES made in this session. "
                        "Original source files will NOT be touched.\nType 'yes' to continue: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            db.close()
            sys.exit(0)

    deleted, errors = rollback_session(db, args.session_id, dry_run=args.dry_run)
    prefix = "[DRY RUN] Would delete" if args.dry_run else "Deleted"
    print(f"\n{prefix} {deleted} files. {errors} errors.")
    if errors > 0:
        print("[WARNING] Some files could not be deleted. Check logs.")

    db.close()


if __name__ == "__main__":
    main()
