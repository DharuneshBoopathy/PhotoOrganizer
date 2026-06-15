# Architecture Review — Photo Organizer

A local-first, offline desktop application for Windows that scans a user's
photo/video library and reorganizes it into a curated, deduplicated,
face-aware archive — without ever sending data over the network.

---

## 1. Goals & non-goals

### Goals
- **Archival-grade safety.** Originals are never moved, never modified, never
  deleted. Every output file is a verified copy.
- **100% offline.** Face recognition, geocoding, duplicate hashing — all
  performed by local libraries against bundled or cached models.
- **Trustworthy.** Every operation is logged, every copy is hash-verified,
  every session can be rolled back.
- **Useful out of the box.** Sensible defaults: faces clustered, duplicates
  flagged, location folders, per-person albums, top-level report.
- **Friendly on Windows.** Native folder icons via `desktop.ini` + `.ico`,
  one-click installer, no terminal required.

### Non-goals
- Cloud sync, multi-user accounts, web UI.
- Real-time camera capture.
- "AI-generated" descriptions / GPT-style commentary.
- Editing the photo files themselves (only sidecars and copies).

---

## 2. High-level pipeline

```
┌──────────────┐
│   scanner    │   walks the source tree, returns absolute paths
└──────┬───────┘
       ↓
┌──────────────┐
│   hasher     │   SHA-256 (exact) + pHash (near-dup)
└──────┬───────┘
       ↓
┌──────────────┐
│   metadata   │   EXIF dates, GPS coords, dimensions
└──────┬───────┘
       ↓
┌──────────────┐
│ face_engine  │   InsightFace buffalo_l → bbox + 512-d embedding + landmarks
└──────┬───────┘
       ↓
┌──────────────┐
│  clustering  │   DBSCAN (cosine) over embeddings → cluster_keys
└──────┬───────┘
       ↓
┌──────────────┐
│  identity    │   per-cluster: cohesion, best face, avatar, contact sheet
└──────┬───────┘
       ↓
┌──────────────┐
│  organizer   │   safe_copy() → Photos_By_Date / By_Location / By_Face / …
└──────┬───────┘
       ↓
┌──────────────┐
│ folder_icon  │   desktop.ini + .ico per cluster folder (Windows only)
└──────┬───────┘
       ↓
┌──────────────┐
│   report     │   top-level report.html dashboard
└──────────────┘
```

Optional secondary stages (toggled by user / CLI flags):
`relationships`, `timeline`, `person_album`, `burst_detector`,
`stranger_filter`, `xmp_tags`, `incremental`.

---

## 3. Module map

| Module | Responsibility |
|---|---|
| `scanner.py` | Walk directories, classify image/video by extension. |
| `hasher.py` | SHA-256, perceptual hash. Read in chunks; never load into memory. |
| `metadata.py` | EXIF/sidecar extraction. Tolerant of missing fields. |
| `database.py` | SQLite WAL. Schema migrations, transactions, cluster CRUD. |
| `face_engine.py` | InsightFace wrapper. Embedding + 5-point landmarks + bbox. |
| `clustering.py` | DBSCAN over embeddings. Stable cluster keys across runs. |
| `identity.py` | Quality scoring (sharpness/pose/eyes), avatar, contact sheet, cohesion. |
| `folder_icon.py` | `.ico` writer + desktop.ini + Explorer cache refresh. Quality rings. |
| `safety.py` | `safe_copy(verify=True)`, `rollback_session()`, copy-operation log. |
| `organizer.py` | High-level "place this media into output structure" logic. |
| `geocoder.py` | Local reverse-geocoder (offline city/country DB). |
| `main.py` | Pipeline orchestrator with progress callbacks + cancel events. |
| `cli.py` | Argparse façade. |
| `gui_app.py` | Tkinter desktop window. |
| `gui_log.py` | logging→queue bridge for the GUI. |
| `labeling.py` | Rename a cluster (DB + folder + desktop.ini + display name). |
| `labeling_ui.py` | Cluster-labeling Toplevel window. |
| `cluster_repair.py` | Merge / split clusters. |
| `incremental.py` | Detect moved files, skip already-processed. |
| `relationships.py` | Co-occurrence pairs → `Photos_By_Relationship/`. |
| `timeline.py` | Per-person `timeline.jpg` + `timeline.html`. |
| `person_album.py` | Per-person `album.html` (tabs, dates, with-others). |
| `burst_detector.py` | Burst-shot grouping + recommended keeper. |
| `stranger_filter.py` | Detect & quarantine clusters that look like background people. |
| `search.py` | Read-only catalog search (person/date/location/filename). |
| `report.py` | Top-level `report.html` dashboard. |
| `xmp_tags.py` | XMP sidecar generation (dc:subject, photoshop:City). |
| `app_main.py` | PyInstaller entry point: AppData paths, logging, GUI launch. |

---

## 4. Data model

```
media               (id, source_path, sha256, perceptual_hash, file_size,
                     date_taken, date_file_modified, gps_latitude, gps_longitude,
                     location_city, location_country, location_place_name,
                     thumbnail_path, media_type, is_duplicate, duplicate_of_id, …)

face_detections     (id, media_id, bbox_x/y/w/h, embedding BLOB, landmarks BLOB,
                     quality_score, cluster_key, cluster_distance)

face_clusters       (cluster_key PK, label, member_count, manual_label,
                     cohesion, quality_flag, is_stranger,
                     avatar_path, folder_path)

duplicates          (sha256 PK, status [exact|near], group_id)

burst_groups        (id, name, keeper_media_id, folder_path)
burst_members       (group_id, media_id, is_keeper)

relationships       (cluster_a, cluster_b, co_count, folder_path)  PK(a,b)

copy_operations     (id, session_id, source_path, dest_path, sha256, verified)
sessions            (id, started_at, finished_at, status, total_files, …)
```

All face data (embeddings, landmarks) lives in BLOBs. Always coerce
`bytes` ↔ `numpy` at boundaries (we hit a real bug where `numpy.int64`
got stored as 8-byte BLOBs and broke comparisons; fixed by `int()`
casting at the producer + a `_coerce_int()` decoder on legacy reads).

---

## 5. Concurrency & threading

- The pipeline runs on a **worker thread**.
- The GUI main thread polls a `queue.Queue` every 100 ms for events:
  `{"type": "log" | "progress" | "done" | "error", …}`.
- `cancel_event: threading.Event` is checked at every stage boundary —
  `PipelineCancelled` propagates up cleanly.
- SQLite is opened with `check_same_thread=False` and used from one
  thread at a time; we don't share connections across threads.

---

## 6. Safety invariants

1. **Read-only on source.** Source files are opened read-only and never
   passed to `os.replace`, `shutil.move`, or `os.remove`.
2. **Verified copies.** `safe_copy(src, dst, verify=True)` recomputes the
   SHA-256 of the destination and compares. On mismatch, the destination
   is removed and the operation logged as failed.
3. **Atomic DB writes.** `db.transaction()` wraps multi-row updates so a
   crash mid-write leaves the catalog consistent. Foreign-key parents
   (e.g. `face_clusters` rows) are upserted **before** child rows
   (`face_detections.cluster_key`).
4. **Append-only logs.** `copy_operations` is never UPDATEd, only
   INSERTed. `rollback_session()` works by replaying that log in reverse.
5. **No internet.** No code in this repo calls `requests`, `urllib`,
   `socket`, or any HTTP client. Verified by `grep`.
6. **Non-destructive Windows attributes.** desktop.ini files get
   Hidden+System+ReadOnly; the folder gets ReadOnly set ONLY for the
   icon-customization marker (Windows requires it). We strip that flag
   before any move/merge so we never get an "access denied".

---

## 7. Performance characteristics

| Stage | Cost on 10k photos | Bottleneck |
|---|---|---|
| Scan + hash | ~3 min | Disk I/O |
| Face detect | ~12 min (CPU) / ~2 min (GPU) | InsightFace inference |
| Clustering | ~10 s | DBSCAN — O(n²) worst case |
| Organize/copy | ~5 min | Disk write throughput |
| Folder icons | ~1 s/cluster | desktop.ini + Explorer cache flush |
| Total | ~20 min CPU / ~10 min GPU | |

Memory ceiling: ~1 GB during clustering (embeddings stay in RAM as a
single `numpy.float32` matrix). For libraries above ~50k photos,
clustering should be batched or switched to HDBSCAN — see hardening
checklist.

---

## 8. Where we make trade-offs

- **DBSCAN over HDBSCAN**: simpler, deterministic, no extra dep. Cost:
  one global eps (`face_threshold=0.4`) — ambiguous faces are surfaced
  for human review rather than auto-resolved.
- **One-folder PyInstaller, not one-file**: 280 MB ONNX models would
  unpack on every `.exe` launch in one-file mode. Folder mode launches
  in ~1 s.
- **Tkinter, not Qt**: Tkinter ships with Python, costs nothing in
  bundle size, and the UI is intentionally simple. If the labeling
  workflow grows (drag-and-drop, multi-select, large grids), Qt would
  pay for itself.
- **SQLite, not Postgres**: single-user offline app. WAL mode handles
  concurrent reads from the GUI while the worker writes.

---

## 9. Failure modes considered

| Failure | Mitigation |
|---|---|
| Power loss mid-pipeline | WAL + transactional batches → DB recovers; `copy_operations` lets us resume. |
| Source file disappears mid-run | `safe_copy` returns `(False, error)`; logged, pipeline continues. |
| Disk full on output | `safe_copy` removes partial dest; session marked `failed`; user can free space + resume. |
| InsightFace model missing | Pipeline runs with `enable_faces=False`; user gets a clear log warning. |
| User cancels mid-cluster | `PipelineCancelled` raises out cleanly; DB is consistent up to last commit. |
| Locked desktop.ini (Explorer) | We retry once, then log + continue. Photos are still organized. |

---

## 10. What's intentionally NOT here

- **Telemetry.** Zero. There is no opt-in, no "anonymous usage stats".
- **Auto-update.** Installer is signed (recommended for v1.1) but
  there's no in-app updater. Updates ship as new installer .exe.
- **OCR / text extraction from images.** Out of scope.
- **Video face detection.** We only detect faces in still images.
  Video gets organized by date/location only.
