"""
Main orchestration pipeline.
Stages:
  1. Preflight safety checks
  2. Scan + index all media (with incremental skip support)
  3. Hash (SHA-256 + pHash) and detect duplicates
  4. Face detection + clustering
  5. Organize: copy files into output structure (transactional)
  6. Identity assets: avatars, icons, contact sheets
  7. Finalize session in DB

Pipeline supports:
  - progress_callback(stage, current, total, **kwargs) for GUI integration
  - cancel_event (threading.Event) for safe interruption
"""
import os
import sys
import logging
import threading
from datetime import datetime
from typing import Optional, Callable, Dict, Any

try:
    from tqdm import tqdm
except ImportError:
    # tqdm is only used for the CLI progress bar. The GUI path uses a
    # progress_callback instead, so a missing tqdm should not break the
    # bundled .exe. Fall back to a no-op shim with the same surface area.
    class _TqdmShim:
        def __init__(self, iterable=None, total=None, **kw):
            self.iterable = iterable if iterable is not None else []
            self.total = total
            self.n = 0
        def __iter__(self):
            for x in self.iterable:
                self.n += 1
                yield x
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def update(self, n=1): self.n += n
        def set_description(self, *a, **kw): pass
        def set_postfix(self, *a, **kw): pass
        def close(self): pass
        def write(self, msg): print(msg)
    def tqdm(iterable=None, **kw):
        return _TqdmShim(iterable=iterable, **kw)

from .database import Database
from .scanner import collect_media, get_media_type, get_mime_type
from .metadata import extract_metadata, format_gps_label
from .hasher import sha256_file, phash_image, find_near_duplicates
from .thumbnail import generate_thumbnail
from .face_engine import FaceEngine, embedding_to_bytes, cluster_embeddings
from .organizer import (
    create_output_structure,
    organize_by_date,
    organize_by_location,
    organize_by_face,
    stage_duplicate_for_review,
    face_folder_path,
)
from .safety import preflight_check, assert_no_network_access, SafetyError
from .utils import setup_logging, new_session_id
from .identity import (
    score_all_detections_for_cluster,
    write_cluster_avatar,
    write_contact_sheet,
    write_person_summary,
    compute_cluster_cohesion,
    find_ambiguous_detections,
)
from .folder_icon import install_folder_icon, refresh_association_cache

logger = logging.getLogger(__name__)


class PipelineCancelled(Exception):
    """Raised when cancel_event is set mid-pipeline."""


def _emit(progress_callback: Optional[Callable], **kwargs) -> None:
    if progress_callback:
        try:
            progress_callback(**kwargs)
        except Exception as e:
            logger.debug(f"[progress callback] error: {e}")


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise PipelineCancelled("Cancelled by user")


def run_pipeline(
    source_dir: str,
    output_dir: str,
    enable_faces: bool = True,
    enable_location: bool = True,
    enable_icons: bool = True,
    enable_duplicates: bool = True,
    enable_timeline: bool = False,
    enable_strangers: bool = False,
    incremental: bool = False,
    scan_only: bool = False,
    verbose: bool = False,
    model_dir: Optional[str] = None,
    face_threshold: float = 0.4,
    progress_callback: Optional[Callable[..., None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Run the full organization pipeline. Returns session_id."""
    session_id = new_session_id()

    # ── Logging ───────────────────────────────────────────────────────────────
    log_dir = os.path.join(output_dir, "Index", "logs")
    setup_logging(log_dir, session_id, verbose)
    logger.info(f"Session ID: {session_id}")
    logger.info(f"Source:     {source_dir}")
    logger.info(f"Output:     {output_dir}")
    _emit(progress_callback, stage="start", session_id=session_id)

    # ── Safety preflight ──────────────────────────────────────────────────────
    logger.info("Running preflight safety checks...")
    assert_no_network_access()
    try:
        warnings = preflight_check(source_dir, output_dir)
    except SafetyError as e:
        logger.error(f"SAFETY ERROR: {e}")
        _emit(progress_callback, stage="error", message=str(e))
        raise

    for w in warnings:
        logger.warning(f"[preflight] {w}")

    # ── Database ──────────────────────────────────────────────────────────────
    db_path = os.path.join(output_dir, "manifest.db")
    db = Database(db_path)
    db.create_session(session_id, source_dir, output_dir)

    create_output_structure(output_dir)
    thumb_dir = os.path.join(output_dir, "Thumbnails")

    try:
        return _run_pipeline_inner(
            db=db, db_path=db_path, session_id=session_id,
            source_dir=source_dir, output_dir=output_dir, thumb_dir=thumb_dir,
            enable_faces=enable_faces, enable_location=enable_location,
            enable_icons=enable_icons, enable_duplicates=enable_duplicates,
            incremental=incremental, scan_only=scan_only, model_dir=model_dir,
            face_threshold=face_threshold,
            progress_callback=progress_callback, cancel_event=cancel_event,
        )
    except PipelineCancelled:
        logger.warning("Pipeline cancelled by user.")
        db.update_session(session_id, status="cancelled",
                          completed_at=datetime.now().isoformat())
        db.close()
        _emit(progress_callback, stage="cancelled")
        return session_id
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        db.update_session(session_id, status="failed",
                          completed_at=datetime.now().isoformat())
        db.close()
        _emit(progress_callback, stage="error", message=str(e))
        raise


def _run_pipeline_inner(
    db, db_path, session_id, source_dir, output_dir, thumb_dir,
    enable_faces, enable_location, enable_icons, enable_duplicates,
    incremental, scan_only, model_dir, face_threshold,
    progress_callback, cancel_event,
) -> str:
    use_tqdm = progress_callback is None

    # ── Stage 1: Scan ─────────────────────────────────────────────────────────
    logger.info("Scanning source directory for media files...")
    _emit(progress_callback, stage="scan", message="Scanning files...")
    all_media_paths = collect_media(source_dir)
    total = len(all_media_paths)
    logger.info(f"Found {total} media files.")
    db.update_session(session_id, total_files=total)
    _emit(progress_callback, stage="scan_done", total=total)
    _check_cancel(cancel_event)

    if total == 0:
        db.update_session(session_id, status="complete_empty",
                          completed_at=datetime.now().isoformat())
        db.close()
        return session_id

    if scan_only:
        for path in all_media_paths:
            print(f"  {path}")
        db.update_session(session_id, status="scan_only",
                          completed_at=datetime.now().isoformat())
        db.close()
        return session_id

    # ── Stage 2: Index, hash, metadata, thumbnails ───────────────────────────
    logger.info("Indexing files (metadata + hashing)...")
    sha256_map: dict = {}
    processed = 0
    skipped_incremental = 0

    iterator = tqdm(all_media_paths, desc="Indexing", unit="file", ncols=80) \
        if use_tqdm else all_media_paths

    for idx, path in enumerate(iterator):
        _check_cancel(cancel_event)
        media_type = get_media_type(path)
        mime = get_mime_type(path)
        try:
            file_size = os.path.getsize(path)
            mtime_ts = os.path.getmtime(path)
        except OSError as e:
            logger.warning(f"stat failed: {path}: {e}")
            continue

        # Incremental: skip if path+size+mtime match an existing row
        if incremental:
            existing = db.get_media_by_path(path)
            if existing and existing["file_size"] == file_size:
                existing_mtime = existing["date_file_modified"]
                if existing_mtime:
                    try:
                        existing_ts = datetime.fromisoformat(existing_mtime).timestamp()
                        if abs(existing_ts - mtime_ts) < 1.0:
                            skipped_incremental += 1
                            processed += 1
                            _emit(progress_callback, stage="index",
                                  current=idx + 1, total=total,
                                  skipped_incremental=skipped_incremental)
                            continue
                    except Exception:
                        pass

        try:
            sha256 = sha256_file(path)
        except Exception as e:
            logger.error(f"Hash failed: {path}: {e}")
            continue

        existing = db.get_media_by_sha256(sha256)
        is_dup = len(existing) > 0
        dup_of_id = existing[0]["id"] if is_dup else None

        phash = phash_image(path) if media_type == "image" else None

        try:
            meta = extract_metadata(path, media_type)
        except Exception as e:
            logger.warning(f"Metadata error: {path}: {e}")
            meta = {"date_taken": None, "gps_lat": None, "gps_lon": None}

        date_taken = meta.get("date_taken")
        gps_lat = meta.get("gps_lat")
        gps_lon = meta.get("gps_lon")
        location_label = format_gps_label(gps_lat, gps_lon) if enable_location else None

        try:
            mtime = datetime.fromtimestamp(mtime_ts).isoformat()
        except Exception:
            mtime = None

        record = {
            "session_id": session_id,
            "source_path": path,
            "filename": os.path.basename(path),
            "sha256": sha256,
            "phash": phash,
            "file_size": file_size,
            "media_type": media_type,
            "mime_type": mime,
            "date_taken": date_taken.isoformat() if date_taken else None,
            "date_file_modified": mtime,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "gps_location_label": location_label,
            "is_duplicate": 1 if is_dup else 0,
            "duplicate_of_id": dup_of_id,
        }

        media_id = db.insert_media(record)
        if media_id is None or media_id == 0:
            row = db.get_media_by_path(path)
            media_id = row["id"] if row else None

        if media_id:
            sha256_map.setdefault(sha256, []).append(media_id)
            thumb_path = generate_thumbnail(path, thumb_dir, media_type)
            if thumb_path:
                db.update_media(media_id, thumbnail_path=thumb_path)

        processed += 1
        if processed % 5 == 0 or processed == total:
            db.update_session(session_id, processed_files=processed)
        _emit(progress_callback, stage="index",
              current=idx + 1, total=total,
              skipped_incremental=skipped_incremental)

    db.update_session(session_id, processed_files=processed)
    if skipped_incremental:
        logger.info(f"Incremental: skipped {skipped_incremental} unchanged files.")

    # ── Stage 3: Near-duplicate detection ────────────────────────────────────
    near_dups = []
    if enable_duplicates:
        logger.info("Detecting near-duplicates (pHash)...")
        _emit(progress_callback, stage="dedup")
        phash_list = db.get_all_phashes()
        near_dups = find_near_duplicates(phash_list)
        logger.info(f"Found {len(near_dups)} near-duplicate pairs.")

        for id_a, id_b, _ in near_dups:
            db.update_media(id_b, is_duplicate=1, duplicate_of_id=id_a)

    dup_count = len([ids for ids in sha256_map.values() if len(ids) > 1])
    db.update_session(session_id, duplicates_found=dup_count + len(near_dups))
    _emit(progress_callback, stage="dedup_done",
          exact_dups=dup_count, near_dups=len(near_dups))
    _check_cancel(cancel_event)

    # ── Stage 4: Face detection ──────────────────────────────────────────────
    if enable_faces:
        logger.info("Initializing face engine...")
        face_engine = FaceEngine(model_dir=model_dir)

        image_rows = [
            m for m in db.get_all_media(session_id)
            if m["media_type"] == "image" and not m["is_duplicate"]
        ]
        n_imgs = len(image_rows)
        logger.info(f"Running face detection on {n_imgs} images...")
        _emit(progress_callback, stage="faces", total=n_imgs, current=0)

        face_iter = tqdm(image_rows, desc="Face detection", unit="img", ncols=80) \
            if use_tqdm else image_rows

        for idx, row in enumerate(face_iter):
            _check_cancel(cancel_event)
            path = row["source_path"]
            media_id = row["id"]
            try:
                detections = face_engine.detect(path)
            except Exception as e:
                logger.warning(f"Face detection failed: {path}: {e}")
                continue

            for det in detections:
                emb_bytes = embedding_to_bytes(det.embedding)
                landmarks_bytes = None
                if det.landmarks is not None:
                    import numpy as np
                    landmarks_bytes = np.asarray(det.landmarks, dtype=np.float32).tobytes()
                db.insert_face_detection(
                    media_id=media_id,
                    cluster_key=None,
                    bbox=det.bbox,
                    embedding_bytes=emb_bytes,
                    confidence=det.confidence,
                    landmarks_bytes=landmarks_bytes,
                )
            _emit(progress_callback, stage="faces",
                  current=idx + 1, total=n_imgs,
                  faces_detected=len(detections))

        # Cluster
        if face_engine.can_cluster:
            logger.info("Clustering faces...")
            _emit(progress_callback, stage="cluster")
            from .face_engine import bytes_to_embedding

            det_rows = db.get_all_embeddings()
            det_ids = [r["id"] for r in det_rows]
            embeddings = [bytes_to_embedding(r["embedding"]) for r in det_rows]

            if embeddings:
                cluster_map = cluster_embeddings(det_ids, embeddings, eps=face_threshold)

                cluster_counts: dict = {}
                for ck in cluster_map.values():
                    if not ck.startswith("unknown_"):
                        cluster_counts[ck] = cluster_counts.get(ck, 0) + 1

                # Transactional: cluster rows, then detection updates
                with db.transaction():
                    for ck, count in cluster_counts.items():
                        db.upsert_face_cluster(ck, member_count=count, commit=False)
                    for det_id, cluster_key in cluster_map.items():
                        db.update_detection_cluster(det_id, cluster_key, commit=False)

                known = sum(1 for ck in cluster_map.values() if not ck.startswith("unknown_"))
                db.update_session(session_id, faces_detected=known)
                logger.info(f"Face clustering: {len(cluster_counts)} clusters, "
                            f"{known} faces assigned.")
                _emit(progress_callback, stage="cluster_done",
                      clusters=len(cluster_counts), faces_assigned=known)

    _check_cancel(cancel_event)

    # ── Stage 5: Organize ─────────────────────────────────────────────────────
    logger.info("Organizing files into output structure...")
    _emit(progress_callback, stage="organize")
    all_rows = db.get_all_media(session_id)

    cluster_labels = {c["cluster_key"]: c["label"] for c in db.get_face_clusters()}

    org_iter = tqdm(all_rows, desc="Organizing", unit="file", ncols=80) \
        if use_tqdm else all_rows

    for idx, row in enumerate(org_iter):
        _check_cancel(cancel_event)
        media_id = row["id"]
        source_path = row["source_path"]
        media_type = row["media_type"]
        is_dup = bool(row["is_duplicate"])
        dup_of = row["duplicate_of_id"]

        date_taken = None
        if row["date_taken"]:
            try:
                date_taken = datetime.fromisoformat(row["date_taken"])
            except Exception:
                pass

        if is_dup and dup_of is not None and enable_duplicates:
            dup_type = "exact" if len(sha256_map.get(row["sha256"], [])) > 1 else "near"
            stage_duplicate_for_review(source_path, output_dir, dup_type, session_id, db)
            continue

        date_path = organize_by_date(source_path, output_dir, date_taken,
                                      media_type, session_id, db)
        if date_path:
            db.update_media(media_id, organized_date_path=date_path)

        if enable_location and row["gps_location_label"]:
            loc_path = organize_by_location(source_path, output_dir,
                                             row["gps_location_label"], session_id, db)
            if loc_path:
                db.update_media(media_id, organized_location_path=loc_path)

        if enable_faces:
            face_dets = db.get_detections_for_media(media_id)
            seen_clusters = set()
            for det in face_dets:
                ck = det["cluster_key"]
                if ck and not ck.startswith("unknown_") and ck not in seen_clusters:
                    seen_clusters.add(ck)
                    label = cluster_labels.get(ck)
                    organize_by_face(source_path, output_dir, ck, label, session_id, db)

        _emit(progress_callback, stage="organize",
              current=idx + 1, total=len(all_rows))

    # ── Stage 6: Identity (avatars, icons, summaries) ────────────────────────
    if enable_faces:
        _check_cancel(cancel_event)
        _install_person_identity(
            db, output_dir, cluster_labels,
            enable_icons=enable_icons,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    # ── Finalize ──────────────────────────────────────────────────────────────
    db.update_session(session_id, status="complete",
                      completed_at=datetime.now().isoformat())

    summary = {
        "session_id": session_id,
        "total": total,
        "processed": processed,
        "exact_dups": dup_count,
        "near_dups": len(near_dups),
        "skipped_incremental": skipped_incremental,
        "output_dir": output_dir,
    }
    db.close()
    _emit(progress_callback, stage="done", **summary)
    _print_summary(summary)
    return session_id


def _install_person_identity(
    db, output_dir: str, cluster_labels: dict,
    enable_icons: bool = True,
    progress_callback: Optional[Callable] = None,
    cancel_event: Optional[threading.Event] = None,
):
    """Avatars, contact sheets, icons, summaries — never aborts pipeline on failure."""
    from .face_engine import bytes_to_embedding
    logger.info("Building per-person identity (avatars + icons)...")

    clusters = db.get_face_clusters()
    if not clusters:
        return

    use_tqdm = progress_callback is None

    # Pre-compute cluster cohesion
    coh_iter = tqdm(clusters, desc="Cluster quality", unit="cluster", ncols=80) \
        if use_tqdm else clusters
    for c in coh_iter:
        _check_cancel(cancel_event)
        ck = c["cluster_key"]
        dets = db.get_detections_by_cluster(ck)
        embs = [bytes_to_embedding(r["embedding"]) for r in dets if r["embedding"]]
        m = compute_cluster_cohesion(embs)
        db.update_cluster_quality(ck, m["cohesion"], m["quality_flag"])

    # Ambiguous detections
    all_dets = db.get_all_embeddings()
    all_tuples = []
    for r in all_dets:
        row = db.conn.execute(
            "SELECT cluster_key FROM face_detections WHERE id=?", (r["id"],)
        ).fetchone()
        ck = row["cluster_key"] if row else None
        all_tuples.append((r["id"], ck, bytes_to_embedding(r["embedding"])))

    ambiguous = find_ambiguous_detections(all_tuples, margin=0.08)
    if ambiguous:
        amb_path = os.path.join(output_dir, "Index", "ambiguous_faces.json")
        os.makedirs(os.path.dirname(amb_path), exist_ok=True)
        import json
        with open(amb_path, "w", encoding="utf-8") as f:
            json.dump(ambiguous, f, indent=2)
        logger.info(f"Flagged {len(ambiguous)} ambiguous face(s) → {amb_path}")

    n = len(clusters)
    pers_iter = tqdm(clusters, desc="Person identity", unit="cluster", ncols=80) \
        if use_tqdm else clusters

    for idx, c in enumerate(pers_iter):
        _check_cancel(cancel_event)
        ck = c["cluster_key"]
        label = cluster_labels.get(ck) or c["label"]
        folder = face_folder_path(output_dir, ck, label)
        if not os.path.isdir(folder):
            continue

        try:
            ranked = score_all_detections_for_cluster(db, ck)
            if not ranked:
                continue

            embs = [bytes_to_embedding(r["embedding"])
                    for r in db.get_detections_by_cluster(ck) if r["embedding"]]
            metrics = compute_cluster_cohesion(embs)

            avatar_path = write_cluster_avatar(folder, ranked, circular=True)
            write_contact_sheet(folder, ranked)
            write_person_summary(folder, ck, label, c["member_count"],
                                  ranked, metrics, avatar_path)
            db.update_cluster_paths(ck, avatar_path=avatar_path, folder_path=folder)

            if enable_icons:
                badge_path = os.path.join(folder, "cluster_avatar_badge.png")
                if os.path.isfile(badge_path):
                    info_tip = f"{label or ck} — {c['member_count']} photos — quality: {metrics['quality_flag']}"
                    install_folder_icon(folder, badge_path, info_tip=info_tip,
                                          quality_flag=metrics["quality_flag"])
        except Exception as e:
            logger.error(f"[identity] Failed for cluster {ck}: {e}", exc_info=True)

        _emit(progress_callback, stage="identity",
              current=idx + 1, total=n, cluster=ck)

    if enable_icons:
        refresh_association_cache()
        logger.info("Icon cache refresh signaled to Explorer.")


def _print_summary(summary: dict):
    print("\n" + "=" * 60)
    print("  ORGANIZATION COMPLETE")
    print("=" * 60)
    print(f"  Session ID   : {summary['session_id']}")
    print(f"  Output dir   : {summary['output_dir']}")
    print(f"  Total scanned: {summary['total']}")
    print(f"  Indexed      : {summary['processed']}")
    print(f"  Exact dups   : {summary['exact_dups']}")
    print(f"  Near dups    : {summary['near_dups']}")
    if summary.get("skipped_incremental"):
        print(f"  Skipped (inc): {summary['skipped_incremental']}")
    print("=" * 60)
