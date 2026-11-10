"""A dry run's matches, kept so Apply can write them without searching again.

A dry run saves one record per book (``<run id>.plan.jsonl`` in the reports
folder): what its search decided (the match, a skip, a review flag) and the
signature (name, size, mtime) of every audio file the book is made of. Apply
reuses a record only when:

- the dry run used the same matching settings (otherwise no record is used);
- every audio file of the book is unchanged since the dry run;
- the record's search result reads back exactly as it was saved.

Any other book is searched as usual. The checks that come before a search
(duplicate sets, applied and manually applied markers) still run first, so a
book applied by hand after the dry run is left alone.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PLAN_VERSION = 1

# The options that change what a search finds or decides. Write options (write
# mode, covers, writer, workers) are applied at write time and may differ.
MATCHING_OPTIONS = (
    "auth_file", "audible_public_region", "provider", "abs_provider", "limit", "min_score",
    "aggressive", "force", "force_original", "skip_pattern", "ignore_folder",
    "duration_review_threshold", "trust_abs_metadata", "weight_abs_metadata",
    "enable_goodreads_fallback", "abs_agg_url", "audiosilo_url", "abs_tract_url",
)

# ItemResult fields that describe the book's place in this run or its writes,
# not what the search decided; Apply sets them itself.
_RUN_FIELDS = frozenset({
    "index", "file_path", "display_path", "log_lines", "clues", "was_manually_applied",
    "write_done", "metadata_json_done", "asin_conflict", "from_plan",
})


def matching_settings(args) -> dict[str, Any]:
    settings = {}
    for name in MATCHING_OPTIONS:
        value = getattr(args, name, None)
        if name == "auth_file" and getattr(args, "audible_public_region", None):
            value = None  # the public catalog never reads the login file
        if isinstance(value, list):
            value = sorted(value)
        settings[name] = value
    return settings


def file_signatures(paths: Iterable[Path]) -> list[list[Any]] | None:
    """[name, size, mtime_ns] for each file, or None when one cannot be read."""
    out = []
    for path in paths:
        try:
            st = path.stat()
        except OSError:
            return None
        out.append([str(path), st.st_size, st.st_mtime_ns])
    return out


def _round_trips(value: Any) -> bool:
    try:
        return json.loads(json.dumps(value)) == value
    except (TypeError, ValueError):
        return False


def result_record(result) -> dict[str, Any] | None:
    """The search decision of one ItemResult, or None if it cannot be saved exactly."""
    decided = {
        f.name: getattr(result, f.name)
        for f in dataclasses.fields(result)
        if f.name not in _RUN_FIELDS
    }
    return decided if _round_trips(decided) else None


class PlanWriter:
    def __init__(self, path: Path, root: Path, settings: dict[str, Any]):
        self.path = Path(path)
        self.header = {
            "plan_version": PLAN_VERSION,
            "root": str(root),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "settings": settings,
        }

    def write(self, books: Iterable[tuple[Path, list[list[Any]] | None, dict[str, Any] | None]]) -> int:
        """books: (path, signatures, record). Returns how many records were saved."""
        saved = 0
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(self.header) + "\n")
            for path, signatures, record in books:
                if signatures is None or record is None:
                    continue
                fh.write(json.dumps({"path": str(path), "files": signatures, "result": record}) + "\n")
                saved += 1
        tmp.replace(self.path)
        return saved


def read_header(path: Path) -> dict[str, Any] | None:
    try:
        with Path(path).open(encoding="utf-8") as fh:
            header = json.loads(fh.readline())
    except (OSError, ValueError):
        return None
    if not isinstance(header, dict) or header.get("plan_version") != PLAN_VERSION:
        return None
    return header


def load_records(plan_paths: Iterable[Path], settings: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Records by book path from the given plans, newest plan first; the first plan
    holding a book wins. Returns (records, notes for the run log)."""
    records: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    for plan_path in plan_paths:
        plan_path = Path(plan_path)
        header = read_header(plan_path)
        if header is None:
            notes.append(f"Dry run plan unreadable, not used: {plan_path.name}")
            continue
        if header.get("settings") != settings:
            changed = sorted(k for k in set(settings) | set(header.get("settings") or {})
                             if (header.get("settings") or {}).get(k) != settings.get(k))
            notes.append(f"Dry run {plan_path.name} used other matching settings ({', '.join(changed)}); "
                         "its books are searched again")
            continue
        run = plan_path.name.removesuffix(".plan.jsonl")
        with plan_path.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                path = entry.get("path")
                if path and path not in records:
                    records[path] = {"run": run, "files": entry.get("files"), "result": entry.get("result")}
    return records, notes


def usable_record(record: dict[str, Any] | None, signatures: list[list[Any]] | None) -> dict[str, Any] | None:
    """The record's saved result when the book's files are unchanged since the dry run."""
    if not record or signatures is None or record.get("files") != signatures:
        return None
    result = record.get("result")
    return result if isinstance(result, dict) else None


def apply_record(result, decided: dict[str, Any]) -> None:
    """Put a saved search decision onto a fresh ItemResult."""
    names = {f.name for f in dataclasses.fields(result)} - _RUN_FIELDS
    for name, value in decided.items():
        if name in names:
            setattr(result, name, value)
