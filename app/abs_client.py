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
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from app.enrichment import extract_series_sequence, strip_series_sequence_suffix
from app.fixer.parsing import is_single_numeric_sequence
from app.fixer.scoring import GENRE_BLOCKLIST, split_genre_string, split_series_trailing_number

logger = logging.getLogger(__name__)

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
    return _abs_send_json("PATCH", path, body, abs_url, abs_api_key, timeout)


def abs_post_json(path: str, body: dict[str, Any], abs_url: str, abs_api_key: str, timeout: int = 15) -> Any:
    """Authenticated POST against the ABS API with a JSON body. Raises on failure."""
    return _abs_send_json("POST", path, body, abs_url, abs_api_key, timeout)


def _abs_send_json(method: str, path: str, body: dict[str, Any], abs_url: str, abs_api_key: str, timeout: int) -> Any:
    import urllib.request as _urlrequest

    url = f"{abs_url.rstrip('/')}{path}"
    req = _urlrequest.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method=method,
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
    _seen_asins: set[str] = set()
    _ambiguous_asins: set[str] = set()
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
        if asin and _is_real_asin(asin):
            if asin in _seen_asins:
                # Two different items share what claims to be the same real
                # ASIN (e.g. duplicate editions) -- never guess between them.
                # Drop it as a lookup key entirely; callers fall through to
                # path, which is always unambiguous for the exact item.
                _ambiguous_asins.add(asin)
            else:
                _seen_asins.add(asin)
                by_asin[asin] = record
        path = item.get("path")
        if path:
            by_path[str(path)] = record
        rel_path = item.get("relPath")
        if rel_path:
            by_path.setdefault(str(rel_path), record)
    for asin in _ambiguous_asins:
        by_asin.pop(asin, None)
    return {"by_asin": by_asin, "by_path": by_path}


_REAL_ASIN_RE = re.compile(r"^B0[0-9A-Z]{8}$")


def _is_real_asin(asin: str) -> bool:
    """True only for a real-shaped Audible ASIN.

    Excludes placeholder/sentinel values the fixer stores when no real ASIN
    exists (NOREALASIN, abs-agg-<provider>-<i> synthetic ids for GraphicAudio/
    SoundBooth Theater matches) -- several unrelated books can share the
    exact same placeholder, so it must never be usable as a lookup key. A
    shared placeholder previously caused one book's Manual Review edit to
    silently PATCH a completely different book in ABS (LibraForge #291) --
    confirmed live: 14 real-library items shared "NOREALASIN", 6 shared
    "abs-agg-graphicaudio-0". The strict B0-prefixed shape already excludes
    every known placeholder on its own; no separate sentinel list needed.

    TODO(#307): too narrow. Audible's older titles use ISBN-10-shaped ASINs
    ([0-9]{9}[0-9X], e.g. 1004027907 Dune: House Atreides; 7% of a real
    library), which this rejects, so those books are never indexed by ASIN.
    That shape cannot collide with any placeholder, so it can be accepted too.
    """
    return bool(_REAL_ASIN_RE.fullmatch(asin))


def lookup_item_in_index(
    index: dict[str, dict[str, dict[str, Any]]], *, asin: str = "", path: str = "", rel_path: str = ""
) -> dict[str, Any] | None:
    """Path first, then relPath, then ASIN as a last resort.

    The caller always knows the book's own current folder -- that's
    unambiguous and must win. ASIN only helps recover a book that was moved
    or renamed since ABS last scanned it (a path miss); it must never
    override a path hit, and build_item_index already guarantees any ASIN
    reaching this function is real and unique, never a shared placeholder
    (see LibraForge #291).
    """
    by_asin = index.get("by_asin") or {}
    by_path = index.get("by_path") or {}
    if path and str(path) in by_path:
        return by_path[str(path)]
    if rel_path and str(rel_path) in by_path:
        return by_path[str(rel_path)]
    asin_key = str(asin or "").strip().upper()
    if asin_key and asin_key in by_asin:
        return by_asin[asin_key]
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
    dict shape.

    Series parsing is two-layered: first strip ABS's own "Name #N" suffix
    convention (app/enrichment.py's strip_series_sequence_suffix/
    extract_series_sequence), then also run split_series_trailing_number
    (the same Pattern-A "<Series>, Book N" wording cleanup every audiobook
    provider already shares via get_primary_series) -- a human editing the
    series field by hand directly in Audiobookshelf is not guaranteed to use
    ABS's own "#N" shorthand, so both need to be checked.
    """
    metadata = media.get("metadata") or {}
    series_name_raw = str(metadata.get("seriesName") or "")
    series = strip_series_sequence_suffix(series_name_raw)
    sequence = extract_series_sequence(series_name_raw) or ""
    series, sequence = split_series_trailing_number(series, sequence)
    return {
        "title": metadata.get("title") or "",
        "subtitle": metadata.get("subtitle") or "",
        "author": ", ".join(_split_comma_names(metadata.get("authorName", "") or "")),
        "narrator": ", ".join(_split_comma_names(metadata.get("narratorName", "") or "")),
        "series": series,
        "sequence": sequence,
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

# ---------------------------------------------------------------------------
# Legacy metadata.json: reconcile into ABS, then delete (LibraForge #298)
#
# metadata.json is retired -- LibraForge writes ABS through its API. But older
# versions left a metadata.json in most book folders, and ABS re-reads it on
# every rescan of that folder and prefers it over its own database, silently
# reverting API edits. Verified 2026-09-28: with the file present a rescan
# reverts an API edit; with it gone, API edits survive rescans (even ones that
# re-read the audio tags). So on every direct write we compare the file with
# the ABS record: identical -> delete; different -> whichever side was edited
# last wins (file mtime vs the item's updatedAt), a newer file's values are
# pushed to ABS first, then the file is deleted.
# ---------------------------------------------------------------------------

_LEGACY_JSON_STRING_FIELDS = ("title", "subtitle", "publishedYear", "publisher", "description", "isbn", "asin", "language")


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _parse_legacy_series(entry: Any) -> tuple[str, str]:
    if isinstance(entry, dict):
        return str(entry.get("name") or "").strip(), str(entry.get("sequence") or "").strip()
    text = str(entry or "").strip()
    m = re.match(r"^(.*?)\s*#\s*([^#]*)$", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return text, ""


def _as_list(value: Any) -> list[Any]:
    """A list field as a list: a hand-edited file may hold one bare string
    ("genres": "Fantasy"), which must stay one value, not be iterated into
    characters. Anything else that isn't a list is ignored."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _names(values: Any) -> list[str]:
    out = []
    for v in _as_list(values):
        name = v.get("name") if isinstance(v, dict) else v
        name = str(name or "").strip()
        if name:
            out.append(name)
    return out


def has_real_genres(values: Any) -> bool:
    """True when any value names a known genre once merged store labels are
    split. "Audiobook", foreign-store labels ("Fantasía") and keyword soup
    don't, so they are safe to replace."""
    from app.genre_taxonomy import _canonical, _is_known_genre, split_compound_genres

    return any(
        _canonical(g) or _is_known_genre(g)
        for g in split_compound_genres(_as_list(values), canonical=False)
    )


def apply_genre_ownership(fields: dict[str, Any], current_genres: Any, new_genres: list[str]) -> None:
    """Metadata Forge sets ABS genres only when ABS holds no real ones. Real
    genres belong to Enrichment Forge and the user, and an empty value never
    clears them, whatever the write mode."""
    fields.pop("genres", None)
    if new_genres and not has_real_genres(current_genres):
        fields["genres"] = new_genres


def _real_genres(values: Any) -> set[str]:
    return {g.strip().lower() for g in _as_list(values) if str(g).strip() and str(g).strip().lower() not in GENRE_BLOCKLIST}


def metadata_json_diff(metadata_json: dict[str, Any], abs_metadata: dict[str, Any]) -> dict[str, Any]:
    """Fields where a legacy metadata.json holds a NON-BLANK value that differs
    from the ABS record, in PATCH /api/items/{id}/media `metadata` shape.
    Blocklisted genre labels ("Audiobook") are ignored on both sides."""
    diff: dict[str, Any] = {}
    for key in _LEGACY_JSON_STRING_FIELDS:
        value = metadata_json.get(key)
        if _blank(value):
            continue
        if _norm_text(value) != _norm_text(abs_metadata.get(key)):
            diff[key] = value
    for key in ("authors", "narrators"):
        names = _names(metadata_json.get(key))
        # Compared as sets: ABS reorders co-authors itself, so order alone isn't a change.
        if names and {n.lower() for n in names} != {n.lower() for n in _names(abs_metadata.get(key))}:
            diff[key] = [{"name": n} for n in names] if key == "authors" else names
    series = [_parse_legacy_series(s) for s in _as_list(metadata_json.get("series"))]
    series = [s for s in series if s[0]]
    if series:
        current = {(n.lower(), q) for n, q in (_parse_legacy_series(s) for s in _as_list(abs_metadata.get("series")))}
        if {(n.lower(), q) for n, q in series} != current:
            diff["series"] = [{"name": n, "sequence": q} for n, q in series]
    genres = [g for g in _as_list(metadata_json.get("genres")) if str(g).strip().lower() not in GENRE_BLOCKLIST]
    if genres and _real_genres(genres) != _real_genres(abs_metadata.get("genres")):
        diff["genres"] = genres
    if isinstance(metadata_json.get("explicit"), bool) and metadata_json["explicit"] != bool(abs_metadata.get("explicit")):
        diff["explicit"] = metadata_json["explicit"]
    return diff


def _decide_legacy_metadata_json(folder: str, abs_item: dict[str, Any], mtime_fn: Callable[[str], float]) -> tuple[str, dict[str, Any]]:
    """Side-effect-free decision shared by the live reconcile and the dry-run
    planner: "none" | "keep_unreadable" | "delete_identical" |
    "delete_abs_newer" | "consolidate_then_delete", plus the diff."""
    if not folder or abs_item.get("isFile") or Path(folder) != Path(str(abs_item.get("path") or "")):
        return "none", {}
    legacy = Path(folder) / "metadata.json"
    if not legacy.is_file():
        return "none", {}
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("metadata.json is not an object")
    except (OSError, ValueError):
        return "keep_unreadable", {}
    diff = metadata_json_diff(data, ((abs_item.get("media") or {}).get("metadata") or {}))
    if not diff:
        return "delete_identical", {}
    try:
        file_newer = mtime_fn(str(legacy)) * 1000 > float(abs_item.get("updatedAt") or 0)
    except OSError:
        return "keep_unreadable", {}
    if file_newer:
        return "consolidate_then_delete", diff
    return "delete_abs_newer", diff


def plan_legacy_metadata_json_migration(
    items: list[dict[str, Any]],
    *,
    get_item: Callable[[str], dict[str, Any]],
    mtime_fn: Callable[[str], float] = os.path.getmtime,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """Dry-run plan for the whole library: one row per book whose own folder
    holds a legacy metadata.json. Only those books are fetched (expanded).
    Never writes, deletes or PATCHes anything."""
    candidates = [it for it in items if not it.get("isFile") and (Path(str(it.get("path") or "")) / "metadata.json").is_file()]
    rows: list[dict[str, Any]] = []
    for n, it in enumerate(candidates, 1):
        decision, diff = _decide_legacy_metadata_json(str(it["path"]), get_item(it["id"]), mtime_fn)
        if decision != "none":
            rows.append({"id": it["id"], "path": str(it["path"]), "action": decision, "fields": sorted(diff), "diff": diff})
        if on_progress:
            on_progress(n, len(candidates))
    return rows


def reconcile_legacy_metadata_json(
    folder: str,
    abs_item: dict[str, Any],
    *,
    abs_url: str,
    abs_api_key: str,
    patch_fn: Callable[..., Any] | None = None,
    mtime_fn: Callable[[str], float] = os.path.getmtime,
) -> dict[str, Any]:
    """Reconcile the legacy metadata.json in `folder` against `abs_item` (the
    expanded /api/items/{id} record) and delete it. Never touches single-file
    items (their folder is shared with other books) or a folder that isn't the
    item's own path. Returns {"action": ..., "fields": [...]}."""
    patch_fn = patch_fn or abs_patch_json
    decision, diff = _decide_legacy_metadata_json(folder, abs_item, mtime_fn)
    if decision in ("none", "keep_unreadable"):
        return {"action": {"none": "none", "keep_unreadable": "kept_unreadable"}[decision], "fields": []}
    legacy = Path(folder) / "metadata.json"
    action = {"delete_identical": "deleted_identical", "delete_abs_newer": "deleted_abs_newer"}.get(decision, "")
    if decision == "consolidate_then_delete":
        try:
            patch_fn(f"/api/items/{abs_item['id']}/media", {"metadata": diff}, abs_url, abs_api_key)
        except Exception:
            return {"action": "kept_patch_failed", "fields": sorted(diff)}
        action = "consolidated_then_deleted"
    try:
        legacy.unlink()
    except OSError:
        return {"action": "kept_unreadable", "fields": sorted(diff)}
    result: dict[str, Any] = {"action": action, "fields": sorted(diff)}
    if action == "consolidated_then_deleted":
        result["patched"] = diff
    return result


def apply_legacy_metadata_json_migration(
    rows: list[dict[str, Any]],
    *,
    get_item: Callable[[str], dict[str, Any]],
    reconcile: Callable[[str, dict[str, Any]], dict[str, Any]],
    backup_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """--apply for the planner's rows. Each file is copied in full to
    backup_dir/<item id>.json before it can be deleted (the report only holds
    the compared fields), and a failing book is recorded on its row
    ("result": "error") instead of aborting the run. A book whose backup
    can't be written is never reconciled."""
    outcome: dict[str, int] = {}
    for n, row in enumerate(rows, 1):
        if row["action"] == "keep_unreadable":
            row["result"] = "kept_unreadable"
        else:
            try:
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup = backup_dir / f"{row['id']}.json"
                shutil.copy2(Path(row["path"]) / "metadata.json", backup)
                row["backup"] = str(backup)
                row["result"] = reconcile(row["path"], get_item(row["id"]))["action"]
            except Exception as exc:
                row["result"], row["error"] = "error", str(exc)
        outcome[row["result"]] = outcome.get(row["result"], 0) + 1
        if on_progress:
            on_progress(n, len(rows))
    return outcome


def sync_book_metadata(
    *,
    metadata: dict[str, Any],
    expected_path: str = "",
    fill_missing: bool = False,
    skip_blank_fields: bool = False,
    abs_url: str = "",
    abs_api_key: str = "",
    lookup_item: Callable[[str, str], dict[str, Any] | None],
    write_file_fallback: Callable[[], Any],
    record_sync: Callable[[dict[str, Any]], None] | None = None,
    record_bootstrap: Callable[[], None] | None = None,
    get_item: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The three-way branch every write call site needs:
      (a) no abs_api_key -> write_file_fallback(). Zero behavior change.
      (b) lookup_item(asin, path) misses (book unknown to ABS yet) ->
          write_file_fallback() (bootstrap file -- no library_item_id to PATCH),
          then record_bootstrap() so the reconciliation sweep can find and
          eventually clean up this file once ABS learns about the book.
      (c) hits but the resolved item's own path/rel_path doesn't match
          expected_path -> refuse to PATCH, write_file_fallback() instead
          ("path_mismatch"). Last-line defense against patching the wrong
          book (LibraForge #291) if a lookup ever resolves to an item other
          than the one the caller is actually editing.
      (d) hits and the path matches -> compute_selective_patch_fields against
          the cached bulk record; a live per-item GET + series merge if the
          result would include `series`; PATCH the diff; record_sync(...) to
          stamp the sidecar. Never touches metadata.json.

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
    record = lookup_item(asin, expected_path)
    if record is None:
        path = write_file_fallback()
        if record_bootstrap is not None:
            record_bootstrap()
        return {"branch": "file", "reason": "unknown_to_abs", "path": path}

    if expected_path:
        resolved_path = str(record.get("path") or "")
        resolved_rel_path = str(record.get("rel_path") or "")
        if expected_path != resolved_path and expected_path != resolved_rel_path:
            # The lookup resolved to a DIFFERENT item than the one we're actually
            # editing -- e.g. an ASIN collision that slipped past build_item_index,
            # or a stale/cached index entry. Refuse the PATCH rather than silently
            # overwriting the wrong book in ABS (LibraForge #291).
            path = write_file_fallback()
            return {"branch": "file", "reason": "path_mismatch", "path": path}

    # A legacy on-disk metadata.json is the only thing that reverts a direct
    # API write on rescan (LibraForge #298), so reconcile it into ABS and
    # delete it before our own PATCH lands.
    fetch = get_item or (lambda item_id: abs_get_json(f"/api/items/{item_id}", {"expanded": "1"}, abs_url, abs_api_key))
    live_item: dict[str, Any] | None = None
    legacy: dict[str, Any] | None = None
    if expected_path:
        try:
            live_item = fetch(record["library_item_id"])
            legacy = reconcile_legacy_metadata_json(expected_path, live_item, abs_url=abs_url, abs_api_key=abs_api_key)
        except Exception:
            legacy = {"action": "kept_unreadable", "fields": []}
        if legacy["action"].startswith("kept_"):
            logger.warning(
                "Legacy metadata.json in %s could not be reconciled (%s); the next ABS rescan may revert this write",
                expected_path, legacy["action"],
            )

    # Values a newer legacy file just pushed to ABS are now ABS's values: diff
    # and merge against them, not the pre-consolidation snapshot.
    patched = (legacy or {}).get("patched") or {}
    base_media = record["media"]
    if patched:
        base_media = {**base_media, "metadata": {**(base_media.get("metadata") or {}), **patched}}

    new_payload = build_media_patch_payload(metadata)
    fields = compute_selective_patch_fields(
        base_media, new_payload["metadata"], fill_missing=fill_missing, skip_blank_fields=skip_blank_fields
    )
    apply_genre_ownership(
        fields, (base_media.get("metadata") or {}).get("genres"), new_payload["metadata"]["genres"]
    )

    series_name = str(metadata.get("series") or "").strip()
    if "series" in fields and series_name:
        current_item = live_item if live_item is not None else fetch(record["library_item_id"])
        current_series = patched.get("series") or ((current_item.get("media") or {}).get("metadata") or {}).get("series") or []
        sequence = str(metadata.get("sequence") or "").strip()
        fields["series"] = merge_series_entries(current_series, series_name, sequence)

    if not fields:
        if record_sync is not None:
            record_sync({"library_item_id": record["library_item_id"], "abs_updated_at": record["updated_at"]})
        return {"branch": "patch", "fields": {}, "library_item_id": record["library_item_id"], "legacy_metadata_json": legacy}

    abs_patch_json(f"/api/items/{record['library_item_id']}/media", {"metadata": fields}, abs_url, abs_api_key)

    if record_sync is not None:
        record_sync({"library_item_id": record["library_item_id"], "abs_updated_at": record["updated_at"]})

    return {"branch": "patch", "fields": fields, "library_item_id": record["library_item_id"], "legacy_metadata_json": legacy}


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
