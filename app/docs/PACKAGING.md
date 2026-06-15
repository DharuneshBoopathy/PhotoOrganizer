# Packaging guide

How `Photo Organizer` becomes a `.exe` + installer + portable
zip, and how to keep that pipeline working.

---

## TL;DR

```bat
build.bat installer
py -3.13 tools\make_portable_zip.py
py -3.13 tools\make_checksums.py
```

Output:

```
dist\PhotoOrganizer\PhotoOrganizer.exe          (~36 MB launcher)
dist\PhotoOrganizer\_internal\                        (~425 MB deps)
dist\portable\PhotoOrganizer-1.0.0-portable.zip       (~150 MB compressed)
installer\Output\PhotoOrganizer-Setup-1.0.0.exe       (~150 MB)
SHA256SUMS.txt
```

---

## Why these choices

### Folder mode, not one-file
PyInstaller can produce a single `.exe` that unpacks itself to `%TEMP%`
on launch. With ~280 MB of ONNX models that's unworkable: 3-8 second
cold start, wasted disk on every run, and AV scanners that re-scan the
unpack on every launch. Folder mode launches in ~1 s and the OS file
cache makes subsequent runs instant.

### Python 3.13, not 3.14
PyInstaller 6.20 had stable wheels for every dep we use on 3.13. As of
this release, NumPy/scikit-learn/onnxruntime were still landing 3.14
wheels. The `build.bat` hard-pins `py -3.13` to avoid the
"works-on-my-machine" trap where `python` ends up resolving to 3.14.

### Inno Setup, not MSIX
MSIX is the modern Windows app format, but it requires a Microsoft
partner account or a Microsoft Store cert chain to install without
sideload mode. Inno Setup runs anywhere, builds a real `.exe` users
recognize, and supports per-user install (no admin password).

### Per-user install by default
`PrivilegesRequired=lowest` in `installer.iss`. Reasoning:
* corporate users on locked-down machines can install without IT;
* SmartScreen reputation builds per-publisher, and per-user installs
  are less suspicious to heuristics;
* upgrades don't need elevation.

The user can still elevate to "all users" via the Inno Setup dialog.

---

## What's bundled

### Python deps
`Pillow`, `imagehash`, `exifread`, `opencv-python`, `numpy`,
`scikit-image`, `scikit-learn`, `scipy`, `tqdm`, `insightface`,
`onnxruntime`, `reverse_geocoder` and their transitive deps. Total
~425 MB.

### Excluded (intentionally)
`matplotlib`, `pandas`, `torch`, `tensorflow`, `dask`, `cupy`,
`pyamg`, `pooch`, `numpydoc`, `IPython`, `jupyter`, `pytest`. These
are pulled by sklearn/scipy as optional accelerators or test deps and
add 200+ MB the runtime never uses.

### Models
**Not bundled.** InsightFace's `buffalo_l` (~280 MB) downloads on
first launch into `%LOCALAPPDATA%\PhotoOrganizer\models\`. Why:
1. Releases are leaner (~150 MB vs ~430 MB).
2. The model can update independently.
3. Air-gapped users can pre-place the model and launch with `--model-dir`.

If you want a fully offline installer, copy `buffalo_l/` into
`assets\insightface_models\` and add a couple of lines to the spec —
see the comments in `PhotoOrganizer.spec`.

---

## Re-building cleanly

```bat
REM Wipes everything PyInstaller produces.
rmdir /s /q build
rmdir /s /q dist
build.bat
```

If a hidden import goes missing after you add a new module, check the
warn file:

```bat
notepad build\PhotoOrganizer\warn-PhotoOrganizer.txt
```

Look for `missing module named src.X` — fix by adding `src.X` to the
`hidden` list in `PhotoOrganizer.spec`.

---

## Code signing (recommended for v1.1+)

The skeleton is in place. To enable:

1. Get a code-signing certificate (DigiCert, Sectigo, etc.).
2. Install `signtool.exe` from the Windows SDK.
3. Uncomment in `installer.iss`:
   ```
   SignTool=signtool $f
   SignedUninstaller=yes
   ```
4. Configure the Inno Setup tool:
   ```bat
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /Ssigntool="signtool.exe sign /f mycert.pfx /p PASSWORD $f" installer.iss
   ```

Sign the `.exe` inside `dist\PhotoOrganizer\` **before** running
the installer step, and sign the `Setup.exe` after. SmartScreen
reputation begins accruing once the first signed binary is publicly
distributed.

---

## winget submission

A draft winget manifest is in `winget-manifest/`. To publish:

1. Cut a GitHub release with the `.exe` + `Setup.exe`.
2. Compute the SHA-256 of the Setup .exe.
3. Update `winget-manifest/PhotoOrganizer.installer.yaml` with
   that hash + the GitHub release URL.
4. Open a PR against
   [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs)
   under `manifests/d/DharuneshBoopathy/PhotoOrganizer/<version>/`.

---

## Troubleshooting

### Bundle is missing a package
Symptom: `warn-…txt` says
`WARNING: collect_data_files - skipping data collection for module 'X' as it is not a package`.

Cause: the package isn't installed in Python 3.13's site-packages.
Fix:
```bat
py -3.13 -m pip install X
```
Then rebuild.

### `'pyinstaller' is not recognized`
The Python launcher is misconfigured. Use `py -3.13 -m PyInstaller`
explicitly, or fix PATH so `py.exe` is reachable.

### App launches then closes silently
Check `%LOCALAPPDATA%\PhotoOrganizer\app.log`. The crash handler
also writes a per-incident report to `crash_reports\`.

### Inno Setup compile fails on `LicenseFile=LICENSE`
Make sure the file is at the repo root (no extension). Or comment that
line out for a quick local build.
