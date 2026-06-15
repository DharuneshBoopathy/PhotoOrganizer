"""
Pack `dist/PhotoOrganizer/` into a portable ZIP.

Why offer a portable build alongside the installer?
  - Users on locked-down corporate machines often can't run an installer
  - "Just unzip and run" is a strong trust signal for privacy-focused apps
  - Same bytes as the installed copy, but no Start Menu / registry entries

Output:
    dist/portable/PhotoOrganizer-<version>-portable.zip

Run:
    py -3.13 tools/make_portable_zip.py
"""
from __future__ import annotations

import os
import sys
import zipfile
import re
from pathlib import Path


def read_version(project_root: Path) -> str:
    p = project_root / "src" / "version.py"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', p.read_text(encoding="utf-8"))
    return m.group(1) if m else "0.0.0"


def main() -> int:
    project = Path(__file__).resolve().parent.parent
    src_dir = project / "dist" / "PhotoOrganizer"
    out_dir = project / "dist" / "portable"

    if not src_dir.is_dir():
        print(f"ERROR: {src_dir} does not exist. Run build.bat first.",
               file=sys.stderr)
        return 1

    version = read_version(project)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"PhotoOrganizer-{version}-portable.zip"
    if zip_path.exists():
        zip_path.unlink()

    # Drop a tiny README into the portable zip explaining the contract
    portable_readme = (
        "Photo Organizer — Portable build\n"
        f"Version {version}\n\n"
        "How to use:\n"
        "  1. Unzip this archive anywhere (USB stick is fine).\n"
        "  2. Double-click PhotoOrganizer.exe.\n\n"
        "Where data goes:\n"
        "  Logs / preferences / face-model cache live under\n"
        "  %LOCALAPPDATA%\\PhotoOrganizer (per Windows user).\n"
        "  Delete that folder to reset the app fully.\n\n"
        "No registry entries, no Start Menu shortcut. Move or delete this\n"
        "folder to uninstall.\n"
    )

    print(f"Packing → {zip_path}")
    n_files = 0
    total_bytes = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # Top-level directory inside the zip = product name + version
        root_in_zip = f"PhotoOrganizer-{version}/"
        zf.writestr(root_in_zip + "PORTABLE-README.txt", portable_readme)

        for path in src_dir.rglob("*"):
            if path.is_file():
                rel = path.relative_to(src_dir)
                arcname = root_in_zip + str(rel).replace("\\", "/")
                zf.write(path, arcname)
                n_files += 1
                total_bytes += path.stat().st_size
                if n_files % 200 == 0:
                    print(f"  ... {n_files} files")

    print(f"Done. {n_files} files, {total_bytes/1024/1024:.1f} MB raw → "
          f"{zip_path.stat().st_size/1024/1024:.1f} MB zip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
