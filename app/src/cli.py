"""
Command-line interface for the Photo Organizer.

Usage:  python -m src.cli <command> [options]

Commands:
  organize          Run the full pipeline (scan + organize + faces + …)
  scan              Just list media files in a folder
  status            Show recent pipeline sessions
  rollback          Undo a session (deletes COPIES, never originals)

  label             Label / rename a face cluster
  list-clusters     Show clusters with quality + count
  review-clusters   Same plus ambiguous-face report
  regenerate-icons  Rebuild avatars, contact sheets, folder icons

  merge             Merge cluster A into cluster B
  split             Split selected detections out into a new cluster

  duplicates        List exact + near duplicates
  timeline          Build per-person timeline.jpg + timeline.html
  album             Build per-person album.html
  burst             Detect burst-shot groups
  strangers         Detect & quarantine stranger clusters
  relationships     Build co-occurrence folders
  search            Query the catalog by person/date/location
  report            Generate root-level report.html
  xmp               Write XMP sidecars for tagged photos
  gui               Launch the desktop GUI
"""
import argparse
import os
import sys
import json

from .main import run_pipeline
from .database import Database
from .safety import rollback_session


DB_NAME = "manifest.db"


def _open_db(output: str) -> Database:
    db_path = os.path.join(output, DB_NAME)
    if not os.path.isfile(db_path):
        print(f"No database found at: {db_path}", file=sys.stderr)
        sys.exit(2)
    return Database(db_path)


# ============================================================================
# Pipeline
# ============================================================================
def cmd_organize(args):
    run_pipeline(
        source_dir=args.source,
        output_dir=args.output,
        enable_faces=not args.no_faces,
        enable_location=not args.no_location,
        enable_icons=not args.no_icons,
        enable_duplicates=not args.no_duplicates,
        enable_timeline=args.timeline,
        enable_strangers=args.strangers,
        incremental=args.incremental,
        scan_only=args.scan_only,
        verbose=args.verbose,
        model_dir=args.model_dir,
        face_threshold=args.face_threshold,
    )


def cmd_scan(args):
    from .scanner import collect_media, get_media_type
    paths = collect_media(args.source)
    print(f"Found {len(paths)} media files in: {args.source}")
    if args.list:
        for p in paths:
            print(f"  [{get_media_type(p):5s}] {p}")


def cmd_status(args):
    db = _open_db(args.output)
    sessions = db.get_all_sessions()
    if not sessions:
        print("No sessions found.")
        return
    print(f"\n{'Session ID':<30} {'Status':<12} {'Files':>8} {'Dups':>6} {'Started'}")
    print("-" * 80)
    for s in sessions:
        print(f"{s['id']:<30} {s['status']:<12} {s['total_files']:>8} "
              f"{s['duplicates_found']:>6} {s['started_at']}")
    db.close()


def cmd_rollback(args):
    db = _open_db(args.output)
    if args.dry_run:
        deleted, errors = rollback_session(db, args.session_id, dry_run=True)
        print(f"[dry-run] would delete {deleted} files; {errors} errors.")
    else:
        confirm = input(
            f"Rollback session {args.session_id}? Deletes COPIES (originals untouched). "
            f"Type 'yes' to proceed: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return
        deleted, errors = rollback_session(db, args.session_id, dry_run=False)
        print(f"Rollback complete. Deleted {deleted} files; {errors} errors.")
    db.close()


# ============================================================================
# Labeling / clusters
# ============================================================================
def cmd_label(args):
    from .labeling import label_person
    db = _open_db(args.output)
    ok = label_person(db, args.output, args.cluster_key, args.name)
    print(f"label {args.cluster_key} → {args.name!r}: {'ok' if ok else 'failed'}")
    db.close()


def cmd_list_clusters(args):
    db = _open_db(args.output)
    clusters = db.get_face_clusters()
    if not clusters:
        print("No face clusters found.")
        db.close()
        return
    print(f"\n{'Cluster':<22} {'Label':<22} {'Count':>6} {'Cohesion':>9} {'Flag':<10} Stranger")
    print("-" * 86)
    for c in clusters:
        if not args.all and c["cluster_key"].startswith("unknown_"):
            continue
        cohesion = f"{c['cohesion']:.3f}" if c["cohesion"] is not None else "-"
        print(f"{c['cluster_key']:<22} {(c['label'] or '(unlabeled)'):<22} "
              f"{c['member_count'] or 0:>6} {cohesion:>9} "
              f"{(c['quality_flag'] or '-'):<10} {'yes' if c['is_stranger'] else ''}")
    db.close()


def cmd_review_clusters(args):
    cmd_list_clusters(args)
    amb_path = os.path.join(args.output, "Index", "ambiguous_faces.json")
    if not os.path.isfile(amb_path):
        return
    with open(amb_path, "r", encoding="utf-8") as f:
        amb = json.load(f)
    print(f"\n{len(amb)} ambiguous face(s) (low margin between top-2 clusters):")
    for a in amb[:20]:
        print(f"  detection {a['detection_id']}: {a['cluster_key']} ~ {a['alt_cluster_key']} "
              f"(margin {a['margin']})")
    if len(amb) > 20:
        print(f"  ... and {len(amb) - 20} more (full list at {amb_path})")


def cmd_regenerate_icons(args):
    from .cluster_repair import _rebuild_cluster_identity
    db = _open_db(args.output)
    clusters = db.get_face_clusters()
    n = 0
    for c in clusters:
        if c["cluster_key"].startswith("unknown_"):
            continue
        _rebuild_cluster_identity(db, args.output, c["cluster_key"])
        n += 1
        print(f"  [{n:3d}] {c['cluster_key']}: {c['label'] or '(unlabeled)'} "
              f"({c['member_count']} photos)")
    db.close()
    print(f"\nRegenerated identity assets for {n} clusters.")


def cmd_merge(args):
    from .cluster_repair import merge_clusters
    db = _open_db(args.output)
    res = merge_clusters(db, args.output, args.source, args.target)
    print(json.dumps(res, indent=2))
    db.close()


def cmd_split(args):
    from .cluster_repair import split_cluster
    db = _open_db(args.output)
    detection_ids = [int(x) for x in args.detection_ids.split(",") if x.strip()]
    res = split_cluster(db, args.output, args.source, detection_ids,
                         new_label=args.label)
    print(json.dumps(res, indent=2))
    db.close()


# ============================================================================
# Auxiliary features
# ============================================================================
def cmd_duplicates(args):
    db = _open_db(args.output)
    rows = [m for m in db.get_all_media() if m["is_duplicate"]]
    print(f"\nDuplicate files ({len(rows)} total):")
    print(f"{'Source Path':<70} {'Dup Of ID':>10}")
    print("-" * 82)
    for r in rows[:200]:
        print(f"{r['source_path'][:70]:<70} {r['duplicate_of_id']:>10}")
    if len(rows) > 200:
        print(f"  ... and {len(rows) - 200} more.")
    db.close()


def cmd_timeline(args):
    from .timeline import build_timeline_for_cluster, build_timelines_all
    db = _open_db(args.output)
    if args.cluster_key:
        out = build_timeline_for_cluster(db, args.output, args.cluster_key)
        print(out or "(failed)")
    else:
        summary = build_timelines_all(db, args.output)
        print(f"Built {sum(1 for v in summary.values() if v)} timelines.")
    db.close()


def cmd_album(args):
    from .person_album import build_album_for_cluster, build_albums_all
    db = _open_db(args.output)
    if args.cluster_key:
        out = build_album_for_cluster(db, args.output, args.cluster_key)
        print(out or "(failed)")
    else:
        summary = build_albums_all(db, args.output)
        print(f"Built {len(summary)} albums.")
    db.close()


def cmd_burst(args):
    from .burst_detector import build_burst_folders
    db = _open_db(args.output)
    summary = build_burst_folders(db, args.output)
    print(f"Found {len(summary)} burst groups.")
    for name, info in list(summary.items())[:20]:
        print(f"  {name}: {info['members']} photos (keeper={info['keeper']})")
    db.close()


def cmd_strangers(args):
    from .stranger_filter import detect_strangers, quarantine_strangers
    db = _open_db(args.output)
    keys = detect_strangers(db, min_recurrence=args.min_recurrence)
    print(f"Flagged {len(keys)} stranger clusters.")
    if args.apply:
        res = quarantine_strangers(db, args.output, keys)
        print(json.dumps(res, indent=2))
    else:
        for k in keys:
            print(f"  {k}")
        if keys:
            print("\n(use --apply to actually quarantine them)")
    db.close()


def cmd_relationships(args):
    from .relationships import build_relationship_folders
    db = _open_db(args.output)
    summary = build_relationship_folders(db, args.output, min_count=args.min_count)
    print(f"Built {len(summary)} relationship folders.")
    db.close()


def cmd_search(args):
    from .search import search_media
    db = _open_db(args.output)
    rows = search_media(
        db,
        person=args.person,
        date_from=args.date_from,
        date_to=args.date_to,
        location=args.location,
        filename=args.filename,
        media_type=args.media_type,
        limit=args.limit,
    )
    print(f"\n{len(rows)} result(s):")
    for r in rows[: args.limit]:
        date = r.get("date_taken") or r.get("date_file_modified") or "?"
        print(f"  [{date[:10]}] {r['source_path']}")
    db.close()


def cmd_report(args):
    from .report import build_report
    db = _open_db(args.output)
    out = build_report(db, args.output)
    print(f"report: {out}")
    db.close()


def cmd_xmp(args):
    from .xmp_tags import write_xmp_sidecars
    db = _open_db(args.output)
    res = write_xmp_sidecars(db, args.output, in_source_dir=args.in_source)
    print(json.dumps(res, indent=2))
    db.close()


def cmd_gui(args):
    from .gui_app import main as gui_main
    gui_main()


# ============================================================================
# Argparse wiring
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        prog="photo-organizer",
        description="Photo Organizer — local-first, offline, archival-grade",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- organize ----
    p = sub.add_parser("organize", help="Run the full pipeline")
    p.add_argument("source")
    p.add_argument("output")
    p.add_argument("--no-faces", action="store_true")
    p.add_argument("--no-location", action="store_true")
    p.add_argument("--no-icons", action="store_true")
    p.add_argument("--no-duplicates", action="store_true")
    p.add_argument("--timeline", action="store_true",
                    help="Also build per-person timelines")
    p.add_argument("--strangers", action="store_true",
                    help="Also detect + quarantine strangers")
    p.add_argument("--incremental", action="store_true",
                    help="Skip files already processed (mtime+size match)")
    p.add_argument("--scan-only", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--model-dir")
    p.add_argument("--face-threshold", type=float, default=0.4)
    p.set_defaults(func=cmd_organize)

    # ---- scan ----
    p = sub.add_parser("scan", help="List media files (no copying)")
    p.add_argument("source")
    p.add_argument("--list", action="store_true")
    p.set_defaults(func=cmd_scan)

    # ---- status / rollback ----
    p = sub.add_parser("status", help="Show recent sessions")
    p.add_argument("output"); p.set_defaults(func=cmd_status)

    p = sub.add_parser("rollback", help="Undo a session (deletes copies only)")
    p.add_argument("output"); p.add_argument("session_id")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_rollback)

    # ---- labeling / clusters ----
    p = sub.add_parser("label", help="Set or change a cluster's name")
    p.add_argument("output")
    p.add_argument("cluster_key")
    p.add_argument("name")
    p.set_defaults(func=cmd_label)

    p = sub.add_parser("list-clusters", help="Show all clusters")
    p.add_argument("output")
    p.add_argument("--all", action="store_true",
                    help="Include unknown_* clusters")
    p.set_defaults(func=cmd_list_clusters)

    p = sub.add_parser("review-clusters", help="List clusters + ambiguous faces")
    p.add_argument("output")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_review_clusters)

    p = sub.add_parser("regenerate-icons",
                        help="Rebuild avatars / contact sheets / folder icons")
    p.add_argument("output")
    p.set_defaults(func=cmd_regenerate_icons)

    p = sub.add_parser("merge", help="Merge cluster A into B")
    p.add_argument("output")
    p.add_argument("source", help="source cluster_key (will be removed)")
    p.add_argument("target", help="target cluster_key")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("split", help="Split detections out into a new cluster")
    p.add_argument("output")
    p.add_argument("source", help="source cluster_key")
    p.add_argument("detection_ids", help="comma-separated detection IDs")
    p.add_argument("--label", help="optional label for the new cluster")
    p.set_defaults(func=cmd_split)

    # ---- features ----
    p = sub.add_parser("duplicates", help="List duplicate files")
    p.add_argument("output"); p.set_defaults(func=cmd_duplicates)

    p = sub.add_parser("timeline", help="Build per-person timeline")
    p.add_argument("output")
    p.add_argument("--cluster-key", help="single cluster (default: all)")
    p.set_defaults(func=cmd_timeline)

    p = sub.add_parser("album", help="Build per-person album.html")
    p.add_argument("output")
    p.add_argument("--cluster-key")
    p.set_defaults(func=cmd_album)

    p = sub.add_parser("burst", help="Detect burst-shot groups")
    p.add_argument("output"); p.set_defaults(func=cmd_burst)

    p = sub.add_parser("strangers", help="Detect / quarantine background people")
    p.add_argument("output")
    p.add_argument("--min-recurrence", type=int, default=3)
    p.add_argument("--apply", action="store_true",
                    help="actually move folders (otherwise just preview)")
    p.set_defaults(func=cmd_strangers)

    p = sub.add_parser("relationships", help="Build co-occurrence folders")
    p.add_argument("output")
    p.add_argument("--min-count", type=int, default=2)
    p.set_defaults(func=cmd_relationships)

    p = sub.add_parser("search", help="Query the catalog")
    p.add_argument("output")
    p.add_argument("--person")
    p.add_argument("--date-from")
    p.add_argument("--date-to")
    p.add_argument("--location")
    p.add_argument("--filename")
    p.add_argument("--media-type", choices=("image", "video"))
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("report", help="Build root-level report.html")
    p.add_argument("output"); p.set_defaults(func=cmd_report)

    p = sub.add_parser("xmp", help="Write XMP sidecars")
    p.add_argument("output")
    p.add_argument("--in-source", action="store_true",
                    help="write next to originals (default: central folder)")
    p.set_defaults(func=cmd_xmp)

    p = sub.add_parser("gui", help="Launch the desktop GUI")
    p.set_defaults(func=cmd_gui)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
