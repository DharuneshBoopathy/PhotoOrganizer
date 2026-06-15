"""
Safety checks, pre-flight validation, and rollback support.
This module is the last line of defense against data loss.
"""
import os
import sys
import shutil
import socket
import hashlib
import logging
from datetime import datetime
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class SafetyError(Exception):
    pass


def assert_no_network_access():
    """
    Verify we cannot reach the internet.
    This is a best-effort canary — it does not enforce isolation,
    but flags accidental network use during testing.
    """
    test_hosts = ["8.8.8.8", "1.1.1.1"]
    for host in test_hosts:
        try:
            socket.setdefaulttimeout(1)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, 53))
            # If we reach here, internet IS accessible (not necessarily used)
            logger.info(f"[safety] Network is accessible (host: {host}) — "
                        "tool makes no network calls, but internet is reachable on this machine.")
            return
        except (socket.timeout, OSError):
            pass
    logger.info("[safety] No network connectivity detected — fully air-gapped.")


def preflight_check(source_dir: str, output_dir: str) -> List[str]:
    """
    Run safety checks before any operation.
    Returns list of warning strings (empty = all clear).
    Raises SafetyError for hard failures.
    """
    warnings = []

    # Source must exist
    if not os.path.exists(source_dir):
        raise SafetyError(f"Source directory does not exist: {source_dir}")

    if not os.path.isdir(source_dir):
        raise SafetyError(f"Source path is not a directory: {source_dir}")

    # Source must be readable
    if not os.access(source_dir, os.R_OK):
        raise SafetyError(f"Source directory is not readable: {source_dir}")

    # Output must NOT be inside source (would create recursive copies)
    src_real = os.path.realpath(source_dir)
    out_real = os.path.realpath(output_dir)
    if out_real.startswith(src_real + os.sep) or out_real == src_real:
        raise SafetyError(
            f"Output directory '{output_dir}' is inside source '{source_dir}'. "
            "This would cause recursive copying. Choose a different output location."
        )

    # Warn if output dir already has content
    if os.path.exists(output_dir) and os.listdir(output_dir):
        warnings.append(f"Output directory already exists and has content: {output_dir}")

    # Check available disk space (rough estimate)
    try:
        src_size = _dir_size_bytes(source_dir)
        free_space = shutil.disk_usage(os.path.dirname(output_dir) or ".").free
        if free_space < src_size * 1.1:
            warnings.append(
                f"Low disk space: source is ~{src_size // (1024**2)} MB, "
                f"only {free_space // (1024**2)} MB free at output location."
            )
    except Exception:
        pass

    return warnings


def _dir_size_bytes(path: str) -> int:
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path, followlinks=False):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except Exception:
        pass
    return total


def verify_copy(source_path: str, dest_path: str) -> bool:
    """
    Verify a copy is byte-perfect by comparing SHA-256 hashes.
    Critical safety check after every file copy.
    """
    try:
        src_hash = _sha256(source_path)
        dst_hash = _sha256(dest_path)
        return src_hash == dst_hash
    except Exception as e:
        logger.error(f"[safety] Copy verification failed: {e}")
        return False


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def safe_copy(source_path: str, dest_path: str, verify: bool = True) -> Tuple[bool, str]:
    """
    Copy source → dest safely.
    - Creates parent dirs as needed
    - Never overwrites existing files (appends _dup_N suffix)
    - Verifies copy integrity if verify=True
    Returns (success, final_dest_path).
    """
    if not os.path.isfile(source_path):
        return False, ""

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    # Avoid overwriting — find unique name
    final_dest = dest_path
    if os.path.exists(final_dest):
        base, ext = os.path.splitext(dest_path)
        counter = 1
        while os.path.exists(final_dest):
            final_dest = f"{base}_dup_{counter}{ext}"
            counter += 1

    try:
        shutil.copy2(source_path, final_dest)
    except Exception as e:
        return False, str(e)

    if verify:
        if not verify_copy(source_path, final_dest):
            # Remove the bad copy immediately
            try:
                os.remove(final_dest)
            except Exception:
                pass
            return False, "hash_mismatch"

    return True, final_dest


def rollback_session(db, session_id: str, dry_run: bool = False) -> Tuple[int, int]:
    """
    Undo all copy operations from a session by deleting the copies.
    Source files are NEVER touched.
    Returns (deleted_count, error_count).
    """
    ops = db.get_copy_operations(session_id)
    deleted = 0
    errors = 0

    for op in ops:
        dest = op["dest_path"]
        if not dest:
            continue
        if not os.path.exists(dest):
            logger.warning(f"[rollback] Already gone: {dest}")
            continue
        if dry_run:
            print(f"[DRY RUN] Would delete: {dest}")
            deleted += 1
            continue
        try:
            os.remove(dest)
            logger.info(f"[rollback] Deleted copy: {dest}")
            deleted += 1
        except Exception as e:
            logger.error(f"[rollback] Failed to delete {dest}: {e}")
            errors += 1

    return deleted, errors


class SourceFileGuard:
    """
    Context manager. Verifies that the source file hash hasn't changed
    after any block of code — catches accidental writes to source.
    """
    def __init__(self, path: str):
        self.path = path
        self._initial_hash = None

    def __enter__(self):
        self._initial_hash = _sha256(self.path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        final_hash = _sha256(self.path)
        if final_hash != self._initial_hash:
            raise SafetyError(
                f"CRITICAL: Source file was modified during processing! "
                f"File: {self.path}\n"
                f"Before: {self._initial_hash}\n"
                f"After:  {final_hash}"
            )
        return False
