#!/usr/bin/env python3

import argparse
import contextlib
import getpass
import os
import html
import io
import json
import queue as _queue
import re
import signal
import stat
import subprocess
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import audible

try:
    from app.title_noise_policy import is_title_noise, remove_trailing_title_noise
    from app.publisher_policy import (
        learn_publishers,
        match_canonical_publisher,
        special_provider_for,
        strip_publisher_noise,
        SPECIAL_PROVIDERS,
    )
    from app.debug_trace import trace, trace_block, log as trace_log, subject as trace_subject, set_subject as trace_set_subject
    from app.debug_trace import ALTER, CHOOSE, SCORE
    from app.fixer.parsing import (
        # text normalization
        clean_text, is_technical_label_block,
        sanitize_technical_labels, sanitize_book_title,
        normalize_for_match, sanitize_tag,
        UNAMBIGUOUS_TECHNICAL_LABEL_RE, AMBIGUOUS_CODEC_LABEL_RE, TECHNICAL_QUALIFIER_RE,
        # parenthetical helpers
        extract_first_parenthetical, remove_parenthetical,
        # author helpers
        clean_author_value, canonicalize_author_credits,
        _split_author_names, _authors_compatible, _initials_dedup_key,
        _NAME_FUNCTION_WORDS,
        looks_like_person_name, should_prefer_path_author,
        # series helpers
        extract_series_from_trailing_segment, clean_series_value,
        # tag utilities
        first_existing_tag,
        # number helpers
        roman_to_int, normalize_book_number,
        extract_book_number_from_text, extract_folder_book_number,
        extract_book_number_from_path, extract_title_identity_number,
        get_local_number_identity_candidates,
        # book number range
        parse_book_number_range, get_local_book_number_range,
        # sequence helpers
        is_single_numeric_sequence, clean_sequence,
        parse_sequence_number, sequence_values_equal, sequence_values_differ,
        # book text parsers
        parse_structured_book_text, parse_descriptive_book_text,
        parse_series_sequence_segment, parse_identity_rich_book_text,
        parse_structured_book_from_path, parse_descriptive_book_from_path,
        # metadata parsers
        parse_title_series_number_from_metadata,
        is_invalid_local_title, recover_invalid_local_title,
        # query noise helpers
        SEARCH_TITLE_PREFIX_NOISE, _TRAILING_BY_AUTHOR_RE,
        strip_publisher_search_noise, strip_title_search_noise,
        extract_author_from_title, goodreads_title_query_variants,
        normalize_book_label_for_match, strip_leading_sequence_from_title,
        # misc utilities
        is_generic_chapter_title, pick_most_common_value,
    )
    from app.fixer.clues import (
        apply_structured_path_override,
        capture_publisher_clue,
        build_search_queries_from_clues,
        choose_group_book_number,
        infer_group_identity_from_path,
        clean_group_folder_title,
    )
    from app.fixer.scoring import (
        AGGRESSIVE_SCORE_THRESHOLD,
        score_product_for_metadata,
        pick_best_match_for_metadata,
        metadata_from_product,
        get_primary_series,
        clean_provider_genres,
        is_generic_series_number_title,
        compare_duration,
        get_audible_duration_minutes,
        get_people,
        get_year,
        has_number_identity_conflict,
        has_sequence_conflict,
        has_reordered_title_conflict,
        has_author_identity_conflict,
        has_matching_omnibus_range,
        omnibus_range_relation,
        get_audible_number_candidates,
        get_audible_book_number_range,
        strong_identity_overrides_number_conflict,
        has_strong_local_number,
        title_evidence_score,
        product_title_equals_series,
        is_omnibus_product,
        significant_title_tokens,
        preferred_audible_sequence,
        determine_edit_mode,
        get_cover_url,
        choose_best_title,
    )
    from app.fixer.tagging import (
        MUTAGEN_MP4_EXTENSIONS,
        MUTAGEN_MP3_EXTENSIONS,
        mutagen_mp4_is_available,
        mutagen_mp3_is_available,
        mutagen_is_available,
        is_mutagen_mp4_candidate,
        is_mutagen_mp3_candidate,
        is_mutagen_candidate,
        mp4_set_text,
        mp4_set_track,
        mp4_set_freeform,
        id3_set_text,
        id3_set_txxx,
        id3_set_track,
        build_metadata_args,
    )
    from app.fixer.search import (
        audible_search,
        audible_lookup_by_asin,
        abs_search,
        abs_agg_search,
        _abs_match_to_product,
        _ABS_TRACT_BREAKER,
        _ABS_TRACT_BREAKER_THRESHOLD,
        _abs_tract_breaker_is_open,
        abs_tract_search,
        detect_special_provider,
        get_thread_client,
        cached_audible_search,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.title_noise_policy import is_title_noise, remove_trailing_title_noise
    from app.publisher_policy import (
        learn_publishers,
        match_canonical_publisher,
        special_provider_for,
        strip_publisher_noise,
        SPECIAL_PROVIDERS,
    )
    from app.debug_trace import trace, trace_block, log as trace_log, subject as trace_subject, set_subject as trace_set_subject
    from app.debug_trace import ALTER, CHOOSE, SCORE
    from app.fixer.parsing import (
        # text normalization
        clean_text, is_technical_label_block,
        sanitize_technical_labels, sanitize_book_title,
        normalize_for_match, sanitize_tag,
        UNAMBIGUOUS_TECHNICAL_LABEL_RE, AMBIGUOUS_CODEC_LABEL_RE, TECHNICAL_QUALIFIER_RE,
        # parenthetical helpers
        extract_first_parenthetical, remove_parenthetical,
        # author helpers
        clean_author_value, canonicalize_author_credits,
        _split_author_names, _authors_compatible, _initials_dedup_key,
        _NAME_FUNCTION_WORDS,
        looks_like_person_name, should_prefer_path_author,
        # series helpers
        extract_series_from_trailing_segment, clean_series_value,
        # tag utilities
        first_existing_tag,
        # number helpers
        roman_to_int, normalize_book_number,
        extract_book_number_from_text, extract_folder_book_number,
        extract_book_number_from_path, extract_title_identity_number,
        get_local_number_identity_candidates,
        # book number range
        parse_book_number_range, get_local_book_number_range,
        # sequence helpers
        is_single_numeric_sequence, clean_sequence,
        parse_sequence_number, sequence_values_equal, sequence_values_differ,
        # book text parsers
        parse_structured_book_text, parse_descriptive_book_text,
        parse_series_sequence_segment, parse_identity_rich_book_text,
        parse_structured_book_from_path, parse_descriptive_book_from_path,
        # metadata parsers
        parse_title_series_number_from_metadata,
        is_invalid_local_title, recover_invalid_local_title,
        # query noise helpers
        SEARCH_TITLE_PREFIX_NOISE, _TRAILING_BY_AUTHOR_RE,
        strip_publisher_search_noise, strip_title_search_noise,
        extract_author_from_title, goodreads_title_query_variants,
        normalize_book_label_for_match, strip_leading_sequence_from_title,
        # misc utilities
        is_generic_chapter_title, pick_most_common_value,
    )
    from app.fixer.clues import (
        apply_structured_path_override,
        capture_publisher_clue,
        build_search_queries_from_clues,
        choose_group_book_number,
        infer_group_identity_from_path,
        clean_group_folder_title,
    )
    from app.fixer.scoring import (
        AGGRESSIVE_SCORE_THRESHOLD,
        score_product_for_metadata,
        pick_best_match_for_metadata,
        metadata_from_product,
        get_primary_series,
        clean_provider_genres,
        is_generic_series_number_title,
        compare_duration,
        get_audible_duration_minutes,
        get_people,
        get_year,
        has_number_identity_conflict,
        has_sequence_conflict,
        has_reordered_title_conflict,
        has_author_identity_conflict,
        has_matching_omnibus_range,
        omnibus_range_relation,
        get_audible_number_candidates,
        get_audible_book_number_range,
        strong_identity_overrides_number_conflict,
        has_strong_local_number,
        title_evidence_score,
        product_title_equals_series,
        is_omnibus_product,
        significant_title_tokens,
        preferred_audible_sequence,
        determine_edit_mode,
        get_cover_url,
        choose_best_title,
    )
    from app.fixer.tagging import (
        MUTAGEN_MP4_EXTENSIONS,
        MUTAGEN_MP3_EXTENSIONS,
        mutagen_mp4_is_available,
        mutagen_mp3_is_available,
        mutagen_is_available,
        is_mutagen_mp4_candidate,
        is_mutagen_mp3_candidate,
        is_mutagen_candidate,
        mp4_set_text,
        mp4_set_track,
        mp4_set_freeform,
        id3_set_text,
        id3_set_txxx,
        id3_set_track,
        build_metadata_args,
    )
    from app.fixer.search import (
        audible_search,
        audible_lookup_by_asin,
        abs_search,
        abs_agg_search,
        _abs_match_to_product,
        _ABS_TRACT_BREAKER,
        _ABS_TRACT_BREAKER_THRESHOLD,
        _abs_tract_breaker_is_open,
        abs_tract_search,
        detect_special_provider,
        get_thread_client,
        cached_audible_search,
    )

try:
    from mutagen.mp4 import MP4, MP4FreeForm, MP4Cover
except Exception:
    MP4 = None
    MP4FreeForm = None
    MP4Cover = None

try:
    from mutagen.id3 import (
        ID3,
        ID3NoHeaderError,
        APIC,
        COMM,
        TALB,
        TCOM,
        TCON,
        TDRC,
        TIT1,
        TIT2,
        TIT3,
        TPE1,
        TPE2,
        TPUB,
        TRCK,
        TXXX,
    )
except Exception:
    ID3 = None
    ID3NoHeaderError = None
    APIC = None
    COMM = None
    TPUB = None
    TALB = None
    TCOM = None
    TCON = None
    TDRC = None
    TIT1 = None
    TIT2 = None
    TIT3 = None
    TPE1 = None
    TPE2 = None
    TRCK = None
    TXXX = None

SUPPORTED_EXTENSIONS = {
    ".m4b",
    ".m4a",
    ".mp4",
    ".mp3",
    ".flac",
    ".ogg",
    ".opus",
    ".aac",
}

IGNORED_EXTENSIONS = set()

MARKER_FILENAME = ".audible-metadata-fixer.json"
METADATA_BACKUP_SUFFIX = ".metadata-backup.json"
MARKER_SUFFIX = ".audible-metadata-fixer.json"
LIBRAFORGE_SUFFIX = ".libraforge.json"
M4B_TOOL_METADATA_SUFFIX = ".m4b-tool-metadata.json"
IGNORED_PATH_PARTS = {"#recycle", "@eadir"}
TEMP_OUTPUT_MARKERS = {".metadata-fixed", ".metadata-restored"}

# Cancel flag: set by SIGTERM handler so the gather loop stops cleanly after
# the current book's writes complete rather than being killed mid-write.
_cancel_requested = False

def _handle_sigterm(signum: int, frame: object) -> None:
    global _cancel_requested
    _cancel_requested = True

try:
    signal.signal(signal.SIGTERM, _handle_sigterm)
except (ValueError, OSError):
    pass  # not in main thread (e.g. imported by FastAPI worker)
# Formats that should be treated as a single audiobook when multiple files
# exist in the same folder. MP3/OPUS/OGG were already supported for tagging;
# M4A/M4B are included for chapter-split MP4 audiobook containers. OGG behaves
# like OPUS here (no embedded MP4 chapters, no in-place mutagen tagging), so a
# folder of per-chapter OGG files (e.g. "1301.ogg".."1900.ogg") groups as one
# book and is written via an m4b-tool sidecar.
MULTI_PART_AUDIO_EXTENSIONS = {".mp3", ".opus", ".ogg", ".m4a", ".m4b"}

# Formats that can commonly contain embedded chapter metadata. When these
# appear in a multi-file folder, validate that each file is really a chapter
# part and not a complete chapterized audiobook before grouping the folder.
CHAPTER_METADATA_EXTENSIONS = {".m4a", ".m4b", ".mp4"}
MAX_CHAPTERS_PER_MULTI_PART_FILE = 1
# Some split M4A chapter files contain tiny internal chapter atoms, usually
# one wrapper chapter plus the actual chapter. Treat low-count embedded
# chapters as safe only when the filename itself looks like a chapter part.
MAX_LOW_EMBEDDED_CHAPTERS_PER_NAMED_PART_FILE = 3

# Leading-ordinal chapter splits (e.g. "0. Opening Credits - Book - Narrator",
# "1. Time Starts Now - ...") number each slice at the *front* of the filename.
# Grouping these is only safe when the folder clearly holds one book cut into
# many parts, so require a decent number of parts and a shared trailing identity
# (book/narrator suffix) before treating leading ordinals as a part sequence.
# Distinct full books that merely share a folder are still rejected by the
# embedded-chapter-count check in classify_multi_part_file_safety.
MIN_LEADING_ORDINAL_PARTS = 3
MIN_SHARED_IDENTITY_TOKENS = 2

# Keep the previous behavior for MP3/OPUS/OGG: write a sidecar for m4b-tool
# instead of tagging the source file directly (none are tagged in-place by
# mutagen here). For M4A/M4B this is only used when the file is part of an
# accepted multi-file group.
SIDECAR_OUTPUT_AUDIO_EXTENSIONS = {".mp3", ".opus", ".ogg"}

@dataclass
class ItemResult:
    index: int
    file_path: Path
    display_path: Path
    log_lines: list[str] = field(default_factory=list)
    status: str = ""  # "matched" | "skipped" | "failed"
    skip_reason: str = ""
    add_to_manual_review: bool = False
    queries: list[str] = field(default_factory=list)
    metadata: dict | None = None
    score: float = 0.0
    clues: dict | None = None
    used_query: str = ""
    edit_mode: str = ""
    duration_status: str = ""
    diff_percent: float | None = None
    review_reasons: list[str] = field(default_factory=list)
    duration_review_item: dict | None = None
    was_manually_applied: bool = False
    write_done: bool = False
    metadata_json_done: bool = False
    asin_conflict: bool = False
    error: str = ""
    source_provider: str = ""  # provider id when matched via fallback/special source
    from_marker: bool = False  # recovered from the existing marker (no fresh Audible match)

def get_marker_path(source: Path) -> Path:
    """Return the preferred per-file marker path.

    Older versions used one hidden marker per directory:
        .audible-metadata-fixer.json

    That was too easy to miss on NAS shares and could also be ambiguous for
    folders with more than one audio file.  New versions use a visible
    per-file marker next to the audiobook:
        Book.m4b.audible-metadata-fixer.json
    """
    return source.with_name(f"{source.name}{MARKER_SUFFIX}")

def get_legacy_marker_path(source: Path) -> Path:
    return source.parent / MARKER_FILENAME

def load_marker(source: Path) -> dict:
    _, payload = _load_libraforge_raw(source)
    return payload.get("marker", {})

def get_metadata_backup_path(source: Path) -> Path:
    return source.with_name(f"{source.name}{METADATA_BACKUP_SUFFIX}")

def get_libraforge_path(
    source: Path, clues: dict | None = None, alone: bool = False
) -> Path:
    group_search = (clues or {}).get("group_search", {}) or {}
    if group_search.get("applied") or alone:
        return source.parent / "libraforge.json"
    return source.with_name(f"{source.name}{LIBRAFORGE_SUFFIX}")

def _write_libraforge(path: Path, payload: dict) -> None:
    try:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass

def _libraforge_folder_file_belongs_to(payload: dict, source: Path) -> bool:
    """True when a folder-level libraforge.json's recorded data covers `source`.

    A folder-level file is meant for a single grouped book or a lone file --
    but a shared "dumping ground" folder (e.g. an unsorted-books root) can
    hold several unrelated, independently-processed loose files. If a
    folder-level libraforge.json already names a different file as its
    owner, it must never be read as -- or overwritten with -- `source`'s
    data. An empty/fresh payload has no conflicting claim yet, so it's
    treated as available.
    """
    if not payload:
        return True
    source_str = str(source)
    for section_key in ("sidecar", "marker", "scan_cache"):
        src = (payload.get(section_key) or {}).get("source") or {}
        root_file = src.get("root_file")
        chapter_files = src.get("chapter_files") or []
        if root_file or chapter_files:
            return root_file == source_str or source_str in chapter_files
    # Marker and backup record only a bare filename (no full source.* block).
    for section_key in ("marker", "backup"):
        named_file = (payload.get(section_key) or {}).get("source_file")
        if named_file:
            return named_file == source.name
    return True

def _load_libraforge_raw(
    source: Path, clues: dict | None = None, alone: bool = False
) -> tuple[Path, dict]:
    """Load the unified libraforge sidecar, migrating old canonical files on first access.

    Multi-file (grouped) books and single-file books alone in their folder
    use a folder-level ``libraforge.json``.  Single-file books sharing a
    folder with other books use a per-file ``<name>.libraforge.json``.
    Detection is by existence: folder-level is checked first, but only when
    it actually belongs to `source` (see _libraforge_folder_file_belongs_to)
    -- otherwise it's another book's data and must not be read or clobbered.

    Returns (libraforge_path, payload). payload is {} when nothing exists yet.
    Migrates old backup/marker files and old group sidecars on first access.
    Also cleans up any orphaned old-format files whenever a libraforge.json
    is found (handles the case where the sidecar was written before cleanup ran).
    """
    folder_lf = source.parent / "libraforge.json"
    file_lf = source.with_name(f"{source.name}{LIBRAFORGE_SUFFIX}")

    _old_per_file = [
        source.with_name(f"{source.name}{METADATA_BACKUP_SUFFIX}"),
        source.with_name(f"{source.name}{MARKER_SUFFIX}"),
    ]

    def _cleanup_orphans() -> None:
        for orphan in _old_per_file:
            if orphan.is_file():
                try:
                    orphan.unlink()
                except OSError:
                    pass

    folder_lf_blocked = False
    if folder_lf.is_file():
        try:
            folder_payload = json.loads(folder_lf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            folder_payload = {}
        if _libraforge_folder_file_belongs_to(folder_payload, source):
            _cleanup_orphans()
            return folder_lf, folder_payload
        # Belongs to a different file sharing this folder (e.g. a shared
        # unsorted root). Never read from or write to it for `source`.
        folder_lf_blocked = True

    if file_lf.is_file():
        _cleanup_orphans()
        payload: dict = {}
        try:
            payload = json.loads(file_lf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
        # If the book is now alone in its folder, migrate file-level to
        # folder-level -- unless that path is already claimed by another file.
        if alone and not folder_lf_blocked:
            _write_libraforge(folder_lf, payload)
            try:
                file_lf.unlink()
            except OSError:
                pass
            return folder_lf, payload
        return file_lf, payload

    # Determine write path for new data
    group_search = (clues or {}).get("group_search", {}) or {}
    wants_folder_level = bool(group_search.get("applied") or alone)
    lf_path = folder_lf if (wants_folder_level and not folder_lf_blocked) else file_lf

    payload: dict = {}
    old_to_remove: list[Path] = []

    # Migrate old group sidecar (multi-file books)
    old_group_sidecar = source.parent / f"{source.parent.name}{M4B_TOOL_METADATA_SUFFIX}"
    if old_group_sidecar.is_file():
        try:
            sd = json.loads(old_group_sidecar.read_text(encoding="utf-8"))
            payload["sidecar"] = {
                k: sd[k]
                for k in ("book", "audible", "matching", "local_before",
                          "audio_summary", "source", "audio_profile_updated_at")
                if k in sd
            }
            if sd.get("file_cache"):
                payload["file_cache"] = sd["file_cache"]
            old_to_remove.append(old_group_sidecar)
            if not folder_lf_blocked:
                lf_path = folder_lf
        except (json.JSONDecodeError, OSError):
            pass

    # Migrate old per-file backup (single-file books)
    old_backup = source.with_name(f"{source.name}{METADATA_BACKUP_SUFFIX}")
    if old_backup.is_file():
        try:
            bd = json.loads(old_backup.read_text(encoding="utf-8"))
            payload["backup"] = {
                k: bd[k]
                for k in ("created_at", "source_file", "duration_minutes",
                          "format_tags", "applied_tags", "applied_at")
                if k in bd
            }
            old_to_remove.append(old_backup)
        except (json.JSONDecodeError, OSError):
            pass

    # Migrate old per-file marker (single-file) or per-directory marker (legacy)
    for old_marker in [
        source.with_name(f"{source.name}{MARKER_SUFFIX}"),
        source.parent / MARKER_FILENAME,
    ]:
        if old_marker.is_file():
            try:
                md = json.loads(old_marker.read_text(encoding="utf-8"))
                payload["marker"] = {
                    k: md[k]
                    for k in ("processed_at", "applied", "mode", "edit_mode",
                              "aggressive", "score", "source_file", "output_kind",
                              "duration", "audible", "local_before", "restored_at")
                    if k in md
                }
                old_to_remove.append(old_marker)
            except (json.JSONDecodeError, OSError):
                pass
            break

    if payload:
        payload["schema_version"] = 2
        payload["tool"] = "audible-metadata-fixer"
        payload["migrated_at"] = datetime.now(timezone.utc).isoformat()
        _write_libraforge(lf_path, payload)
        for old_file in old_to_remove:
            try:
                old_file.unlink()
            except OSError:
                pass

    return lf_path, payload

def get_m4b_tool_metadata_path(source: Path, clues: dict | None = None) -> Path:
    group_search = (clues or {}).get("group_search", {}) or {}

    if group_search.get("applied"):
        folder = source.parent
        return folder / f"{folder.name}{M4B_TOOL_METADATA_SUFFIX}"

    return source.with_name(f"{source.name}{M4B_TOOL_METADATA_SUFFIX}")

def get_audiobookshelf_metadata_path(
    source: Path, clues: dict | None = None, alone_in_folder: bool = False
) -> Path:
    """Resolve where the Audiobookshelf ``metadata.json`` should be written.

    A multi-file book (grouped as a single book) or a single file that is alone
    in its folder gets a plain ``folder/metadata.json`` — Audiobookshelf reads it
    directly. A loose single file that shares its folder with other books gets a
    collision-safe companion ``<file>.metadata.json``; the organizer renames it to
    ``metadata.json`` once the book has its own folder.
    """
    group_search = (clues or {}).get("group_search", {}) or {}

    if group_search.get("applied") or alone_in_folder:
        return source.parent / "metadata.json"

    return source.with_name(source.name + ".metadata.json")

def write_original_metadata_backup(
    source: Path,
    tags: dict | None = None,
    duration_minutes: float | None = None,
    alone: bool = False,
) -> Path:
    """Store the original container-level metadata in the unified .libraforge.json sidecar.

    Pass tags and duration_minutes when the file has already been probed to
    avoid a second ffprobe call.
    """
    lf_path, payload = _load_libraforge_raw(source, alone=alone)

    if "backup" in payload:
        return lf_path

    if tags is None or duration_minutes is None:
        probed_tags, probed_duration = probe_file(source)
        if tags is None:
            tags = probed_tags
        if duration_minutes is None:
            duration_minutes = probed_duration

    payload.setdefault("schema_version", 2)
    payload.setdefault("tool", "audible-metadata-fixer")
    payload["backup"] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source.name,
        "duration_minutes": round(duration_minutes, 4) if duration_minutes else None,
        "format_tags": tags,
    }

    _write_libraforge(lf_path, payload)
    return lf_path

def build_raw_metadata_args(tags: dict) -> list[str]:
    args: list[str] = []

    for key, value in sorted((tags or {}).items()):
        key = str(key).strip()
        value = sanitize_tag(str(value))

        if not key or not value:
            continue

        args.extend(["-metadata", f"{key}={value}"])

    return args

def mark_metadata_restored(source: Path) -> None:
    lf_path, payload = _load_libraforge_raw(source)
    if not payload.get("marker"):
        return
    try:
        payload["marker"]["applied"] = False
        payload["marker"]["restored_at"] = datetime.now(timezone.utc).isoformat()
        _write_libraforge(lf_path, payload)
    except (OSError, KeyError):
        return

def path_is_ignored(file_path: Path) -> bool:
    parts = {part.lower() for part in file_path.parts}
    return bool(parts & IGNORED_PATH_PARTS)

def is_temporary_output_file(file_path: Path) -> bool:
    name_lower = file_path.name.lower()
    return any(marker in name_lower for marker in TEMP_OUTPUT_MARKERS)

def is_supported_audio_file(file_path: Path) -> bool:
    if path_is_ignored(file_path):
        return False

    if is_temporary_output_file(file_path):
        return False

    suffix = file_path.suffix.lower()

    if suffix in IGNORED_EXTENSIONS:
        return False

    if suffix not in SUPPORTED_EXTENSIONS:
        return False

    return True

def get_file_type(file_path: Path) -> str:
    suffix = file_path.suffix.lower().lstrip(".")
    return suffix or "unknown"

def safe_ffmpeg_copy_metadata_command(
    source: Path,
    tmp_path: Path,
    metadata_args: list[str],
    clear_existing_metadata: bool = False,
) -> list[str]:
    """Build an ffmpeg command that updates container metadata without copying
    incompatible data/subtitle/text streams.

    Some M4B files contain auxiliary text/data streams that the ipod/mp4 muxer
    cannot write back when using `-map 0`.  Copying only audio + video/cover
    streams preserves the actual audiobook content and cover art while avoiding
    errors such as:

        Tag text incompatible with output codec id '98314'

    Chapters are still copied from the source with `-map_chapters 0`.
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a?",
        "-map",
        "0:v?",
        "-map_chapters",
        "0",
        "-sn",
        "-dn",
        "-c",
        "copy",
    ]

    if clear_existing_metadata:
        cmd.extend(["-map_metadata", "-1"])

    cmd.extend(metadata_args)
    cmd.append(str(tmp_path))
    return cmd

def load_metadata_backup_payload(source: Path) -> tuple[Path, dict]:
    lf_path, payload = _load_libraforge_raw(source)
    backup = payload.get("backup", {})
    tags = backup.get("format_tags", {})
    if not isinstance(tags, dict) or not tags:
        raise FileNotFoundError(f"no backup data found: {lf_path}")
    return lf_path, tags

def ffmpeg_restore_metadata_from_backup(source: Path) -> Path:
    backup_path, tags = load_metadata_backup_payload(source)

    tmp_path = source.with_name(f"{source.stem}.metadata-restored{source.suffix}")
    metadata_args = build_raw_metadata_args(tags)

    cmd = safe_ffmpeg_copy_metadata_command(
        source=source,
        tmp_path=tmp_path,
        metadata_args=metadata_args,
        clear_existing_metadata=True,
    )

    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:
        if tmp_path.exists():
            tmp_path.unlink()

        raise RuntimeError(
            f"ffmpeg restore failed for {source}\n{result.stderr.strip()}"
        )

    tmp_path.replace(source)
    mark_metadata_restored(source)

    return backup_path

def is_multi_part_audio_candidate(source: Path) -> bool:
    return source.suffix.lower() in MULTI_PART_AUDIO_EXTENSIONS

def is_chapter_metadata_candidate(source: Path) -> bool:
    return source.suffix.lower() in CHAPTER_METADATA_EXTENSIONS

def natural_audio_sort_key(file_path: Path) -> list[tuple[int, object]]:
    """Sort chapter files naturally, so 2 comes before 10."""
    parts = re.split(r"(\d+)", file_path.name.lower())
    return [
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts
    ]

_chapter_count_cache: dict[str, int | None] = {}
_chapter_count_cache_lock = threading.Lock()

# redirect_stdout sets sys.stdout globally and is not thread-safe.
# Serialise print_plan captures across workers with this lock.
# print_plan is pure string formatting — contention is negligible.
_print_plan_lock = threading.Lock()

CHAPTER_COUNT_CACHE_SUFFIX = ".chapter-count-cache.json"

def read_file_chapter_count(file_path: Path) -> int | None:
    """Return embedded chapter count using ffprobe, or None when unreadable.

    Results are stored in _chapter_count_cache (thread-safe). The cache can be
    pre-populated from disk by prefetch_chapter_counts so ffprobe is skipped on
    recurring runs for files that have not changed since the last probe.
    """
    key = str(file_path)
    with _chapter_count_cache_lock:
        if key in _chapter_count_cache:
            return _chapter_count_cache[key]

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_chapters",
        str(file_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print(f"  WARNING: ffprobe chapter check timed out for: {file_path}")
        count = None
    else:
        if result.returncode != 0:
            print(f"  WARNING: ffprobe chapter check failed for: {file_path}")
            count = None
        else:
            try:
                data = json.loads(result.stdout)
                count = len(data.get("chapters", []) or [])
            except json.JSONDecodeError:
                print(f"  WARNING: ffprobe returned invalid chapter JSON for: {file_path}")
                count = None

    with _chapter_count_cache_lock:
        _chapter_count_cache[key] = count
    return count

def _chapter_count_cache_path(folder: Path) -> Path:
    return folder / f"{folder.name}{CHAPTER_COUNT_CACHE_SUFFIX}"

def _load_chapter_count_persistent(folder: Path) -> dict[str, dict]:
    cache_path = _chapter_count_cache_path(folder)
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data.get("entries", {}) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}

def _save_chapter_count_persistent(folder: Path, entries: dict[str, dict]) -> None:
    cache_path = _chapter_count_cache_path(folder)
    try:
        payload = {
            "schema_version": 1,
            "tool": "audible-metadata-fixer",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "entries": entries,
        }
        cache_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass

def normalize_part_filename(value: str) -> str:
    value = html.unescape(str(value or "")).lower()
    value = re.sub(r"\[[^\]]+\]", " ", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[_.\-–—:]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()

def looks_like_chapter_part_filename(file_path: Path) -> bool:
    """Return True when the filename looks like one chapter/section file.

    This is used only for low-count embedded chapters. It lets folders such as
    a chapter-split M4A book through even when each M4A has 2 tiny chapter atoms,
    while still rejecting complete M4B books that contain many real chapters.
    """
    name = normalize_part_filename(file_path.stem)

    if not name:
        return False

    patterns = [
        r"\b(?:chapter|chap|ch)\s*\d+\b",
        r"\b(?:part|track)\s*\d+\b",
        r"\b(?:disc|cd)\s*\d+(?:\s+track\s*\d+)?\b",
        r"\b(?:prologue|epilogue|afterword|foreword)\b",
        r"\b(?:opening|end)\s+credits?\b",
        r"\bcredits?\b",
        r"\b(?:intro|introduction|outro)\b",
    ]

    return any(re.search(pattern, name, flags=re.IGNORECASE) for pattern in patterns)

def numeric_part_sequence_files(file_paths: list[Path]) -> set[Path]:
    """Recognize groups named with a shared identity plus `- 01`, `- 02`, etc.

    The part number may be the last thing in the filename ("Book - 01.mp3")
    or sit between the shared identity and a varying chapter title ("Book -
    01 - Opening Credits.m4b"). Only the identity prefix has to match across
    files; the trailing chapter title is intentionally ignored here so a
    "Preface"/"Chapter 40"-style suffix that varies per file doesn't block
    grouping.
    """
    grouped: dict[tuple[str, int], list[tuple[Path, int]]] = {}
    for file_path in file_paths:
        match = re.match(r"^(.+?)\s*[-_.]\s*(\d{2,4})(?:\s*[-_.]\s*\S.*)?$", file_path.stem)
        if not match:
            continue
        prefix = normalize_part_filename(match.group(1))
        if not prefix:
            continue
        number_text = match.group(2)
        grouped.setdefault((prefix, len(number_text)), []).append(
            (file_path, int(number_text))
        )

    best: set[Path] = set()
    for matches in grouped.values():
        numbers = sorted(number for _path, number in matches)
        if (
            len(matches) >= 2
            and len(numbers) == len(set(numbers))
            and numbers[0] in {0, 1}
            and numbers == list(range(numbers[0], numbers[0] + len(numbers)))
        ):
            candidate = {path for path, _number in matches}
            if len(candidate) > len(best):
                best = candidate
    return best

# Explicit, high-confidence "this file is one slice of a larger book" markers.
# Centralised here so new spellings only need adding to this list. A *confident*
# match (an explicit word, not just a bare trailing number) is strong enough to
# group files even when they carry their own embedded chapters -- a dramatised
# "Part 1" can legitimately hold 10+ chapters. New patterns must capture the
# part index as group(1).
_PART_MARKER_PATTERNS = [
    re.compile(r"\bpart\s*0*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\bpt\.?\s*0*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(?:disc|disk|cd)\s*0*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b0*(\d{1,3})\s+of\s+0*\d{1,3}\b", re.IGNORECASE),  # "1 of 3"
]

def detect_part_marker(stem: str) -> tuple[str, int] | None:
    """Return (identity_prefix, part_index) for an explicit multi-part marker.

    Recognises 'Part N', 'Pt N', 'Disc/CD N' and 'N of M' anywhere in the name,
    including inside parentheses. The last marker wins so a leading series number
    (e.g. 'LotR1 - ... - Part 2') does not shadow the real part index. Returns
    None when no confident marker is present.
    """
    best: tuple[int, int, int] | None = None  # (start, end, index)
    for pattern in _PART_MARKER_PATTERNS:
        for match in pattern.finditer(stem):
            if best is None or match.start() > best[0]:
                best = (match.start(), match.end(), int(match.group(1)))
    if best is None:
        return None
    start, end, index = best
    identity = normalize_part_filename(stem[:start] + " " + stem[end:])
    return (identity or "_", index)

def marker_sequence_files(file_paths: list[Path]) -> set[Path]:
    """Recognize groups sharing an explicit part marker (Part N, Disc N, N of M).

    Bare numeric prefixes (LotR1/LotR2) are deliberately not treated as parts
    here to avoid merging distinct series entries -- only detect_part_marker's
    explicit-word matches count.
    """
    grouped: dict[str, list[tuple[Path, int]]] = {}
    for file_path in file_paths:
        marker = detect_part_marker(file_path.stem)
        if marker is None:
            continue
        identity, index = marker
        grouped.setdefault(identity, []).append((file_path, index))

    best: set[Path] = set()
    for matches in grouped.values():
        numbers = sorted(index for _path, index in matches)
        if (
            len(matches) >= 2
            and len(numbers) == len(set(numbers))
            and numbers[0] in {0, 1}
            and numbers == list(range(numbers[0], numbers[0] + len(numbers)))
        ):
            candidate = {path for path, _index in matches}
            if len(candidate) > len(best):
                best = candidate
    return best

# Leading ordinal: a number at the *start* of the name followed by a separator
# and a title, e.g. "0. Opening Credits ...", "10. Suspect Alchemy ...",
# "001 - ...". Leading zeros are tolerated; the captured value is the index.
_LEADING_ORDINAL_RE = re.compile(r"^\s*0*(\d{1,4})\s*[.)\]_-]\s+(?=\S)")

def _common_trailing_tokens(token_lists: list[list[str]]) -> list[str]:
    """Longest run of tokens shared at the END of every token list."""
    if not token_lists:
        return []
    common = list(token_lists[0])
    for tokens in token_lists[1:]:
        shared = 0
        while (
            shared < len(common)
            and shared < len(tokens)
            and common[-1 - shared] == tokens[-1 - shared]
        ):
            shared += 1
        common = common[len(common) - shared:] if shared else []
        if not common:
            break
    return common

def leading_ordinal_sequence_files(file_paths: list[Path]) -> set[Path]:
    """Recognize ONE book split into many leading-ordinal-numbered parts.

    Example: "0. Opening Credits - The Book - Narrator", "1. Time Starts Now -
    The Book - Narrator", ... "71. ...". The chapter title varies per file, so
    these cannot be grouped by a shared prefix the way trailing "- 01" numbering
    is; instead group them when:
      * every matched ordinal is unique and they form a contiguous run from 0/1,
      * there are at least MIN_LEADING_ORDINAL_PARTS of them,
      * the parts share a common trailing identity (the book/narrator suffix).
    Distinct full books that happen to be leading-numbered in one folder are
    still rejected by the embedded-chapter-count check in
    classify_multi_part_file_safety (a real book carries many chapters).
    """
    indexed: list[tuple[Path, int, list[str]]] = []
    for file_path in file_paths:
        match = _LEADING_ORDINAL_RE.match(file_path.stem)
        if not match:
            continue
        rest = normalize_part_filename(file_path.stem[match.end():])
        indexed.append((file_path, int(match.group(1)), rest.split()))

    if len(indexed) < MIN_LEADING_ORDINAL_PARTS:
        return set()

    by_number: dict[int, tuple[Path, list[str]]] = {}
    for file_path, number, tokens in indexed:
        if number in by_number:
            return set()  # duplicate index (e.g. two encodings of the same part)
        by_number[number] = (file_path, tokens)

    numbers = sorted(by_number)
    if numbers[0] not in {0, 1}:
        return set()
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return set()

    token_lists = [by_number[n][1] for n in numbers]
    if len(_common_trailing_tokens(token_lists)) < MIN_SHARED_IDENTITY_TOKENS:
        return set()

    return {by_number[n][0] for n in numbers}

def part_sequence_files(file_paths: list[Path]) -> set[Path]:
    """Files that belong to a recognized numbered part sequence.

    Prefers an explicit part marker (Part N, Disc N, "N of M") found anywhere
    in the name; falls back to trailing "- 01" numbering (shared-prefix
    groups); falls back to leading-ordinal chapter splits. Used both to choose
    grouping candidates and to mark a file as a safe chapter part during
    validation.
    """
    return (
        marker_sequence_files(file_paths)
        or numeric_part_sequence_files(file_paths)
        or leading_ordinal_sequence_files(file_paths)
    )

def confident_part_sequence_files(file_paths: list[Path]) -> set[Path]:
    """Subset of part_sequence_files() strong enough to override the
    embedded-chapter-count veto: an explicit marker (Part N, Disc N, N of M),
    as opposed to a bare trailing/leading number.
    """
    return marker_sequence_files(file_paths)

def classify_multi_part_file_safety(
    file_path: Path,
    chapter_count: int | None,
    numeric_part_sequence: bool = False,
    confident_part: bool = False,
) -> tuple[bool, str]:
    # An explicit part marker (Part N, N of M, Disc N) in a contiguous sequence is
    # strong evidence the file is one slice of a larger book, even when it carries
    # its own embedded chapters. A dramatised "Part 1" with 12 chapters plus a
    # "Part 2" with 10 is one book, so this overrides the chapter-count veto below.
    if confident_part:
        if chapter_count is None:
            return True, "explicit part marker (chapter metadata unreadable)"
        return True, f"explicit part marker overrides embedded chapter count ({chapter_count})"

    if chapter_count is None:
        return False, "chapter metadata unreadable"

    suffix = file_path.suffix.lower()
    chapter_named = (
        looks_like_chapter_part_filename(file_path)
        or numeric_part_sequence
    )

    if (
        chapter_count <= MAX_CHAPTERS_PER_MULTI_PART_FILE
        and suffix != ".m4b"
    ):
        return True, "no embedded chapters or one wrapper chapter"

    if (
        chapter_count <= MAX_LOW_EMBEDDED_CHAPTERS_PER_NAMED_PART_FILE
        and chapter_named
    ):
        return (
            True,
            f"low embedded chapter count ({chapter_count}) with chapter-like filename",
        )

    if suffix == ".m4b" and chapter_count <= MAX_CHAPTERS_PER_MULTI_PART_FILE:
        return False, "low chapter count M4B lacks a chapter-like filename"

    return False, f"embedded chapter count {chapter_count} suggests a complete audiobook"

def validate_multi_part_group_files(
    file_paths: list[Path],
    chapter_count_reader=None,
) -> dict:
    """Validate an accepted multi-file audiobook candidate.

    MP3/OPUS do not need chapter-metadata validation here. M4A/M4B/MP4 can
    contain embedded chapters, so high chapter counts are treated as complete
    audiobooks and are not grouped. Low embedded chapter counts are allowed
    only for filenames that clearly look like chapter/section parts.
    """
    chapter_count_reader = chapter_count_reader or read_file_chapter_count
    checked = []
    unsafe = []
    numeric_parts = part_sequence_files(file_paths)
    confident_parts = confident_part_sequence_files(file_paths)

    for file_path in sorted(file_paths, key=natural_audio_sort_key):
        if not is_chapter_metadata_candidate(file_path):
            continue

        chapter_count = chapter_count_reader(file_path)
        safe_as_part, reason = classify_multi_part_file_safety(
            file_path=file_path,
            chapter_count=chapter_count,
            numeric_part_sequence=file_path in numeric_parts,
            confident_part=file_path in confident_parts,
        )
        item = {
            "file": str(file_path),
            "format": file_path.suffix.lower().lstrip("."),
            "chapter_count": chapter_count,
            "safe_as_part": safe_as_part,
            "reason": reason,
        }
        checked.append(item)

        if not item["safe_as_part"]:
            unsafe.append(item)

    return {
        "safe": not unsafe,
        "checked_files": checked,
        "unsafe_files": unsafe,
    }

def inspect_mp4_top_level_layout(source: Path) -> dict:
    """Read only top-level atom headers to predict expensive in-place shifts."""
    file_size = source.stat().st_size
    atoms: dict[str, dict] = {}
    offset = 0

    with source.open("rb") as file:
        while offset + 8 <= file_size:
            file.seek(offset)
            header = file.read(16)
            if len(header) < 8:
                break

            atom_size = struct.unpack(">I", header[:4])[0]
            atom_type = header[4:8].decode("latin1")
            header_size = 8

            if atom_size == 1:
                if len(header) < 16:
                    break
                atom_size = struct.unpack(">Q", header[8:16])[0]
                header_size = 16
            elif atom_size == 0:
                atom_size = file_size - offset

            if atom_size < header_size:
                break

            if atom_type in {"moov", "mdat"}:
                atoms[atom_type] = {"offset": offset, "size": atom_size}
                if len(atoms) == 2:
                    break

            offset += atom_size

    return {
        "file_size": file_size,
        "moov": atoms.get("moov"),
        "mdat": atoms.get("mdat"),
        "metadata_before_media": bool(
            atoms.get("moov")
            and atoms.get("mdat")
            and atoms["moov"]["offset"] < atoms["mdat"]["offset"]
        ),
    }

def mutagen_write_mp4_tags(
    source: Path,
    metadata: dict,
    backup: bool,
    cover_if_missing: bool = False,
    replace_cover: bool = False,
) -> None:
    """Write MP4/M4B tags in-place using mutagen."""
    if not mutagen_mp4_is_available():
        raise RuntimeError("mutagen MP4 support is not installed in this environment")

    if not is_mutagen_mp4_candidate(source):
        raise RuntimeError(
            f"mutagen MP4 writer does not support this extension: {source.suffix}"
        )

    if backup:
        backup_path = write_original_metadata_backup(source)
        print(f"  Metadata backup: {backup_path}")

    audio = MP4(str(source))
    if audio.tags is None:
        audio.add_tags()

    tags = audio.tags

    title = metadata.get("title", "")
    author = metadata.get("author", "")
    series = metadata.get("series", "")
    sequence = metadata.get("sequence", "")
    narrator = metadata.get("narrator", "")
    year = metadata.get("year", "")
    subtitle = metadata.get("subtitle", "")
    genre = metadata.get("genre", "")
    isbn = metadata.get("isbn", "")

    # Audiobookshelf reads album/title as the displayed book title.
    # Keep album equal to the book title, not the series.
    mp4_set_text(tags, "\xa9nam", title)
    mp4_set_text(tags, "\xa9alb", title)

    mp4_set_text(tags, "\xa9ART", author)
    mp4_set_text(tags, "aART", author)
    mp4_set_text(tags, "\xa9grp", series)
    mp4_set_text(tags, "\xa9wrt", narrator)
    mp4_set_text(tags, "\xa9day", year)
    if genre:
        mp4_set_text(tags, "\xa9gen", genre)
    mp4_set_track(tags, sequence)

    if subtitle:
        mp4_set_freeform(tags, "subtitle", subtitle)

    # ffprobe exposes these freeform MP4 tags as mvnm/mvin.
    mp4_set_freeform(tags, "mvnm", series)
    mp4_set_freeform(tags, "mvin", sequence)

    asin = metadata.get("asin", "")
    if asin:
        mp4_set_freeform(tags, "asin", asin)

    if isbn:
        mp4_set_freeform(tags, "isbn", isbn)

    publisher = metadata.get("publisher", "")
    if publisher:
        mp4_set_freeform(tags, "publisher", publisher)

    if metadata.get("write_summary"):
        mp4_set_text(tags, "\xa9cmt", metadata.get("summary", ""))

    if metadata.get("edit_mode") == "full" and (cover_if_missing or replace_cover):
        has_cover = mp4_has_cover(tags)
        should_write_cover = replace_cover or (cover_if_missing and not has_cover)

        if should_write_cover:
            cover_url = metadata.get("cover_url", "")

            if cover_url:
                if backup and has_cover:
                    cover_backup_path = backup_existing_mp4_cover(source, tags)
                    if cover_backup_path:
                        print(f"  Cover backup: {cover_backup_path}")

                cover_bytes, cover_format = download_cover_bytes(cover_url)
                mp4_set_cover(tags, cover_bytes, cover_format)
                print(f"  Cover embedded: {cover_format}")
            else:
                print("  Cover skipped: no Audible cover URL")

    layout = inspect_mp4_top_level_layout(source)
    write_started = time.monotonic()
    if layout["metadata_before_media"]:
        media_size_gib = layout["mdat"]["size"] / (1024 ** 3)
        print(
            f"  Mutagen MP4 write: metadata is before {media_size_gib:.2f} GiB of media; "
            "the payload may be shifted in place. This can take several minutes on NAS storage. "
            "Do not cancel while the file is being written.",
            flush=True,
        )
    else:
        print("  Mutagen MP4 write: saving metadata in place...", flush=True)
    audio.save()
    print(
        f"  Mutagen MP4 write complete in {time.monotonic() - write_started:.1f}s",
        flush=True,
    )

def mutagen_write_mp3_tags(
    source: Path,
    metadata: dict,
    backup: bool,
    cover_if_missing: bool = False,
    replace_cover: bool = False,
) -> None:
    """Write MP3 ID3 tags in-place using mutagen."""
    if not mutagen_mp3_is_available():
        raise RuntimeError(
            "mutagen MP3/ID3 support is not installed in this environment"
        )

    if not is_mutagen_mp3_candidate(source):
        raise RuntimeError(
            f"mutagen MP3 writer does not support this extension: {source.suffix}"
        )

    if backup:
        backup_path = write_original_metadata_backup(source)
        print(f"  Metadata backup: {backup_path}")

    try:
        tags = ID3(str(source))
    except ID3NoHeaderError:
        tags = ID3()

    title = metadata.get("title", "")
    author = metadata.get("author", "")
    series = metadata.get("series", "")
    sequence = metadata.get("sequence", "")
    narrator = metadata.get("narrator", "")
    year = metadata.get("year", "")
    subtitle = metadata.get("subtitle", "")
    genre = metadata.get("genre", "")
    isbn = metadata.get("isbn", "")

    # Audiobookshelf reads album/title as the displayed book title.
    id3_set_text(tags, "TIT2", TIT2, title)
    id3_set_text(tags, "TALB", TALB, title)

    id3_set_text(tags, "TPE1", TPE1, author)
    id3_set_text(tags, "TPE2", TPE2, author)
    id3_set_text(tags, "TCOM", TCOM, narrator)
    id3_set_text(tags, "TDRC", TDRC, year)
    if genre:
        id3_set_text(tags, "TCON", TCON, genre)
    id3_set_text(tags, "TIT1", TIT1, series)
    if subtitle and TIT3 is not None:
        id3_set_text(tags, "TIT3", TIT3, subtitle)
    id3_set_track(tags, sequence)

    # TXXX frames give ffprobe/other scanners multiple chances to expose series.
    id3_set_txxx(tags, "mvnm", series)
    id3_set_txxx(tags, "mvin", sequence)
    id3_set_txxx(tags, "series", series)
    id3_set_txxx(tags, "series-part", sequence)

    asin = metadata.get("asin", "")
    if asin:
        id3_set_txxx(tags, "asin", asin)

    if isbn:
        id3_set_txxx(tags, "isbn", isbn)

    publisher = metadata.get("publisher", "")
    if publisher and TPUB is not None:
        id3_set_text(tags, "TPUB", TPUB, publisher)

    if metadata.get("write_summary") and COMM is not None:
        summary = sanitize_tag(metadata.get("summary", ""))
        tags.delall("COMM")
        if summary:
            tags.add(COMM(encoding=3, lang="eng", desc="", text=[summary]))

    if metadata.get("edit_mode") == "full" and (cover_if_missing or replace_cover):
        has_cover = mp3_has_cover(tags)
        should_write_cover = replace_cover or (cover_if_missing and not has_cover)

        if should_write_cover:
            cover_url = metadata.get("cover_url", "")

            if cover_url:
                if backup and has_cover:
                    cover_backup_path = backup_existing_mp3_cover(source, tags)
                    if cover_backup_path:
                        print(f"  Cover backup: {cover_backup_path}")

                cover_bytes, cover_format = download_cover_bytes(cover_url)
                mp3_set_cover(tags, cover_bytes, cover_format)
                print(f"  Cover embedded: {cover_format}")
            else:
                print("  Cover skipped: no Audible cover URL")

    tags.save(str(source))

def mutagen_restore_metadata_from_backup(source: Path) -> Path:
    backup_path, tags = load_metadata_backup_payload(source)

    if is_mutagen_mp4_candidate(source):
        if not mutagen_mp4_is_available():
            raise RuntimeError(
                "mutagen MP4 support is not installed in this environment"
            )

        audio = MP4(str(source))
        if audio.tags is None:
            audio.add_tags()

        existing_covers = list(audio.tags.get("covr") or [])
        audio.tags.clear()

        if existing_covers:
            audio.tags["covr"] = existing_covers

        mp4_set_text(audio.tags, "\xa9nam", tags.get("title", ""))
        mp4_set_text(audio.tags, "\xa9ART", tags.get("artist", ""))
        mp4_set_text(audio.tags, "aART", tags.get("album_artist", ""))
        mp4_set_text(audio.tags, "\xa9alb", tags.get("album") or tags.get("title", ""))
        mp4_set_text(audio.tags, "\xa9grp", tags.get("grouping", ""))
        mp4_set_text(audio.tags, "\xa9wrt", tags.get("composer", ""))
        mp4_set_text(audio.tags, "\xa9day", tags.get("date", ""))
        mp4_set_text(audio.tags, "\xa9gen", tags.get("genre", ""))
        mp4_set_text(audio.tags, "\xa9cmt", tags.get("comment", ""))
        mp4_set_track(audio.tags, tags.get("track", ""))

        audio.save()

    elif is_mutagen_mp3_candidate(source):
        if not mutagen_mp3_is_available():
            raise RuntimeError(
                "mutagen MP3/ID3 support is not installed in this environment"
            )

        try:
            audio = ID3(str(source))
        except ID3NoHeaderError:
            audio = ID3()

        existing_covers = list(audio.getall("APIC"))
        audio.clear()

        for cover in existing_covers:
            audio.add(cover)

        id3_set_text(audio, "TIT2", TIT2, tags.get("title", ""))
        id3_set_text(audio, "TPE1", TPE1, tags.get("artist", ""))
        id3_set_text(audio, "TPE2", TPE2, tags.get("album_artist", ""))
        id3_set_text(audio, "TALB", TALB, tags.get("album") or tags.get("title", ""))
        id3_set_text(audio, "TCOM", TCOM, tags.get("composer", ""))
        id3_set_text(audio, "TDRC", TDRC, tags.get("date", ""))
        id3_set_text(audio, "TCON", TCON, tags.get("genre", ""))
        id3_set_track(audio, tags.get("track", ""))
        audio.save(str(source))

    else:
        raise RuntimeError(
            f"mutagen restore does not support this extension: {source.suffix}"
        )

    mark_metadata_restored(source)
    return backup_path

def restore_metadata_from_backup(source: Path, writer: str = "auto") -> Path:
    if writer in {"auto", "mutagen"} and is_mutagen_candidate(source):
        try:
            return mutagen_restore_metadata_from_backup(source)
        except Exception as error:
            if writer == "mutagen":
                raise
            print(f"  WARNING: mutagen restore failed, falling back to ffmpeg: {error}")

    return ffmpeg_restore_metadata_from_backup(source)

def restore_metadata_backups(
    files: list[Path], writer: str = "auto"
) -> tuple[int, int, int]:
    restored = 0
    skipped = 0
    failed = 0

    for index, file_path in enumerate(files, start=1):
        print(f"[{index}/{len(files)}] Restoring: {file_path}", flush=True)

        _, _lf = _load_libraforge_raw(file_path)
        if not _lf.get("backup", {}).get("format_tags"):
            print(f"  SKIP: no backup data found: {get_libraforge_path(file_path)}")
            print()
            skipped += 1
            continue

        try:
            restore_metadata_from_backup(file_path, writer=writer)
            print(f"  RESTORED from: {get_libraforge_path(file_path)}")
            print()
            restored += 1
        except Exception as error:
            reason = f"failed: {error}"
            print(f"  ERROR: {error}")
            append_manual_review(
                manual_review,
                file_path,
                [reason],
                clues=locals().get("clues", {}),
                score=locals().get("score", None),
                query=locals().get("used_query", ""),
                status="failed",
            )
            print()
            failed += 1

    print("Restore summary:")
    print(f"  Found:    {len(files)} files")
    print(f"  Restored: {restored}")
    print(f"  Skipped:  {skipped}")
    print(f"  Failed:   {failed}")

    return restored, skipped, failed

def should_skip_due_to_marker(
    source: Path,
    aggressive_run: bool,
    force: bool,
    minimum_score: float = AGGRESSIVE_SCORE_THRESHOLD,
) -> tuple[bool, str]:
    if force:
        return False, ""

    marker = load_marker(source)

    if not marker:
        return False, ""

    if aggressive_run:
        if marker.get("aggressive") is True:
            return True, "already aggressively processed"
        return False, ""

    if marker.get("applied") is True:
        if marker.get("manually_applied"):
            return True, "already manually applied"
        try:
            marker_score = float(marker.get("score"))
        except (TypeError, ValueError):
            marker_score = None

        if marker_score is not None and marker_score < minimum_score:
            return False, ""
        return True, "already processed"

    return False, ""

# Fields the fixer fills into file tags / metadata.json, in report order.
FILL_FIELDS = ("title", "author", "series", "sequence", "narrator", "year", "asin")

def marker_real_asin(marker: dict) -> str:
    """Return the marker's stored real ASIN (upper), or '' for none/NOREALASIN."""
    asin = str((marker.get("audible") or {}).get("asin") or "").strip().upper()
    return "" if (not asin or asin == "NOREALASIN") else asin

@trace(ALTER, capture=[])
def metadata_from_marker(marker: dict) -> dict:
    """Rebuild a fill-metadata dict from a marker's stored Audible match.

    Lets a previously-applied book be re-filled with the *same* match it got
    before, without a fresh Audible lookup. NOREALASIN is treated as no ASIN.
    """
    a = marker.get("audible") or {}
    return {
        "asin": marker_real_asin(marker),
        "title": a.get("chosen_title") or a.get("title") or "",
        "audible_title": a.get("title") or "",
        "author": a.get("author") or "",
        "narrator": a.get("narrator") or "",
        "series": a.get("series") or "",
        "sequence": a.get("sequence") or "",
        "audible_sequence": a.get("sequence") or "",
        "year": a.get("year") or "",
        "cover_url": a.get("cover_url") or "",
        "audible_duration_minutes": a.get("duration_minutes"),
        "audible_number_candidates": a.get("number_candidates") or [],
        "edit_mode": marker.get("edit_mode") or marker.get("mode") or "full",
        "duration": marker.get("duration") or {},
    }

def marker_skip_is_clean(
    source: Path, marker: dict, alone: bool, meta_target: Path
) -> bool:
    """True when an applied-marker book needs no maintenance and can be skipped fast.

    Uses only cheap filesystem stats (no media probe). A book is clean when its
    ASIN is recorded as written (or there is no real ASIN to write), its
    metadata.json already exists, and its sidecar is already at the final
    consolidated location. Anything else routes to the recovery path so missing
    tags / metadata.json / sidecars get repaired. Legacy markers (no
    ``written_fields``) are never clean, so they are repaired once and then
    stamped, after which they short-circuit here.
    """
    if marker_real_asin(marker) and "asin" not in set(marker.get("written_fields") or []):
        return False
    if not meta_target.exists():
        return False
    if alone and source.with_name(f"{source.name}{LIBRAFORGE_SUFFIX}").is_file():
        return False
    return True

def write_marker(
    source: Path,
    metadata: dict,
    clues: dict,
    score: float,
    mode: str,
    aggressive: bool,
    output_kind: str = "tags",
    alone: bool = False,
    written_fields: list[str] | None = None,
) -> None:
    lf_path, payload = _load_libraforge_raw(source, clues, alone=alone)
    payload.setdefault("schema_version", 2)
    payload.setdefault("tool", "audible-metadata-fixer")
    existing_marker = payload.get("marker") or {}
    # Preserve any previously-recorded written fields so a fill-missing run that
    # adds one field doesn't erase the record of fields written by an earlier run.
    merged_written = sorted(set(existing_marker.get("written_fields") or []) | set(written_fields or []))
    payload["marker"] = {
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "applied": True,
        "manually_applied": mode.startswith("manual_"),
        "mode": mode,
        "edit_mode": metadata.get("edit_mode", mode),
        "aggressive": aggressive,
        "score": score,
        "source_file": source.name,
        "output_kind": output_kind,
        "written_fields": merged_written,
        "duration": metadata.get("duration", {}),
        "audible": {
            "asin": metadata.get("asin", ""),
            "title": metadata.get("audible_title", metadata.get("title", "")),
            "chosen_title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "narrator": metadata.get("narrator", ""),
            "series": metadata.get("series", ""),
            "sequence": metadata.get("sequence", ""),
            "year": metadata.get("year", ""),
            "cover_url": metadata.get("cover_url", ""),
            "duration_minutes": metadata.get("audible_duration_minutes"),
            "number_candidates": metadata.get("audible_number_candidates", []),
        },
        "local_before": {
            "raw_title": clues.get("raw_title", ""),
            "title": clues.get("title", ""),
            "author": clues.get("author", ""),
            "series": clues.get("series", ""),
            "number": clues.get("book_number", ""),
            "number_source": clues.get("book_number_source", ""),
            "narrator": clues.get("narrator", ""),
        },
    }
    _write_libraforge(lf_path, payload)

def should_write_json_sidecar(source: Path, clues: dict | None = None) -> bool:
    suffix = source.suffix.lower()
    group_search = (clues or {}).get("group_search", {}) or {}
    # Sidecar only for grouped multi-part books: stamping every chapter file with
    # book-level metadata is wrong. Standalone single files get direct tag writes.
    return bool(group_search.get("applied") and suffix in MULTI_PART_AUDIO_EXTENSIONS)

def write_skip_marker(source: Path, clues: dict | None = None, alone: bool = False) -> None:
    """Write a non-applied marker for books that could not be matched.

    Preserves any real ASIN already present (existing_asin from clues or the
    sidecar's marker.audible.asin). Only writes NOREALASIN when no real ASIN
    is known anywhere, so the Start Here scanner can skip mutagen on books
    with no ASIN while keeping the correct value for books that do have one.
    Does not set applied=True so the fixer will re-process on the next run.
    """
    lf_path, payload = _load_libraforge_raw(source, clues, alone=alone)
    payload.setdefault("schema_version", 2)
    payload.setdefault("tool", "audible-metadata-fixer")
    existing_audible = (payload.get("marker") or {}).get("audible") or {}
    existing_asin = (
        existing_audible.get("asin")
        or (clues or {}).get("existing_asin")
        or ""
    )
    asin_to_write = (
        existing_asin
        if existing_asin and existing_asin != "NOREALASIN"
        else "NOREALASIN"
    )
    payload["marker"] = {
        **payload.get("marker", {}),
        "applied": False,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source.name,
        "audible": {
            **existing_audible,
            "asin": asin_to_write,
        },
    }
    _write_libraforge(lf_path, payload)

def is_single_file_mp3(source: Path, clues: dict | None = None) -> bool:
    """True for a standalone single-file .mp3 (not a multi-part folder group)."""
    if source.suffix.lower() != ".mp3":
        return False
    group_search = (clues or {}).get("group_search", {}) or {}
    return not group_search.get("applied")

def probe_audio_stream_properties(file_path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,codec_long_name,profile,bit_rate,channels,sample_rate:format=format_name,format_long_name,bit_rate",
        "-of",
        "json",
        str(file_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        probe = json.loads(result.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return {"probed": False}

    stream = (probe.get("streams") or [{}])[0]
    format_info = probe.get("format") or {}
    bitrate = stream.get("bit_rate") or format_info.get("bit_rate")
    codec = str(stream.get("codec_name", "") or "").lower()
    codec_label = str(stream.get("codec_long_name", "") or codec.upper())
    profile = str(stream.get("profile", "") or "")
    if profile and profile.lower() not in codec_label.lower():
        codec_label = f"{codec_label} ({profile})"
    return {
        "probed": bool(stream),
        "codec": codec,
        "codec_label": codec_label,
        "container": str(
            format_info.get("format_long_name", "")
            or format_info.get("format_name", "")
            or ""
        ),
        "bitrate_kbps": round(int(bitrate) / 1000) if bitrate else None,
        "channels": int(stream["channels"]) if stream.get("channels") else None,
        "sample_rate_hz": (
            int(stream["sample_rate"]) if stream.get("sample_rate") else None
        ),
    }

def summarize_audio_stream_properties(file_paths: list[Path]) -> dict:
    probes = [probe_audio_stream_properties(file_path) for file_path in file_paths]
    successful = [probe for probe in probes if probe.get("probed")]

    def values(field: str) -> list:
        return sorted(
            {
                probe[field]
                for probe in successful
                if probe.get(field) not in (None, "")
            }
        )

    codecs = values("codec")
    codec_labels = values("codec_label")
    containers = values("container")
    bitrates = values("bitrate_kbps")
    channels = values("channels")
    sample_rates = values("sample_rate_hz")
    incomplete = len(successful) != len(file_paths) or any(
        not probe.get("codec")
        or not probe.get("channels")
        or not probe.get("sample_rate_hz")
        for probe in successful
    )
    mixed = {
        "codec": len(codecs) > 1,
        "container": len(containers) > 1,
        "bitrate": len(bitrates) > 1,
        "channels": len(channels) > 1,
        "sample_rate": len(sample_rates) > 1,
    }

    if not file_paths or not successful:
        recommendation = {
            "status": "unknown",
            "recommended": False,
            "label": "Convert to AAC",
            "reason": "Audio properties could not be read, so stream-copy compatibility cannot be confirmed.",
        }
    elif incomplete:
        recommendation = {
            "status": "convert",
            "recommended": False,
            "label": "Convert to AAC",
            "reason": "Some source stream properties are missing or unreadable, so no-conversion cannot be recommended safely.",
        }
    elif len(codecs) != 1 or codecs[0] != "aac":
        shown = ", ".join(codec_labels or [codec.upper() for codec in codecs]) or "unknown"
        recommendation = {
            "status": "convert",
            "recommended": False,
            "label": "Convert to AAC",
            "reason": f"The source codec is {shown}; AAC provides the most reliable M4B playback compatibility.",
        }
    elif mixed["sample_rate"] or mixed["channels"]:
        differing = []
        if mixed["sample_rate"]:
            differing.append("sample rates")
        if mixed["channels"]:
            differing.append("channel layouts")
        recommendation = {
            "status": "convert",
            "recommended": False,
            "label": "Convert to AAC",
            "reason": f"The source files have mixed {' and '.join(differing)}, which should be normalized before merging.",
        }
    else:
        bitrate_note = (
            " Bitrates vary, which is acceptable for stream-copy."
            if mixed["bitrate"]
            else ""
        )
        recommendation = {
            "status": "copy",
            "recommended": True,
            "label": "No conversion recommended",
            "reason": "All source files use AAC with matching sample rate and channel layout; stream-copy avoids quality loss and is faster."
            + bitrate_note,
        }

    mixed_properties = [name for name, is_mixed in mixed.items() if is_mixed]
    return {
        "file_count": len(file_paths),
        "probed_file_count": len(successful),
        "codecs": codecs,
        "codec_labels": codec_labels,
        "containers": containers,
        "bitrates_kbps": bitrates,
        "channels": channels,
        "sample_rates_hz": sample_rates,
        "mixed": mixed,
        "mixed_properties": mixed_properties,
        "is_mixed": bool(mixed_properties),
        "no_conversion": recommendation,
    }

def build_m4b_tool_metadata_payload(
    source: Path, metadata: dict, clues: dict, score: float
) -> dict:
    sidecar_path = get_m4b_tool_metadata_path(source, clues)
    group_search = clues.get("group_search", {}) or {}
    chapter_files = []

    if group_search.get("applied"):
        explicit_files = group_search.get("files") or []
        if explicit_files:
            chapter_files = [str(file_path) for file_path in explicit_files]
        else:
            for chapter_file in sorted(source.parent.iterdir(), key=natural_audio_sort_key):
                if chapter_file.is_file() and is_supported_audio_file(chapter_file):
                    if chapter_file.suffix.lower() in MULTI_PART_AUDIO_EXTENSIONS:
                        chapter_files.append(str(chapter_file))
    else:
        chapter_files.append(str(source))

    audio_summary = summarize_audio_stream_properties(
        [Path(file_path) for file_path in chapter_files]
    )

    return {
        "schema_version": 1,
        "tool": "audible-metadata-fixer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_format": source.suffix.lower().lstrip("."),
        "output_intent": "m4b-tool-remux",
        "metadata_file": str(sidecar_path),
        "book": {
            "title": metadata.get("title", ""),
            "subtitle": metadata.get("subtitle", ""),
            "author": metadata.get("author", ""),
            "narrator": metadata.get("narrator", ""),
            "series": metadata.get("series", ""),
            "sequence": metadata.get("sequence", ""),
            "year": metadata.get("year", ""),
            "summary": metadata.get("summary", ""),
            "genre": metadata.get("genre", ""),
            "isbn": metadata.get("isbn", ""),
            "cover_url": metadata.get("cover_url", ""),
        },
        "audible": {
            "asin": metadata.get("asin", ""),
            "title": metadata.get("audible_title", ""),
            "sequence": metadata.get("audible_sequence", ""),
            "year": metadata.get("audible_year", ""),
            "duration_minutes": metadata.get("audible_duration_minutes"),
            "number_candidates": metadata.get("audible_number_candidates", []),
        },
        "matching": {
            "score": score,
            "edit_mode": metadata.get("edit_mode", ""),
            "duration": metadata.get("duration", {}),
        },
        "local_before": {
            "raw_title": clues.get("raw_title", ""),
            "title": clues.get("title", ""),
            "author": clues.get("author", ""),
            "series": clues.get("series", ""),
            "number": clues.get("book_number", ""),
            "number_source": clues.get("book_number_source", ""),
            "narrator": clues.get("narrator", ""),
            "local_duration_minutes": clues.get("local_duration_minutes"),
        },
        "audio_summary": audio_summary,
        "source": {
            "root_file": str(source),
            "group_search": group_search,
            "chapter_files": chapter_files,
        },
    }

def write_m4b_tool_metadata_sidecar(
    source: Path, metadata: dict, clues: dict, score: float
) -> Path:
    sidecar_data = build_m4b_tool_metadata_payload(source, metadata, clues, score)
    lf_path, lf_payload = _load_libraforge_raw(source, clues)
    lf_payload.setdefault("schema_version", 2)
    lf_payload.setdefault("tool", "audible-metadata-fixer")
    lf_payload["sidecar"] = {
        k: sidecar_data[k]
        for k in ("book", "audible", "matching", "local_before", "audio_summary", "source")
        if k in sidecar_data
    }
    _write_libraforge(lf_path, lf_payload)
    return lf_path

def write_audiobookshelf_metadata_json(
    source: Path,
    metadata: dict,
    clues: dict | None = None,
    alone_in_folder: bool = False,
    fill_missing: bool = False,
) -> Path:
    """Write an Audiobookshelf-compatible metadata.json for the book.

    Placement is resolved by :func:`get_audiobookshelf_metadata_path`: a grouped
    multi-file book or a single file alone in its folder gets folder/metadata.json;
    a loose single file sharing its folder gets a collision-safe companion
    <file>.metadata.json (the organizer renames it to metadata.json post-move).

    When ``fill_missing`` is True and a metadata.json already exists, only empty
    fields in the existing file are populated; values already present are kept.
    This mirrors the fill-missing tag policy so we never clobber good data.
    """
    if source.is_dir():
        # Fallback for directory source — shouldn't happen in normal flow
        target = source / "metadata.json"
    else:
        target = get_audiobookshelf_metadata_path(source, clues, alone_in_folder)

    authors = [
        name.strip()
        for name in re.split(r"\s*,\s*", metadata.get("author", "") or "")
        if name.strip()
    ]
    narrators = [
        name.strip()
        for name in re.split(r"\s*,\s*", metadata.get("narrator", "") or "")
        if name.strip()
    ]
    series = []
    if metadata.get("series"):
        series_name = metadata["series"]
        seq = metadata.get("sequence", "") or ""
        series.append(f"{series_name} #{seq}" if seq else series_name)

    payload = {
        "title": metadata.get("title", "") or "",
        "subtitle": metadata.get("subtitle", "") or "",
        "authors": authors,
        "narrators": narrators,
        "series": series,
        "genres": [g for g in [metadata.get("genre", "")] if g],
        "publishedYear": str(metadata.get("year", "") or ""),
        "publisher": metadata.get("publisher", "") or "",
        "description": metadata.get("summary", "") or "",
        "isbn": metadata.get("isbn") or None,
        "asin": metadata.get("asin", "") or None,
        "language": None,
        "explicit": False,
    }

    if fill_missing and target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        if isinstance(existing, dict):
            # Keep any non-empty existing value; only fill where the file is blank.
            def _blank(v) -> bool:
                return v in (None, "", [], {}) or (isinstance(v, str) and not v.strip())

            for key, new_value in payload.items():
                old_value = existing.get(key, None)
                if _blank(old_value):
                    continue
                # For the series list: don't preserve a fraction sequence (e.g. "1/1"
                # written by Audible's old catalog data) when the fresh value has a
                # clean numeric sequence for the same series.
                if key == "series" and isinstance(new_value, list) and isinstance(old_value, list):
                    old_fractions = [
                        s.get("sequence", "") for s in old_value
                        if isinstance(s, dict) and "/" in str(s.get("sequence", ""))
                    ]
                    new_valid = [
                        s.get("sequence", "") for s in new_value
                        if isinstance(s, dict) and is_single_numeric_sequence(str(s.get("sequence", "")))
                    ]
                    if old_fractions and new_valid:
                        continue  # use the fresh value instead of preserving the fraction
                payload[key] = old_value
            # Preserve any extra keys the existing file carried (e.g. language, tags).
            for key, old_value in existing.items():
                if key not in payload:
                    payload[key] = old_value

    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    try:
        target.write_text(content, encoding="utf-8")
    except PermissionError:
        # existing file may be read-only; unlink (directory write lets us do this) and retry
        target.unlink()
        target.write_text(content, encoding="utf-8")
    return target

def refresh_multipart_sidecar_audio_profile(
    folder: Path,
    chapter_files: list[Path],
    audio_summary: dict | None = None,
) -> Path:
    lf_path = folder / "libraforge.json"
    lf_payload: dict = {}
    if lf_path.is_file():
        try:
            lf_payload = json.loads(lf_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            lf_payload = {}

    lf_payload.setdefault("schema_version", 2)
    lf_payload.setdefault("tool", "audible-metadata-fixer")

    ordered_files = sorted(chapter_files, key=natural_audio_sort_key)
    sidecar = lf_payload.setdefault("sidecar", {})
    sidecar["audio_summary"] = audio_summary or summarize_audio_stream_properties(ordered_files)
    sidecar["audio_profile_updated_at"] = datetime.now(timezone.utc).isoformat()

    source_section = sidecar.setdefault("source", {})
    source_section["chapter_files"] = [str(fp) for fp in ordered_files]
    group_search = source_section.get("group_search")
    if isinstance(group_search, dict):
        group_search["file_count"] = len(ordered_files)
        group_search["files"] = [str(fp) for fp in ordered_files]

    _write_libraforge(lf_path, lf_payload)
    return lf_path

def probe_file(file_path: Path) -> tuple[dict, float | None]:
    """Single ffprobe -show_format call returning (tags_dict, duration_minutes).

    -show_format already includes both the embedded tag block and the
    container duration, so one subprocess call covers both needs.
    """
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        str(file_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print(f"  WARNING: ffprobe timed out for: {file_path}")
        return {}, None

    if result.returncode != 0:
        print(f"  WARNING: ffprobe failed for: {file_path}")
        return {}, None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  WARNING: ffprobe returned invalid JSON for: {file_path}")
        return {}, None

    fmt = data.get("format", {}) or {}
    tags = {
        str(key).lower(): str(value).strip()
        for key, value in (fmt.get("tags", {}) or {}).items()
        if str(value).strip()
    }

    try:
        seconds = float(fmt.get("duration") or 0)
        duration_minutes = (seconds / 60) if seconds > 0 else None
    except (TypeError, ValueError):
        duration_minutes = None

    return tags, duration_minutes

def read_file_tags(file_path: Path) -> dict:
    return probe_file(file_path)[0]

def read_file_duration_minutes(file_path: Path) -> float | None:
    return probe_file(file_path)[1]

def _synthesize_applied_tags(metadata: dict) -> dict:
    """Build a probe-format tags dict from applied metadata for backup caching.

    Stored as applied_tags in the backup so force re-runs can skip ffprobe
    while still searching from the clean Audible-matched values.
    """
    tags: dict[str, str] = {}
    for src_key, dst_key in (
        ("title", "title"),
        ("title", "album"),
        ("author", "artist"),
        ("author", "album_artist"),
        ("series", "grouping"),
        ("narrator", "composer"),
        ("year", "date"),
        ("asin", "asin"),
    ):
        val = str(metadata.get(src_key, "") or "").strip()
        if val:
            tags[dst_key] = val
    seq = str(metadata.get("sequence", "") or "").strip()
    if seq:
        tags["track"] = seq
    return tags

def update_backup_with_applied_metadata(source: Path, metadata: dict) -> None:
    """Append applied_tags to the backup section so future runs skip probing the file."""
    lf_path, payload = _load_libraforge_raw(source)
    if "backup" not in payload:
        return
    try:
        payload["backup"]["applied_tags"] = _synthesize_applied_tags(metadata)
        payload["backup"]["applied_at"] = datetime.now(timezone.utc).isoformat()
        _write_libraforge(lf_path, payload)
    except (OSError, KeyError):
        pass

def _save_group_file_cache(
    file_paths: list[Path],
    per_file: list[tuple[dict, float | None]],
) -> None:
    """Store per-chapter probe data in the folder-level libraforge.json for future cache reads.

    Only writes format_tags when an entry is new — never overwrites an
    existing format_tags with post-apply synthesized data so the original
    pre-apply tags are always preserved.
    """
    if not file_paths:
        return
    lf_path = file_paths[0].parent / "libraforge.json"
    lf_payload: dict = {}
    if lf_path.is_file():
        try:
            lf_payload = json.loads(lf_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            lf_payload = {}

    lf_payload.setdefault("schema_version", 2)
    lf_payload.setdefault("tool", "audible-metadata-fixer")

    existing_cache: dict = lf_payload.get("file_cache", {})
    changed = False

    for fp, (tags, duration) in zip(file_paths, per_file):
        key = str(fp)
        entry = dict(existing_cache.get(key, {}))
        if not entry.get("format_tags") and isinstance(tags, dict):
            entry["format_tags"] = tags
            changed = True
        if entry.get("duration_minutes") is None and duration is not None:
            entry["duration_minutes"] = duration
            changed = True
        existing_cache[key] = entry

    if not changed:
        return

    lf_payload["file_cache"] = existing_cache
    lf_payload["file_cache_updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_libraforge(lf_path, lf_payload)

def read_tags_and_duration(
    file_path: Path,
    use_backup_tags: bool = False,
    reprobe: bool = False,
) -> tuple[dict, float | None]:
    """Return (tags, duration_minutes) from backup when available, else probe.

    reprobe=True (--reprobe): always probe the file, ignoring any backup.

    use_backup_tags=True (--force-original): use the original pre-apply tags
    from the backup (format_tags). Skips probing. Useful when the prior match
    was wrong and you want to re-search from the original local metadata.

    Default: prefer applied_tags from backup (the clean Audible values written
    last time) then fall back to format_tags, then probe if no backup exists.
    Duration always comes from the backup when available since it never changes
    with tag-only writes.
    """
    if reprobe:
        return probe_file(file_path)

    # Folder-level libraforge (multi-file / grouped books).
    try:
        folder_lf = file_path.parent / "libraforge.json"
        if folder_lf.is_file():
            lf = json.loads(folder_lf.read_text(encoding="utf-8"))
            entry = (lf.get("file_cache") or {}).get(str(file_path))
            if entry:
                duration = entry.get("duration_minutes")
                if duration is not None:
                    if use_backup_tags:
                        tags = entry.get("format_tags")
                    else:
                        book = (lf.get("sidecar") or {}).get("book")
                        tags = (
                            _synthesize_applied_tags(book)
                            if book
                            else entry.get("format_tags")
                        )
                    if isinstance(tags, dict):
                        return tags, float(duration)
    except (json.JSONDecodeError, OSError, ValueError):
        pass

    # File-level libraforge (single-file books).
    try:
        _, lf = _load_libraforge_raw(file_path)
        backup = lf.get("backup", {})
        duration = backup.get("duration_minutes")
        if duration is not None:
            if use_backup_tags:
                tags = backup.get("format_tags")
            else:
                tags = backup.get("applied_tags") or backup.get("format_tags")
            if isinstance(tags, dict):
                return tags, float(duration)
    except (json.JSONDecodeError, OSError, ValueError):
        pass

    return probe_file(file_path)

@trace(ALTER, capture=["file_path"])
def build_search_clues_from_file(file_path: Path, tags: dict | None = None) -> dict:
    if tags is None:
        tags = read_file_tags(file_path)
    clues = parse_title_series_number_from_metadata(tags)

    # If the folder/file path is clearly structured, trust it over stale embedded tags.
    # This is intentionally narrow and does not change the matching/scoring model.
    clues = apply_structured_path_override(clues, file_path)

    # Path-derived book numbers are stronger than embedded track numbers.
    # This handles cases where the file tag track is stale, but the folder says Book 8.
    path_book_number = extract_book_number_from_path(file_path)
    if path_book_number and clues.get("book_number_source") in {"", "track"}:
        clues["book_number"] = path_book_number
        clues["book_number_source"] = "path"

    # Reuse Folder Forge's clean Author/Series/Book hierarchy assumption.
    # A leading sequence folder identifies the book, while its parent identifies
    # the series. This also replaces album values that merely repeat the title.
    parent_number = extract_folder_book_number(file_path.parent.name)
    sequence_free_parent = strip_leading_sequence_from_title(file_path.parent.name)
    parent_has_sequence = bool(parent_number)
    if parent_has_sequence:
        hierarchy_series = clean_series_value(file_path.parent.parent.name)
        generic_series = {
            "audiobooks",
            "books",
            "library",
            "media",
            "unorganized",
            "_unorganized",
            "unknown",
        }
        current_series_norm = normalize_for_match(clues.get("series", ""))
        current_title_norm = normalize_for_match(clues.get("title", ""))
        if (
            hierarchy_series
            and normalize_for_match(hierarchy_series) not in generic_series
            and (
                not current_series_norm
                or current_series_norm == current_title_norm
                or current_series_norm
                == normalize_for_match(file_path.parent.name)
            )
        ):
            clues["series"] = hierarchy_series

    descriptive_path_meta = parse_descriptive_book_from_path(
        file_path, known_author=clues.get("author", "")
    )
    if descriptive_path_meta:
        if (
            descriptive_path_meta.get("author")
            and should_prefer_path_author(
                clues.get("author", ""),
                descriptive_path_meta.get("author", ""),
            )
        ):
            clues["author"] = descriptive_path_meta["author"]

        if (
            descriptive_path_meta.get("title")
            and (
                not clues.get("title")
                or is_generic_chapter_title(clues.get("title", ""))
                or (
                    descriptive_path_meta.get("author")
                    and normalize_for_match(descriptive_path_meta.get("author", ""))
                    in normalize_for_match(clues.get("title", ""))
                )
            )
        ):
            clues["raw_title"] = descriptive_path_meta.get("raw_title", clues.get("raw_title", ""))
            clues["title"] = descriptive_path_meta["title"]

        if (
            not clues.get("narrator")
            and descriptive_path_meta.get("narrator")
        ):
            clues["narrator"] = descriptive_path_meta["narrator"]

        if (
            descriptive_path_meta.get("series")
            and (
                not clues.get("series")
                or normalize_for_match(clues.get("series", "")) in normalize_for_match(clues.get("title", ""))
            )
        ):
            clues["series"] = descriptive_path_meta["series"]

        if (
            descriptive_path_meta.get("book_number")
            and clues.get("book_number_source") in {"", "track"}
        ):
            clues["book_number"] = descriptive_path_meta["book_number"]
            clues["book_number_source"] = "path"

    # Extract existing ASIN from embedded tags or filename bracket pattern [B0XXXXXXXX] / [ASIN.B0XXXXXXXX].
    # Audible ASINs always start with B0; the B0-prefix pattern avoids false matches on other bracket
    # tokens that happen to be 10 characters. The separate title-cleaning strip regex stays broad
    # because it removes noise rather than extracting for validation.
    existing_asin = (tags or {}).get("asin", "").strip().upper()
    if not existing_asin:
        # Audible ASINs always start with B0 followed by 8 alphanumeric characters.
        # The tighter pattern avoids false matches on other bracket tokens in filenames.
        m = re.search(r"\[(?:ASIN\.)?([Bb]0[A-Z0-9]{8})\]", str(file_path), flags=re.IGNORECASE)
        if m:
            existing_asin = m.group(1).upper()
    if existing_asin:
        clues["existing_asin"] = existing_asin

    # Recover an author baked into the title ("... by Douglas Adams") when the
    # author tag is empty. This only fills a missing field; it never overrides an
    # existing author, and the search-only title noise is stripped elsewhere.
    if not clues.get("author"):
        embedded_author = extract_author_from_title(
            clues.get("title", "") or clues.get("raw_title", "")
        )
        if embedded_author:
            clues["author"] = embedded_author
            clues["author_source"] = "title"

    capture_publisher_clue(clues, tags or {})

    return recover_invalid_local_title(clues, file_path)

@trace(CHOOSE, capture=["file_path"])
def build_search_queries_from_metadata(file_path: Path, tags: dict | None = None) -> tuple[list[str], dict]:
    clues = build_search_clues_from_file(file_path, tags=tags)
    return build_search_queries_from_clues(clues), clues

@trace(ALTER, capture=[], show_result=False)
def build_multi_file_search_context(
    file_paths: list[Path],
    use_backup_tags: bool = False,
    reprobe: bool = False,
    save_probe_cache: bool = False,
) -> tuple[list[str], dict]:
    per_file = [
        read_tags_and_duration(fp, use_backup_tags=use_backup_tags, reprobe=reprobe)
        for fp in file_paths
    ]
    if save_probe_cache:
        _save_group_file_cache(file_paths, per_file)
    clues_list = [
        build_search_clues_from_file(fp, tags=tags)
        for fp, (tags, _) in zip(file_paths, per_file)
    ]
    folder = file_paths[0].parent
    folder_name = sanitize_technical_labels(folder.name)
    path_author, path_series = infer_group_identity_from_path(folder)
    # Feed a known author into the structured parse so a "Series N - Author Name"
    # folder is read as series + number (not author-as-title). Prefer the tag
    # author shared across the group, then the path-inferred author.
    group_known_author = (
        pick_most_common_value([clues.get("author", "") for clues in clues_list])
        or path_author
    )
    folder_structured = parse_structured_book_text(
        folder_name, known_author=group_known_author
    )
    folder_descriptive = parse_descriptive_book_text(folder_name)
    folder_identity = parse_identity_rich_book_text(folder_name)

    specific_titles = [
        clues.get("title", "")
        for clues in clues_list
        if clues.get("title") and not is_generic_chapter_title(clues.get("title", ""))
    ]
    raw_titles = [
        clues.get("raw_title", "")
        for clues in clues_list
        if clues.get("raw_title")
        and not is_generic_chapter_title(clues.get("raw_title", ""))
    ]

    title = (
        folder_identity.get("title")
        or
        folder_structured.get("title")
        or folder_descriptive.get("title")
        or (folder_name if not is_generic_chapter_title(folder_name) else "")
        or pick_most_common_value(specific_titles)
        or pick_most_common_value(raw_titles)
    )
    author = (
        folder_identity.get("author")
        or folder_descriptive.get("author")
        or pick_most_common_value([clues.get("author", "") for clues in clues_list])
        or path_author
    )
    if title == folder_name:
        title = clean_group_folder_title(title, author) or title
    narrator = pick_most_common_value(
        [clues.get("narrator", "") for clues in clues_list]
    )
    series = (
        folder_identity.get("series")
        or folder_structured.get("series")
        or pick_most_common_value([clues.get("series", "") for clues in clues_list])
        or path_series
    )
    book_number, book_number_source = choose_group_book_number(clues_list, folder_name)
    if folder_identity.get("book_number"):
        book_number = folder_identity["book_number"]
        book_number_source = "path"
    if not book_number and folder_descriptive.get("book_number"):
        book_number = folder_descriptive["book_number"]
        book_number_source = "path"
    local_duration_minutes = sum(
        (duration or 0.0) for _, duration in per_file
    ) or None

    validation = validate_multi_part_group_files(file_paths)
    extension_counts = Counter(file_path.suffix.lower().lstrip(".") for file_path in file_paths)

    clues = {
        "raw_title": title or folder_name,
        "title": title,
        "series": series,
        "book_number": book_number,
        "book_number_source": book_number_source,
        "author": author,
        "narrator": narrator,
        "album": pick_most_common_value([clues.get("album", "") for clues in clues_list]),
        "local_duration_minutes": local_duration_minutes,
        "group_search": {
            "applied": True,
            "folder": str(folder),
            "file_count": len(file_paths),
            "formats": dict(sorted(extension_counts.items())),
            "files": [str(file_path) for file_path in sorted(file_paths, key=natural_audio_sort_key)],
            "chapter_validation": validation,
        },
    }

    # Carry the publisher captured per file up to the group (most common value).
    group_publisher = pick_most_common_value(
        [c.get("publisher", "") for c in clues_list if c.get("publisher")]
    )
    if group_publisher:
        clues["publisher"] = group_publisher
        canonical = match_canonical_publisher(group_publisher)
        clues["publisher_verified"] = bool(canonical)

    queries = build_search_queries_from_clues(clues)
    return queries, clues

def build_multi_part_group_map(
    files: list[Path],
    chapter_count_reader=None,
) -> dict[Path, list[Path]]:
    grouped: dict[Path, list[Path]] = {}

    for file_path in files:
        if not is_multi_part_audio_candidate(file_path):
            continue
        grouped.setdefault(file_path.parent, []).append(file_path)

    accepted: dict[Path, list[Path]] = {}

    for parent, group_files in sorted(grouped.items()):
        group_files = sorted(group_files, key=natural_audio_sort_key)

        if len(group_files) <= 1:
            continue

        numeric_parts = part_sequence_files(group_files)
        candidate_files = (
            sorted(numeric_parts, key=natural_audio_sort_key)
            if len(numeric_parts) >= 2
            else group_files
        )
        validation = validate_multi_part_group_files(
            candidate_files,
            chapter_count_reader=chapter_count_reader,
        )
        if not validation.get("safe", True):
            print(f"  WARNING: not grouping multi-file folder with embedded chapters: {parent}")
            for unsafe in validation.get("unsafe_files", []):
                print(
                    "    unsafe: "
                    f"{unsafe.get('file')} "
                    f"chapters={unsafe.get('chapter_count')} "
                    f"reason={unsafe.get('reason', '-')}"
                )
            continue

        accepted[parent] = candidate_files

    return accepted

def prefetch_chapter_counts(files: list[Path], workers: int) -> None:
    """Pre-warm read_file_chapter_count from disk cache, probing only new/changed files.

    On recurring runs, chapter counts are read from per-folder JSON cache files
    (<folder>/<folder>.chapter-count-cache.json) keyed by path + mtime. No
    ffprobe is run for files whose mtime has not changed since the last probe.

    On a clean run (or for files not yet cached), ffprobe calls are batched and
    run concurrently with `workers` threads. Results are written back to disk so
    the next run is instant.

    All multi-part audio files are written to the cache regardless of type.
    chapter_count is populated only for is_chapter_metadata_candidate files
    (m4a/m4b/mp4); other types (ogg/mp3/opus) are recorded with chapter_count=None
    so the cache covers every multi-file book for m4b merging and format support.
    """
    grouped: dict[Path, list[Path]] = {}
    for fp in files:
        if is_multi_part_audio_candidate(fp):
            grouped.setdefault(fp.parent, []).append(fp)

    folder_persistent: dict[Path, dict[str, dict]] = {}
    to_probe: list[Path] = []

    for parent, group in sorted(grouped.items()):
        if len(group) <= 1:
            continue

        persistent = _load_chapter_count_persistent(parent)
        folder_persistent[parent] = persistent

        for fp in group:
            key = str(fp)
            entry = persistent.get(key)
            if entry is not None:
                try:
                    if entry.get("mtime") == fp.stat().st_mtime:
                        if is_chapter_metadata_candidate(fp):
                            with _chapter_count_cache_lock:
                                _chapter_count_cache[key] = entry.get("chapter_count")
                        continue
                except OSError:
                    pass
            if is_chapter_metadata_candidate(fp):
                to_probe.append(fp)
            else:
                # No ffprobe needed; record with chapter_count=None
                try:
                    mtime = fp.stat().st_mtime
                except OSError:
                    mtime = None
                persistent[key] = {"chapter_count": None, "mtime": mtime}

    if to_probe:
        if workers > 1:
            print(
                f"  Pre-checking {len(to_probe)} files for embedded chapters "
                f"({workers} workers)...",
                flush=True,
            )
            with ThreadPoolExecutor(max_workers=workers) as executor:
                list(executor.map(read_file_chapter_count, to_probe))
        else:
            for fp in to_probe:
                read_file_chapter_count(fp)

        for parent, persistent in folder_persistent.items():
            for fp in to_probe:
                if fp.parent != parent:
                    continue
                key = str(fp)
                with _chapter_count_cache_lock:
                    count = _chapter_count_cache.get(key)
                try:
                    mtime = fp.stat().st_mtime
                except OSError:
                    mtime = None
                persistent[key] = {"chapter_count": count, "mtime": mtime}

    for parent, persistent in folder_persistent.items():
        _save_chapter_count_persistent(parent, persistent)

def build_processing_items(
    files: list[Path], multi_part_group_map: dict[Path, list[Path]]
) -> list[Path]:
    items: list[Path] = []
    seen_group_parents: set[Path] = set()

    for file_path in files:
        group_files = multi_part_group_map.get(file_path.parent)
        if group_files and file_path in group_files:
            if file_path.parent in seen_group_parents:
                continue
            items.append(group_files[0])
            seen_group_parents.add(file_path.parent)
            continue

        items.append(file_path)

    return items

def get_processing_display_path(
    file_path: Path, multi_part_group_map: dict[Path, list[Path]]
) -> Path:
    group_files = multi_part_group_map.get(file_path.parent)
    if group_files and is_multi_part_audio_candidate(file_path):
        return file_path.parent
    return file_path

def build_search_context(
    file_path: Path,
    multi_part_group_map: dict[Path, list[Path]],
    use_backup_tags: bool = False,
    reprobe: bool = False,
    save_probe_cache: bool = False,
) -> tuple[list[str], dict, str]:
    group_files = multi_part_group_map.get(file_path.parent)

    if group_files and is_multi_part_audio_candidate(file_path):
        queries, clues = build_multi_file_search_context(
            group_files,
            use_backup_tags=use_backup_tags,
            reprobe=reprobe,
            save_probe_cache=save_probe_cache,
        )
        cache_key = f"group::{file_path.parent}"
        return queries, clues, cache_key

    tags, duration = read_tags_and_duration(file_path, use_backup_tags=use_backup_tags, reprobe=reprobe)
    if save_probe_cache and not should_write_json_sidecar(file_path, None):
        write_original_metadata_backup(file_path, tags=tags, duration_minutes=duration)
    queries, clues = build_search_queries_from_metadata(file_path, tags=tags)
    clues["local_duration_minutes"] = duration
    clues["_raw_tags"] = tags
    cache_key = f"file::{file_path}"
    return queries, clues, cache_key

def get_search_context_cache_key(
    file_path: Path, multi_part_group_map: dict[Path, list[Path]]
) -> str:
    if (
        is_multi_part_audio_candidate(file_path)
        and file_path.parent in multi_part_group_map
    ):
        return f"group::{file_path.parent}"

    return f"file::{file_path}"

def search_item(
    index: int,
    file_path: Path,
    total: int,
    multi_part_group_map: dict,
    args,
    auth_file: str,
    auth_password: str | None,
    search_context_cache: dict,
    search_context_lock: threading.Lock,
    match_cache: dict,
    match_cache_lock: threading.Lock,
    search_cache: dict,
    search_cache_lock: threading.Lock,
    search_in_flight: dict,
    folder_audio_counts: dict | None = None,
) -> ItemResult:
    log: list[str] = []
    display_path = get_processing_display_path(file_path, multi_part_group_map)
    log.append(f"[{index}/{total}] Processing: {display_path}")

    result = ItemResult(
        index=index,
        file_path=file_path,
        display_path=display_path,
        log_lines=log,
    )

    trace_set_subject(display_path)
    try:
        existing_marker = load_marker(file_path)
        if existing_marker:
            log.append(
                f"  Marker: applied={existing_marker.get('applied')} "
                f"aggressive={existing_marker.get('aggressive')} "
                f"score={existing_marker.get('score')}"
            )
            result.was_manually_applied = bool(existing_marker.get("manually_applied"))

        skip_due_to_marker, marker_reason = should_skip_due_to_marker(
            source=file_path,
            aggressive_run=args.aggressive,
            force=args.force,
            minimum_score=args.min_score,
        )
        recovering_from_marker = False
        if skip_due_to_marker:
            _rec_alone = bool(folder_audio_counts) and folder_audio_counts.get(file_path.parent, 1) == 1
            _rec_meta_target = get_audiobookshelf_metadata_path(file_path, None, _rec_alone)
            if marker_skip_is_clean(file_path, existing_marker, _rec_alone, _rec_meta_target):
                log.append(f"  SKIP: {marker_reason}")
                log.append("")
                result.status = "skipped"
                result.skip_reason = marker_reason
                return result
            # Otherwise: re-apply the marker's stored match (fill-missing only writes
            # gaps) and ensure metadata.json / sidecar are in order — no fresh lookup.
            recovering_from_marker = True

        match_cache_key = get_search_context_cache_key(file_path, multi_part_group_map)
        with search_context_lock:
            cached_ctx = search_context_cache.get(match_cache_key)
        if cached_ctx is not None:
            queries, clues = cached_ctx
        else:
            queries, clues, _ = build_search_context(
                file_path,
                multi_part_group_map,
                use_backup_tags=args.force_original,
                reprobe=args.reprobe,
                save_probe_cache=args.backup,
            )
            with search_context_lock:
                search_context_cache.setdefault(match_cache_key, (queries, clues))
                queries, clues = search_context_cache[match_cache_key]

        local_duration_minutes = clues.get("local_duration_minutes")

        result.queries = queries
        result.clues = clues

        if recovering_from_marker:
            rec_md = metadata_from_marker(existing_marker)
            try:
                rec_score = float(existing_marker.get("score"))
            except (TypeError, ValueError):
                rec_score = 1.0
            result.status = "matched"
            result.from_marker = True
            result.metadata = rec_md
            result.score = rec_score
            result.edit_mode = rec_md.get("edit_mode", "full")
            result.duration_status = "unknown"
            _rec_asin = rec_md.get("asin") or "none"
            log.append(
                f"  RECOVER: re-applying stored match from marker "
                f"(score={rec_score:g}, asin={_rec_asin})"
            )
            return result

        skip_due_to_folder, skip_folder = matches_ignored_folders(
            file_path=file_path,
            folders=args.ignore_folder,
        )
        if skip_due_to_folder:
            reason = f"skipped: ignored folder: {skip_folder}"
            log.append(f"  SKIP: ignored folder: {skip_folder}")
            log.append("")
            result.status = "skipped"
            result.skip_reason = reason
            result.add_to_manual_review = True
            return result

        skip_due_to_pattern, skip_pattern = matches_skip_patterns(
            file_path=file_path,
            clues=clues,
            patterns=args.skip_pattern,
        )
        if skip_due_to_pattern:
            reason = f"skipped: matched skip pattern: {skip_pattern}"
            log.append(f"  SKIP: matched skip pattern: {skip_pattern}")
            log.append("")
            result.status = "skipped"
            result.skip_reason = reason
            result.add_to_manual_review = True
            return result

        if not queries:
            reason = "skipped: no useful embedded metadata to search from"
            log.append("  SKIP: no useful embedded metadata to search from")
            log.append("")
            result.status = "skipped"
            result.skip_reason = reason
            result.add_to_manual_review = True
            return result

        # Check if match is already cached (e.g. another chapter of the same group)
        effective_min_score = args.min_score
        with match_cache_lock:
            cached_match = match_cache.get(match_cache_key)

        if cached_match is not None:
            product = cached_match["product"]
            score = cached_match["score"]
            used_query = cached_match["used_query"]
            match_ambiguity = cached_match.get("ambiguity")
            log.append("  Reusing cached match for shared search context")
        else:
            product = None
            score = 0.0
            used_query = ""
            match_ambiguity = None

            # Special provider search (GraphicAudio, SoundBooth Theater via abs-agg).
            # Triggered by publisher policy, series name, composer tag, or dramatized subtitle.
            # Result competes with Audible: whichever scores higher wins.
            _abs_agg_url = getattr(args, "abs_agg_url", "")
            _detected_provider = detect_special_provider(clues)
            if _detected_provider and _abs_agg_url:
                _sp_label = SPECIAL_PROVIDERS.get(_detected_provider, _detected_provider)
                log.append(f"  Trying {_sp_label} source (abs-agg/{_detected_provider})")
                _sp_products = abs_agg_search(
                    title=clues.get("title", ""),
                    author=clues.get("author", ""),
                    provider=_detected_provider,
                    abs_agg_url=_abs_agg_url,
                    limit=args.limit,
                    existing_asin=clues.get("existing_asin", ""),
                )
                log.append(f"  {_sp_label} results: {len(_sp_products)}")
                # Collapse results that are the same book in different formats
                # (e.g. full-length vs individual parts with different ISBNs).
                # Identical (title, series, sequence) tuples all score the same
                # against a single consolidated file, so keep only the first.
                if _sp_products:
                    _seen_keys: set[tuple[str, str, str]] = set()
                    _deduped: list[dict] = []
                    for _p in _sp_products:
                        _ser, _seq = get_primary_series(_p)
                        _key = (
                            (_p.get("title") or "").lower().strip(),
                            _ser.lower().strip(),
                            str(_seq).strip(),
                        )
                        if _key not in _seen_keys:
                            _seen_keys.add(_key)
                            _deduped.append(_p)
                    if len(_deduped) < len(_sp_products):
                        log.append(f"  {_sp_label} deduplicated: {len(_sp_products)} -> {len(_deduped)}")
                    _sp_products = _deduped
                if _sp_products:
                    # Temporarily strip book_number AND series-embedded numbers so
                    # sequence-conflict hard-rejects don't eliminate valid GA/SBT
                    # results. Dedicated catalog sequences often differ from local
                    # tags (e.g. Alloy of Law is Mistborn #4 but Wax & Wayne #1).
                    # The composer+title+author check in determine_edit_mode is the
                    # real safety gate for these dedicated-catalog searches.
                    _saved_num = clues.pop("book_number", "")
                    _saved_num_src = clues.pop("book_number_source", "")
                    _saved_series = clues.get("series", "")
                    if _saved_series:
                        _clean_series = re.sub(
                            r"(?:,\s*)?(?:Book|Vol\.?|Volume|Part)\s*#?\s*\d+",
                            "",
                            _saved_series,
                            flags=re.IGNORECASE,
                        ).strip(" ,")
                        clues["series"] = _clean_series
                    try:
                        _sp_candidate, _sp_score, _sp_ambiguity = pick_best_match_for_metadata(
                            clues, _sp_products, local_duration_minutes
                        )
                    finally:
                        if _saved_num:
                            clues["book_number"] = _saved_num
                        if _saved_num_src:
                            clues["book_number_source"] = _saved_num_src
                        if _saved_series:
                            clues["series"] = _saved_series
                    if _sp_candidate:
                        _sp_debug = metadata_from_product(_sp_candidate, clues, _sp_score)
                        log.append(
                            f"  {_sp_label} candidate: score={_sp_score} "
                            f"title={_sp_debug.get('audible_title')} "
                            f"mode={_sp_debug.get('edit_mode')}"
                        )
                        # Lower threshold for dedicated catalog searches: the endpoint
                        # is already filtered to that publisher so a title+author match
                        # is highly reliable even without a duration signal.
                        _sp_threshold = 0.30
                        if _sp_score >= _sp_threshold and _sp_score > score:
                            product = _sp_candidate
                            score = _sp_score
                            used_query = f"{_detected_provider}:{clues.get('title','')}"
                            match_ambiguity = _sp_ambiguity
                            effective_min_score = min(effective_min_score, _sp_threshold)
                            queries = []  # skip Audible text search -- special provider matched
                            result.source_provider = _detected_provider

            use_abs = getattr(args, "provider", "audible") == "abs"

            if use_abs:
                # ABS provider: keyword searches only (no per-ASIN direct lookup via ABS).
                for query in queries:
                    if product and score >= args.min_score:
                        break
                    log.append(f"  Trying ABS query ({args.abs_provider}): {query}")
                    title_part, _, author_part = query.partition(" - ")
                    query_products = abs_search(
                        title=title_part.strip() or query,
                        author=author_part.strip(),
                        provider=args.abs_provider,
                        abs_url=args.abs_url,
                        abs_api_key=args.abs_api_key,
                        limit=args.limit,
                    )
                    log.append(f"  Results: {len(query_products)}")
                    if not query_products:
                        continue
                    candidate, candidate_score, candidate_ambiguity = pick_best_match_for_metadata(
                        clues, query_products, local_duration_minutes,
                    )
                    if candidate:
                        debug_metadata = metadata_from_product(candidate, clues, candidate_score)
                        log.append(
                            f"  Candidate: score={candidate_score} "
                            f"title={debug_metadata.get('audible_title')} "
                            f"mode={debug_metadata.get('edit_mode')} "
                            f"asin={debug_metadata.get('asin')}"
                        )
                        if candidate_ambiguity:
                            log.append(f"  {candidate_ambiguity['reason']}")
                        if candidate_score > score:
                            product = candidate
                            score = candidate_score
                            used_query = query
                            match_ambiguity = candidate_ambiguity
            else:
                client = get_thread_client(auth_file, auth_password)

                # ASIN-first: if the file already embeds an ASIN, attempt a direct
                # product lookup before falling back to keyword searches.
                existing_asin = clues.get("existing_asin", "")
                if existing_asin:
                    log.append(f"  Trying ASIN direct lookup: {existing_asin}")
                    asin_product = audible_lookup_by_asin(client, existing_asin)
                    if asin_product:
                        asin_candidate_score = score_product_for_metadata(
                            clues, asin_product, local_duration_minutes
                        )
                        asin_debug = metadata_from_product(asin_product, clues, asin_candidate_score)
                        log.append(
                            f"  ASIN lookup: score={asin_candidate_score} "
                            f"title={asin_debug.get('audible_title')} "
                            f"mode={asin_debug.get('edit_mode')}"
                        )
                        _asin_threshold = 0.40
                        if asin_candidate_score >= _asin_threshold and asin_candidate_score > score:
                            product = asin_product
                            score = asin_candidate_score
                            used_query = f"ASIN:{existing_asin}"
                            match_ambiguity = None
                            effective_min_score = _asin_threshold
                            result.source_provider = ""  # ASIN overrides any prior special-provider match

            for query in queries if not use_abs else []:
                if product and score >= args.min_score:
                    break
                log.append(f"  Trying query: {query}")
                cache_key = (query.lower(), args.limit)
                with search_cache_lock:
                    already_cached = cache_key in search_cache
                query_products = cached_audible_search(
                    client,
                    query,
                    args.limit,
                    args.api_delay_ms,
                    search_cache,
                    search_cache_lock,
                    search_in_flight,
                )
                suffix = " (cached)" if already_cached else ""
                log.append(f"  Results: {len(query_products)}{suffix}")

                if not query_products:
                    continue

                candidate, candidate_score, candidate_ambiguity = pick_best_match_for_metadata(
                    clues, query_products, local_duration_minutes,
                )
                if candidate:
                    debug_metadata = metadata_from_product(candidate, clues, candidate_score)
                    log.append(
                        f"  Candidate: score={candidate_score} "
                        f"title={debug_metadata.get('audible_title')} "
                        f"sequence={debug_metadata.get('audible_sequence')} "
                        f"duration={debug_metadata.get('audible_duration_minutes')} "
                        f"mode={debug_metadata.get('edit_mode')} "
                        f"asin={debug_metadata.get('asin')}"
                    )
                    if candidate_ambiguity:
                        log.append(f"  {candidate_ambiguity['reason']}")

                if not candidate:
                    continue

                if candidate_score > score:
                    product = candidate
                    score = candidate_score
                    used_query = query
                    match_ambiguity = candidate_ambiguity

                if candidate_score >= args.min_score:
                    break

            # Goodreads fallback (abs-tract): fires whenever Audible + ASIN did
            # not yield a confident *full* match. That covers three cases: no
            # match, a match below the score gate, and a match that only resolves
            # the series (series_only) without confidently identifying the book
            # (e.g. an omnibus matched in place of a missing standalone). No
            # duration/composer is available, so acceptance is gated on a strong
            # title+author match (determine_edit_mode -> "full"). The Audible
            # result is preserved unless Goodreads returns a genuinely valid full
            # match. Kindle then enriches the cover only; its ebook ASIN is never
            # used.
            abs_tract_url = getattr(args, "abs_tract_url", "")
            goodreads_fallback_enabled = bool(
                getattr(args, "enable_goodreads_fallback", False)
            )
            audible_edit_mode = (
                metadata_from_product(product, clues, score).get("edit_mode", "none")
                if product else "none"
            )
            audible_is_full = (
                bool(product) and score >= args.min_score and audible_edit_mode == "full"
            )
            if (
                goodreads_fallback_enabled
                and abs_tract_url
                and clues.get("title")
                and not audible_is_full
            ):
                if product:
                    log.append(
                        f"  Audible match not full (score={score:.4f}, "
                        f"mode={audible_edit_mode}) -> trying Goodreads (abs-tract)"
                    )
                else:
                    log.append("  No Audible match -> trying Goodreads (abs-tract)")
                gr_queries = goodreads_title_query_variants(clues.get("title", ""))
                _gr_series = clues.get("series", "")
                _gr_number = clues.get("book_number", "")
                if (
                    is_generic_series_number_title(clues)
                    and clean_sequence(_gr_number) == "1"
                    and _gr_series
                ):
                    gr_queries.extend(goodreads_title_query_variants(_gr_series))
                # When the title looks like a subtitle (different from series+N),
                # also try "Series N" directly - often better-indexed on Goodreads.
                if _gr_series and _gr_number and not is_generic_series_number_title(clues):
                    _sn_query = f"{_gr_series} {_gr_number}"
                    gr_queries.extend(goodreads_title_query_variants(_sn_query))
                gr_queries = list(dict.fromkeys(q for q in gr_queries if q))

                for gr_query in gr_queries:
                    gr_products = abs_tract_search(
                        title=gr_query,
                        author=clues.get("author", ""),
                        provider="goodreads",
                        abs_tract_url=abs_tract_url,
                        limit=args.limit,
                        existing_asin=clues.get("existing_asin", ""),
                        log=log,
                    )
                    log.append(f"  Goodreads results: {len(gr_products)}")
                    if gr_products:
                        gr_candidate, gr_score, gr_ambiguity = pick_best_match_for_metadata(
                            clues, gr_products, local_duration_minutes
                        )
                        if gr_candidate:
                            gr_md = metadata_from_product(gr_candidate, clues, gr_score)
                            log.append(
                                f"  Goodreads candidate: title={gr_md.get('audible_title')} "
                                f"mode={gr_md.get('edit_mode')}"
                            )
                            if gr_md.get("edit_mode") == "full":
                                # Enrich the cover from Kindle (high quality; ASIN
                                # ignored) only when the run is actually writing a
                                # cover. Without a cover flag the Kindle scrape is
                                # wasted work (and an extra slow abs-tract round-trip),
                                # so skip it.
                                if getattr(args, "cover_if_missing", False) or getattr(
                                    args, "replace_cover", False
                                ):
                                    k_products = abs_tract_search(
                                        title=gr_query,
                                        author=clues.get("author", ""),
                                        provider="kindle",
                                        abs_tract_url=abs_tract_url,
                                        limit=args.limit,
                                        existing_asin=clues.get("existing_asin", ""),
                                        kindle_region=getattr(args, "abs_tract_kindle_region", "us"),
                                        log=log,
                                    )
                                    k_cover = ""
                                    if k_products:
                                        k_cand, _k_score, _k_amb = pick_best_match_for_metadata(
                                            clues, k_products, local_duration_minutes
                                        )
                                        k_cover = ((k_cand or {}).get("product_images") or {}).get("500", "")
                                    if k_cover:
                                        gr_candidate = {**gr_candidate, "product_images": {"500": k_cover}}
                                        log.append("  Kindle cover enrichment applied")
                                product = gr_candidate
                                score = gr_score
                                used_query = f"goodreads:{gr_query}"
                                match_ambiguity = gr_ambiguity
                                result.source_provider = "goodreads"
                                effective_min_score = min(effective_min_score, gr_score)
                                break
                    if result.source_provider == "goodreads":
                        break

            # Store in match_cache; if another thread beat us, use its result
            with match_cache_lock:
                match_cache.setdefault(match_cache_key, {
                    "product": product,
                    "score": score,
                    "used_query": used_query,
                    "ambiguity": match_ambiguity,
                })
                stored = match_cache[match_cache_key]
                product = stored["product"]
                score = stored["score"]
                used_query = stored["used_query"]
                match_ambiguity = stored.get("ambiguity")

        result.score = score
        result.used_query = used_query

        if not product:
            log.append("  SKIP: no usable Audible match")
            log.append(f"  Tried queries: {queries}")
            log.append("")
            result.status = "skipped"
            result.skip_reason = "skipped: no usable Audible match"
            result.add_to_manual_review = True
            return result

        metadata = metadata_from_product(product, clues, score)
        metadata["file_type"] = get_file_type(file_path)

        buf = io.StringIO()
        with _print_plan_lock:
            with contextlib.redirect_stdout(buf):
                print_plan(
                    file_path, used_query, score, metadata, clues,
                    source_provider=result.source_provider,
                )
        for line in buf.getvalue().rstrip("\n").split("\n"):
            log.append(line)

        edit_mode = metadata.get("edit_mode", "none") or "none"
        duration = metadata.get("duration", {}) or {}
        duration_status = duration.get("status", "unknown") or "unknown"
        diff_percent = duration.get("diff_percent")

        result.metadata = metadata
        result.edit_mode = edit_mode
        result.duration_status = duration_status
        result.diff_percent = diff_percent

        if score < effective_min_score:
            reason = f"skipped: score below minimum: {score} < {effective_min_score}"
            log.append(f"  SKIP: score below minimum: {score} < {effective_min_score}")
            log.append("")
            result.status = "skipped"
            result.skip_reason = reason
            result.add_to_manual_review = True
            return result

        if not metadata["title"] or not metadata["author"]:
            reason = "skipped: missing title or author from Audible result"
            log.append("  SKIP: missing title or author from Audible result")
            log.append("")
            result.status = "skipped"
            result.skip_reason = reason
            result.add_to_manual_review = True
            return result

        if metadata.get("edit_mode") == "none":
            reason = "skipped: match marked unsafe / no editable metadata action"
            log.append("  SKIP: match marked unsafe / no editable metadata action")
            log.append("")
            result.status = "skipped"
            result.skip_reason = reason
            result.add_to_manual_review = True
            return result

        # Multiple candidates tied at the top score and the duration fallbacks
        # could not pick a clear winner: route to manual review rather than guess.
        if match_ambiguity and not match_ambiguity.get("resolved"):
            reason = f"skipped: {match_ambiguity['reason']}"
            log.append(f"  SKIP: {match_ambiguity['reason']}")
            log.append("")
            result.status = "skipped"
            result.skip_reason = reason
            result.add_to_manual_review = True
            return result

        result.status = "matched"

        # Pre-compute review data for the gather phase
        review_reasons = selected_match_review_reasons(
            metadata, clues, score, args.duration_review_threshold,
        )

        # A resolved tie still gets flagged so the ambiguity is visible in review.
        if match_ambiguity:
            review_reasons.append(match_ambiguity["reason"])

        # Flag if existing embedded ASIN differs from the matched product ASIN.
        existing_asin = clues.get("existing_asin", "")
        matched_asin = (metadata.get("asin") or "").upper()
        if existing_asin and matched_asin and existing_asin != matched_asin:
            review_reasons.append(
                f"existing ASIN {existing_asin} does not match matched ASIN {matched_asin}"
            )

        result.review_reasons = review_reasons

        if (
            diff_percent is not None
            and float(diff_percent) > args.duration_review_threshold
        ):
            result.duration_review_item = {
                "path": str(file_path),
                "file_type": get_file_type(file_path),
                "local_title": clues.get("title") or clues.get("raw_title") or "-",
                "audible_title": metadata.get("audible_title") or metadata.get("title") or "-",
                "mode": edit_mode,
                "score": score,
                "status": duration_status,
                "diff_percent": diff_percent,
                "local_minutes": duration.get("local_minutes"),
                "audible_minutes": duration.get("audible_minutes"),
            }

        # Emit a per-item FILL marker (fill-missing mode) so the report can list which
        # books gained fields. Computed here in the worker (Pass 1) where the log line
        # streams under the correct Processing header; the serial Pass-2 counters
        # recompute the same deterministic result, so totals stay in sync.
        if getattr(args, "write_mode", "smart") == "fill-missing" and not should_write_json_sidecar(
            file_path, clues
        ):
            _eff, fill_filled = merge_fill_missing_metadata(
                (clues or {}).get("_raw_tags") or {}, metadata
            )
            if fill_filled:
                log.append(f"  FILL: filled {', '.join(fill_filled)}")
            else:
                log.append("  FILL: complete")

        # In metadata-json-only mode with multiple workers, write metadata.json inside
        # the worker for parallel NAS I/O. Only for single-file books (no group_search):
        # each has its own collision-safe target. Multipart groups and the (suppressed)
        # in-file writes stay in the serial gather phase. metadata-json-only means there
        # is no in-file write to do, so this fully completes the book (write_done).
        is_single_file = not (clues or {}).get("group_search", {}).get("applied")
        if args.metadata_json_only and args.apply and args.workers > 1 and is_single_file:
            aggressive_edit = args.aggressive or score >= AGGRESSIVE_SCORE_THRESHOLD
            mode = "aggressive" if aggressive_edit else "normal"
            current_tags = (clues or {}).get("_raw_tags") or {}
            write_mode = getattr(args, "write_mode", "smart")
            effective_metadata, skip_write, write_note, _filled = decide_write(
                current_tags,
                metadata,
                metadata.get("edit_mode", "none") or "none",
                write_mode,
                result.source_provider,
            )
            alone = bool(folder_audio_counts) and folder_audio_counts.get(file_path.parent, 1) == 1
            meta_target = get_audiobookshelf_metadata_path(file_path, clues, alone)
            if skip_write and meta_target.exists():
                log.append(f"  {write_note} (metadata.json unchanged)")
                log.append(
                    "WRITE_ACTION_JSON: "
                    + json.dumps({
                        "path": str(file_path),
                        "write_action": "smart_skipped" if write_mode == "smart" else "no_op",
                        "write_note": write_note,
                        "write_mode": write_mode,
                        "metadata_json_pending": False,
                        "tag_write_pending": False,
                    })
                )
            else:
                abs_path = write_audiobookshelf_metadata_json(
                    file_path, effective_metadata, clues, alone,
                    fill_missing=(write_mode != "overwrite"),
                )
                suffix = f" [{write_note}]" if write_note else ""
                log.append(f"  APPLIED ({mode}, metadata_json={abs_path}){suffix}")
                log.append(
                    "WRITE_ACTION_JSON: "
                    + json.dumps({
                        "path": str(file_path),
                        "write_action": "written",
                        "write_note": write_note,
                        "write_mode": write_mode,
                        "metadata_json_pending": True,
                        "tag_write_pending": False,
                    })
                )
            write_marker(
                source=file_path,
                metadata=effective_metadata,
                clues=clues,
                score=score,
                mode=mode,
                aggressive=aggressive_edit,
                output_kind="metadata_json",
            )
            log.append("")
            result.metadata_json_done = True
            result.write_done = True

        return result

    except Exception as error:
        log.append(f"  ERROR: {error}")
        log.append("")
        result.status = "failed"
        result.error = str(error)
        return result
    finally:
        trace_set_subject(None)

@trace(ALTER, capture=[])
def final_metadata_preview(metadata: dict) -> dict:
    preview = {
        "file_type": metadata.get("file_type", ""),
        "title": metadata.get("title", ""),
        "artist": metadata.get("author", ""),
        "album_artist": metadata.get("author", ""),
        "album": metadata.get("title", ""),
        "grouping": metadata.get("series", ""),
        "mvnm": metadata.get("series", ""),
        "mvin": metadata.get("sequence", ""),
        "composer": metadata.get("narrator", ""),
        "date": metadata.get("year", ""),
        "genre": metadata.get("genre", ""),
        "publisher": metadata.get("publisher", ""),
    }

    if metadata.get("sequence"):
        preview["track"] = metadata["sequence"]

    if metadata.get("isbn"):
        preview["isbn"] = metadata["isbn"]

    return {key: value for key, value in preview.items() if value}

def ffmpeg_write_tags(source: Path, metadata: dict, backup: bool) -> None:
    tmp_path = source.with_name(f"{source.stem}.metadata-fixed{source.suffix}")

    if backup:
        backup_path = write_original_metadata_backup(source)
        print(f"  Metadata backup: {backup_path}")

    metadata_args = build_metadata_args(metadata)

    cmd = safe_ffmpeg_copy_metadata_command(
        source=source,
        tmp_path=tmp_path,
        metadata_args=metadata_args,
        clear_existing_metadata=False,
    )

    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:
        if tmp_path.exists():
            tmp_path.unlink()

        raise RuntimeError(f"ffmpeg failed for {source}\n{result.stderr.strip()}")

    tmp_path.replace(source)

def download_cover_bytes(url: str) -> tuple[bytes, str]:
    from urllib.request import Request, urlopen

    if not url:
        raise RuntimeError("No cover URL available from Audible result")

    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )

    with urlopen(request, timeout=30) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "").lower()

    if data.startswith(b"\xff\xd8\xff"):
        return data, "jpeg"

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "png"

    if "jpeg" in content_type or "jpg" in content_type:
        return data, "jpeg"

    if "png" in content_type:
        return data, "png"

    raise RuntimeError(f"Unsupported cover image format from URL: {content_type}")

def mp4_has_cover(tags) -> bool:
    return bool(tags.get("covr"))

def mp3_has_cover(tags) -> bool:
    return bool(tags.getall("APIC"))

def backup_existing_mp4_cover(source: Path, tags) -> Path | None:
    covers = tags.get("covr") or []

    if not covers:
        return None

    cover = covers[0]
    suffix = (
        ".cover-backup.png"
        if getattr(cover, "imageformat", None) == MP4Cover.FORMAT_PNG
        else ".cover-backup.jpg"
    )
    backup_path = source.with_name(f"{source.name}{suffix}")

    if not backup_path.exists():
        backup_path.write_bytes(bytes(cover))

    return backup_path

def backup_existing_mp3_cover(source: Path, tags) -> Path | None:
    covers = tags.getall("APIC")

    if not covers:
        return None

    cover = covers[0]
    suffix = (
        ".cover-backup.png" if "png" in str(cover.mime).lower() else ".cover-backup.jpg"
    )
    backup_path = source.with_name(f"{source.name}{suffix}")

    if not backup_path.exists():
        backup_path.write_bytes(bytes(cover.data))

    return backup_path

def mp4_set_cover(tags, image_bytes: bytes, image_format: str) -> None:
    if image_format == "png":
        cover = MP4Cover(image_bytes, imageformat=MP4Cover.FORMAT_PNG)
    else:
        cover = MP4Cover(image_bytes, imageformat=MP4Cover.FORMAT_JPEG)

    tags["covr"] = [cover]

def mp3_set_cover(tags, image_bytes: bytes, image_format: str) -> None:
    tags.delall("APIC")
    mime = "image/png" if image_format == "png" else "image/jpeg"

    tags.add(
        APIC(
            encoding=3,
            mime=mime,
            type=3,
            desc="Cover",
            data=image_bytes,
        )
    )

@trace(ALTER, capture=[])
def compare_tags_for_write(
    current_tags: dict,
    metadata: dict,
    edit_mode: str,
    source_provider: str = "",
) -> tuple[bool, list[str]]:
    """Compare current embedded tags to planned write values.

    Returns (all_match, list_of_changed_field_names).
    current_tags is the raw ffprobe/mutagen tag dict with lowercase keys.
    """
    def cur(keys: list[str]) -> str:
        for k in keys:
            v = str(current_tags.get(k, "") or "").strip()
            if v:
                return v
        return ""

    source_provider = (source_provider or metadata.get("_abs_provider") or "").lower()
    checks = [
        ("title",  cur(["title"]),                              metadata.get("title", "")),
        ("author", cur(["artist", "album_artist"]),             metadata.get("author", "")),
    ]
    if source_provider == "goodreads":
        # Goodreads does not reliably supply audiobook-only fields such as ASIN,
        # narrator, year, genre, or duration. Treat blank Goodreads fields as
        # "not asserted" for smart-skip, and only require series/sequence when
        # the match actually provided them.
        if str(metadata.get("series", "") or "").strip():
            checks.append(("series", cur(["grouping", "mvnm"]), metadata.get("series", "")))
        if edit_mode == "full" and str(metadata.get("sequence", "") or "").strip():
            checks.append(("sequence", cur(["track", "mvin"]), metadata.get("sequence", "")))
    else:
        checks += [
            ("series", cur(["grouping", "mvnm"]),                   metadata.get("series", "")),
            ("genre",  cur(["genre"]),                              metadata.get("genre", "")),
            ("asin",   cur(["asin"]).upper(),                       (metadata.get("asin") or "").upper()),
        ]
        if edit_mode == "full":
            checks += [
                ("sequence", cur(["track", "mvin"]),                metadata.get("sequence", "")),
                ("narrator", cur(["composer"]),                      metadata.get("narrator", "")),
                ("year",     cur(["date", "year"]),                  metadata.get("year", "")),
            ]

    changed = [
        field for field, current, planned in checks
        if normalize_for_match(current) != normalize_for_match(planned)
    ]
    return len(changed) == 0, changed

@trace(ALTER, capture=[], show_result=False)
def merge_fill_missing_metadata(current_tags: dict, metadata: dict) -> tuple[dict, list[str]]:
    """Return a copy of metadata where already-populated fields keep their current value.

    Returns (merged_metadata, list_of_fields_that_were_filled).
    Only fields with no current value (empty/missing) are taken from metadata.
    """
    field_map = {
        "title":    ["title"],
        "author":   ["artist", "album_artist"],
        "series":   ["grouping", "mvnm"],
        "sequence": ["track", "mvin"],
        "narrator": ["composer"],
        "year":     ["date", "year"],
        "asin":     ["asin"],
    }
    merged = dict(metadata)
    filled: list[str] = []
    for field, tag_keys in field_map.items():
        current_value = next(
            (str(current_tags.get(k, "") or "").strip() for k in tag_keys if current_tags.get(k)),
            "",
        )
        planned_value = str(metadata.get(field, "") or "").strip()
        if normalize_for_match(current_value):
            merged[field] = sanitize_tag(current_value)
        elif planned_value:
            filled.append(field)
    return merged, filled

@trace(CHOOSE, capture=[])
def decide_write(
    current_tags: dict,
    metadata: dict,
    edit_mode: str,
    write_mode: str,
    source_provider: str = "",
) -> tuple[dict, bool, str, list[str]]:
    """Resolve the effective metadata and whether the in-file tag write is a NO-OP.

    Shared by the worker (parallel metadata.json write) and the serial gather phase
    so the two never diverge. Returns
    ``(effective_metadata, skip_write, write_note, filled_fields)`` where
    ``skip_write`` means the in-file tags already satisfy the plan and
    ``filled_fields`` lists the gaps filled in fill-missing mode (for counters).
    """
    effective_metadata = metadata
    skip_write = False
    write_note = ""
    filled_fields: list[str] = []

    if write_mode == "smart":
        all_match, _changed = compare_tags_for_write(
            current_tags, metadata, edit_mode, source_provider
        )
        if all_match:
            skip_write = True
            write_note = "Smart-skip (tags already match)"
    elif write_mode == "fill-missing":
        effective_metadata, filled_fields = merge_fill_missing_metadata(
            current_tags, metadata
        )
        if not filled_fields:
            skip_write = True
            write_note = "NO-OP (fill-missing: all fields already present)"
        else:
            write_note = f"fill-missing: filled {', '.join(filled_fields)}"

    return effective_metadata, skip_write, write_note, filled_fields

def write_tags(
    source: Path,
    metadata: dict,
    backup: bool,
    writer: str = "auto",
    cover_if_missing: bool = False,
    replace_cover: bool = False,
) -> str:
    """Write metadata and return the writer used: mutagen or ffmpeg."""
    if writer in {"auto", "mutagen"}:
        # NAS/CIFS files may arrive read-only; ensure write bit is set so mutagen
        # can modify the file in-place (we own the file, so chmod should succeed).
        try:
            mode = source.stat().st_mode
            if not (mode & stat.S_IWRITE):
                source.chmod(mode | stat.S_IWRITE)
        except OSError:
            pass
        try:
            if is_mutagen_mp4_candidate(source):
                mutagen_write_mp4_tags(
                    source,
                    metadata,
                    backup=backup,
                    cover_if_missing=cover_if_missing,
                    replace_cover=replace_cover,
                )
                return "mutagen-mp4"

            if is_mutagen_mp3_candidate(source):
                mutagen_write_mp3_tags(
                    source,
                    metadata,
                    backup=backup,
                    cover_if_missing=cover_if_missing,
                    replace_cover=replace_cover,
                )
                return "mutagen-mp3"

            if writer == "mutagen":
                raise RuntimeError(
                    f"mutagen writer does not support this extension: {source.suffix}"
                )

        except Exception as error:
            if writer == "mutagen":
                raise

            print(f"  WARNING: mutagen writer failed, falling back to ffmpeg: {error}")

    ffmpeg_write_tags(source, metadata, backup=backup)
    return "ffmpeg"

def find_audio_files(root: Path) -> list[Path]:
    files = []

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue

        if not is_supported_audio_file(file_path):
            continue

        files.append(file_path)

    return sorted(files)

def collect_audio_files(root: Path) -> list[Path]:
    if root.is_file():
        if not is_supported_audio_file(root):
            return []

        return [root]

    return find_audio_files(root)

def _build_report_item(result: "ItemResult") -> dict:
    clues = result.clues or {}
    # For manually applied books use the stored marker data so the report
    # reflects what was actually written, not a fresh (potentially different) match.
    if result.was_manually_applied:
        stored = load_marker(result.file_path)
        meta = metadata_from_marker(stored) if stored else (result.metadata or {})
    else:
        meta = result.metadata or {}
    duration = meta.get("duration") or {}
    item: dict = {
        "path": str(result.file_path),
        "status": result.status,
        "skip_reason": result.skip_reason,
        "score": result.score,
        "mode": result.edit_mode,
        "duration_status": result.duration_status,
        "provider": result.source_provider,
        "used_query": result.used_query or "",
        "was_manually_applied": result.was_manually_applied,
        "local": {
            "title": clues.get("title") or clues.get("raw_title") or "",
            "author": clues.get("author") or "",
            "series": clues.get("series") or "",
            "sequence": str(clues.get("book_number") or ""),
            "narrator": clues.get("narrator") or "",
            "genre": clues.get("genre") or "",
            "duration_minutes": clues.get("local_duration_minutes"),
        },
    }
    if meta:
        item["match"] = {
            "title": meta.get("title") or "",
            "subtitle": meta.get("subtitle") or "",
            "author": meta.get("author") or "",
            "narrator": meta.get("narrator") or "",
            "series": meta.get("series") or "",
            "sequence": meta.get("sequence") or "",
            "year": meta.get("year") or "",
            "asin": meta.get("asin") or "",
            "isbn": meta.get("isbn") or "",
            "genre": meta.get("genre") or "",
            "cover_url": meta.get("cover_url") or "",
            "duration_minutes": meta.get("audible_duration_minutes"),
            "duration_local": duration.get("local_minutes"),
            "duration_diff_pct": duration.get("diff_percent"),
        }
    return item

def print_plan(
    file_path: Path, query: str, score: float, metadata: dict, clues: dict,
    source_provider: str = "",
) -> None:
    print("FILE:")
    print(f"  {file_path}")
    print(f"  Type: {get_file_type(file_path)}")

    print("LOCAL METADATA:")
    print(f"  Raw Title: {clues.get('raw_title') or '-'}")
    print(f"  Title:     {clues.get('title') or '-'}")
    print(f"  Author:    {clues.get('author') or '-'}")
    print(f"  Series:    {clues.get('series') or '-'}")
    number_source = clues.get("book_number_source") or "-"
    print(f"  Number:    {clues.get('book_number') or '-'} ({number_source})")
    print(f"  Narrator:  {clues.get('narrator') or '-'}")
    local_duration = clues.get("local_duration_minutes")
    print(f"  Duration:  {round(local_duration, 2) if local_duration else '-'} min")

    if clues.get("group_search", {}).get("applied"):
        group_search = clues.get("group_search", {})
        print("  Search Scope: folder")
        print(f"    Folder: {group_search.get('folder', '-')}")
        print(f"    Files:  {group_search.get('file_count', '-')}")
        formats = group_search.get("formats") or {}
        if formats:
            print(
                "    Formats: "
                + ", ".join(f"{key}={value}" for key, value in sorted(formats.items()))
            )
        validation = (group_search.get("chapter_validation") or {})
        checked_files = validation.get("checked_files") or []
        if checked_files:
            print("    Chapter metadata validation:")
            for item in checked_files:
                print(
                    "      "
                    f"{Path(item.get('file', '')).name}: "
                    f"chapters={item.get('chapter_count')} "
                    f"safe={item.get('safe_as_part')} "
                    f"reason={item.get('reason', '-')}"
                )

    if clues.get("path_override", {}).get("applied"):
        override = clues.get("path_override", {})
        embedded = clues.get("embedded_before_path_override", {})
        print("  WARNING: structured path override applied")
        print(f"    Source:  {override.get('source', '-')}")
        print(f"    Changed: {', '.join(override.get('changed', [])) or '-'}")
        print(f"    Embedded raw title: {embedded.get('raw_title') or '-'}")
        print(f"    Embedded series:    {embedded.get('series') or '-'}")
        print(
            f"    Embedded number:    {embedded.get('book_number') or '-'} ({embedded.get('book_number_source') or '-'})"
        )

    print("SEARCH:")
    print(f"  {query}")

    _match_header = {
        "goodreads": "GOODREADS MATCH:",
        "graphicaudio": "GRAPHICAUDIO MATCH:",
        "soundbooththeater": "SOUNDBOOTH THEATER MATCH:",
    }.get(source_provider, "AUDIBLE MATCH:")
    print(_match_header)
    print(f"  Score:    {score}")
    print(f"  Mode:     {metadata.get('edit_mode', '-')}")
    print(f"  ASIN:     {metadata['asin']}")

    if metadata.get("audible_title"):
        print(f"  Audible Title: {metadata['audible_title']}")

    if metadata.get("audible_sequence"):
        print(f"  Audible Sequence: {metadata['audible_sequence']}")

    if metadata.get("audible_number_candidates"):
        print(
            f"  Audible Number Candidates: {', '.join(metadata['audible_number_candidates'])}"
        )

    if metadata.get("audible_duration_minutes"):
        print(
            f"  Audible Duration: {round(metadata['audible_duration_minutes'], 2)} min"
        )

    if metadata["subtitle"]:
        print(f"  Subtitle: {metadata['subtitle']}")

    print(f"  Author:   {metadata['author'] or '-'}")
    print(f"  Narrator: {metadata['narrator'] or '-'}")
    print(f"  Series:   {metadata['series'] or '-'}")
    print(f"  Sequence: {metadata['sequence'] or '-'}")
    print(f"  Year:     {metadata['year'] or metadata.get('audible_year') or '-'}")
    print()

    duration = metadata.get("duration", {})
    if duration:
        print("DURATION CHECK:")
        print(f"  Local:   {duration.get('local_minutes') or '-'} min")
        print(f"  Audible: {duration.get('audible_minutes') or '-'} min")
        print(
            f"  Diff:    {duration.get('diff_percent') if duration.get('diff_percent') is not None else '-'}%"
        )
        print(f"  Status:  {duration.get('status') or '-'}")
        print()

    print("FINAL METADATA PREVIEW:")
    for key, value in final_metadata_preview(metadata).items():
        if key == "comment" and len(value) > 180:
            value = value[:180].rstrip() + " ..."
        print(f"  {key}: {value}")
    if should_write_json_sidecar(file_path, clues):
        if is_single_file_mp3(file_path, clues):
            print("  output: id3 tags (direct) + json sidecar -> "
                  f"{get_m4b_tool_metadata_path(file_path, clues)}")
        else:
            print(f"  output: json sidecar -> {get_m4b_tool_metadata_path(file_path, clues)}")
    print()

def print_asin_verification_report(asin_matches: list[dict]) -> None:
    print("ASIN VERIFICATION REPORT:")

    if not asin_matches:
        print("  No matched ASINs to verify.")
        print()
        return

    by_asin: dict[str, list[dict]] = {}
    for item in asin_matches:
        asin = item.get("asin") or "-"
        by_asin.setdefault(asin, []).append(item)

    duplicates = {
        asin: items for asin, items in by_asin.items() if asin != "-" and len(items) > 1
    }

    if not duplicates:
        print("  No duplicate ASIN selections found.")
        print()
        return

    print(f"  Duplicate ASIN selections found: {len(duplicates)}")
    print(
        "  Review these before applying globally; duplicates may be real duplicate files, but can also indicate a bad match."
    )
    print()

    for asin, items in sorted(duplicates.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        modes = sorted({item.get("mode", "-") for item in items})
        local_numbers = sorted({str(item.get("local_number", "-")) for item in items})
        print(
            f"  ASIN: {asin}  count={len(items)}  modes={','.join(modes)}  local_numbers={','.join(local_numbers)}"
        )
        for item in items[:10]:
            print(
                "    - "
                f"type={item.get('file_type', '-')} "
                f"mode={item.get('mode', '-')} "
                f"local={item.get('local_number', '-')}/{item.get('local_number_source', '-')} "
                f"audible_seq={item.get('audible_sequence', '-')} "
                f"title={item.get('audible_title', '-')} "
                f"file={item.get('path', '-')}"
            )
        if len(items) > 10:
            print(f"    ... {len(items) - 10} more")
        print()

def matches_ignored_folders(file_path: Path, folders: list[str]) -> tuple[bool, str]:
    """Return True when any *directory* in the path begins with an ignore token.

    Only directory components are checked (the filename is excluded), and the
    match is a case-insensitive prefix. This lets short tokens like ``.``, ``#``
    and ``@`` skip hidden/temp/system folders (e.g. ``.thumbs``, ``@eaDir``)
    without matching every file via its extension.
    """
    if not folders:
        return False, ""

    dir_components = [part.lower() for part in Path(file_path).parent.parts]
    for folder in folders:
        needle = str(folder or "").strip().lower()
        if not needle:
            continue
        if any(component.startswith(needle) for component in dir_components):
            return True, folder

    return False, ""

def matches_skip_patterns(
    file_path: Path, clues: dict, patterns: list[str]
) -> tuple[bool, str]:
    """Return True when a file should be skipped by user supplied patterns.

    Patterns are case-insensitive plain substrings checked against the full path
    and the extracted local metadata fields. This keeps the option simple and
    safe for excluding known-problem folders/series such as Casual Farming.
    Folder-prefix ignore tokens are handled separately by
    :func:`matches_ignored_folders`.
    """
    if not patterns:
        return False, ""

    haystack = " ".join(
        [
            str(file_path),
            clues.get("raw_title", ""),
            clues.get("title", ""),
            clues.get("series", ""),
            clues.get("author", ""),
            clues.get("narrator", ""),
        ]
    ).lower()

    for pattern in patterns:
        needle = str(pattern or "").strip().lower()
        if needle and needle in haystack:
            return True, pattern

    return False, ""

def append_unique_reason(reasons: list[str], reason: str) -> None:
    reason = clean_text(reason)
    if reason and reason not in reasons:
        reasons.append(reason)

def build_manual_review_item(
    file_path: Path,
    reasons: list[str] | tuple[str, ...],
    *,
    clues: dict | None = None,
    metadata: dict | None = None,
    score: float | None = None,
    mode: str = "",
    query: str = "",
    status: str = "",
) -> dict:
    """Build one compact item for the final manual-review report.

    These items are intentionally independent of whether metadata was applied.
    They capture actionable risk: skipped/failed processing, unsafe matches, and
    selected matches where Audible/local sequence evidence conflicts.
    """
    clues = clues or {}
    metadata = metadata or {}
    duration = metadata.get("duration", {}) if metadata else {}

    return {
        "path": str(file_path),
        "file_type": get_file_type(file_path),
        "reasons": list(reasons),
        "status": status or ("selected" if metadata else "review"),
        "mode": mode or metadata.get("edit_mode", ""),
        "score": round(float(score), 4) if score is not None else None,
        "query": query,
        "local_title": clues.get("title") or clues.get("raw_title") or "",
        "local_series": clues.get("series", ""),
        "local_number": clues.get("book_number", ""),
        "local_number_source": clues.get("book_number_source", ""),
        "local_duration_minutes": clues.get("local_duration_minutes"),
        "audible_title": metadata.get("audible_title", ""),
        "audible_series": metadata.get("series", ""),
        "audible_sequence": metadata.get("audible_sequence") or metadata.get("sequence", ""),
        "audible_number_candidates": metadata.get("audible_number_candidates", []),
        "asin": metadata.get("asin", ""),
        "duration": duration,
    }

def append_manual_review(
    manual_review: list[dict],
    file_path: Path,
    reasons: list[str] | tuple[str, ...],
    *,
    clues: dict | None = None,
    metadata: dict | None = None,
    score: float | None = None,
    mode: str = "",
    query: str = "",
    status: str = "",
) -> None:
    reasons = [clean_text(reason) for reason in reasons if clean_text(reason)]
    if not reasons:
        return

    path = str(file_path)
    existing = next((item for item in manual_review if item.get("path") == path), None)
    if existing:
        for reason in reasons:
            if reason not in existing.setdefault("reasons", []):
                existing["reasons"].append(reason)
        return

    manual_review.append(
        build_manual_review_item(
            file_path,
            reasons,
            clues=clues,
            metadata=metadata,
            score=score,
            mode=mode,
            query=query,
            status=status,
        )
    )

def selected_match_review_reasons(
    metadata: dict,
    clues: dict,
    score: float,
    duration_review_threshold: float,
) -> list[str]:
    """Return review reasons for a selected Audible match."""
    reasons: list[str] = []
    edit_mode = metadata.get("edit_mode", "none") or "none"
    duration = metadata.get("duration", {}) or {}

    if edit_mode == "series_only":
        append_unique_reason(
            reasons,
            "series-only match: full metadata rewrite not considered safe",
        )
    elif edit_mode == "none":
        append_unique_reason(
            reasons,
            "unsafe match: no editable metadata action",
        )

    diff_percent = duration.get("diff_percent")
    if diff_percent is not None and float(diff_percent) > duration_review_threshold:
        append_unique_reason(
            reasons,
            f"duration differs by {diff_percent}% from Audible",
        )

    local_number = str(clues.get("book_number", "") or "").strip()
    local_source = str(clues.get("book_number_source", "") or "").strip() or "-"
    audible_sequence = str(
        metadata.get("audible_sequence")
        or metadata.get("sequence")
        or ""
    ).strip()

    if sequence_values_differ(local_number, audible_sequence):
        append_unique_reason(
            reasons,
            (
                "local/Audible sequence conflict: "
                f"local {local_number} ({local_source}) vs Audible {audible_sequence}"
            ),
        )

    if score < AGGRESSIVE_SCORE_THRESHOLD:
        append_unique_reason(
            reasons,
            f"low match score: {round(float(score), 4)}",
        )

    return reasons

def print_manual_review_report(manual_review: list[dict]) -> None:
    print("MANUAL REVIEW REPORT:")

    if not manual_review:
        print("  No items require manual review.")
        print()
        return

    print(f"  Items: {len(manual_review)}")
    print()

    def sort_key(item: dict) -> tuple[str, str]:
        reasons = " | ".join(item.get("reasons") or [])
        return (reasons, item.get("path", ""))

    for item in sorted(manual_review, key=sort_key):
        print(f"  - {item.get('path', '-')}")
        for reason in item.get("reasons") or []:
            print(f"    reason: {reason}")

        if item.get("status"):
            print(f"    status: {item.get('status')}")
        if item.get("mode"):
            print(f"    mode:   {item.get('mode')}")
        if item.get("score") is not None:
            print(f"    score:  {item.get('score')}")
        if item.get("local_title"):
            print(f"    local:  {item.get('local_title')}")
        if item.get("local_number"):
            print(
                f"    local number: {item.get('local_number')} "
                f"({item.get('local_number_source') or '-'})"
            )
        if item.get("audible_title"):
            print(f"    audible: {item.get('audible_title')}")
        if item.get("audible_sequence"):
            print(f"    audible sequence: {item.get('audible_sequence')}")
        duration = item.get("duration") or {}
        if duration.get("diff_percent") is not None:
            print(
                f"    duration diff: {duration.get('diff_percent')}% "
                f"({duration.get('status') or '-'})"
            )
        print()

def print_duration_review_report(duration_review: list[dict], threshold: float) -> None:
    print(f"DURATION REVIEW REPORT (> {threshold:g}% difference):")

    if not duration_review:
        print("  No selected matches exceeded the duration review threshold.")
        print()
        return

    for item in sorted(
        duration_review, key=lambda i: float(i.get("diff_percent") or 0), reverse=True
    ):
        print(
            f"  - diff={item.get('diff_percent')}% "
            f"status={item.get('status', '-')} "
            f"mode={item.get('mode', '-')} "
            f"type={item.get('file_type', '-')} "
            f"score={item.get('score', '-')}"
        )
        print(f"    file:    {item.get('path', '-')}")
        print(f"    local:   {item.get('local_title', '-')}")
        print(f"    audible: {item.get('audible_title', '-')}")
        print(
            f"    minutes: local={item.get('local_minutes', '-')} "
            f"audible={item.get('audible_minutes', '-')}"
        )
    print()

def detect_asin_conflicts(results: list["ItemResult"]) -> None:
    """Flag matched items where the same Audible ASIN was selected for multiple
    books in the same series with disagreeing local/Audible sequence numbers.

    When a series has gaps in the Audible catalog, the fixer can match several
    local books to the same ASIN (e.g. Books 4, 5, and 6 all matching the Book 6
    listing). The item whose local sequence agrees with the Audible sequence is
    likely correct; the others are flagged so their writes are suppressed and
    they appear in the manual review report.
    """
    from collections import defaultdict

    # Group matched items by (normalised series, asin)
    series_asin_groups: dict[tuple[str, str], list[ItemResult]] = defaultdict(list)
    for result in results:
        if result.status != "matched" or not result.metadata:
            continue
        series = result.metadata.get("series", "") or ""
        asin = result.metadata.get("asin", "") or ""
        if not series or not asin:
            continue
        series_key = re.sub(r"[^a-z0-9]+", "", series.lower())
        series_asin_groups[(series_key, asin)].append(result)

    for (_, asin), group in series_asin_groups.items():
        if len(group) <= 1:
            continue
        series_name = group[0].metadata.get("series", "") or ""
        for result in group:
            local_seq = str((result.clues or {}).get("book_number", "") or "")
            audible_seq = str(
                result.metadata.get("audible_sequence", "")
                or result.metadata.get("sequence", "")
                or ""
            )

            # Also derive the book number directly from the file path. This is
            # the ground truth when applied tags have corrupted the clues — e.g.
            # Book 3's folder is "Series 03" but its applied title says "Book 2"
            # so clues.book_number was set to "2" via the title source and the
            # path override was skipped. The folder name is unambiguous.
            path_seq = normalize_book_number(
                extract_book_number_from_path(result.file_path)
            )

            # An item is the correct match only when BOTH the clues sequence
            # AND the path-derived sequence agree with the Audible sequence.
            clues_agree = bool(local_seq and audible_seq and local_seq == audible_seq)
            path_agrees = bool(path_seq and audible_seq and path_seq == audible_seq)

            # If either source has a number and it disagrees with Audible, flag.
            if clues_agree and (not path_seq or path_agrees):
                continue

            effective_local = path_seq or local_seq
            result.asin_conflict = True
            reason = (
                f"duplicate Audible ASIN {asin} in series '{series_name}': "
                f"local book {effective_local or '?'} matched to Audible sequence {audible_seq or '?'}"
            )
            if reason not in result.review_reasons:
                result.review_reasons.append(reason)

# Local (non-NAS) cache of each file's embedded ASIN, keyed by path + mtime, so the
# whole-library scan that powers the duplicate-ASIN guard is a one-time cost: after the
# first run only new/changed files are re-probed. Stored under reports/ (bind-mounted,
# fast local disk) — never written to the audiobook library folder.
DISK_ASIN_CACHE_PATH = Path(
    os.environ.get("DISK_ASIN_CACHE_PATH", "/app/reports/.disk-asin-cache.json")
)

def _load_disk_asin_cache() -> dict[str, dict]:
    try:
        data = json.loads(DISK_ASIN_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def _save_disk_asin_cache(cache: dict[str, dict]) -> None:
    try:
        DISK_ASIN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        DISK_ASIN_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass

def build_disk_asin_map(files: list[Path], workers: int) -> dict[str, set[str]]:
    """Map each ASIN already present on disk -> set of file paths that carry it.

    Resolves each file's ASIN from the cheapest source available -- the
    ``[B0XXXXXXXX]`` filename token, then the ``libraforge.json`` sidecar, and
    only then the embedded media tag -- so the cold scan of a large network
    library rarely opens a media file. Results are cached by path + mtime, so
    only new or changed files are re-resolved on later runs. Used by
    :func:`detect_global_asin_duplicates` to avoid assigning an ASIN that already
    belongs to a different book in the library.
    """
    cache = _load_disk_asin_cache()
    resolved: dict[str, str] = {}
    to_probe: list[tuple[str, float | None]] = []

    for fp in files:
        key = str(fp)
        try:
            mtime = fp.stat().st_mtime
        except OSError:
            mtime = None
        entry = cache.get(key)
        if entry is not None and mtime is not None and entry.get("mtime") == mtime:
            resolved[key] = str(entry.get("asin", "") or "")
        else:
            to_probe.append((key, mtime))

    if to_probe:
        def read_one(item: tuple[str, float | None]) -> tuple[str, float | None, str]:
            key, mtime = item
            fp = Path(key)
            # Cheap sources first (same idea as the owned-ASIN check): the
            # [B0XXXXXXXX] filename token, then the libraforge.json sidecar, so
            # most organized books resolve without opening the media file over
            # the network mount. Fall back to probing only when neither has it.
            m = re.search(r"\[(?:ASIN\.)?([Bb]0[A-Z0-9]{8})\]", fp.name, flags=re.IGNORECASE)
            if m:
                return key, mtime, m.group(1).upper()
            try:
                sidecar_asin = str((load_marker(fp).get("audible") or {}).get("asin") or "").strip().upper()
                if sidecar_asin and sidecar_asin != "NOREALASIN":
                    return key, mtime, sidecar_asin
            except Exception:
                pass
            tags, _ = probe_file(fp)
            asin = str((tags or {}).get("asin", "") or "").strip().upper()
            return key, mtime, asin

        if workers and workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                probed = list(executor.map(read_one, to_probe))
        else:
            probed = [read_one(item) for item in to_probe]

        for key, mtime, asin in probed:
            resolved[key] = asin
            cache[key] = {"mtime": mtime, "asin": asin}

    # Prune cache to the current file set so it can't grow without bound, then persist.
    pruned = {str(fp): cache[str(fp)] for fp in files if str(fp) in cache}
    _save_disk_asin_cache(pruned)

    asin_map: dict[str, set[str]] = {}
    for key, asin in resolved.items():
        if asin:
            asin_map.setdefault(asin, set()).add(key)
    return asin_map

def detect_global_asin_duplicates(
    results: list["ItemResult"], disk_asin_map: dict[str, set[str]]
) -> None:
    """Suppress writes that would put the same ASIN on more than one book.

    Extends :func:`detect_asin_conflicts` (same-series only) to also catch
    cross-series duplicates within this run AND collisions with an ASIN already
    embedded on a *different* book on disk. Conflicting items are flagged
    (``asin_conflict``) so their writes are suppressed and they surface in the
    manual review report. The book that already owns the ASIN on disk is kept;
    when no on-disk owner exists, an in-run collision has no reliable winner so
    every claimant is flagged.
    """
    from collections import defaultdict

    # This run's planned ASIN per file, ignoring items the same-series detector
    # already flagged (their writes are suppressed already).
    planned: dict[str, str] = {}
    run_by_asin: dict[str, list[ItemResult]] = defaultdict(list)
    for result in results:
        if result.status != "matched" or result.asin_conflict or not result.metadata:
            continue
        asin = str(result.metadata.get("asin", "") or "").strip().upper()
        if not asin:
            continue
        planned[str(result.file_path)] = asin
        run_by_asin[asin].append(result)

    for asin, writers in run_by_asin.items():
        disk_files = disk_asin_map.get(asin, set())
        # On-disk books that will still hold this ASIN after the run (i.e. not being
        # rewritten to a different ASIN this run). A writer re-confirming the ASIN it
        # already carries counts as a legitimate incumbent, not a duplicate.
        incumbents = {p for p in disk_files if planned.get(p, asin) == asin}
        writer_files = {str(r.file_path) for r in writers}

        if len(incumbents | writer_files) <= 1:
            continue  # only one book will hold this ASIN — fine

        if incumbents:
            # Another book already owns this ASIN: keep it, flag any writer adding the
            # ASIN to a book that does not already carry it.
            keeper = Path(sorted(incumbents)[0]).name
            for result in writers:
                if str(result.file_path) in incumbents:
                    continue  # this book already owns the ASIN on disk
                result.asin_conflict = True
                reason = (
                    f"duplicate Audible ASIN {asin}: already embedded on another book "
                    f"in the library ({keeper})"
                )
                if reason not in result.review_reasons:
                    result.review_reasons.append(reason)
        elif len(writer_files) > 1:
            # No on-disk owner; multiple books in this run matched the same ASIN with
            # no reliable winner — flag them all for manual review.
            for result in writers:
                result.asin_conflict = True
                reason = (
                    f"duplicate Audible ASIN {asin}: matched to "
                    f"{len(writer_files)} different books in this run"
                )
                if reason not in result.review_reasons:
                    result.review_reasons.append(reason)

def print_run_summary(
    found: int,
    matched: int,
    skipped: int,
    failed: int,
    mode_counts: Counter,
    duration_counts: Counter,
    file_type_counts: Counter,
    duration_review: list[dict],
    duration_review_threshold: float,
    manual_review: list[dict],
    write_mode: str = "smart",
    fill_books_filled: int = 0,
    fill_books_complete: int = 0,
    fill_field_counts: "Counter | None" = None,
    smart_skip_count: int = 0,
) -> None:
    print("Summary:")
    print(f"  Found:   {found} files")
    print(f"  Matched: {matched}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed:  {failed}")
    print()

    print("Mode breakdown:")
    for mode in ["full", "series_only", "none"]:
        print(f"  {mode + ':':<13}{mode_counts.get(mode, 0)}")

    extra_modes = sorted(set(mode_counts) - {"full", "series_only", "none"})
    for mode in extra_modes:
        print(f"  {mode + ':':<13}{mode_counts.get(mode, 0)}")
    print()

    print("Duration breakdown:")
    for status in ["perfect", "strong", "acceptable", "mismatch", "unknown"]:
        count = duration_counts.get(status, 0)
        if count or status != "unknown":
            print(f"  {status + ':':<13}{count}")
    print()

    print("File type breakdown:")
    if file_type_counts:
        for file_type, count in sorted(file_type_counts.items()):
            print(f"  {file_type + ':':<13}{count}")
    else:
        print("  none:        0")
    print()

    if write_mode == "smart" and smart_skip_count:
        print(f"  Smart-skipped:  {smart_skip_count}")
        print()

    if write_mode == "fill-missing":
        field_counts = fill_field_counts or Counter()
        print("Fill-missing breakdown:")
        print(f"  Books filled:     {fill_books_filled}")
        print(f"  Already complete: {fill_books_complete}")
        print(f"  ASIN filled:      {field_counts.get('asin', 0)}")
        print("  Fields filled (books that gained each field):")
        for field_name in ["title", "author", "series", "sequence", "narrator", "year", "asin"]:
            label = "ASIN" if field_name == "asin" else field_name
            print(f"    {label + ':':<11}{field_counts.get(field_name, 0)}")
        print()

    print_duration_review_report(duration_review, duration_review_threshold)
    print_manual_review_report(manual_review)

def main():
    parser = argparse.ArgumentParser(
        description="Fix audiobook metadata using Audible catalog metadata. Supports MP4/M4B and MP3 tag writing with mutagen."
    )

    parser.add_argument(
        "root",
        help="Audiobook root folder, example: /audiobooks",
    )

    parser.add_argument(
        "--auth-file",
        default="/auth/audible-metadata.json",
        help="Audible auth file path",
    )

    parser.add_argument(
        "--ask-password",
        action="store_true",
        help="Ask for encrypted auth file password",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write metadata tags. Default is dry-run only.",
    )

    parser.add_argument(
        "--write-mode",
        choices=["smart", "overwrite", "fill-missing"],
        default="smart",
        dest="write_mode",
        help=(
            "Controls how existing tags are handled when --apply is set. "
            "smart (default): skip the write if all planned fields already match the current tags. "
            "overwrite: always write all fields regardless of current values. "
            "fill-missing: only write fields that are currently empty; existing values are kept."
        ),
    )

    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create a per-file JSON backup of the original metadata before writing tags. Recommended on first apply.",
    )

    parser.add_argument(
        "--restore-metadata",
        action="store_true",
        help="Restore original metadata from JSON backups created by --backup, then exit. Does not contact Audible.",
    )

    parser.add_argument(
        "--writer",
        choices=["auto", "mutagen", "ffmpeg"],
        default="auto",
        help=(
            "Metadata writer backend. auto uses mutagen for MP4/M4B/MP3 files and "
            "falls back to ffmpeg for other supported containers. Use mutagen to "
            "avoid ffmpeg fallback entirely."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Audible search result limit per file",
    )

    parser.add_argument(
        "--min-score",
        type=float,
        default=0.70,
        help="Minimum match score required to apply metadata",
    )

    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Only process first N files. 0 means all files.",
    )

    parser.add_argument(
        "--aggressive",
        action="store_true",
        help="Process files that were previously non-aggressively processed. Skip files already aggressively processed.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore existing marker files and process again.",
    )

    parser.add_argument(
        "--force-original",
        action="store_true",
        help=(
            "Use the original pre-apply tags from the metadata backup JSON as the "
            "search context. Only meaningful when a backup exists from a prior "
            "--backup apply. Use when the previous match was wrong and you want "
            "to re-search from the original local metadata."
        ),
    )

    parser.add_argument(
        "--reprobe",
        action="store_true",
        help=(
            "Always probe the audio file with ffprobe, ignoring any cached backup "
            "data. Use when you suspect the backup is stale or the file has been "
            "replaced since it was last backed up."
        ),
    )

    parser.add_argument(
        "--skip-pattern",
        action="append",
        default=[],
        help=(
            "Skip files whose path or extracted metadata contains this case-insensitive "
            "text. Can be used multiple times, e.g. --skip-pattern 'Casual Farming'."
        ),
    )

    parser.add_argument(
        "--ignore-folder",
        action="append",
        default=[],
        help=(
            "Skip files inside any directory whose name begins with this "
            "case-insensitive token. Only directory names are matched (not the "
            "filename), so short tokens like '.', '#' or '@' skip hidden/system "
            "folders such as '.thumbs' or '@eaDir'. Can be repeated."
        ),
    )

    parser.add_argument(
        "--duration-review-threshold",
        type=float,
        default=10.0,
        help="Show selected matches with duration difference above this percentage in the final report.",
    )

    parser.add_argument(
        "--show-asin-report",
        action="store_true",
        help="Print duplicate ASIN verification report at the end. Hidden by default.",
    )
    parser.add_argument(
        "--asin-scan-workers",
        type=int,
        default=int(os.environ.get("ASIN_SCAN_WORKERS", "8")),
        help=(
            "Concurrent ffprobe workers for the one-time on-disk ASIN scan used by the "
            "duplicate-ASIN guard. Independent of --workers because this scan never "
            "calls Audible (no rate limit). Default 8; env ASIN_SCAN_WORKERS overrides. "
            "Each probe has its own 30s timeout, so a single stuck file only stalls its "
            "own worker, not the whole scan."
        ),
    )
    parser.add_argument(
        "--cover-if-missing",
        action="store_true",
        help="Embed Audible cover art only when the file has no existing embedded cover.",
    )

    parser.add_argument(
        "--replace-cover",
        action="store_true",
        help="Replace existing embedded cover art with Audible cover art.",
    )

    parser.add_argument(
        "--metadata-json-only",
        action="store_true",
        dest="metadata_json_only",
        help=(
            "Write ONLY the Audiobookshelf metadata.json and do not modify the audio "
            "files' embedded tags. An Audiobookshelf-compatible metadata.json is always "
            "written for matched books regardless of this flag; this flag just suppresses "
            "the in-file tag rewrite. (Loose/multi-file books still get their M4B-tool "
            "merge sidecar.)"
        ),
    )

    parser.add_argument(
        "--provider",
        choices=["audible", "abs"],
        default="audible",
        help=(
            "Metadata search backend. audible (default): queries Audible directly using the auth file. "
            "abs: queries your Audiobookshelf instance, which supports Audible and other providers "
            "without requiring an Audible auth file."
        ),
    )

    parser.add_argument(
        "--abs-provider",
        default="audible",
        dest="abs_provider",
        help=(
            "Provider to use when --provider=abs. Matches the ABS provider slug "
            "(e.g. audible, audible.uk, google, itunes, openlibrary). Default: audible."
        ),
    )

    parser.add_argument(
        "--abs-url",
        default=os.environ.get("ABS_URL", "http://audiobookshelf"),
        dest="abs_url",
        help="Base URL of the Audiobookshelf instance. Defaults to ABS_URL env var or http://audiobookshelf.",
    )

    parser.add_argument(
        "--abs-api-key",
        default=os.environ.get("ABS_API_KEY", ""),
        dest="abs_api_key",
        help="Audiobookshelf API key. Defaults to ABS_API_KEY env var.",
    )

    parser.add_argument(
        "--abs-agg-url",
        default=os.environ.get("ABS_AGG_URL", "http://abs-agg:3000"),
        dest="abs_agg_url",
        help="Base URL of the abs-agg service used for GraphicAudio/SoundBooth Theater searches.",
    )

    parser.add_argument(
        "--abs-tract-url",
        default=os.environ.get("ABS_TRACT_URL", ""),
        dest="abs_tract_url",
        help=(
            "Base URL of the abs-tract service (Goodreads/Kindle). Used only when "
            "--enable-goodreads-fallback is set, or for Kindle cover enrichment "
            "after a Goodreads match."
        ),
    )
    parser.add_argument(
        "--enable-goodreads-fallback",
        action="store_true",
        dest="enable_goodreads_fallback",
        help=(
            "Allow automatic Goodreads fallback via abs-tract when Audible does not "
            "return a confident full match. Goodreads rate-limits aggressively; use "
            "--workers 5 or lower when enabling this."
        ),
    )
    parser.add_argument(
        "--abs-tract-kindle-region",
        default=os.environ.get("ABS_TRACT_KINDLE_REGION", "us"),
        dest="abs_tract_kindle_region",
        help="Kindle store region for abs-tract cover enrichment (us, uk, de, ...).",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "Parallel search/match workers. Bottleneck is API latency. "
            "Recommended 10-20 for fast runs; raise to 50 only if not hitting rate limits. "
            "Defaults to 5 when --metadata-json-only is set, otherwise 1."
        ),
    )

    parser.add_argument(
        "--write-workers",
        type=int,
        default=None,
        dest="write_workers",
        help=(
            "Parallel write workers (Pass 2). Bottleneck is disk/NAS throughput. "
            "Defaults to the --workers value. For NAS storage 4-8 is typical; "
            "local SSD can handle more."
        ),
    )

    parser.add_argument(
        "--api-delay-ms",
        type=int,
        default=0,
        dest="api_delay_ms",
        help="Milliseconds to sleep after each Audible API call per worker.",
    )

    parser.add_argument(
        "--debug-trace",
        action="store_true",
        dest="debug_trace",
        help="Enable function-level debug tracing (output to stderr or --debug-trace-file).",
    )

    parser.add_argument(
        "--debug-trace-file",
        default=None,
        dest="debug_trace_file",
        metavar="PATH",
        help="Write debug trace output to this file instead of stderr.",
    )

    parser.add_argument(
        "--debug-trace-categories",
        default=None,
        dest="debug_trace_categories",
        metavar="CATS",
        help="Comma-separated trace categories to enable (choose,alter,score). Default: all.",
    )

    args = parser.parse_args()

    if args.debug_trace:
        cats = None
        if args.debug_trace_categories:
            cats = [c.strip() for c in args.debug_trace_categories.split(",") if c.strip()]
        from app.debug_trace import configure as trace_configure
        trace_configure(enabled=True, file_path=args.debug_trace_file, categories=cats)

    if args.workers is None:
        args.workers = 5 if args.metadata_json_only else 1
    if args.write_workers is None:
        args.write_workers = args.workers

    root = Path(args.root).resolve()

    if not root.exists():
        raise SystemExit(f"ERROR: path does not exist: {root}")

    # These three steps walk the whole library before any per-book output and can
    # take a while on network mounts (NAS/SMB/NFS). Announce each so the UI shows the
    # run is alive and reaching the library folder rather than looking stuck.
    print(f"Scanning library folder: {root}", flush=True)
    files = collect_audio_files(root)
    if not args.restore_metadata:
        print(f"Reading chapter data from {len(files)} files in the library folder...", flush=True)
        prefetch_chapter_counts(files, args.workers)
    print("Analyzing multi-part audiobooks...", flush=True)
    multi_part_group_map = build_multi_part_group_map(files)

    # Full library file list (kept before --max-files truncation) so the duplicate-ASIN
    # check can compare against every book on disk, not just this run's subset.
    full_library_files = list(files)

    # Per-folder audio-file counts (whole library, computed once from data already in
    # memory — no extra NAS stat). A folder with exactly one audio file means its single
    # book is alone there, so metadata.json can be written as folder/metadata.json.
    folder_audio_counts: Counter = Counter(fp.parent for fp in full_library_files)

    if args.max_files > 0:
        files = files[: args.max_files]
        multi_part_group_map = build_multi_part_group_map(files)

    processing_items = build_processing_items(files, multi_part_group_map)

    if args.restore_metadata:
        print(f"Found {len(processing_items)} supported files.")
        print("Mode: RESTORE METADATA")
        print()
        restore_metadata_backups(files, writer=args.writer)
        return

    if args.ask_password:
        password = getpass.getpass("Audible auth file password: ")
    else:
        password = None

    print(f"Found {len(processing_items)} supported files.")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Minimum score: {args.min_score}")
    print(f"Writer: {args.writer}")
    print(f"Search workers: {args.workers}")
    print(f"Write workers:  {args.write_workers}")
    if args.enable_goodreads_fallback:
        if args.abs_tract_url:
            print("Goodreads fallback: ENABLED via abs-tract")
            if args.workers > 5:
                print(
                    "WARNING: Goodreads fallback is rate-limited; use 5 search "
                    f"workers or fewer when enabling it (current: {args.workers})."
                )
        else:
            print("Goodreads fallback: requested but disabled because --abs-tract-url is empty")
    print()

    found = len(processing_items)
    file_type_counts: Counter = Counter(
        get_file_type(file_path) for file_path in processing_items
    )
    matched = 0
    skipped = 0
    failed = 0
    mode_counts: Counter = Counter()
    duration_counts: Counter = Counter()
    duration_review: list[dict] = []
    manual_review: list[dict] = []
    asin_matches: list[dict] = []
    # fill-missing reporting: how many books gained fields vs were already complete,
    # plus a per-field tally (ASIN included) for the run summary.
    fill_books_filled = 0
    fill_books_complete = 0
    fill_field_counts: Counter = Counter()
    smart_skip_count = 0
    search_cache: dict = {}
    search_cache_lock = threading.Lock()
    search_in_flight: dict = {}
    search_context_cache: dict = {}
    search_context_lock = threading.Lock()
    match_cache: dict = {}
    match_cache_lock = threading.Lock()
    total = len(processing_items)

    # Scatter phase submits all items; gather phase consumes futures as they
    # complete so one slow book cannot stall visible progress for later workers.
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                search_item,
                index=index,
                file_path=file_path,
                total=total,
                multi_part_group_map=multi_part_group_map,
                args=args,
                auth_file=args.auth_file,
                auth_password=password,
                search_context_cache=search_context_cache,
                search_context_lock=search_context_lock,
                match_cache=match_cache,
                match_cache_lock=match_cache_lock,
                search_cache=search_cache,
                search_cache_lock=search_cache_lock,
                search_in_flight=search_in_flight,
                folder_audio_counts=folder_audio_counts,
            )
            for index, file_path in enumerate(processing_items, start=1)
        ]

        # Pass 1: stream log output as futures complete; collect results
        all_results: list[ItemResult] = []
        completed = 0
        for future in as_completed(futures):
            result = future.result()
            completed += 1
            print(
                f"PASS 1 PROGRESS: completed {completed}/{total}",
                flush=True,
            )
            for line in result.log_lines:
                print(line, flush=True)
            print(f"REPORT_ITEM_JSON: {json.dumps(_build_report_item(result))}", flush=True)
            print("─" * 72, flush=True)
            all_results.append(result)

    all_results.sort(key=lambda result: result.index)

    # Detect same-series ASIN conflicts across all results before writing.
    # Must run outside the ThreadPoolExecutor block (workers have finished).
    detect_asin_conflicts(all_results)

    # Then guard against assigning a duplicate ASIN globally: same ASIN matched to
    # multiple books this run (cross-series), or an ASIN already embedded on a
    # different book on disk. Scans every file's embedded ASIN once (parallelised).
    needs_dup_check = any(
        result.status == "matched"
        and not result.asin_conflict
        and (result.metadata or {}).get("asin")
        for result in all_results
    )
    if needs_dup_check:
        print(
            "Checking the library for existing ASINs to prevent duplicates...",
            flush=True,
        )
        disk_asin_map = build_disk_asin_map(full_library_files, args.asin_scan_workers)
        detect_global_asin_duplicates(all_results, disk_asin_map)

    # Pass 2: concurrent writes via a per-book queue.
    # Each worker pops one book at a time; output and shared counters are
    # updated under a single lock so stdout lines are never interleaved.
    _write_q: _queue.Queue = _queue.Queue()
    for _r in all_results:
        _write_q.put(_r)

    _write_lock = threading.Lock()
    _cancel_notice_sent = threading.Event()
    _write_shared: dict = {
        "matched": 0, "skipped": 0, "failed": 0,
        "mode_counts": Counter(), "duration_counts": Counter(),
        "fill_books_filled": 0, "fill_books_complete": 0,
        "fill_field_counts": Counter(), "smart_skip_count": 0,
        "duration_review": [], "manual_review": [], "asin_matches": [],
    }

    def _write_worker() -> None:
        while True:
            try:
                result = _write_q.get_nowait()
            except _queue.Empty:
                break

            if _cancel_requested:
                if not _cancel_notice_sent.is_set() and _cancel_notice_sent.set() is None:
                    with _write_lock:
                        print(
                            f"\n[{result.index}/{total}] Cancelled - stopping cleanly after previous writes.",
                            flush=True,
                        )
                break

            # Pass 1 already printed result.log_lines in full.
            # Pass 2 emits a "Writing:" header (distinct from "Processing:" so the
            # backend can track write_current without overwriting match current)
            # plus the write-specific lines (APPLIED/PLAN/SOURCE).
            _p1_header = result.log_lines[0] if result.log_lines else ""
            out: list[str] = [_p1_header.replace("] Processing:", "] Writing:", 1)] if _p1_header else []
            w_matched = 0
            w_skipped = 0
            w_failed = 0
            w_mode_counts: Counter = Counter()
            w_duration_counts: Counter = Counter()
            w_fill_filled = 0
            w_fill_complete = 0
            w_fill_field_counts: Counter = Counter()
            w_smart_skip = 0
            w_duration_review: list = []
            w_manual_review: list = []
            w_asin_matches: list = []

            file_path = result.file_path
            clues = result.clues or {}
            metadata = result.metadata or {}
            score = result.score
            w_edit_mode = result.edit_mode
            used_query = result.used_query

            if result.status == "skipped":
                w_skipped = 1
                out.append(f"  Write-skip: {result.skip_reason}")
                out.append(
                    "WRITE_ACTION_JSON: "
                    + json.dumps({
                        "path": str(file_path),
                        "write_action": "write_skipped",
                        "write_note": result.skip_reason,
                    })
                )
                out.append("")
                if result.add_to_manual_review:
                    reason = result.skip_reason
                    query_str = (
                        " | ".join(result.queries)
                        if reason == "skipped: no usable Audible match"
                        else used_query
                    )
                    _local_mr: list = []
                    append_manual_review(
                        _local_mr, file_path, [reason],
                        clues=clues, metadata=metadata or None,
                        score=score or None, mode=w_edit_mode,
                        query=query_str, status="skipped",
                    )
                    w_manual_review.extend(_local_mr)
                    _alone = bool(folder_audio_counts) and folder_audio_counts.get(file_path.parent, 1) == 1
                    write_skip_marker(file_path, clues, alone=_alone)

            elif result.status == "failed":
                w_failed = 1
                out.append(f"  Write-error: {result.error}")
                out.append(
                    "WRITE_ACTION_JSON: "
                    + json.dumps({
                        "path": str(file_path),
                        "write_action": "write_error",
                        "write_note": result.error,
                    })
                )
                out.append("")

            else:
                # status == "matched"
                w_mode_counts[w_edit_mode] += 1
                w_duration_counts[result.duration_status] += 1

                if result.duration_review_item:
                    w_duration_review.append(result.duration_review_item)

                if result.asin_conflict and result.review_reasons:
                    out.append(f"[{result.index}/{total}] Writing: {result.display_path}")
                    for _reason in result.review_reasons:
                        if "duplicate Audible ASIN" in _reason:
                            out.append(f"  SKIP: {_reason}")
                            break
                    out.append("")

                if result.review_reasons:
                    _local_mr = []
                    append_manual_review(
                        _local_mr, file_path, result.review_reasons,
                        clues=clues, metadata=metadata, score=score,
                        mode=w_edit_mode, query=used_query,
                        status="selected" if not result.asin_conflict else "skipped",
                    )
                    w_manual_review.extend(_local_mr)

                w_asin_matches.append({
                    "asin": metadata.get("asin", ""),
                    "file_type": get_file_type(file_path),
                    "mode": metadata.get("edit_mode", ""),
                    "path": str(file_path),
                    "local_title": clues.get("title", ""),
                    "local_number": clues.get("book_number", ""),
                    "local_number_source": clues.get("book_number_source", ""),
                    "audible_title": metadata.get("audible_title", ""),
                    "audible_sequence": metadata.get("audible_sequence", ""),
                    "audible_number_candidates": metadata.get("audible_number_candidates", []),
                    "score": score,
                })

                if result.asin_conflict:
                    w_skipped += 1
                elif not result.write_done:
                    aggressive_edit = args.aggressive or score >= AGGRESSIVE_SCORE_THRESHOLD
                    _write_kind = "aggressive" if aggressive_edit else "normal"
                    w_edit_mode = metadata.get("edit_mode", "none") or "none"
                    write_mode = getattr(args, "write_mode", "smart")
                    current_tags = clues.get("_raw_tags") or {}
                    only_json = args.metadata_json_only
                    is_sidecar = should_write_json_sidecar(file_path, clues)
                    _alone = bool(folder_audio_counts) and folder_audio_counts.get(file_path.parent, 1) == 1

                    if not is_sidecar:
                        effective_metadata, skip_write, write_note, filled_fields = decide_write(
                            current_tags,
                            metadata,
                            w_edit_mode,
                            write_mode,
                            result.source_provider,
                        )
                        if write_mode == "fill-missing":
                            if not filled_fields:
                                w_fill_complete += 1
                            else:
                                w_fill_filled += 1
                                for _ff in filled_fields:
                                    w_fill_field_counts[_ff] += 1
                        elif write_mode == "smart" and skip_write:
                            w_smart_skip += 1
                    else:
                        effective_metadata, skip_write, write_note = metadata, False, ""

                    meta_target = get_audiobookshelf_metadata_path(file_path, clues, _alone)
                    metadata_json_pending = (
                        not result.metadata_json_done
                        and not (skip_write and meta_target.exists())
                    )

                    if not args.apply:
                        plan_parts = []
                        if metadata_json_pending:
                            plan_parts.append("metadata.json")
                        if not skip_write:
                            if is_sidecar:
                                plan_parts.append("json_sidecar")
                            elif not only_json:
                                plan_parts.append("tags")
                        _rec = " [recovered from marker]" if result.from_marker else ""
                        if plan_parts:
                            _sfx = f" [{write_note}]" if write_note else ""
                            out.append(f"  PLAN: would write {' + '.join(plan_parts)} ({_write_kind}){_sfx}{_rec}")
                        else:
                            out.append(f"  PLAN: {write_note or 'NO-OP (nothing to write)'}{_rec}")
                        out.append(
                            "WRITE_ACTION_JSON: "
                            + json.dumps({
                                "path": str(file_path),
                                "write_action": (
                                    "smart_skipped"
                                    if write_mode == "smart" and skip_write
                                    else "no_op" if skip_write else "would_write"
                                ),
                                "write_note": write_note,
                                "write_mode": write_mode,
                                "metadata_json_pending": metadata_json_pending,
                                "tag_write_pending": not skip_write and not only_json,
                            })
                        )
                        out.append("")
                    else:
                        applied_parts: list[str] = []
                        primary_output_kind = "tags"

                        if metadata_json_pending:
                            abs_path = write_audiobookshelf_metadata_json(
                                file_path, effective_metadata, clues, _alone,
                                fill_missing=(write_mode != "overwrite"),
                            )
                            applied_parts.append(f"metadata_json={abs_path}")
                            primary_output_kind = "metadata_json"

                        if not skip_write:
                            if (
                                not is_sidecar
                                and not args.backup
                                and "backup" not in _load_libraforge_raw(file_path, alone=_alone)[1]
                            ):
                                bp = write_original_metadata_backup(file_path, alone=_alone)
                                out.append(f"  Auto-backup: {bp}")
                            if is_sidecar:
                                if is_single_file_mp3(file_path, clues) and not only_json:
                                    writer_used = write_tags(
                                        file_path, effective_metadata,
                                        backup=args.backup, writer=args.writer,
                                        cover_if_missing=args.cover_if_missing,
                                        replace_cover=args.replace_cover,
                                    )
                                    update_backup_with_applied_metadata(file_path, effective_metadata)
                                    applied_parts.append(f"writer={writer_used}")
                                sidecar_path = write_m4b_tool_metadata_sidecar(
                                    file_path, effective_metadata, clues, score
                                )
                                applied_parts.append(f"json_sidecar={sidecar_path}")
                                primary_output_kind = "json_sidecar"
                            elif not only_json:
                                writer_used = write_tags(
                                    file_path, effective_metadata,
                                    backup=args.backup, writer=args.writer,
                                    cover_if_missing=args.cover_if_missing,
                                    replace_cover=args.replace_cover,
                                )
                                update_backup_with_applied_metadata(file_path, effective_metadata)
                                applied_parts.append(f"writer={writer_used}")
                                primary_output_kind = "tags"

                        # Record which fields are now in the file tags so future runs
                        # can trust the marker and skip re-probing. Only claim tag
                        # fields when we actually write tags (not metadata-json-only,
                        # not a multi-part sidecar without a single-file tag write).
                        _wrote_tags = (not only_json) and (
                            (not is_sidecar) or is_single_file_mp3(file_path, clues)
                        )
                        _written_fields = (
                            [f for f in FILL_FIELDS if str((effective_metadata or {}).get(f) or "").strip()]
                            if _wrote_tags else None
                        )
                        write_marker(
                            source=file_path, metadata=effective_metadata,
                            clues=clues, score=score, mode=_write_kind,
                            aggressive=aggressive_edit,
                            output_kind=primary_output_kind, alone=_alone,
                            written_fields=_written_fields,
                        )
                        _sfx = f" [{write_note}]" if write_note else ""
                        _rec = " [recovered from marker]" if result.from_marker else ""
                        if applied_parts:
                            out.append(f"  APPLIED ({_write_kind}, {', '.join(applied_parts)}){_sfx}{_rec}")
                        else:
                            out.append(f"  {write_note or 'NO-OP'}{_rec}")
                        out.append(
                            "WRITE_ACTION_JSON: "
                            + json.dumps({
                                "path": str(file_path),
                                "write_action": (
                                    "smart_skipped"
                                    if write_mode == "smart" and skip_write
                                    else "no_op" if skip_write else "written"
                                ),
                                "write_note": write_note,
                                "write_mode": write_mode,
                                "metadata_json_pending": metadata_json_pending,
                                "tag_write_pending": not skip_write and not only_json,
                            })
                        )
                        out.append("")

                # Emit SOURCE: now that the book is confirmed written (or planned).
                # Backend parse_line() catches this to add provider:{id} category.
                if result.source_provider:
                    out.append(f"  SOURCE: {result.source_provider}")

                w_matched = 1

            # Flush output and merge counters atomically.
            with _write_lock:
                for _line in out:
                    print(_line, flush=True)
                _write_shared["matched"]           += w_matched
                _write_shared["skipped"]           += w_skipped
                _write_shared["failed"]            += w_failed
                _write_shared["mode_counts"]       += w_mode_counts
                _write_shared["duration_counts"]   += w_duration_counts
                _write_shared["fill_books_filled"] += w_fill_filled
                _write_shared["fill_books_complete"] += w_fill_complete
                _write_shared["fill_field_counts"] += w_fill_field_counts
                _write_shared["smart_skip_count"]  += w_smart_skip
                _write_shared["duration_review"].extend(w_duration_review)
                _write_shared["manual_review"].extend(w_manual_review)
                _write_shared["asin_matches"].extend(w_asin_matches)

    _n_write_workers = args.write_workers or 1
    with ThreadPoolExecutor(max_workers=_n_write_workers) as _pool:
        _futs = [_pool.submit(_write_worker) for _ in range(_n_write_workers)]
        for _f in _futs:
            _f.result()

    matched           = _write_shared["matched"]
    skipped           = _write_shared["skipped"]
    failed            = _write_shared["failed"]
    mode_counts       = _write_shared["mode_counts"]
    duration_counts   = _write_shared["duration_counts"]
    fill_books_filled = _write_shared["fill_books_filled"]
    fill_books_complete = _write_shared["fill_books_complete"]
    fill_field_counts = _write_shared["fill_field_counts"]
    smart_skip_count  = _write_shared["smart_skip_count"]
    duration_review   = _write_shared["duration_review"]
    manual_review     = _write_shared["manual_review"]
    asin_matches      = _write_shared["asin_matches"]

    # Learn publishers seen this run that aren't yet in the canonical catalog, so
    # future runs recognize them (and can sanitize/flag them). Done once, serially,
    # to avoid worker write races; learned entries are editable in Settings.
    # Names that appear as an author/narrator anywhere in this run. A "publisher"
    # tag equal to one of these is a mis-tag (common on self-published books where
    # the publisher field holds the author's name), so it must not be learned.
    run_person_names: set[str] = set()
    for result in all_results:
        clues = result.clues or {}
        for field in ("author", "narrator"):
            for part in re.split(r"[,;&/]| and ", str(clues.get(field, "") or "")):
                part = part.strip()
                if part:
                    run_person_names.add(part)

    learned_candidates = sorted(
        {
            str((result.clues or {}).get("publisher", "")).strip()
            for result in all_results
            if (result.clues or {}).get("publisher")
            and not (result.clues or {}).get("publisher_verified")
        }
    )
    if learned_candidates:
        try:
            if learn_publishers(learned_candidates, exclude_names=run_person_names):
                print(f"  Learned {len(learned_candidates)} new publisher(s) for future runs.")
        except Exception as error:
            print(f"  WARNING: could not update publisher catalog: {error}")

    print_run_summary(
        found=found,
        matched=matched,
        skipped=skipped,
        failed=failed,
        mode_counts=mode_counts,
        duration_counts=duration_counts,
        file_type_counts=file_type_counts,
        duration_review=duration_review,
        duration_review_threshold=args.duration_review_threshold,
        manual_review=manual_review,
        write_mode=getattr(args, "write_mode", "smart"),
        fill_books_filled=fill_books_filled,
        fill_books_complete=fill_books_complete,
        fill_field_counts=fill_field_counts,
        smart_skip_count=smart_skip_count,
    )

    if args.show_asin_report:
        print_asin_verification_report(asin_matches)

    if not args.apply:
        print()
        print("Dry-run only. Re-run with --apply to write tags.")

if __name__ == "__main__":
    main()
