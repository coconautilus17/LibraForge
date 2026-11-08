"""What the shared media inspection learned about each file, kept across processes.

The web app and the fixer and Folder Forge scripts it runs all read and write the same
SQLite file, so a file read once is not read again by the next run, the next page load
or after a restart, as long as its path, size, nanosecond mtime and the reader (with the
ffprobe release it follows) are unchanged. Only successful reads are stored; a store that
cannot be opened or written is skipped, never an error for the caller.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    reader_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    stored_at REAL NOT NULL
)
"""


class MediaFactsStore:
    def __init__(self, path: Path, reader_version: str) -> None:
        self.path = Path(path)
        self.reader_version = reader_version
        self._local = threading.local()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(SCHEMA)
            # Facts from another reader version may be shaped or derived differently.
            db.execute("DELETE FROM facts WHERE reader_version != ?", (reader_version,))

    def _connect(self) -> sqlite3.Connection:
        db = getattr(self._local, "db", None)
        if db is None:
            db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            self._local.db = db
        return db

    def get(self, path: str, size: int, mtime_ns: int) -> dict[str, Any] | None:
        try:
            row = self._connect().execute(
                "SELECT payload FROM facts WHERE path = ? AND size = ? AND mtime_ns = ? AND reader_version = ?",
                (path, size, mtime_ns, self.reader_version),
            ).fetchone()
        except sqlite3.Error:
            return None
        if not row:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None

    def put(self, path: str, size: int, mtime_ns: int, payload: dict[str, Any]) -> None:
        try:
            self._connect().execute(
                "INSERT OR REPLACE INTO facts (path, size, mtime_ns, reader_version, payload, stored_at) VALUES (?, ?, ?, ?, ?, ?)",
                (path, size, mtime_ns, self.reader_version, json.dumps(payload, ensure_ascii=False), time.time()),
            )
        except sqlite3.Error:
            pass

    def forget(self, path: str) -> None:
        try:
            self._connect().execute("DELETE FROM facts WHERE path = ?", (path,))
        except sqlite3.Error:
            pass

    def paths_under(self, root: str) -> list[str]:
        prefix = root.rstrip("/") + "/"
        try:
            rows = self._connect().execute(
                "SELECT path FROM facts WHERE substr(path, 1, ?) = ?", (len(prefix), prefix)
            ).fetchall()
        except sqlite3.Error:
            return []
        return [path for (path,) in rows]
