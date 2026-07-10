"""Enrichment Forge: series-wide genre/narrator/explicit-evidence compilation.

Pure aggregation logic plus thin network-calling helpers. Every function that
needs to make a network call (ABS API, Audible, abs-tract) takes the caller
as an injected parameter instead of importing app.main directly, so this
module has no import-time dependency on app.main and no circular-import risk
(mirrors the app/fixer/*.py rule of never importing the fixer script itself).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

_SERIES_SEQUENCE_SUFFIX_RE = re.compile(r"\s*#\d+\s*$")


def strip_series_sequence_suffix(series_name: str) -> str:
    """Strip a trailing Audiobookshelf '#N' sequence marker, e.g.
    'Youngest Son of the Black-Hearted #1' becomes
    'Youngest Son of the Black-Hearted'.
    """
    return _SERIES_SEQUENCE_SUFFIX_RE.sub("", series_name or "").strip()


def normalize_abs_series_name(series_name: str, normalize_series_fn: Callable[[str], str]) -> str:
    """Normalize an ABS seriesName string to a dedup key.

    Strips the ABS-specific '#N' suffix first, then delegates to the
    existing normalize_series() from scripts/review-libraforge-report.py
    (already strips ', Book N' / 'Vol. N' / trailing 'Series'), so tag
    variants collapse into one key without duplicating that cleanup logic.
    """
    return normalize_series_fn(strip_series_sequence_suffix(series_name))


def fetch_all_abs_book_items(abs_request_fn: Callable[[str, dict[str, str]], Any]) -> list[dict[str, Any]]:
    """Walk every book-type ABS library and return every indexed item.

    Mirrors app.main._abs_owned_asins()'s pagination shape, but keeps the
    whole item (not just the ASIN) since series/genre/narrator/explicit all
    come from the same response.
    """
    libs_raw = abs_request_fn("/api/libraries", {})
    libraries = libs_raw.get("libraries", []) if isinstance(libs_raw, dict) else (libs_raw or [])
    book_libs = [lib for lib in libraries if lib.get("mediaType") == "book"] or libraries

    items: list[dict[str, Any]] = []
    for lib in book_libs:
        lib_id = lib.get("id")
        if not lib_id:
            continue
        page = 0
        while True:
            data = abs_request_fn(f"/api/libraries/{lib_id}/items", {"limit": "1000", "page": str(page)})
            results = data.get("results", []) if isinstance(data, dict) else []
            total = int(data.get("total", 0) or 0) if isinstance(data, dict) else 0
            items.extend(results)
            page += 1
            if not results or page * 1000 >= total:
                break
    return items


def group_items_by_series(
    items: list[dict[str, Any]],
    normalize_series_fn: Callable[[str], str],
) -> dict[str, list[dict[str, Any]]]:
    """Group raw ABS items by normalized series name.

    Items with no series name at all are skipped, Enrichment Forge only
    operates on books already carrying an ABS series tag.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        raw_series = str(((item.get("media") or {}).get("metadata") or {}).get("seriesName") or "").strip()
        if not raw_series:
            continue
        key = normalize_abs_series_name(raw_series, normalize_series_fn)
        if not key:
            continue
        groups.setdefault(key, []).append(item)
    return groups


def _display_series_name(group_items: list[dict[str, Any]]) -> str:
    """Pick a representative display name for a normalized series group: the
    most common exact raw seriesName (with its #N suffix stripped), so the
    UI shows real casing/punctuation rather than the normalized key.
    """
    counts: dict[str, int] = {}
    for item in group_items:
        raw = str(((item.get("media") or {}).get("metadata") or {}).get("seriesName") or "").strip()
        display = strip_series_sequence_suffix(raw)
        if display:
            counts[display] = counts.get(display, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda pair: pair[1])[0]


def list_series_summary(
    groups: dict[str, list[dict[str, Any]]],
    query: str = "",
) -> list[dict[str, Any]]:
    """Return [{name, book_count}] sorted by book_count descending, filtered
    by a case-insensitive substring match on the display name.
    """
    query_lower = query.strip().lower()
    summary = []
    for group_items in groups.values():
        display_name = _display_series_name(group_items)
        if query_lower and query_lower not in display_name.lower():
            continue
        summary.append({"name": display_name, "book_count": len(group_items)})
    summary.sort(key=lambda row: (-row["book_count"], row["name"].lower()))
    return summary


def get_series_books(
    groups: dict[str, list[dict[str, Any]]],
    series_name: str,
    normalize_series_fn: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Return the lightweight per-book dicts for a chosen series (matched by
    its display or normalized name), used to drive the compile step.
    """
    query_key = normalize_abs_series_name(series_name, normalize_series_fn)
    group_items = groups.get(query_key, [])
    books = []
    for item in group_items:
        metadata = ((item.get("media") or {}).get("metadata") or {})
        books.append({
            "id": item.get("id", ""),
            "path": item.get("path", ""),
            "is_file": bool(item.get("isFile", False)),
            "title": metadata.get("title", "") or "",
            "asin": str(metadata.get("asin", "") or "").strip().upper(),
            "author": metadata.get("authorName", "") or "",
            "existing_genres": list((item.get("media") or {}).get("tags") or []),
            "existing_narrator": metadata.get("narratorName", "") or "",
            "existing_explicit": bool(metadata.get("explicit", False)),
        })
    return books
