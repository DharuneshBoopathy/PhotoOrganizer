# Verification Checklist — No Data Loss

Run through this checklist after every organize session.

---

## Before Running

- [ ] Source directory is backed up (or is on read-only media)
- [ ] Output directory has enough free space (≥ source size)
- [ ] Output directory is NOT inside source directory
- [ ] Run `run.bat scan "C:\YourPhotos"` to preview count

---

## After Running

### 1. Automated Verification (Required)

```bat
call .venv\Scripts\activate.bat
python scripts/verify_no_data_loss.py "C:\YourPhotos" "D:\Organized"
```

Expected output:
```
[OK]   All N source files still exist.
[OK]   All source files have matching SHA-256 hashes (unmodified).
[OK]   N verified copies are all byte-perfect.
[OK]   No source files have been deleted.
RESULT: ALL CHECKS PASSED. No data loss detected.
```

### 2. Manual Spot Checks

- [ ] Pick 5 random files from source — verify they exist unchanged
- [ ] Open `D:\Organized\manifest.db` in DB Browser for SQLite
  - Check `media` table: every row has a valid `source_path`
  - Check `operations_log`: all rows have `status = 'ok'`
- [ ] Browse `D:\Organized\Photos_By_Date\` — folders should be YYYY/YYYY-MM/YYYY-MM-DD
- [ ] Browse `D:\Organized\Duplicate_Review\` — verify duplicates are there but NOT deleted from source
- [ ] Check `D:\Organized\Index\logs\` — review log file for any ERROR lines

### 3. Duplicate Review (Manual — Never Automatic)

- [ ] Open `D:\Organized\Duplicate_Review\exact\` — byte-perfect duplicates
- [ ] Open `D:\Organized\Duplicate_Review\near\` — visually similar photos
- [ ] **Manually decide** which to keep — the organizer NEVER auto-deletes
- [ ] To remove a duplicate from source, do it manually after visual confirmation

### 4. Face Clustering (If Enabled)

- [ ] Browse `D:\Organized\Photos_By_Face\` — each folder is one person cluster
- [ ] Run `run.bat label-faces "D:\Organized"` to assign real names
- [ ] Verify unknown faces in `unknown_*` folders are actually unrecognized people

---

## Rollback

If something went wrong, undo the entire session:

```bat
run.bat status "D:\Organized"              # find session ID
run.bat rollback "D:\Organized" SESSION_ID --dry-run   # preview
run.bat rollback "D:\Organized" SESSION_ID             # execute
```

Rollback ONLY deletes copies in the output directory.
**It never touches source files.**

---

## Privacy Verification

- [ ] Run Wireshark or Resource Monitor during organize — confirm zero outbound connections
- [ ] Check Windows Firewall logs — no connections from python.exe to internet
- [ ] The code contains no `requests`, `urllib`, `http.client`, or socket calls to external hosts
- [ ] InsightFace models are loaded from local disk only (`~/.insightface/` or custom `--model-dir`)

---

## USB Portability Check

When moving the organized USB to another computer:

- [ ] `manifest.db` at root of output — opens with any SQLite viewer
- [ ] `Thumbnails/` — standard JPEG files, viewable in any image app
- [ ] `Photos_By_Date/`, `Photos_By_Face/`, `Photos_By_Location/` — standard folders
- [ ] Original file paths in DB are absolute — use `verify_no_data_loss.py` only on the original machine
