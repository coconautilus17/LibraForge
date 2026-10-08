"""Whose book is a folder-level libraforge.json?

A folder-level libraforge.json is meant for a single grouped book or a lone
file. A shared folder (an unsorted root, or an audiobook next to its study
guides) can hold several books, and the file must never be read or written as
if it described a book it does not name. Shared by the fixer and Folder Forge
so both apply the same rule.
"""
import json
from pathlib import Path


def folder_sidecar_belongs_to(payload: dict, source: Path) -> bool:
    """True when a folder-level libraforge.json's recorded data covers `source`.

    An empty/fresh payload has no conflicting claim yet, so it is available.
    Recorded paths are where the book lived when it was processed; a move,
    copy or conversion changes the directory but not the file name, so names
    are compared, not full paths.
    """
    if not payload:
        return True
    source_str = str(source)
    for section_key in ("sidecar", "marker", "scan_cache"):
        src = (payload.get(section_key) or {}).get("source") or {}
        root_file = src.get("root_file")
        chapter_files = src.get("chapter_files") or []
        if root_file or chapter_files:
            if root_file == source_str or source_str in chapter_files:
                return True
            recorded_names = {Path(str(p)).name for p in [root_file, *chapter_files] if p}
            return source.name in recorded_names
    # Marker and backup record only a bare filename (no full source.* block).
    for section_key in ("marker", "backup"):
        named_file = (payload.get(section_key) or {}).get("source_file")
        if named_file:
            return named_file == source.name
    return True


def folder_sidecar_file_belongs_to(sidecar_path: Path, source: Path) -> bool:
    """folder_sidecar_belongs_to() for a file on disk; an unreadable file is
    treated as available, matching how readers already skip a bad sidecar."""
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return folder_sidecar_belongs_to(payload if isinstance(payload, dict) else {}, source)
