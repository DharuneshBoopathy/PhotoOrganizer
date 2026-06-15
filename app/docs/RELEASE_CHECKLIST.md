# Release checklist

Sign-off procedure for cutting a new public release. Run through every
section in order. Don't skip ahead — these have caught me before.

---

## 0. Prerequisites

- [ ] You're on `main`, fully committed, working tree clean
      (`git status` shows nothing).
- [ ] Last green CI run is on the commit you intend to release.

---

## 1. Bump version

- [ ] Edit `src/version.py` — bump `__version__` and `__version_info__`
      together. Follow [SemVer](https://semver.org/):
      * patch (1.0.0 → 1.0.1) — bug fixes only
      * minor (1.0.0 → 1.1.0) — new features, no breaking API changes
      * major (1.0.0 → 2.0.0) — breaking changes (CLI, output layout, DB schema)
- [ ] Update `CHANGELOG.md`:
      * Move `## [Unreleased]` items into `## [x.y.z] — YYYY-MM-DD`
      * Add fresh empty `## [Unreleased]` section
      * Update the comparison links at the bottom

---

## 2. Smoke tests

- [ ] `py -3.13 -m pytest tests/ -v` passes
- [ ] `py -3.13 -m src.cli --help` lists every expected subcommand
- [ ] `py -3.13 app_main.py --version` prints the new version
- [ ] Run the GUI from source: `py -3.13 app_main.py`
      * Welcome wizard appears (only if you cleared
        `%LOCALAPPDATA%\PhotoOrganizer\preferences.json`)
      * About dialog shows new version
      * Settings open / save / round-trip
      * Pipeline starts on a 100-photo test corpus and finishes
        without errors

---

## 3. Build

- [ ] `rmdir /s /q build dist` (full clean)
- [ ] `build.bat installer`
- [ ] Verify outputs:
      * `dist\PhotoOrganizer\PhotoOrganizer.exe`
      * `installer\Output\PhotoOrganizer-Setup-x.y.z.exe`
- [ ] Right-click `PhotoOrganizer.exe` → Properties → Details:
      * File version reads `x.y.z`
      * Product name reads "Photo Organizer"
- [ ] `py -3.13 tools\make_portable_zip.py`
- [ ] `py -3.13 tools\make_checksums.py`
- [ ] `SHA256SUMS.txt` lists exactly 3 files (`.exe`, `Setup.exe`, `.zip`).

---

## 4. Verify on a clean machine

This is the most important step.

- [ ] Spin up a fresh Windows 10 or 11 VM (no Python, no dev tools).
- [ ] Copy the installer in. Run it. Click through.
- [ ] Launch from Start Menu. Welcome wizard appears.
- [ ] Drop a small folder of mixed photos (~30 files including a couple
      of duplicates and a couple of GPS-tagged photos) and run.
- [ ] After completion: `report.html` opens in browser, folder icons
      appear in `Photos_By_Face\`, no crash dialog.
- [ ] Uninstall via Apps & Features. Confirm `%LOCALAPPDATA%\PhotoOrganizer\`
      is preserved (we keep models and prefs intentionally).

---

## 5. Privacy verification

- [ ] On the clean VM, capture network traffic during the full pipeline:
      `pktmon start --etw -m real-time` or Wireshark.
- [ ] Filter for any TCP/UDP traffic from the .exe to a non-loopback,
      non-LAN address. Expected: zero.
      *Exception:* the very first run with face detection may download
      `buffalo_l` from `huggingface.co` (InsightFace's CDN). After
      that, no further calls.
- [ ] Optional: pre-place the model under
      `%LOCALAPPDATA%\PhotoOrganizer\models\models\buffalo_l\`
      and verify the run goes fully offline.

---

## 6. Tag + push

```bat
git add -A
git commit -m "release: v1.x.y"
git tag -a v1.x.y -m "Photo Organizer 1.x.y"
git push origin main
git push origin v1.x.y
```

GitHub Actions will:
1. Build on the tag.
2. Attach `PhotoOrganizer-Setup-1.x.y.exe`,
   `PhotoOrganizer-1.x.y-portable.zip`, and `SHA256SUMS.txt`
   to the release page.

---

## 7. Polish the release page

- [ ] Open
      [Releases](https://github.com/DharuneshBoopathy/PhotoOrganizer/releases),
      edit the auto-created `v1.x.y` draft.
- [ ] Title: `Photo Organizer 1.x.y`
- [ ] Body: paste the matching CHANGELOG section.
- [ ] If this is the latest stable, check **Set as the latest release**.
- [ ] Hit Publish.

---

## 8. After the release

- [ ] Verify the README badges turn green for the new version.
- [ ] If you submitted a winget manifest, open the PR against
      `microsoft/winget-pkgs`.
- [ ] If you announce anywhere (HN, reddit), wait 24 h after release
      so the SHA256SUMS hashes have settled and any auto-update logic
      has caught up.

---

## 9. Roll back (if something burns)

If a release goes out and is broken:

```bat
REM Mark it as a draft on GitHub (don't delete — links break)
gh release edit v1.x.y --draft

REM Yank a published version on winget if accepted
REM (open a PR removing the manifest)
```

Then ship `v1.x.(y+1)` with the fix and a `CHANGELOG.md` note about
the yanked version.
