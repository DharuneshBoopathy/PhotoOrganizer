# Production Hardening Checklist

Things to check before shipping `PhotoOrganizer-Setup.exe` to a
non-technical user. Items grouped by risk; most-important first.

---

## A. Data safety (must-pass before any release)

- [ ] **Run the full pipeline against a 1k-photo corpus**, then verify:
  - source folder mtime / contents are byte-identical to a pre-run snapshot
    (`Compare-Object` or hash all files before/after).
  - no source file appears in `copy_operations` as a destination.
  - every `copy_operations` row has `verified = 1`.
- [ ] **Power-cut test.** Mid-pipeline, kill the process. Restart with
  `--incremental`. Confirm:
  - DB opens without errors.
  - No half-written `desktop.ini` / `.ico` files cause Explorer hangs.
  - The session is reported as `failed` in `cmd_status`.
- [ ] **Disk-full test.** Fill the output drive to ~100 MB free, run a
  large pipeline. Confirm `safe_copy` cleans partial files.
- [ ] **Rollback test.** After a successful run, `rollback <session>`
  must remove every copy and leave originals untouched.
- [ ] **Read-only USB stick test.** Source = write-protected USB drive.
  Pipeline must succeed end-to-end without any write attempt to the
  source.

---

## B. Privacy & offline guarantees

- [ ] `grep -RIn "requests\|urllib\|http://\|https://" src/` returns
  zero hits in production code paths.
- [ ] Run with the network adapter disabled — pipeline succeeds.
- [ ] Confirm `INSIGHTFACE_HOME` points inside `%LOCALAPPDATA%`, not the
  user's roaming profile (so models don't sync to OneDrive/AD).
- [ ] No file under `%APPDATA%\Local\PhotoOrganizer\` contains
  user content (faces, paths) **outside** the explicit DB. The `app.log`
  should contain operational events only, not photo paths verbatim where
  avoidable.

---

## C. Windows integration

- [ ] desktop.ini is written as **UTF-16 LE with BOM**. `file` /
  PowerShell `Get-Content -Encoding Unicode` confirms.
- [ ] Folder gets attribute `+R` (ReadOnly) — required for icon to
  apply. `.ico` and `desktop.ini` get `+H +S`.
- [ ] After install, Explorer cache refresh (`SHChangeNotify`) actually
  shows icons without a logoff/login. Test on Windows 10 22H2 and
  Windows 11 23H2.
- [ ] App icon is multi-resolution `.ico` (16/24/32/48/64/128/256). The
  taskbar at 200% DPI uses the 64-px or 128-px layer.
- [ ] Long-path support: test with a source path > 260 chars. We rely
  on `\\?\` prefixing for paths that overflow `MAX_PATH`.
- [ ] Unicode paths (Cyrillic, CJK, emoji) round-trip through DB +
  filesystem. SQLite is UTF-8; we must avoid `os.fsencode` shortcuts.

---

## D. Performance & scale

- [ ] Library of 50k photos completes in < 2 hours on a baseline laptop
  (i5 + 16 GB + SSD, no GPU).
- [ ] Memory peak stays under 4 GB. Watch the clustering stage — if a
  user library pushes past, swap DBSCAN for HDBSCAN with mini-batches.
- [ ] SQLite remains responsive (`PRAGMA wal_autocheckpoint=1000`).
  After a long run, `wal` file should not stay > 100 MB.
- [ ] `os.walk` + `stat` over a network drive: pipeline must not hang.
  Add a per-file timeout? (Currently no; flagged as a known limit.)

---

## E. Build & release

- [ ] `build.bat installer` from a clean repo, fresh `pip install -r
  requirements.txt`, succeeds end-to-end.
- [ ] The `.exe` is **code-signed** (Authenticode). Without a signature
  Windows SmartScreen will block users on first launch.
- [ ] Installer is signed too. SmartScreen reputation grows with signed
  downloads — start now, not at v2.
- [ ] Run `dist/.../PhotoOrganizer.exe` on a clean Windows VM with
  no Python installed. No "VCRUNTIME140.dll missing" pop-ups.
- [ ] Antivirus quick scan on the installed folder. Some heuristic AV
  flags PyInstaller bundles — submit a false-positive sample to MS
  Defender if needed.
- [ ] `--clean` build directory: confirm `.spec` doesn't pick up stale
  `__pycache__` files that bloat the bundle.

---

## F. Error handling & UX

- [ ] Every CLI command opens DB defensively (`_open_db`) and exits
  with code 2 if missing — no stack trace.
- [ ] GUI: a fatal exception during the pipeline shows a `messagebox`,
  not a silent dead window.
- [ ] Cancel during clustering: confirm worker thread exits within
  3 seconds (DBSCAN holds the GIL — may need a coarser cancel-check
  inside the loop).
- [ ] Logs rotate. Currently `app.log` grows forever — add
  `RotatingFileHandler(maxBytes=5MB, backupCount=3)` in `app_main.py`.
- [ ] `report.html` opens in default browser at end of run. Confirm
  this respects "Always ask which browser" setting on Windows 11.

---

## G. Maintenance follow-ups (not blocking v1.0)

- [ ] Add a `--repair-db` CLI command that runs `PRAGMA
  integrity_check` and rebuilds the FTS index if we add one.
- [ ] Add a "Verify archive" button in the GUI that walks
  `copy_operations` and re-hashes a random 5% sample.
- [ ] Plug-in HDBSCAN as an optional alternative clusterer for users
  with > 50k photos.
- [ ] Add a "Delete duplicates" workflow — currently we only flag.
  Must be opt-in, with two-step confirm and rollback.
- [ ] Migrate the GUI to ttk theming (Sun-Valley) for a more native
  Win 11 look. Optional.
- [ ] Add automated tests: smoke test (10-photo corpus), copy-
  verification test, rollback test, cancel test.

---

## H. Known issues / accepted debt

- **DBSCAN scaling**: O(n²) memory for the distance matrix. Acceptable
  up to ~20k embeddings; document the limit in the README.
- **No video face detection**: out of scope for v1.0. Videos get
  date/location only.
- **No HEIC support out of the box**: relies on `pillow-heif` if
  present. Bundle it, or document the optional dep.
- **Tkinter is dated**: works, but the Label People grid will feel
  cramped over ~200 clusters. Consider Qt for v2.

---

## Sign-off

Before tagging `v1.0.0`:

```
[ ] All A items pass
[ ] All B items pass
[ ] At least 90% of C, D, E, F items pass
[ ] HARDENING.md updated with whatever items got punted to v1.1
```
