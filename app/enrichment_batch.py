"""Whole-library Enrichment Forge run.

Compiles every unit (series and standalone books) one at a time with the same
compile the series page uses, so every source's pacing applies across the
whole run. Results are kept in one JSON store as a review report: nothing is
written to Audiobookshelf until the user applies selected units. The store is
saved after every unit, so a stopped or interrupted run resumes where it left
off, and an applied unit is never applied again by accident.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

_DONE_STATES = ("compiled", "applied")


class BatchStore:
    """The run's state in one JSON file, written atomically."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("units", {})
                data.setdefault("order", [])
                return data
        except (OSError, ValueError):
            pass
        return {"status": "idle", "units": {}, "order": []}

    def save(self, data: dict[str, Any]) -> None:
        data["updated_at"] = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


def effective_status(data: dict[str, Any], *, thread_alive: bool) -> str:
    """A run the process no longer drives (container restart) is resumable."""
    status = data.get("status", "idle")
    if status in ("running", "stopping") and not thread_alive:
        return "stopped"
    return status


def slim_result(compiled: dict[str, Any]) -> dict[str, Any]:
    """What the review needs from one compile."""
    status = compiled.get("source_status") or {}
    return {
        "main_genres": compiled.get("main_genres") or [],
        "sub_genres": compiled.get("sub_genres") or [],
        "pinned_genres": compiled.get("pinned_genres") or [],
        "genre_evidence": compiled.get("genre_evidence") or {},
        "agreement": compiled.get("agreement", "ok"),
        "series_evidence": compiled.get("series_evidence") or [],
        "explicit_summary": compiled.get("explicit_summary") or {},
        # How many sources answered at all: a quick "how much do we know" badge.
        "coverage": sum(1 for s in status.values() if int((s or {}).get("found") or 0) > 0),
        "books": [
            {key: book.get(key) for key in ("id", "path", "is_file", "title", "has_audio", "existing_genres", "explicit")}
            for book in compiled.get("books") or []
        ],
    }


def run_batch(
    store: BatchStore,
    units: list[dict[str, Any]],
    compile_fn: Callable[[str, str], dict[str, Any]],
    *,
    should_stop: Callable[[], bool],
    on_progress: Callable[[int, int, str], None] | None = None,
    restart: bool = False,
) -> dict[str, Any]:
    """Compile every unit not already compiled or applied. A failing unit is
    recorded and the run goes on; should_stop() is checked between units."""
    with store.lock:
        data = {"status": "idle", "units": {}, "order": []} if restart else store.load()
        if restart:
            data["started_at"] = time.time()
        for unit in units:
            entry = data["units"].setdefault(unit["key"], {"state": "pending"})
            entry.update({"name": unit["name"], "standalone": bool(unit.get("standalone")),
                          "book_count": unit.get("book_count", 0)})
            if unit["key"] not in data["order"]:
                data["order"].append(unit["key"])
        data["status"] = "running"
        data.setdefault("started_at", time.time())
        store.save(data)

    total = len(data["order"])
    for n, key in enumerate(list(data["order"]), 1):
        entry = data["units"][key]
        if entry["state"] in _DONE_STATES:
            continue
        if should_stop():
            data["status"] = "stopped"
            with store.lock:
                store.save(data)
            return data
        data["current"] = entry["name"]
        try:
            entry["result"] = slim_result(compile_fn(key, entry["name"]))
            entry["state"] = "compiled"
            entry.pop("error", None)
        except Exception as exc:
            entry["state"] = "failed"
            entry["error"] = str(exc) or type(exc).__name__
        with store.lock:
            store.save(data)
        if on_progress:
            on_progress(n, total, entry["name"])
    data["status"] = "done"
    data.pop("current", None)
    with store.lock:
        store.save(data)
    return data


def apply_batch(
    store: BatchStore,
    selections: list[dict[str, Any]],
    apply_fn: Callable[[dict[str, Any], list[str], bool | None], None],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Write the chosen genres (and, when asked, the HaremLit-backed explicit
    flag) to every audio book of each selected unit. One failing book never
    stops the rest; an applied unit is skipped unless `force`."""
    out: dict[str, Any] = {"units": 0, "books": 0, "failed": [], "skipped": []}
    with store.lock:
        data = store.load()
    for selection in selections:
        entry = data["units"].get(selection.get("key"))
        if not entry or entry["state"] not in _DONE_STATES or (entry["state"] == "applied" and not force):
            out["skipped"].append(selection.get("key"))
            continue
        genres = list(selection.get("genres") or [])
        failures = []
        for book in (entry.get("result") or {}).get("books") or []:
            if not book.get("has_audio", True):
                continue  # placeholders / ebooks are never written (#301)
            explicit = None
            ev = book.get("explicit") or {}
            if selection.get("apply_explicit") and ev.get("strength") == "authoritative":
                explicit = ev.get("suggestion") == "explicit"
            try:
                apply_fn(book, genres, explicit)
                out["books"] += 1
            except Exception as exc:
                failures.append({"unit": entry["name"], "title": book.get("title", ""), "error": str(exc)})
        entry.update({"state": "applied", "applied_genres": genres, "applied_at": time.time(), "failures": failures})
        out["units"] += 1
        out["failed"].extend(failures)
        with store.lock:
            store.save(data)
    return out
