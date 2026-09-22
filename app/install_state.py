"""First-run state: is this a fresh install or an upgrade, and has the user seen the
author-naming notice? Stored in the reports volume (a dotfile, never touched by report
pruning), because that volume persists across image upgrades in every compose file."""
import json
import os
import time
from pathlib import Path
from typing import Any

from app import author_names


def _has_entries(directory: Path, ignore: tuple[str, ...] = ()) -> bool:
    try:
        return any(entry.name not in ignore for entry in directory.iterdir())
    except OSError:
        return False


def detect_origin(reports_dir: Path, auth_dir: Path, config_dirs: list[Path]) -> str:
    """"upgraded" when earlier use left state behind, else "fresh"."""
    if _has_entries(reports_dir, ignore=(author_names.STATE_FILE.name, author_names.STATE_FILE.name + ".tmp")):
        return "upgraded"
    if _has_entries(auth_dir):
        return "upgraded"
    for config_dir in config_dirs:
        try:
            for entry in config_dir.iterdir():
                if entry.is_file() and not entry.name.endswith(".default.json") and not entry.name.endswith(".tmp"):
                    return "upgraded"
        except OSError:
            continue
    return "fresh"


def _read(state_file: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema_version") == 1 else None


def _write(state: dict[str, Any], state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temp = state_file.with_name(state_file.name + ".tmp")
    temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, state_file)


def init_install_state(version: str, reports_dir: Path, auth_dir: Path, config_dirs: list[Path],
                       state_file: Path | None = None) -> dict[str, Any]:
    """Decide once, on the first start of a version that has this file."""
    state_file = state_file or author_names.STATE_FILE
    existing = _read(state_file)
    if existing is not None:
        return existing
    origin = detect_origin(reports_dir, auth_dir, config_dirs)
    state = {
        "schema_version": 1,
        "first_seen_version": version,
        "origin": origin,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "author_scheme_enabled": origin == "fresh",
        "author_notice_pending": origin == "upgraded",
    }
    _write(state, state_file)
    return state


def update_state(changes: dict[str, Any], state_file: Path | None = None) -> dict[str, Any]:
    state_file = state_file or author_names.STATE_FILE
    state = _read(state_file) or {"schema_version": 1}
    state.update(changes)
    _write(state, state_file)
    return state


def public_view(state_file: Path | None = None) -> dict[str, Any]:
    state = _read(state_file or author_names.STATE_FILE) or {}
    return {
        "origin": state.get("origin", "unknown"),
        "author_scheme_enabled": state.get("author_scheme_enabled") is True,
        "author_notice_pending": state.get("author_notice_pending") is True,
        "first_seen_version": state.get("first_seen_version", ""),
    }
