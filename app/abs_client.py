"""Direct Audiobookshelf (ABS) API metadata sync.

Pure module plus thin network-calling helpers -- no import-time dependency on
app.main, mirroring the app/enrichment.py rule, so both app/main.py and the
standalone scripts/audible-metadata-fixer-v5.py can import it directly without
a circular-import risk (the script already imports other app.* modules the
same way, e.g. app.title_noise_policy).

Replaces the metadata.json file-write channel with a direct
PATCH /api/items/{id}/media call whenever ABS already knows the book, closing
a real, confirmed bug: ABS prioritizes a stale on-disk metadata.json over its
own already-correct database record on rescan, silently reverting a human's
in-app edit. A brand-new, never-scanned book still needs the file (a PATCH
requires an ABS library_item_id that doesn't exist yet) -- see
sync_book_metadata's three-way branch.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from app.enrichment import extract_series_sequence, strip_series_sequence_suffix
from app.fixer.parsing import is_single_numeric_sequence
from app.fixer.scoring import split_genre_string

_COMMA_SPLIT_RE = re.compile(r"\s*,\s*")


def _split_comma_names(value: str) -> list[str]:
    """Split a comma-joined display string into separate names, order-preserving.

    Mirrors the inline splitting write_audiobookshelf_metadata_json has always
    used for authors/narrators -- kept as its own small copy rather than
    reusing app/fixer/parsing.py's _split_author_names, which lowercases for
    match-comparison and would be wrong for a display/write payload.
    """
    return [name.strip() for name in _COMMA_SPLIT_RE.split(value or "") if name.strip()]


def _blank(value: Any) -> bool:
    return value in (None, "", [], {}) or (isinstance(value, str) and not value.strip())


# ---------------------------------------------------------------------------
# Raw HTTP helpers
# ---------------------------------------------------------------------------

def abs_get_json(path: str, params: dict[str, str], abs_url: str, abs_api_key: str, timeout: int = 15) -> Any:
    """Authenticated GET against the ABS API. Raises on failure (like
    app/fixer/search.py:abs_search) -- callers decide how to handle it."""
    import urllib.parse as _urlparse
    import urllib.request as _urlrequest

    url = f"{abs_url.rstrip('/')}{path}"
    qs = _urlparse.urlencode(params or {})
    if qs:
        url = f"{url}?{qs}"
    req = _urlrequest.Request(
        url, headers={"Authorization": f"Bearer {abs_api_key}", "Accept": "application/json"}
    )
    with _urlrequest.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def abs_patch_json(path: str, body: dict[str, Any], abs_url: str, abs_api_key: str, timeout: int = 15) -> Any:
    """Authenticated PATCH against the ABS API with a JSON body. Raises on failure."""
    import urllib.request as _urlrequest

    url = f"{abs_url.rstrip('/')}{path}"
    req = _urlrequest.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="PATCH",
        headers={
            "Authorization": f"Bearer {abs_api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with _urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


# ---------------------------------------------------------------------------
# Lookup index (ASIN / path -> ABS library item), built from a bulk item fetch
# ---------------------------------------------------------------------------

def build_item_index(items: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Build an ASIN-and-path keyed lookup from fetch_all_abs_book_items()'s output.

    Each record keeps the full `media` dict from the bulk response (title,
    authorName, narratorName, seriesName, genres, publishedYear, description,
    isbn, asin, language, explicit, abridged, plus library_item_id/path/
    updated_at) -- this is already present in the bulk response, so reads that
    only need scalar fields never need a second per-item GET. A PATCH that
    would include `series` still needs a live per-item GET first (see
    sync_book_metadata) since the bulk response flattens series to a single
    string and can't safely be merged from.
    """
    by_asin: dict[str, dict[str, Any]] = {}
    by_path: dict[str, dict[str, Any]] = {}
    for item in items:
        media = item.get("media") or {}
        metadata = media.get("metadata") or {}
        record = {
            "library_item_id": item.get("id"),
            "path": item.get("path"),
            "rel_path": item.get("relPath"),
            "updated_at": item.get("updatedAt"),
            "media": media,
        }
        asin = str(metadata.get("asin") or "").strip().upper()
        if asin:
            by_asin[asin] = record
        path = item.get("path")
        if path:
            by_path[str(path)] = record
        rel_path = item.get("relPath")
        if rel_path:
            by_path.setdefault(str(rel_path), record)
    return {"by_asin": by_asin, "by_path": by_path}


def lookup_item_in_index(
    index: dict[str, dict[str, dict[str, Any]]], *, asin: str = "", path: str = "", rel_path: str = ""
) -> dict[str, Any] | None:
    """ASIN first (survives a Folder Forge move/rename), then path, then relPath."""
    by_asin = index.get("by_asin") or {}
    by_path = index.get("by_path") or {}
    asin_key = str(asin or "").strip().upper()
    if asin_key and asin_key in by_asin:
        return by_asin[asin_key]
    if path and str(path) in by_path:
        return by_path[str(path)]
    if rel_path and str(rel_path) in by_path:
        return by_path[str(rel_path)]
    return None


# ---------------------------------------------------------------------------
# metadata dict <-> ABS media payload shape
# ---------------------------------------------------------------------------

def build_media_patch_payload(metadata: dict[str, Any], tags: list[str] | None = None) -> dict[str, Any]:
    """Build a PATCH /api/items/{id}/media body from LibraForge's internal
    metadata dict. `authors` is [{"name": ...}], `narrators`/`genres` are
    plain string lists, `series` is [{"name", "sequence"}] -- confirmed
    against ABS 2.35.1's Book.updateFromRequest/updateSeriesFromRequest.

    This builds LibraForge's *desired* single-series/full-author entry with
    no knowledge of ABS's current state -- sync_book_metadata is responsible
    for merging the series entry into ABS's current full list before sending,
    since ABS treats a PATCH's series array as the complete desired set.
    """
    authors = _split_comma_names(metadata.get("author", "") or "")
    narrators = _split_comma_names(metadata.get("narrator", "") or "")
    series_name = str(metadata.get("series") or "").strip()
    sequence = str(metadata.get("sequence") or "").strip()

    payload_metadata: dict[str, Any] = {
        "title": metadata.get("title", "") or "",
        "subtitle": metadata.get("subtitle", "") or "",
        "authors": [{"name": name} for name in authors],
        "narrators": narrators,
        "series": [{"name": series_name, "sequence": sequence}] if series_name else [],
        "genres": split_genre_string(metadata.get("genre", "")),
        "publishedYear": str(metadata.get("year", "") or ""),
        "publisher": metadata.get("publisher", "") or "",
        "description": metadata.get("summary", "") or "",
        "isbn": metadata.get("isbn") or None,
        "asin": metadata.get("asin", "") or None,
        "language": metadata.get("language") or None,
    }
    if "explicit" in metadata:
        payload_metadata["explicit"] = bool(metadata["explicit"])

    result: dict[str, Any] = {"metadata": payload_metadata}
    if tags is not None:
        result["tags"] = tags
    return result


def normalize_abs_media_to_internal(media: dict[str, Any]) -> dict[str, Any]:
    """Inverse of build_media_patch_payload: ABS's flattened media.metadata
    (authorName/narratorName/seriesName strings, as returned by the bulk
    /api/libraries/{id}/items endpoint) back to LibraForge's internal field
    dict shape. Series parsing reuses app/enrichment.py's existing
    strip_series_sequence_suffix/extract_series_sequence, since ABS's
    "Name #N" convention is exactly what those already handle."""
    metadata = media.get("metadata") or {}
    series_name_raw = str(metadata.get("seriesName") or "")
    return {
        "title": metadata.get("title") or "",
        "subtitle": metadata.get("subtitle") or "",
        "author": ", ".join(_split_comma_names(metadata.get("authorName", "") or "")),
        "narrator": ", ".join(_split_comma_names(metadata.get("narratorName", "") or "")),
        "series": strip_series_sequence_suffix(series_name_raw),
        "sequence": extract_series_sequence(series_name_raw) or "",
        "year": str(metadata.get("publishedYear") or ""),
        "publisher": metadata.get("publisher") or "",
        "summary": metadata.get("description") or "",
        "isbn": metadata.get("isbn") or "",
        "asin": metadata.get("asin") or "",
        "language": metadata.get("language") or "",
        "explicit": bool(metadata.get("explicit")),
        "genre": ", ".join(metadata.get("genres") or []),
    }


def merge_series_entries(current_series: list[dict[str, Any]], series_name: str, sequence: str) -> list[dict[str, Any]]:
    """Merge LibraForge's corrected series entry into ABS's current full
    series list (matched by name, case-insensitive), so a PATCH never drops a
    series the book already has in ABS that LibraForge's single-series
    internal model doesn't know about. Only call this once the caller has
    already decided `series` belongs in the outgoing PATCH."""
    if not series_name:
        return [
            {"name": str(entry.get("name") or ""), "sequence": str(entry.get("sequence") or "")}
            for entry in (current_series or [])
        ]
    target_key = series_name.strip().lower()
    merged: list[dict[str, Any]] = []
    replaced = False
    for entry in current_series or []:
        name = str(entry.get("name") or "")
        if name.strip().lower() == target_key:
            merged.append({"name": series_name, "sequence": sequence})
            replaced = True
        else:
            merged.append({"name": name, "sequence": str(entry.get("sequence") or "")})
    if not replaced:
        merged.append({"name": series_name, "sequence": sequence})
    return merged


# ---------------------------------------------------------------------------
# fill_missing / skip_blank_fields, reimplemented against ABS's field names
# ---------------------------------------------------------------------------

def compute_selective_patch_fields(
    current_media: dict[str, Any],
    new_payload_metadata: dict[str, Any],
    *,
    fill_missing: bool = False,
    skip_blank_fields: bool = False,
) -> dict[str, Any]:
    """Decide which fields actually belong in the outgoing PATCH body, given
    ABS's current media.metadata and LibraForge's newly-computed payload
    metadata. Ports write_audiobookshelf_metadata_json's blank-check logic
    verbatim, just keyed against ABS's field names instead of metadata.json's
    -- the two shapes are already nearly identical, that's what the file
    format was modeled on. Never combine both flags (same implicit contract
    the file writer has always had).

    Returns only the fields that should change -- a partial PATCH body,
    since ABS leaves any field not present untouched.
    """
    assert not (fill_missing and skip_blank_fields), "fill_missing and skip_blank_fields are never combined"

    current = current_media.get("metadata") or {}
    result: dict[str, Any] = {}

    if fill_missing:
        for key, new_value in new_payload_metadata.items():
            old_value = current.get(key)
            if _blank(old_value):
                result[key] = new_value
                continue
            # Same rationale as the file writer: an old fraction-shaped
            # sequence (e.g. Audible's legacy "1/1") loses to a fresh, clean
            # numeric sequence for the same series -- now meaningful for real
            # (the metadata.json version of this check was dead code, since
            # that format only ever stored series as flat strings).
            if key == "series" and isinstance(new_value, list) and isinstance(old_value, list):
                old_fractions = [s.get("sequence", "") for s in old_value if isinstance(s, dict) and "/" in str(s.get("sequence", ""))]
                new_valid = [
                    s.get("sequence", "")
                    for s in new_value
                    if isinstance(s, dict) and is_single_numeric_sequence(str(s.get("sequence", "")))
                ]
                if old_fractions and new_valid:
                    result[key] = new_value
        return result

    if skip_blank_fields:
        for key, new_value in new_payload_metadata.items():
            if not _blank(new_value):
                result[key] = new_value
        return result

    return dict(new_payload_metadata)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def sync_book_metadata(
    *,
    metadata: dict[str, Any],
    fill_missing: bool = False,
    skip_blank_fields: bool = False,
    abs_url: str = "",
    abs_api_key: str = "",
    lookup_item: Callable[[str, str], dict[str, Any] | None],
    write_file_fallback: Callable[[], Any],
    record_sync: Callable[[dict[str, Any]], None] | None = None,
    record_bootstrap: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """The three-way branch every write call site needs:
      (a) no abs_api_key -> write_file_fallback(). Zero behavior change.
      (b) lookup_item(asin, path) misses (book unknown to ABS yet) ->
          write_file_fallback() (bootstrap file -- no library_item_id to PATCH),
          then record_bootstrap() so the reconciliation sweep can find and
          eventually clean up this file once ABS learns about the book.
      (c) hits -> compute_selective_patch_fields against the cached bulk
          record; a live per-item GET + series merge if the result would
          include `series`; PATCH the diff; record_sync(...) to stamp the
          sidecar. Never touches metadata.json.

    `lookup_item` and `write_file_fallback` are injected because both differ
    between the two callers (the standalone fixer script vs. app/main.py's
    dynamically-loaded fixer module) -- this is the one place dependency
    injection is actually necessary; everything else in this module takes
    explicit params. `record_bootstrap` is only ever called in branch (b) --
    branch (a) has no API key configured at all, so there's no way the
    reconciliation sweep could ever check it; registering there would just
    accumulate entries nothing can act on.

    Returns {"branch": "file", "path": <write_file_fallback()'s return value>,
    "reason": ...} for branches (a)/(b) -- callers that log the written path
    (as write_audiobookshelf_metadata_json's callers already do) read it from
    here instead of capturing the fallback call themselves. Returns
    {"branch": "patch", "fields": {...}} for branch (c).
    """
    assert not (fill_missing and skip_blank_fields)

    if not abs_api_key:
        path = write_file_fallback()
        return {"branch": "file", "reason": "no_api_key", "path": path}

    asin = str(metadata.get("asin") or "")
    record = lookup_item(asin, "")
    if record is None:
        path = write_file_fallback()
        if record_bootstrap is not None:
            record_bootstrap()
        return {"branch": "file", "reason": "unknown_to_abs", "path": path}

    new_payload = build_media_patch_payload(metadata)
    fields = compute_selective_patch_fields(
        record["media"], new_payload["metadata"], fill_missing=fill_missing, skip_blank_fields=skip_blank_fields
    )

    series_name = str(metadata.get("series") or "").strip()
    if "series" in fields and series_name:
        current_item = abs_get_json(
            f"/api/items/{record['library_item_id']}", {}, abs_url, abs_api_key
        )
        current_series = ((current_item.get("media") or {}).get("metadata") or {}).get("series") or []
        sequence = str(metadata.get("sequence") or "").strip()
        fields["series"] = merge_series_entries(current_series, series_name, sequence)

    if not fields:
        if record_sync is not None:
            record_sync({"library_item_id": record["library_item_id"], "abs_updated_at": record["updated_at"]})
        return {"branch": "patch", "fields": {}, "library_item_id": record["library_item_id"]}

    abs_patch_json(f"/api/items/{record['library_item_id']}/media", {"metadata": fields}, abs_url, abs_api_key)

    if record_sync is not None:
        record_sync({"library_item_id": record["library_item_id"], "abs_updated_at": record["updated_at"]})

    return {"branch": "patch", "fields": fields, "library_item_id": record["library_item_id"]}


# ---------------------------------------------------------------------------
# Bootstrap-file reconciliation: a metadata.json written because ABS didn't
# know the book yet (sync_book_metadata's branch (b)) has no owner once
# written. If nothing ever re-touches that exact book, the file sits there
# permanently -- even after ABS eventually scans it, that stale file remains
# a rescan-priority landmine (the original bug this whole module exists to
# close, just deferred past the first scan instead of prevented). A tracked
# pending-list -- populated at write time, checked periodically -- closes
# that gap without a filesystem walk or a live ABS listener (ABS's socket
# auth only accepts a login-session JWT, not the API key this module uses;
# see the plan doc for why that was ruled out).
# ---------------------------------------------------------------------------

_BOOTSTRAP_REGISTRY_FILENAME = "abs-bootstrap-pending.json"


def bootstrap_registry_path(reports_dir: Path) -> Path:
    return reports_dir / _BOOTSTRAP_REGISTRY_FILENAME


def load_bootstrap_registry(reports_dir: Path) -> dict[str, dict[str, Any]]:
    try:
        return json.loads(bootstrap_registry_path(reports_dir).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_bootstrap_registry(reports_dir: Path, registry: dict[str, dict[str, Any]]) -> None:
    path = bootstrap_registry_path(reports_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def upsert_bootstrapped_file(reports_dir: Path, file_path: Path, asin: str, path: str) -> None:
    """Record that `file_path` was just written as a bootstrap metadata.json.
    Called once per sync_book_metadata branch-(b) write; re-writing the same
    book's bootstrap file just refreshes its entry, never duplicates it."""
    registry = load_bootstrap_registry(reports_dir)
    registry[str(file_path)] = {"asin": asin, "path": path}
    save_bootstrap_registry(reports_dir, registry)


def remove_bootstrapped_file(reports_dir: Path, file_path: Path) -> None:
    registry = load_bootstrap_registry(reports_dir)
    if str(file_path) in registry:
        del registry[str(file_path)]
        save_bootstrap_registry(reports_dir, registry)


def metadata_json_title_matches_abs_media(metadata_json: dict[str, Any], media: dict[str, Any]) -> bool:
    """Conservative "is this really the same book" sanity check before the
    reconciliation sweep deletes a bootstrap file -- guards against a
    partial/bad scan or a race where the file was rewritten since, so an
    unconfirmed match never causes a delete. Compares title only: it's the
    one field reliably present and comparable across both metadata.json's
    shape and ABS's flattened media.metadata shape, and a coincidental exact
    title match on a genuinely different book is vanishingly unlikely."""
    file_title = str(metadata_json.get("title") or "").strip().lower()
    abs_title = str((media.get("metadata") or {}).get("title") or "").strip().lower()
    return bool(file_title) and file_title == abs_title


def reconcile_bootstrap_registry(
    reports_dir: Path,
    *,
    abs_url: str,
    abs_api_key: str,
    fetch_items: Callable[[], list[dict[str, Any]]],
) -> dict[str, int]:
    """One reconciliation pass: for every tracked bootstrap file, check
    whether ABS now knows the book and, if its title still matches, delete
    the file and drop it from the registry. Never touches a file that's
    still a genuine bootstrap (ABS doesn't know it yet) or whose content no
    longer matches (left for the next pass rather than risking a bad delete).

    Callers gate this on abs_api_key being configured and the registry being
    non-empty *before* calling, so a steady-state tick with nothing to do
    never reaches this function at all -- see the periodic task in app/main.py.
    """
    registry = load_bootstrap_registry(reports_dir)
    if not registry:
        return {"checked": 0, "reconciled": 0, "skipped_mismatch": 0}

    index = build_item_index(fetch_items())
    reconciled = 0
    skipped_mismatch = 0
    for file_path_str, entry in list(registry.items()):
        record = lookup_item_in_index(index, asin=entry.get("asin", ""), path=entry.get("path", ""))
        if record is None:
            continue
        file_path = Path(file_path_str)
        try:
            metadata_json = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not metadata_json_title_matches_abs_media(metadata_json, record["media"]):
            skipped_mismatch += 1
            continue
        try:
            file_path.unlink()
        except OSError:
            continue
        del registry[file_path_str]
        reconciled += 1

    save_bootstrap_registry(reports_dir, registry)
    return {"checked": len(registry) + reconciled, "reconciled": reconciled, "skipped_mismatch": skipped_mismatch}
