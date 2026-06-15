"""
Generate SHA-256 checksums for release artifacts.

Run after `build.bat installer` produces the .exe + setup. Writes a
`SHA256SUMS.txt` you upload alongside the binaries on the GitHub
release page so users can verify integrity.

Usage:
    py -3.13 tools/make_checksums.py
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


CANDIDATES = [
    "dist/PhotoOrganizer/PhotoOrganizer.exe",
    "installer/Output",   # all setup .exe files in here
    "dist/portable",      # portable zip output (if make_portable_zip ran)
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*")
                  if p.is_file()
                  and p.suffix.lower() in (".exe", ".zip", ".msi"))


def main() -> int:
    project = Path(__file__).resolve().parent.parent
    os.chdir(project)

    targets: list[Path] = []
    for c in CANDIDATES:
        targets += collect_files(Path(c))

    if not targets:
        print("No release artifacts found. Build first:", file=sys.stderr)
        print("  build.bat installer", file=sys.stderr)
        print("  py -3.13 tools/make_portable_zip.py", file=sys.stderr)
        return 1

    out = project / "SHA256SUMS.txt"
    lines = []
    for f in targets:
        digest = sha256_of(f)
        rel = f.relative_to(project).as_posix()
        lines.append(f"{digest}  {rel}")
        print(f"{digest}  {rel}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
