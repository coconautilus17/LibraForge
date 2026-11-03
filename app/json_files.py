"""Saving LibraForge's own JSON files (caches, policies, state)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: Any, *, indent: int | None = None, sort_keys: bool = False) -> None:
    """Write `data` to `path` through a temporary file swapped into place, so a
    reader (or a crash mid-write) never leaves a half-written file. Raises
    OSError like any write; callers that may fail quietly catch it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)
