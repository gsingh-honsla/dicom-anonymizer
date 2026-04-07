"""SQLite audit trail for anonymization operations."""

from __future__ import annotations

import logging
import sqlite3
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..core.anonymizer import AnonymizationResult

logger = logging.getLogger(__name__)

_COMMIT_BATCH_SIZE = 50
_MAX_RETRIES = 3
_RETRY_DELAY = 0.5


class AuditLogger:
    """Logs all anonymization operations to a SQLite database.

    Designed for reliability on external drives (exFAT, FAT32, USB) commonly
    used in hospital data collection.  Key resilience measures:
    - Batched commits (every 50 files) to reduce fsync pressure
    - Automatic retry with backoff for transient I/O errors
    - DELETE journal mode instead of WAL for broader filesystem support
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = None
        self._pending = 0
        self._init_db()

    def _execute_with_retry(self, fn, *args, **kwargs):
        """Execute a database operation with retry logic for transient I/O errors."""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if attempt == _MAX_RETRIES:
                    logger.error("Audit DB error after %d retries: %s", _MAX_RETRIES, e)
                    raise
                logger.warning("Audit DB retry %d/%d: %s", attempt, _MAX_RETRIES, e)
                time.sleep(_RETRY_DELAY * attempt)

    def _commit(self, force: bool = False):
        """Commit pending changes, batching by default for performance."""
        self._pending += 1
        if force or self._pending >= _COMMIT_BATCH_SIZE:
            self._execute_with_retry(self._conn.commit)
            self._pending = 0

    def _init_db(self):
        """Create the audit database and tables if they don't exist."""
        self._conn = sqlite3.connect(str(self.db_path), timeout=30)
        # Use DELETE journal mode — more compatible with external/USB drives
        # than WAL, which requires shared-memory support the filesystem may lack.
        self._conn.execute("PRAGMA journal_mode=DELETE")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS anonymization_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                source_dir TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                total_files INTEGER DEFAULT 0,
                files_processed INTEGER DEFAULT 0,
                files_failed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'in_progress'
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS file_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                source_path TEXT NOT NULL,
                output_path TEXT,
                output_hash TEXT,
                tags_modified TEXT,
                tags_removed TEXT,
                uids_replaced TEXT,
                private_tags_removed INTEGER DEFAULT 0,
                warnings TEXT,
                success INTEGER NOT NULL,
                error TEXT,
                FOREIGN KEY (run_id) REFERENCES anonymization_runs(run_id)
            )
        """)
        self._conn.commit()

    def start_run(self, source_dir: Path, output_dir: Path, total_files: int) -> int:
        """Record the start of an anonymization run. Returns run_id."""
        cursor = self._conn.execute(
            """INSERT INTO anonymization_runs
               (started_at, source_dir, output_dir, total_files)
               VALUES (?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                str(source_dir),
                str(output_dir),
                total_files,
            ),
        )
        self._commit(force=True)
        return cursor.lastrowid

    def log_file(
        self,
        run_id: int,
        result: AnonymizationResult,
        output_path: Optional[Path] = None,
        output_hash: str = "",
    ):
        """Log the result of processing a single file."""
        self._conn.execute(
            """INSERT INTO file_log
               (run_id, timestamp, source_path, output_path, output_hash,
                tags_modified, tags_removed, uids_replaced,
                private_tags_removed, warnings, success, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                datetime.now(timezone.utc).isoformat(),
                str(result.source_path),
                str(output_path) if output_path else None,
                output_hash,
                json.dumps(result.tags_modified),
                json.dumps(result.tags_removed),
                json.dumps(result.uids_replaced),
                result.private_tags_removed,
                json.dumps(result.warnings),
                1 if result.success else 0,
                result.error,
            ),
        )
        self._commit()

    def complete_run(self, run_id: int, files_processed: int, files_failed: int):
        """Record the completion of an anonymization run."""
        self._conn.execute(
            """UPDATE anonymization_runs
               SET completed_at = ?, files_processed = ?, files_failed = ?,
                   status = 'completed'
               WHERE run_id = ?""",
            (
                datetime.now(timezone.utc).isoformat(),
                files_processed,
                files_failed,
                run_id,
            ),
        )
        self._commit(force=True)

    def fail_run(self, run_id: int, files_processed: int, files_failed: int):
        """Record a failed/cancelled run."""
        self._conn.execute(
            """UPDATE anonymization_runs
               SET completed_at = ?, files_processed = ?, files_failed = ?,
                   status = 'failed'
               WHERE run_id = ?""",
            (
                datetime.now(timezone.utc).isoformat(),
                files_processed,
                files_failed,
                run_id,
            ),
        )
        self._commit(force=True)

    def close(self):
        """Flush pending writes and close the database connection."""
        if self._conn:
            if self._pending > 0:
                try:
                    self._conn.commit()
                except sqlite3.OperationalError:
                    logger.warning("Failed to flush audit log on close")
                self._pending = 0
            self._conn.close()
            self._conn = None
