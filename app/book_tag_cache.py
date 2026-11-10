"""Start Here's per-book tag check (ASIN and core fields), kept in the reports folder.

A scan only reads the library; what it learned is remembered here, keyed by
the audio file's path, and trusted only while the file's mtime is unchanged.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.json_files import write_json_atomic

BOOK_TAG_CACHE_VERSION = 1


class BookTagCache:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] | None = None
        self._dirty = False

    def _loaded(self) -> dict[str, dict[str, Any]]:
        if self._entries is None:
            entries: dict[str, dict[str, Any]] = {}
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("version") == BOOK_TAG_CACHE_VERSION and isinstance(data.get("books"), dict):
                    entries = data["books"]
            except (OSError, ValueError, AttributeError):
                pass
            self._entries = entries
        return self._entries

    def get(self, audio_file: Path, mtime: int | None) -> dict[str, Any] | None:
        """``{"asin": str, "fields": {field: bool}}`` from the last read of an unchanged file, or None."""
        if mtime is None:
            return None
        with self._lock:
            entry = self._loaded().get(str(audio_file))
        if not entry or entry.get("mtime") != mtime or not isinstance(entry.get("fields"), dict):
            return None
        return {"asin": entry.get("asin") or "", "fields": entry["fields"]}

    def put(self, audio_file: Path, mtime: int | None, probe: dict[str, Any]) -> None:
        if mtime is None:
            return
        with self._lock:
            self._loaded()[str(audio_file)] = {"mtime": mtime, "asin": probe.get("asin") or "",
                                               "fields": dict(probe.get("fields") or {})}
            self._dirty = True

    def save(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            write_json_atomic(self.path, {"version": BOOK_TAG_CACHE_VERSION, "books": self._entries})
            self._dirty = False
