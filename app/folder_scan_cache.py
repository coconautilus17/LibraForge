from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FOLDER_SCAN_CACHE_VERSION = 2
# v2: each folder entry's per-folder "category" field became a "units" map of
# {unit_ref: category}, so a folder with multiple standalone book units (each
# possibly its own category) no longer collapses onto one shared value. Bumped
# so a v1 cache file on disk from before this change is discarded outright
# rather than partially read under the new shape.


def scan_cache_key(path: Path, ignored_folders: list[str] | None) -> str:
    tokens = sorted(f.strip().lower() for f in (ignored_folders or []) if f and f.strip())
    value = json.dumps({"path": str(path), "ignored_folders": tokens}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_scan_cache_file(cache_path: Path) -> dict[str, Any]:
    if not cache_path.is_file():
        return {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {}}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {}}
    if data.get("version") != FOLDER_SCAN_CACHE_VERSION or not isinstance(data.get("scans"), dict):
        return {"version": FOLDER_SCAN_CACHE_VERSION, "scans": {}}
    return data


def save_scan_cache_file(cache_path: Path, cache: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    temporary.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(cache_path)
