<div align="center">

<img src="assets/app_icon_256.png" width="128" alt="App icon">

# Photo Organizer

**Local-first, offline AI photo & video organizer for Windows.**
Sort thousands of photos by date, location, and face — entirely on your machine.

[![Release](https://img.shields.io/github/v/release/DharuneshBoopathy/PhotoOrganizer?include_prereleases&label=release)](https://github.com/DharuneshBoopathy/PhotoOrganizer/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4.svg)](#install)
[![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB.svg)](#build-from-source)
[![Build](https://github.com/DharuneshBoopathy/PhotoOrganizer/actions/workflows/build.yml/badge.svg)](https://github.com/DharuneshBoopathy/PhotoOrganizer/actions)

</div>

---

## Why this exists

Most "AI photo organizers" upload your library to a cloud service. This
one doesn't. It does face recognition, location lookup, duplicate
detection, and clustering 100% on your computer — there is no account,
no telemetry, no outbound network call after install.

Your originals are never moved or modified. Every output is a verified
copy and every operation is logged so it can be rolled back.

---

## What you get

| Feature | Details |
|---|---|
| 🗓 **Date organization** | EXIF → file mtime fallback → `Photos_By_Date/YYYY/YYYY-MM/YYYY-MM-DD/` |
| 👤 **Face clustering** | InsightFace (local ONNX) + DBSCAN — no cloud API |
| 🌍 **Location folders** | GPS EXIF → bundled offline reverse-geocoder |
| 🔁 **Duplicate detection** | SHA-256 (exact) + perceptual hash (near) |
| 🛡 **Verified copies** | Every copy hash-checked; originals never touched |
| ↩️ **Full rollback** | Undo any session — copies removed, originals untouched |
| 🖼 **Folder icons** | Each person folder shows their face as the icon |
| 📊 **HTML report** | One-page dashboard of your library |
| 📓 **Per-person albums** | Tabs for All / Best / Solo / With <other person> |
| 📅 **Per-person timelines** | `timeline.jpg` + sortable `timeline.html` |
| 🔥 **Burst detection** | Group continuous-shoot photos, recommend a keeper |
| 👥 **Relationships** | `Photos_By_Relationship/A_and_B/` for co-occurring faces |
| 🚫 **Stranger filter** | Quarantine clusters with too few recurrences |
| 🏷 **XMP sidecars** | Optional `.xmp` files (dc:subject keywords) — never mutates your originals |
| 🔍 **Search** | CLI query by person / date range / location / filename |

---

## Install

### Option A — Installer (recommended)

1. Go to **[Releases](https://github.com/DharuneshBoopathy/PhotoOrganizer/releases)**.
2. Download `PhotoOrganizer-Setup-x.y.z.exe`.
3. Run it. The installer is per-user by default — no admin password required.
4. Launch from Start Menu. The first run shows a 3-step welcome wizard.

### Option B — Portable ZIP

1. Download `PhotoOrganizer-x.y.z-portable.zip` from Releases.
2. Unzip anywhere (USB stick is fine).
3. Double-click `PhotoOrganizer.exe`.

No registry entries, no Start Menu shortcut. Move or delete the folder
to "uninstall".

### Verify your download

Each release ships a `SHA256SUMS.txt`. Open PowerShell:

```powershell
Get-FileHash .\PhotoOrganizer-Setup-1.0.0.exe -Algorithm SHA256
```

The output should match the line in `SHA256SUMS.txt`.

---

## Use it

1. **Open the app** → pick a **source folder** (your photo library) and
   an **output folder** (where the organized copies go — pick a
   different drive if you have one).
2. **Choose options** — Detect faces / Geo-locate / Find duplicates /
   Folder icons (sane defaults are pre-selected).
3. **Click START.** The activity log streams progress in real time.
4. **Open the report** when it finishes. It's a self-contained
   `report.html` with stats, a clickable people grid, and links into
   every subdirectory.

To **rename a face cluster**: Tools → Label People → click a person →
"Rename / label". The folder is renamed, the desktop.ini icon refreshed,
and the cluster locked from auto-stranger detection.

---

## Output structure

```
D:\Organized\
├── Photos_By_Date\
│   └── 2023\2023-07\2023-07-15\IMG_0001.jpg
├── Photos_By_Location\
│   └── Paris_IDF_FR\
├── Photos_By_Face\
│   ├── Alice (cluster_0001)\
│   │   ├── desktop.ini           ← Windows folder icon
│   │   ├── cluster_avatar.jpg    ← best face
│   │   ├── contact_sheet.jpg
│   │   ├── album.html            ← per-person album
│   │   ├── timeline.jpg
│   │   ├── timeline.html
│   │   ├── person_summary.json
│   │   └── … photos …
│   ├── Bob (cluster_0002)\
│   └── _strangers\               ← quarantined low-confidence clusters
├── Photos_By_Relationship\
│   └── Alice_and_Bob\
├── Photos_By_Burst\
│   └── burst_2023-07-15_142003_001\
│       └── _KEEPER.txt
├── _Duplicates\
│   ├── exact\
│   └── near\
├── Thumbnails\
├── Index\
│   └── ambiguous_faces.json
├── manifest.db                    ← portable SQLite catalog
└── report.html                    ← top-level dashboard
```

---

## Privacy & safety

* **No internet calls.** The runtime grep is in `docs/HARDENING.md`.
  InsightFace runs entirely on local CPU via ONNX Runtime; the location
  lookup uses a bundled offline dataset.
* **No telemetry.** Zero. There is no opt-in, no "anonymous usage stats".
* **Read-only on source.** Source files are opened read-only and never
  passed to `os.replace`, `shutil.move`, or `os.remove`.
* **Verified copies.** Every copy's SHA-256 is recomputed and compared
  to the source before the operation is logged.
* **Full rollback.** `copy_operations` is append-only — every release
  ships a CLI command to undo a session by replaying that log in reverse.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full
threat model + safety invariants.

---

## Where the app stores things

| Path | What's there |
|---|---|
| `<output>\manifest.db` | Portable SQLite catalog of this output |
| `<output>\report.html` | Top-level dashboard |
| `<output>\Photos_By_…\` | Organized copies |
| `%LOCALAPPDATA%\PhotoOrganizer\app.log` | Rolling log file (5 MB × 3) |
| `%LOCALAPPDATA%\PhotoOrganizer\preferences.json` | UI settings, recent folders |
| `%LOCALAPPDATA%\PhotoOrganizer\models\` | Cached InsightFace model (~280 MB) |
| `%LOCALAPPDATA%\PhotoOrganizer\crash_reports\` | One file per crash (rare) |

The `manifest.db` is portable — copy the output folder to another
machine and the catalog comes with it.

---

## Build from source

Prerequisites: **Python 3.13 64-bit** (Microsoft Store or python.org),
**Inno Setup 6** (only for the installer step).

```bat
git clone https://github.com/DharuneshBoopathy/PhotoOrganizer.git
cd PhotoOrganizer
py -3.13 -m pip install -r requirements.txt
py -3.13 -m pip install pyinstaller
build.bat installer
```

Outputs:

* `dist\PhotoOrganizer\PhotoOrganizer.exe`
* `installer\Output\PhotoOrganizer-Setup-1.0.0.exe`

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the dev workflow,
[`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) for the
release procedure.

---

## CLI

The .exe accepts a few flags. Most users won't need them.

```bat
PhotoOrganizer.exe                    REM normal launch
PhotoOrganizer.exe --version
PhotoOrganizer.exe --reset-prefs      REM erase saved settings
PhotoOrganizer.exe --safe-mode        REM skip welcome wizard
PhotoOrganizer.exe --cli organize SRC OUT  REM full CLI under the hood
```

Or directly:

```bat
python -m src.cli --help
python -m src.cli organize "C:\Photos" "D:\Organized"
python -m src.cli rollback "D:\Organized" SESSION_ID --dry-run
python -m src.cli search "D:\Organized" --person Alice --date-from 2023-01-01
```

20 subcommands total. See `python -m src.cli --help` for the full list.

---

## Roadmap

* **v1.1** — auto-update check (opt-in), HEIC support bundled by
  default, signed installer.
* **v1.2** — HDBSCAN as an alternative clusterer for libraries > 50k
  photos, in-app duplicate-resolution UI.
* **v2.0** — Qt port for the labeling grid (Tkinter strains past ~200
  clusters).

Tracked in [GitHub issues](https://github.com/DharuneshBoopathy/PhotoOrganizer/issues).

---

## Known limitations

* **DBSCAN scaling**: O(n²) memory; comfortable up to ~20k faces.
  Beyond that, expect long clustering times.
* **Video face detection**: not implemented. Videos still get
  date/location organization.
* **HEIC support**: requires `pillow-heif` — not bundled by default.
* **Tkinter**: the Label People grid feels cramped past ~200 clusters.

---

## License

[MIT](LICENSE). Bundles third-party software whose licenses may
differ — see the LICENSE file for attributions.

---

## Acknowledgements

Built on the shoulders of [InsightFace](https://github.com/deepinsight/insightface),
[ONNX Runtime](https://onnxruntime.ai/), [Pillow](https://python-pillow.org/),
[OpenCV](https://opencv.org/), [scikit-learn](https://scikit-learn.org/),
[imagehash](https://github.com/JohannesBuchner/imagehash), and
[reverse_geocoder](https://github.com/thampiman/reverse-geocoder).
