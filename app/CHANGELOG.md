# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-04-28

First public release as a desktop application.

### Added
- **Tkinter desktop GUI** with menu bar (File / Tools / Help), recent-folders
  history, log viewer, progress bar, status bar.
- **First-run welcome wizard** — three-step privacy / folder / options intro.
- **Settings window** — three tabs (General / Pipeline / Advanced), tunable
  face-cluster strictness and InsightFace model directory.
- **About dialog** — version, license, credits, links to docs and bug
  tracker.
- **User preferences** persisted to
  `%LOCALAPPDATA%\PhotoOrganizer\preferences.json`.
- **Crash handler** — global `sys.excepthook` writes a per-incident report
  to `%LOCALAPPDATA%\PhotoOrganizer\crash_reports\` and shows a
  user-friendly Tk dialog with copy / open-folder actions.
- **Single-instance lock** — second launch focuses an info dialog instead
  of opening a duplicate window.
- **`--version`, `--reset-prefs`, `--safe-mode`, `--cli` CLI flags** on
  the bundled .exe.
- **Database integrity check** + best-effort repair (`PRAGMA
  integrity_check` + WAL checkpoint + VACUUM).
- **PyInstaller spec** with embedded Windows file-version resource,
  bundled assets, explicit hidden-import list for all `src.*` modules,
  exclude list for `matplotlib`/`pandas`/`torch` to slim the bundle.
- **Inno Setup installer** with auto-uninstall on upgrade, license page,
  per-user default, registry entry under `HKCU\Software\PhotoOrganizer`,
  preserved app data on uninstall.
- **Portable ZIP build** via `tools/make_portable_zip.py` — same bytes,
  no install.
- **SHA-256 release checksums** via `tools/make_checksums.py`.
- **GitHub Actions** — `.github/workflows/build.yml` (release-on-tag) and
  `test.yml` (lint + import-check on push).

### Changed
- **`build.bat`** now hard-pins `py -3.13` (Python launcher) and pre-flights
  both interpreter and PyInstaller before running.
- **`tqdm`** import in `src/main.py` is now optional with a no-op shim, so
  the GUI build doesn't hard-depend on a CLI-only package.
- **`README.md`** rewritten for end users (download → install → run),
  with screenshots, install steps, known limits, roadmap.

### Pipeline features (already present from Phase B)
- Per-cluster avatars, contact sheets, `person_summary.json`.
- Windows folder icons via `desktop.ini` + multi-resolution `.ico`,
  with quality-flag colored rings (good / fair / suspect / poor).
- Cluster cohesion scoring, ambiguous-face detection.

### Pipeline features (new in this release)
- `labeling` — rename a cluster (DB + folder + desktop.ini in one step).
- `cluster_repair` — merge / split clusters with automatic identity rebuild.
- `incremental` — detect moved files, skip already-processed.
- `relationships` — `Photos_By_Relationship/A_and_B/` co-occurrence folders.
- `timeline` — per-person `timeline.jpg` + `timeline.html`.
- `stranger_filter` — quarantine clusters with too few recurrences.
- `burst_detector` — group continuous-shoot sequences, recommend a keeper.
- `person_album` — per-person `album.html` (tabs: All / Best / Solo / With X).
- `search` — read-only catalog query (person, date range, location, filename).
- `report` — top-level `report.html` dashboard.
- `xmp_tags` — write `.xmp` sidecars (dc:subject / photoshop:City) without
  modifying the original photos.

### Safety
- All copies remain SHA-256 verified; rollback log is append-only.
- New transactional batches in `database.py` prevent FK errors during
  cluster updates.
- `int()` coercion at face-engine / database / identity boundaries
  defends against legacy `numpy.int64` BLOB rows.

### Known limitations
- DBSCAN scaling: O(n²) memory; comfortable up to ~20k faces.
- No video face detection (videos still get date / location organization).
- HEIC support requires `pillow-heif`; not bundled by default.
- Tkinter UI is intentionally simple — Label People grid feels cramped
  past ~200 clusters. Qt port tracked for v2.0.

[Unreleased]: https://github.com/DharuneshBoopathy/PhotoOrganizer/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/DharuneshBoopathy/PhotoOrganizer/releases/tag/v1.0.0
