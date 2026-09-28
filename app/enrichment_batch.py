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


def effective_status(data: dict[str, Any], *, thread_alive: bool, stop_requested: bool = False) -> str:
    """The thread is the truth: alive means running (or stopping once asked),
    even before it has saved; a run the process no longer drives (container
    restart) is resumable."""
    if thread_alive:
        return "stopping" if stop_requested else "running"
    status = data.get("status", "idle")
    return "stopped" if status in ("running", "stopping") else status


def _update(store: BatchStore, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Load the latest file, change it, save it: every writer merges into what
    is on disk, so the run never overwrites an apply (or the other way round)."""
    with store.lock:
        data = store.load()
        change(data)
        store.save(data)
        return data


def _needs_compile(entry: dict[str, Any]) -> bool:
    if entry["state"] in ("applied", "apply_failed"):
        return False
    if entry["state"] == "compiled":
        # Compiled while a source was paused: recompile on the next run.
        return bool((entry.get("result") or {}).get("degraded"))
    return True


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
        # Sources that were paused or failing while this unit compiled.
        "degraded": sorted(key for key, s in status.items()
                           if (s or {}).get("rate_limited") or int((s or {}).get("skipped") or 0) > 0
                           or (s or {}).get("state") == "failed"),
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
    """Compile every unit that still needs it (pending, failed, or compiled
    while a source was paused). A failing unit is recorded and the run goes
    on; should_stop() is checked between units."""
    def start(data: dict[str, Any]) -> None:
        if restart:
            data.clear()
            data.update({"status": "idle", "units": {}, "order": [], "started_at": time.time()})
        for unit in units:
            entry = data["units"].setdefault(unit["key"], {"state": "pending"})
            entry.update({"name": unit["name"], "standalone": bool(unit.get("standalone")),
                          "book_count": unit.get("book_count", 0)})
            if unit["key"] not in data["order"]:
                data["order"].append(unit["key"])
        data["status"] = "running"
        data.setdefault("started_at", time.time())

    order = list(_update(store, start)["order"])
    total = len(order)
    for n, key in enumerate(order, 1):
        entry = store.load()["units"].get(key)
        if entry is None or not _needs_compile(entry):
            continue
        if should_stop():
            return _update(store, lambda d: (d.update({"status": "stopped"}), d.pop("current", None)))
        name = entry.get("name", key)
        _update(store, lambda d: d.update({"current": name}))
        try:
            result, error = slim_result(compile_fn(key, name)), ""
        except Exception as exc:
            result, error = None, str(exc) or type(exc).__name__

        def put(d: dict[str, Any]) -> None:
            current = d["units"].get(key)
            if current is None or current["state"] in ("applied", "apply_failed"):
                return  # applied meanwhile: keep it
            if result is not None:
                current.update({"state": "compiled", "result": result})
                current.pop("error", None)
            else:
                current.update({"state": "failed", "error": error})

        _update(store, put)
        if on_progress:
            on_progress(n, total, name)
    return _update(store, lambda d: (d.update({"status": "done"}), d.pop("current", None)))


def apply_batch(
    store: BatchStore,
    selections: list[dict[str, Any]],
    apply_fn: Callable[[dict[str, Any], list[str], bool | None], None],
    *,
    force: bool = False,
    on_unit_done: Callable[[dict[str, Any], list[str], list[str]], None] | None = None,
) -> dict[str, Any]:
    """Write the chosen genres (and, when asked, the HaremLit-backed explicit
    flag) to every audio book of each selected unit. One failing book never
    stops the rest; a unit with failures is "apply_failed" and can be applied
    again; an applied unit is skipped unless `force`."""
    out: dict[str, Any] = {"units": 0, "books": 0, "failed": [], "skipped": []}
    for selection in selections:
        key = selection.get("key")
        entry = store.load()["units"].get(key)
        allowed = ("compiled", "apply_failed") + (("applied",) if force else ())
        if not entry or entry["state"] not in allowed:
            out["skipped"].append(key)
            continue
        genres = list(selection.get("genres") or [])
        failures: list[dict[str, str]] = []
        written_ids: list[str] = []
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
                written_ids.append(book.get("id"))
            except Exception as exc:
                failures.append({"unit": entry.get("name", key), "title": book.get("title", ""), "error": str(exc)})
        state = "apply_failed" if failures else "applied"
        _update(store, lambda d: d["units"][key].update({
            "state": state, "applied_genres": genres, "applied_at": time.time(), "failures": failures}))
        out["units"] += 1
        out["failed"].extend(failures)
        if on_unit_done:
            on_unit_done(entry, written_ids, genres)
    return out


def mark_applied(store: BatchStore, key: str, genres: list[str]) -> bool:
    """A unit curated and applied on the series page: record it so a later
    batch apply never overwrites that curation with the batch's proposal."""
    changed = []

    def change(data: dict[str, Any]) -> None:
        entry = data["units"].get(key)
        if entry and entry["state"] in ("compiled", "apply_failed", "failed", "pending"):
            entry.update({"state": "applied", "applied_genres": list(genres), "applied_at": time.time(),
                          "failures": [], "applied_via": "series page"})
            changed.append(key)

    if key in store.load()["units"]:
        _update(store, change)
    return bool(changed)
