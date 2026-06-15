# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Photo Organizer.
"""
import os
import re
import sys
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    collect_dynamic_libs,
)

block_cipher = None

# ROOT is the project base directory
_spec_path = Path(SPECPATH)
if _spec_path.is_file():
    ROOT = str(_spec_path.parent.resolve())
else:
    ROOT = str(_spec_path.resolve())

APP_ROOT = os.path.join(ROOT, "app")

# ----------------------------------------------------------------------------
# Read version from app/src/version.py
# ----------------------------------------------------------------------------
def _read_version():
    p = os.path.join(APP_ROOT, "src", "version.py")
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            if "__version__" in line:
                return line.split("=")[1].strip().strip('"').strip("'")

VERSION = _read_version()

# ----------------------------------------------------------------------------
# Vendor packages with native bits / data
# ----------------------------------------------------------------------------
hidden = []
datas = []
binaries = []

for pkg in (
    "onnxruntime",
    "insightface",
    "PIL",
    "skimage",
    "scipy",
    "sklearn",
    "imagehash",
    "cv2",
    "reverse_geocoder",
    "exifread",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden += h
    except Exception:
        pass

try:
    datas += collect_data_files("tkinter")
except Exception:
    pass

hidden += collect_submodules("PIL")

# Our own packages
hidden += [
    "src", "src.about_dialog", "src.burst_detector", "src.cli",
    "src.cluster_repair", "src.database", "src.error_handler",
    "src.face_engine", "src.folder_icon", "src.gui_app", "src.gui_log",
    "src.hasher", "src.identity", "src.incremental", "src.labeling",
    "src.labeling_ui", "src.main", "src.metadata", "src.organizer",
    "src.person_album", "src.preferences", "src.relationships",
    "src.report", "src.safety", "src.scanner", "src.search",
    "src.settings_window", "src.stranger_filter", "src.thumbnail",
    "src.timeline", "src.utils", "src.version", "src.welcome_wizard",
    "src.xmp_tags",
]

# ----------------------------------------------------------------------------
# Bundle assets/, docs/ icons, license
# ----------------------------------------------------------------------------
def _bundle_app_dir(rel_dir: str):
    """Bundle a directory from inside 'app/' into the same relative path in the bundle."""
    abs_src = os.path.join(APP_ROOT, rel_dir)
    if not os.path.isdir(abs_src):
        return
    for root, _, files in os.walk(abs_src):
        for f in files:
            full = os.path.join(root, f)
            # We want 'app/assets/foo' to end up at 'assets/foo' in the bundle
            target_dir = os.path.relpath(os.path.dirname(full), APP_ROOT)
            datas.append((full, target_dir))

_bundle_app_dir("assets")

# Metadata files from root
for fname in ("LICENSE", "README.md", "NOTICE"):
    p = os.path.join(ROOT, fname)
    if os.path.isfile(p):
        datas.append((p, "."))

# Metadata files from app/
for fname in ("CHANGELOG.md", "CONTRIBUTING.md"):
    p = os.path.join(APP_ROOT, fname)
    if os.path.isfile(p):
        datas.append((p, "."))

# ----------------------------------------------------------------------------
# Versioned EXE metadata
# ----------------------------------------------------------------------------
def _write_version_resource() -> str:
    parts = [int(x) for x in VERSION.split(".")] + [0, 0, 0, 0]
    a, b, c, d = parts[:4]
    body = f"""
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {d}),
    prodvers=({a}, {b}, {c}, {d}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(u'040904B0', [
        StringStruct(u'CompanyName', u'Photo Organizer Project'),
        StringStruct(u'FileDescription', u'Photo Organizer'),
        StringStruct(u'FileVersion', u'{VERSION}'),
        StringStruct(u'InternalName', u'PhotoOrganizer'),
        StringStruct(u'LegalCopyright', u'(c) 2026 Photo Organizer Project. MIT License.'),
        StringStruct(u'OriginalFilename', u'PhotoOrganizer.exe'),
        StringStruct(u'ProductName', u'Photo Organizer'),
        StringStruct(u'ProductVersion', u'{VERSION}'),
      ])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    out = os.path.join(ROOT, "build", "_version_info.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(body)
    return out

VERSION_FILE = _write_version_resource()

# ----------------------------------------------------------------------------
# Analysis → PYZ → EXE → COLLECT
# ----------------------------------------------------------------------------
a = Analysis(
    ["app_main.py"],
    pathex=[ROOT, APP_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "matplotlib.pyplot", "pandas", "torch", "tensorflow",
        "dask", "dask.array", "cupy", "ndonnx", "pyamg", "pooch", "numpydoc",
        "pytest", "IPython", "notebook", "jupyter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

ICON = os.path.join(APP_ROOT, "assets", "app_icon.ico")
if not os.path.isfile(ICON):
    ICON = None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PhotoOrganizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
    version=VERSION_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PhotoOrganizer",
)
