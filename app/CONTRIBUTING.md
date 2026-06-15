# Contributing

Thanks for considering a contribution! This project ships as a Windows
desktop app built from a single source tree, so the workflow is fairly
direct.

---

## Development setup

```bat
git clone https://github.com/DharuneshBoopathy/PhotoOrganizer.git
cd PhotoOrganizer

REM Use Python 3.13 (the launcher pins it)
py -3.13 -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt
pip install pyinstaller pytest

REM Run from source
python app_main.py
```

For the CLI:

```bat
python -m src.cli --help
```

---

## How to build the .exe

```bat
build.bat            REM produces dist\PhotoOrganizer\
build.bat installer  REM also produces installer\Output\PhotoOrganizer-Setup-*.exe
```

For a portable ZIP and SHA-256 checksums:

```bat
py -3.13 tools\make_portable_zip.py
py -3.13 tools\make_checksums.py
```

---

## Testing

```bat
run_tests.bat
```

Smoke test against a tiny media corpus:

```bat
python tests\create_test_media.py
python -m src.cli organize test_data\source test_data\output
python scripts\verify_no_data_loss.py test_data\source test_data\output
```

---

## Code style

* PEP 8, 4-space indent, max line ~100 cols.
* Type hints encouraged on new public functions.
* Logging via `logging.getLogger(__name__)` — never `print()` in library
  code (the GUI captures the root logger and shows it in the activity
  log box).
* Defensive coercion at SQLite boundaries (`int()`, `bytes_to_embedding`)
  — see `src/face_engine.py` and `src/identity.py` for the pattern.

---

## Safety invariants — please don't break these

These are documented in detail in `docs/ARCHITECTURE.md`:

1. Source files are never moved, modified, or deleted.
2. All copies are SHA-256 verified before the operation is recorded.
3. All multi-row writes go through `db.transaction()`.
4. `copy_operations` is append-only — rollback replays it in reverse.
5. No outbound network calls in the runtime code path.

A PR that touches `src/safety.py`, `src/database.py`, or `src/main.py`
is expected to come with a test that exercises the new path.

---

## Submitting changes

1. Fork the repo
2. Create a topic branch: `git checkout -b fix/short-description`
3. Make your change + add tests if applicable
4. Run `pytest` and `python -m src.cli --help` — both must succeed
5. Update `CHANGELOG.md` under `## [Unreleased]`
6. Open a PR against `main`

The maintainer will run a smoke build against a real photo corpus
before merging.

---

## Reporting bugs

Open an issue at the [bug tracker](https://github.com/DharuneshBoopathy/PhotoOrganizer/issues)
and include:

* The version (Help → About inside the app)
* What you expected to happen
* What actually happened
* The contents of `%LOCALAPPDATA%\PhotoOrganizer\app.log` (or a
  recent file from `crash_reports\` if the app crashed)

Crash reports never contain photo paths beyond what was logged at the
WARNING/ERROR level — review before sending if in doubt.

---

## Releasing (maintainer notes)

See `docs/RELEASE_CHECKLIST.md` for the full procedure. Short version:

```bat
REM 1. Bump version in src\version.py
REM 2. Update CHANGELOG.md
REM 3. Commit, tag, push:
git commit -am "release: v1.x.y"
git tag v1.x.y
git push origin main --tags

REM 4. GitHub Actions builds + uploads release artifacts.
```
