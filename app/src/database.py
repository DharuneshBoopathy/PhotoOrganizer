"""
Portable SQLite manifest database.
WAL mode for reliability. All paths stored relative to output_dir for portability.
Supports transactional batches via the .transaction() context manager.
"""
import sqlite3
import json
import os
import contextlib
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS scan_sessions (
    id TEXT PRIMARY KEY,
    source_dir TEXT NOT NULL,
    output_dir TEXT NOT NULL,
    total_files INTEGER DEFAULT 0,
    processed_files INTEGER DEFAULT 0,
    duplicates_found INTEGER DEFAULT 0,
    faces_detected INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    source_path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    phash TEXT,
    file_size INTEGER,
    media_type TEXT,
    mime_type TEXT,
    date_taken TEXT,
    date_file_modified TEXT,
    gps_lat REAL,
    gps_lon REAL,
    gps_location_label TEXT,
    organized_date_path TEXT,
    organized_location_path TEXT,
    thumbnail_path TEXT,
    is_duplicate INTEGER DEFAULT 0,
    duplicate_of_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES scan_sessions(id),
    FOREIGN KEY (duplicate_of_id) REFERENCES media(id)
);

CREATE INDEX IF NOT EXISTS idx_media_sha256 ON media(sha256);
CREATE INDEX IF NOT EXISTS idx_media_phash ON media(phash);
CREATE INDEX IF NOT EXISTS idx_media_date ON media(date_taken);
CREATE INDEX IF NOT EXISTS idx_media_session ON media(session_id);

CREATE TABLE IF NOT EXISTS face_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_key TEXT NOT NULL UNIQUE,
    label TEXT,
    representative_media_id INTEGER,
    member_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (representative_media_id) REFERENCES media(id)
);

CREATE TABLE IF NOT EXISTS face_detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL,
    cluster_key TEXT,
    bbox_x1 INTEGER,
    bbox_y1 INTEGER,
    bbox_x2 INTEGER,
    bbox_y2 INTEGER,
    embedding BLOB,
    confidence REAL,
    FOREIGN KEY (media_id) REFERENCES media(id)
);

CREATE INDEX IF NOT EXISTS idx_face_media ON face_detections(media_id);
CREATE INDEX IF NOT EXISTS idx_face_cluster ON face_detections(cluster_key);

CREATE TABLE IF NOT EXISTS operations_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    source_path TEXT,
    dest_path TEXT,
    status TEXT,
    error_message TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ops_session ON operations_log(session_id);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Idempotent schema migrations for existing DBs."""
        fd_cols = [r[1] for r in self.conn.execute("PRAGMA table_info(face_detections)").fetchall()]
        if "quality_score" not in fd_cols:
            self.conn.execute("ALTER TABLE face_detections ADD COLUMN quality_score REAL")
        if "landmarks" not in fd_cols:
            self.conn.execute("ALTER TABLE face_detections ADD COLUMN landmarks BLOB")
        if "is_stranger" not in fd_cols:
            self.conn.execute("ALTER TABLE face_detections ADD COLUMN is_stranger INTEGER DEFAULT 0")

        cc_cols = [r[1] for r in self.conn.execute("PRAGMA table_info(face_clusters)").fetchall()]
        for col, ddl in [
            ("cohesion", "REAL"),
            ("quality_flag", "TEXT"),
            ("avatar_path", "TEXT"),
            ("folder_path", "TEXT"),
            ("is_stranger", "INTEGER DEFAULT 0"),
            ("manual_label", "INTEGER DEFAULT 0"),
        ]:
            if col not in cc_cols:
                self.conn.execute(f"ALTER TABLE face_clusters ADD COLUMN {col} {ddl}")

        # Burst groups + relationships tables (created on first run)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS burst_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                burst_key TEXT NOT NULL UNIQUE,
                photo_count INTEGER,
                best_media_id INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS burst_members (
                burst_id INTEGER NOT NULL,
                media_id INTEGER NOT NULL,
                PRIMARY KEY (burst_id, media_id),
                FOREIGN KEY (burst_id) REFERENCES burst_groups(id),
                FOREIGN KEY (media_id) REFERENCES media(id)
            );
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_a TEXT NOT NULL,
                cluster_b TEXT NOT NULL,
                co_count INTEGER DEFAULT 0,
                folder_path TEXT,
                UNIQUE(cluster_a, cluster_b)
            );
            CREATE INDEX IF NOT EXISTS idx_media_size ON media(file_size);
            CREATE INDEX IF NOT EXISTS idx_media_mtime ON media(date_file_modified);
            CREATE INDEX IF NOT EXISTS idx_media_isdup ON media(is_duplicate);
        """)
        self.conn.commit()

    # ── Transaction helper ────────────────────────────────────────────────────

    @contextlib.contextmanager
    def transaction(self):
        """Atomic batch. On exception, rolls back; on success, commits once."""
        try:
            self.conn.execute("BEGIN")
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def close(self):
        self.conn.commit()
        self.conn.close()

    # ── Integrity / repair ────────────────────────────────────────────────────

    def integrity_check(self) -> Tuple[bool, List[str]]:
        """
        Run SQLite's `PRAGMA integrity_check`.
        Returns (ok, problems). `ok=True` means the DB is healthy.
        """
        try:
            rows = self.conn.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as e:
            return False, [f"integrity_check failed: {e}"]
        problems = [r[0] for r in rows if r[0] != "ok"]
        return (len(problems) == 0), problems

    def vacuum(self) -> None:
        """Reclaim space + defragment. Safe to run while no other writer is open."""
        self.conn.commit()
        self.conn.execute("VACUUM")

    def repair(self) -> Tuple[bool, str]:
        """
        Best-effort repair. Strategy:
          1. integrity_check — bail if already OK
          2. checkpoint WAL into the main DB
          3. VACUUM
          4. integrity_check again

        For genuine corruption the safe answer is: dump → reimport, which
        is out of scope for an in-process repair. The caller (GUI tool)
        should fall back to renaming the .db aside and asking the user
        to re-run the pipeline.
        """
        ok, _ = self.integrity_check()
        if ok:
            return True, "already healthy"
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()
            self.conn.execute("VACUUM")
            ok2, problems = self.integrity_check()
            if ok2:
                return True, "repaired via vacuum"
            return False, "; ".join(problems[:5]) or "still corrupt"
        except sqlite3.DatabaseError as e:
            return False, str(e)

    # ── Sessions ──────────────────────────────────────────────────────────────

    def create_session(self, session_id: str, source_dir: str, output_dir: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO scan_sessions (id, source_dir, output_dir, started_at) VALUES (?, ?, ?, ?)",
            (session_id, source_dir, output_dir, datetime.now().isoformat()),
        )
        self.conn.commit()

    def update_session(self, session_id: str, **kwargs) -> None:
        allowed = {"total_files", "processed_files", "duplicates_found", "faces_detected", "status", "completed_at"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k}=?" for k in updates)
        self.conn.execute(f"UPDATE scan_sessions SET {cols} WHERE id=?", (*updates.values(), session_id))
        self.conn.commit()

    def get_session(self, session_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM scan_sessions WHERE id=?", (session_id,)).fetchone()

    # ── Media ─────────────────────────────────────────────────────────────────

    def insert_media(self, record: Dict[str, Any]) -> int:
        cols = ", ".join(record.keys())
        placeholders = ", ".join("?" * len(record))
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO media ({cols}) VALUES ({placeholders})",
            list(record.values()),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_media_by_path(self, source_path: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM media WHERE source_path=?", (source_path,)).fetchone()

    def get_media_by_sha256(self, sha256: str) -> List[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM media WHERE sha256=?", (sha256,)).fetchall()

    def get_all_phashes(self) -> List[Tuple[int, str]]:
        rows = self.conn.execute("SELECT id, phash FROM media WHERE phash IS NOT NULL").fetchall()
        return [(r["id"], r["phash"]) for r in rows]

    def update_media(self, media_id: int, **kwargs) -> None:
        if not kwargs:
            return
        cols = ", ".join(f"{k}=?" for k in kwargs)
        self.conn.execute(f"UPDATE media SET {cols} WHERE id=?", (*kwargs.values(), media_id))
        self.conn.commit()

    def get_all_media(self, session_id: Optional[str] = None) -> List[sqlite3.Row]:
        if session_id:
            return self.conn.execute("SELECT * FROM media WHERE session_id=?", (session_id,)).fetchall()
        return self.conn.execute("SELECT * FROM media").fetchall()

    def count_media(self, session_id: Optional[str] = None) -> int:
        if session_id:
            row = self.conn.execute("SELECT COUNT(*) FROM media WHERE session_id=?", (session_id,)).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM media").fetchone()
        return row[0]

    # ── Face Clusters ─────────────────────────────────────────────────────────

    def upsert_face_cluster(self, cluster_key: str, label: Optional[str] = None,
                             rep_media_id: Optional[int] = None, member_count: int = 0,
                             commit: bool = True) -> None:
        self.conn.execute(
            """INSERT INTO face_clusters (cluster_key, label, representative_media_id, member_count)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(cluster_key) DO UPDATE SET
                 member_count=excluded.member_count,
                 label=COALESCE(excluded.label, face_clusters.label),
                 representative_media_id=COALESCE(excluded.representative_media_id,
                                                   face_clusters.representative_media_id)""",
            (cluster_key, label, rep_media_id, member_count),
        )
        if commit:
            self.conn.commit()

    def get_face_clusters(self) -> List[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM face_clusters ORDER BY member_count DESC").fetchall()

    def label_face_cluster(self, cluster_key: str, label: str) -> None:
        self.conn.execute("UPDATE face_clusters SET label=? WHERE cluster_key=?", (label, cluster_key))
        self.conn.commit()

    # ── Face Detections ───────────────────────────────────────────────────────

    def insert_face_detection(self, media_id: int, cluster_key: Optional[str],
                               bbox: Tuple[int, int, int, int], embedding_bytes: bytes,
                               confidence: float,
                               landmarks_bytes: Optional[bytes] = None,
                               commit: bool = True) -> None:
        x1, y1, x2, y2 = bbox
        self.conn.execute(
            """INSERT INTO face_detections
               (media_id, cluster_key, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                embedding, confidence, landmarks)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(media_id), cluster_key, int(x1), int(y1), int(x2), int(y2),
             embedding_bytes, float(confidence), landmarks_bytes),
        )
        if commit:
            self.conn.commit()

    def get_detections_for_media(self, media_id: int) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM face_detections WHERE media_id=?", (media_id,)
        ).fetchall()

    def get_all_embeddings(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, media_id, embedding, bbox_x1, bbox_y1, bbox_x2, bbox_y2 FROM face_detections"
        ).fetchall()

    def update_detection_cluster(self, detection_id: int, cluster_key: str,
                                  commit: bool = True) -> None:
        self.conn.execute(
            "UPDATE face_detections SET cluster_key=? WHERE id=?", (cluster_key, detection_id)
        )
        if commit:
            self.conn.commit()

    def update_detection_quality(self, detection_id: int, quality_score: float) -> None:
        self.conn.execute(
            "UPDATE face_detections SET quality_score=? WHERE id=?", (quality_score, detection_id)
        )
        self.conn.commit()

    def get_detections_by_cluster(self, cluster_key: str) -> List[sqlite3.Row]:
        return self.conn.execute(
            """SELECT fd.*, m.source_path AS media_source_path, m.thumbnail_path AS media_thumbnail_path
               FROM face_detections fd
               JOIN media m ON m.id = fd.media_id
               WHERE fd.cluster_key=?""",
            (cluster_key,),
        ).fetchall()

    def update_cluster_quality(self, cluster_key: str, cohesion: float, quality_flag: str) -> None:
        self.conn.execute(
            "UPDATE face_clusters SET cohesion=?, quality_flag=? WHERE cluster_key=?",
            (cohesion, quality_flag, cluster_key),
        )
        self.conn.commit()

    def update_cluster_paths(self, cluster_key: str, avatar_path: Optional[str] = None,
                              folder_path: Optional[str] = None) -> None:
        updates = {}
        if avatar_path is not None:
            updates["avatar_path"] = avatar_path
        if folder_path is not None:
            updates["folder_path"] = folder_path
        if not updates:
            return
        cols = ", ".join(f"{k}=?" for k in updates)
        self.conn.execute(
            f"UPDATE face_clusters SET {cols} WHERE cluster_key=?",
            (*updates.values(), cluster_key),
        )
        self.conn.commit()

    # ── Operations Log ────────────────────────────────────────────────────────

    def log_operation(self, session_id: str, operation: str, source_path: str = "",
                       dest_path: str = "", status: str = "ok", error: str = "") -> None:
        self.conn.execute(
            """INSERT INTO operations_log (session_id, operation, source_path, dest_path, status, error_message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, operation, source_path, dest_path, status, error),
        )
        self.conn.commit()

    def get_copy_operations(self, session_id: Optional[str] = None) -> List[sqlite3.Row]:
        if session_id:
            return self.conn.execute(
                """SELECT * FROM operations_log
                   WHERE session_id=? AND operation='copy' AND status='ok'
                   ORDER BY id DESC""",
                (session_id,),
            ).fetchall()
        return self.conn.execute(
            """SELECT * FROM operations_log
               WHERE operation='copy' AND status='ok'
               ORDER BY id DESC"""
        ).fetchall()

    def get_all_sessions(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM scan_sessions ORDER BY started_at DESC"
        ).fetchall()

    # ── Search / labeling / repair helpers ───────────────────────────────────

    def get_cluster(self, cluster_key: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM face_clusters WHERE cluster_key=?", (cluster_key,)
        ).fetchone()

    def rename_cluster(self, old_key: str, new_key: str) -> None:
        with self.transaction() as c:
            c.execute("UPDATE face_clusters SET cluster_key=? WHERE cluster_key=?",
                       (new_key, old_key))
            c.execute("UPDATE face_detections SET cluster_key=? WHERE cluster_key=?",
                       (new_key, old_key))
            c.execute("UPDATE relationships SET cluster_a=? WHERE cluster_a=?",
                       (new_key, old_key))
            c.execute("UPDATE relationships SET cluster_b=? WHERE cluster_b=?",
                       (new_key, old_key))

    def label_cluster(self, cluster_key: str, label: str, manual: bool = True) -> None:
        self.conn.execute(
            "UPDATE face_clusters SET label=?, manual_label=? WHERE cluster_key=?",
            (label, 1 if manual else 0, cluster_key),
        )
        self.conn.commit()

    def merge_clusters(self, source_key: str, target_key: str) -> int:
        """Move all detections from source_key into target_key, drop source. Returns moved count."""
        moved = 0
        with self.transaction() as c:
            cur = c.execute("UPDATE face_detections SET cluster_key=? WHERE cluster_key=?",
                             (target_key, source_key))
            moved = cur.rowcount
            # Recompute counts
            new_count = c.execute("SELECT COUNT(*) FROM face_detections WHERE cluster_key=?",
                                   (target_key,)).fetchone()[0]
            c.execute("UPDATE face_clusters SET member_count=? WHERE cluster_key=?",
                       (new_count, target_key))
            c.execute("DELETE FROM face_clusters WHERE cluster_key=?", (source_key,))
        return moved

    def split_cluster(self, source_key: str, detection_ids: List[int],
                       new_key: str) -> int:
        """Move specific detection_ids into a new cluster."""
        if not detection_ids:
            return 0
        placeholders = ",".join("?" * len(detection_ids))
        with self.transaction() as c:
            c.execute(f"UPDATE face_detections SET cluster_key=? "
                       f"WHERE id IN ({placeholders})",
                       (new_key, *detection_ids))
            new_count = c.execute(
                "SELECT COUNT(*) FROM face_detections WHERE cluster_key=?", (new_key,)
            ).fetchone()[0]
            c.execute(
                """INSERT INTO face_clusters (cluster_key, member_count) VALUES (?, ?)
                   ON CONFLICT(cluster_key) DO UPDATE SET member_count=excluded.member_count""",
                (new_key, new_count),
            )
            old_count = c.execute(
                "SELECT COUNT(*) FROM face_detections WHERE cluster_key=?", (source_key,)
            ).fetchone()[0]
            c.execute("UPDATE face_clusters SET member_count=? WHERE cluster_key=?",
                       (old_count, source_key))
        return len(detection_ids)

    def media_with_cluster(self, cluster_key: str) -> List[sqlite3.Row]:
        return self.conn.execute(
            """SELECT DISTINCT m.* FROM media m
               JOIN face_detections fd ON fd.media_id = m.id
               WHERE fd.cluster_key=?""",
            (cluster_key,),
        ).fetchall()

    def media_in_date_range(self, start_iso: str, end_iso: str) -> List[sqlite3.Row]:
        return self.conn.execute(
            """SELECT * FROM media
               WHERE date_taken BETWEEN ? AND ?
               ORDER BY date_taken""",
            (start_iso, end_iso),
        ).fetchall()

    def media_with_two_clusters(self, key_a: str, key_b: str) -> List[sqlite3.Row]:
        return self.conn.execute(
            """SELECT DISTINCT m.* FROM media m
               WHERE EXISTS (SELECT 1 FROM face_detections fd
                             WHERE fd.media_id = m.id AND fd.cluster_key=?)
                 AND EXISTS (SELECT 1 FROM face_detections fd
                             WHERE fd.media_id = m.id AND fd.cluster_key=?)""",
            (key_a, key_b),
        ).fetchall()

    # ── Burst groups ──────────────────────────────────────────────────────────

    def insert_burst_group(self, burst_key: str, photo_count: int,
                            best_media_id: Optional[int] = None) -> int:
        with self.transaction() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO burst_groups (burst_key, photo_count, best_media_id)
                   VALUES (?, ?, ?)""",
                (burst_key, photo_count, best_media_id),
            )
            burst_id = cur.lastrowid
            if not burst_id:
                row = c.execute("SELECT id FROM burst_groups WHERE burst_key=?",
                                 (burst_key,)).fetchone()
                burst_id = row["id"] if row else None
        return burst_id

    def add_burst_member(self, burst_id: int, media_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO burst_members (burst_id, media_id) VALUES (?, ?)",
            (burst_id, media_id),
        )
        self.conn.commit()

    # ── Relationships ─────────────────────────────────────────────────────────

    def upsert_relationship(self, key_a: str, key_b: str, count: int,
                             folder_path: Optional[str] = None) -> None:
        # Always store with key_a < key_b for uniqueness
        a, b = sorted([key_a, key_b])
        self.conn.execute(
            """INSERT INTO relationships (cluster_a, cluster_b, co_count, folder_path)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(cluster_a, cluster_b) DO UPDATE SET
                 co_count=excluded.co_count,
                 folder_path=COALESCE(excluded.folder_path, relationships.folder_path)""",
            (a, b, count, folder_path),
        )
        self.conn.commit()

    def get_relationships(self, min_count: int = 2) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM relationships WHERE co_count >= ? ORDER BY co_count DESC",
            (min_count,),
        ).fetchall()

    # ── Stranger flag ─────────────────────────────────────────────────────────

    def mark_cluster_stranger(self, cluster_key: str, is_stranger: bool = True) -> None:
        self.conn.execute(
            "UPDATE face_clusters SET is_stranger=? WHERE cluster_key=?",
            (1 if is_stranger else 0, cluster_key),
        )
        self.conn.commit()

    def get_stranger_clusters(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM face_clusters WHERE is_stranger=1"
        ).fetchall()
