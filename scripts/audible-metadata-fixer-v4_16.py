#!/usr/bin/env python3

import argparse
import getpass
import html
import json
import re
import subprocess
import struct
import sys
import time
from datetime import datetime, timezone
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import audible

try:
    from app.title_noise_policy import is_title_noise, remove_trailing_title_noise
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.title_noise_policy import is_title_noise, remove_trailing_title_noise

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
        TALB,
        TCOM,
        TCON,
        TDRC,
        TIT1,
        TIT2,
        TPE1,
        TPE2,
        TRCK,
        TXXX,
    )
except Exception:
    ID3 = None
    ID3NoHeaderError = None
    APIC = None
    TALB = None
    TCOM = None
    TCON = None
    TDRC = None
    TIT1 = None
    TIT2 = None
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
M4B_TOOL_METADATA_SUFFIX = ".m4b-tool-metadata.json"
IGNORED_PATH_PARTS = {"#recycle", "@eadir"}
TEMP_OUTPUT_MARKERS = {".metadata-fixed", ".metadata-restored"}
MUTAGEN_MP4_EXTENSIONS = {".m4b", ".m4a", ".mp4"}
MUTAGEN_MP3_EXTENSIONS = {".mp3"}
# Formats that should be treated as a single audiobook when multiple files
# exist in the same folder. MP3/OPUS were already supported; M4A/M4B are
# included for chapter-split MP4 audiobook containers.
MULTI_PART_AUDIO_EXTENSIONS = {".mp3", ".opus", ".m4a", ".m4b"}

# Formats that can commonly contain embedded chapter metadata. When these
# appear in a multi-file folder, validate that each file is really a chapter
# part and not a complete chapterized audiobook before grouping the folder.
CHAPTER_METADATA_EXTENSIONS = {".m4a", ".m4b", ".mp4"}
MAX_CHAPTERS_PER_MULTI_PART_FILE = 1
# Some split M4A chapter files contain tiny internal chapter atoms, usually
# one wrapper chapter plus the actual chapter. Treat low-count embedded
# chapters as safe only when the filename itself looks like a chapter part.
MAX_LOW_EMBEDDED_CHAPTERS_PER_NAMED_PART_FILE = 3

# Keep the previous behavior for MP3/OPUS: write a sidecar for m4b-tool instead
# of tagging the source file directly. For M4A/M4B this is only used when the
# file is part of an accepted multi-file group.
SIDECAR_OUTPUT_AUDIO_EXTENSIONS = {".mp3", ".opus"}

AGGRESSIVE_SCORE_THRESHOLD = 0.70

RESPONSE_GROUPS = ",".join(
    [
        "contributors",
        "media",
        "product_attrs",
        "product_desc",
        "product_extended_attrs",
        "series",
    ]
)


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
    marker_paths = [get_marker_path(source), get_legacy_marker_path(source)]

    for marker_path in marker_paths:
        if not marker_path.exists():
            continue

        try:
            with marker_path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError):
            continue

    return {}


def get_metadata_backup_path(source: Path) -> Path:
    return source.with_name(f"{source.name}{METADATA_BACKUP_SUFFIX}")


def get_m4b_tool_metadata_path(source: Path, clues: dict | None = None) -> Path:
    group_search = (clues or {}).get("group_search", {}) or {}

    if group_search.get("applied"):
        folder = source.parent
        return folder / f"{folder.name}{M4B_TOOL_METADATA_SUFFIX}"

    return source.with_name(f"{source.name}{M4B_TOOL_METADATA_SUFFIX}")


def write_original_metadata_backup(source: Path) -> Path:
    """Store the original container-level metadata in a small JSON file.

    This is intentionally a metadata backup, not a media-file duplicate. The
    restore operation uses this file to clear current container metadata and
    write these tags back to the file with ffmpeg copy mode.
    """
    backup_path = get_metadata_backup_path(source)

    if backup_path.exists():
        return backup_path

    tags = read_file_tags(source)
    duration_minutes = read_file_duration_minutes(source)

    payload = {
        "schema_version": 1,
        "tool": "audible-metadata-fixer",
        "backup_type": "format_tags",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source.name,
        "source_path": str(source),
        "duration_minutes": round(duration_minutes, 4) if duration_minutes else None,
        "format_tags": tags,
    }

    with backup_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")

    return backup_path


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
    marker_path = get_marker_path(source)

    if not marker_path.exists():
        return

    try:
        marker = load_marker(source)
        if not marker:
            return

        marker["applied"] = False
        marker["restored_at"] = datetime.now(timezone.utc).isoformat()

        with marker_path.open("w", encoding="utf-8") as file:
            json.dump(marker, file, indent=2, ensure_ascii=False)
            file.write("\n")
    except OSError:
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
    backup_path = get_metadata_backup_path(source)

    if not backup_path.exists():
        raise FileNotFoundError(f"metadata backup not found: {backup_path}")

    with backup_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    tags = payload.get("format_tags", {})

    if not isinstance(tags, dict):
        raise ValueError(f"metadata backup has invalid format_tags: {backup_path}")

    return backup_path, tags


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


def mutagen_mp4_is_available() -> bool:
    return MP4 is not None and MP4FreeForm is not None and MP4Cover is not None


def mutagen_mp3_is_available() -> bool:
    return ID3 is not None and APIC is not None and TXXX is not None


def mutagen_is_available() -> bool:
    return mutagen_mp4_is_available() or mutagen_mp3_is_available()


def is_mutagen_mp4_candidate(source: Path) -> bool:
    return source.suffix.lower() in MUTAGEN_MP4_EXTENSIONS


def is_mutagen_mp3_candidate(source: Path) -> bool:
    return source.suffix.lower() in MUTAGEN_MP3_EXTENSIONS


def is_mutagen_candidate(source: Path) -> bool:
    return is_mutagen_mp4_candidate(source) or is_mutagen_mp3_candidate(source)


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


@lru_cache(maxsize=None)
def read_file_chapter_count(file_path: Path) -> int | None:
    """Return embedded chapter count using ffprobe, or None when unreadable."""
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
        return None

    if result.returncode != 0:
        print(f"  WARNING: ffprobe chapter check failed for: {file_path}")
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  WARNING: ffprobe returned invalid chapter JSON for: {file_path}")
        return None

    chapters = data.get("chapters", []) or []
    return len(chapters)


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
    """Recognize groups named with a shared identity plus `- 01`, `- 02`, etc."""
    grouped: dict[tuple[str, int], list[tuple[Path, int]]] = {}
    for file_path in file_paths:
        match = re.match(r"^(.+?)\s*[-_.]\s*(\d{2,4})$", file_path.stem)
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


def classify_multi_part_file_safety(
    file_path: Path,
    chapter_count: int | None,
    numeric_part_sequence: bool = False,
) -> tuple[bool, str]:
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
    numeric_parts = numeric_part_sequence_files(file_paths)

    for file_path in sorted(file_paths, key=natural_audio_sort_key):
        if not is_chapter_metadata_candidate(file_path):
            continue

        chapter_count = chapter_count_reader(file_path)
        safe_as_part, reason = classify_multi_part_file_safety(
            file_path=file_path,
            chapter_count=chapter_count,
            numeric_part_sequence=file_path in numeric_parts,
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


def mp4_set_text(tags: dict, key: str, value: str) -> None:
    value = sanitize_tag(value)

    if value:
        tags[key] = [value]
    else:
        tags.pop(key, None)


def mp4_set_track(tags: dict, value: str) -> None:
    value = clean_sequence(value)

    if value:
        tags["trkn"] = [(int(value), 0)]
    else:
        tags.pop("trkn", None)


def mp4_set_freeform(tags, name: str, value: str) -> None:
    key = f"----:com.apple.iTunes:{name}"
    value = sanitize_tag(value)

    if value:
        tags[key] = [MP4FreeForm(value.encode("utf-8"))]
    else:
        tags.pop(key, None)


def id3_set_text(tags, frame_id: str, frame_cls, value: str) -> None:
    value = sanitize_tag(value)
    tags.delall(frame_id)

    if value:
        tags.add(frame_cls(encoding=3, text=[value]))


def id3_set_txxx(tags, name: str, value: str) -> None:
    value = sanitize_tag(value)
    tags.delall(f"TXXX:{name}")

    if value:
        tags.add(TXXX(encoding=3, desc=name, text=[value]))


def id3_set_track(tags, value: str) -> None:
    value = clean_sequence(value)
    tags.delall("TRCK")

    if value:
        tags.add(TRCK(encoding=3, text=[value]))


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

    # Audiobookshelf reads album/title as the displayed book title.
    # Keep album equal to the book title, not the series.
    mp4_set_text(tags, "\xa9nam", title)
    mp4_set_text(tags, "\xa9alb", title)

    mp4_set_text(tags, "\xa9ART", author)
    mp4_set_text(tags, "aART", author)
    mp4_set_text(tags, "\xa9grp", series)
    mp4_set_text(tags, "\xa9wrt", narrator)
    mp4_set_text(tags, "\xa9day", year)
    mp4_set_text(tags, "\xa9gen", "Audiobook")
    mp4_set_track(tags, sequence)

    # ffprobe exposes these freeform MP4 tags as mvnm/mvin.
    mp4_set_freeform(tags, "mvnm", series)
    mp4_set_freeform(tags, "mvin", sequence)

    # Preserve existing comment/description.

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

    # Audiobookshelf reads album/title as the displayed book title.
    id3_set_text(tags, "TIT2", TIT2, title)
    id3_set_text(tags, "TALB", TALB, title)

    id3_set_text(tags, "TPE1", TPE1, author)
    id3_set_text(tags, "TPE2", TPE2, author)
    id3_set_text(tags, "TCOM", TCOM, narrator)
    id3_set_text(tags, "TDRC", TDRC, year)
    id3_set_text(tags, "TCON", TCON, "Audiobook")
    id3_set_text(tags, "TIT1", TIT1, series)
    id3_set_track(tags, sequence)

    # TXXX frames give ffprobe/other scanners multiple chances to expose series.
    id3_set_txxx(tags, "mvnm", series)
    id3_set_txxx(tags, "mvin", sequence)
    id3_set_txxx(tags, "series", series)
    id3_set_txxx(tags, "series-part", sequence)

    # Preserve existing comment/description.

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

        backup_path = get_metadata_backup_path(file_path)
        if not backup_path.exists():
            print(f"  SKIP: metadata backup not found: {backup_path}")
            print()
            skipped += 1
            continue

        try:
            restore_metadata_from_backup(file_path, writer=writer)
            print(f"  RESTORED from: {backup_path}")
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
        try:
            marker_score = float(marker.get("score"))
        except (TypeError, ValueError):
            marker_score = None

        if marker_score is not None and marker_score < minimum_score:
            return False, ""
        return True, "already processed"

    return False, ""


def write_marker(
    source: Path,
    metadata: dict,
    clues: dict,
    score: float,
    mode: str,
    aggressive: bool,
    output_kind: str = "tags",
) -> None:
    marker_path = get_marker_path(source)

    marker = {
        "schema_version": 1,
        "tool": "audible-metadata-fixer",
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "applied": True,
        "mode": mode,
        "edit_mode": metadata.get("edit_mode", mode),
        "aggressive": aggressive,
        "score": score,
        "source_file": source.name,
        "output_kind": output_kind,
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

    with marker_path.open("w", encoding="utf-8") as file:
        json.dump(marker, file, indent=2, ensure_ascii=False)
        file.write("\n")


def should_write_json_sidecar(source: Path, clues: dict | None = None) -> bool:
    suffix = source.suffix.lower()

    if suffix in SIDECAR_OUTPUT_AUDIO_EXTENSIONS:
        return True

    group_search = (clues or {}).get("group_search", {}) or {}
    return bool(group_search.get("applied") and suffix in MULTI_PART_AUDIO_EXTENSIONS)


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
            "genre": "Audiobook",
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
    sidecar_path = get_m4b_tool_metadata_path(source, clues)
    payload = build_m4b_tool_metadata_payload(source, metadata, clues, score)

    with sidecar_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")

    return sidecar_path


def refresh_multipart_sidecar_audio_profile(
    folder: Path,
    chapter_files: list[Path],
    audio_summary: dict | None = None,
) -> Path:
    sidecar_path = folder / f"{folder.name}{M4B_TOOL_METADATA_SUFFIX}"
    with sidecar_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, dict):
        raise ValueError("sidecar root must be a JSON object")

    ordered_files = sorted(chapter_files, key=natural_audio_sort_key)
    payload["audio_summary"] = audio_summary or summarize_audio_stream_properties(
        ordered_files
    )
    payload["audio_profile_updated_at"] = datetime.now(timezone.utc).isoformat()

    source_payload = payload.get("source")
    if not isinstance(source_payload, dict):
        source_payload = {}
        payload["source"] = source_payload
    source_payload["chapter_files"] = [str(file_path) for file_path in ordered_files]

    group_search = source_payload.get("group_search")
    if isinstance(group_search, dict):
        group_search["file_count"] = len(ordered_files)
        group_search["files"] = [str(file_path) for file_path in ordered_files]

    temporary_path = sidecar_path.with_name(f".{sidecar_path.name}.tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")
    temporary_path.replace(sidecar_path)
    return sidecar_path


def clean_text(value: str) -> str:
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


UNAMBIGUOUS_TECHNICAL_LABEL_RE = re.compile(
    r"\b(?:"
    r"xhe[\s._-]*aac(?:[\s._-]*llc)?|"
    r"he[\s._-]*aac(?:[\s._-]*v?[12])?|"
    r"aac[\s._-]*lc|"
    r"mpeg[\s._-]*4[\s._-]*aac|"
    r"e[\s._-]*ac[\s._-]*3|"
    r"ac[\s._-]*3|"
    r"dolby[\s._-]*digital(?:[\s._-]*plus)?"
    r")\b",
    re.IGNORECASE,
)
AMBIGUOUS_CODEC_LABEL_RE = re.compile(
    r"\b(?:aac|mp3|m4a|m4b|mp4|opus|flac|ogg(?:\s+vorbis)?|vorbis|alac|wav|wave)\b",
    re.IGNORECASE,
)
TECHNICAL_QUALIFIER_RE = re.compile(
    r"\b(?:"
    r"\d+(?:\.\d+)?\s*(?:k?hz|kbps|kbit/s|bit)|"
    r"mono|stereo|joint\s+stereo|"
    r"cbr|vbr|abr|lossless|lossy|audio|codec|encoder|encoded|llc"
    r")\b",
    re.IGNORECASE,
)
def is_technical_label_block(value: str) -> bool:
    value = clean_text(value)
    if not value:
        return False
    if not (
        UNAMBIGUOUS_TECHNICAL_LABEL_RE.search(value)
        or AMBIGUOUS_CODEC_LABEL_RE.search(value)
    ):
        return False

    remainder = UNAMBIGUOUS_TECHNICAL_LABEL_RE.sub(" ", value)
    remainder = AMBIGUOUS_CODEC_LABEL_RE.sub(" ", remainder)
    remainder = TECHNICAL_QUALIFIER_RE.sub(" ", remainder)
    remainder = re.sub(r"[\d\s.,;+|/_-]+", " ", remainder)
    return not clean_text(remainder)


def sanitize_technical_labels(value: str) -> str:
    """Remove codec/release noise without deleting ambiguous title words."""
    value = clean_text(value)
    if not value:
        return ""

    value = UNAMBIGUOUS_TECHNICAL_LABEL_RE.sub(" ", value)

    def strip_bracketed(match: re.Match) -> str:
        inner = match.group(1)
        return " " if is_technical_label_block(inner) else match.group(0)

    value = re.sub(r"[\[({]\s*([^])}]+?)\s*[\])}]", strip_bracketed, value)
    value = re.sub(r"[\[({]\s*[\])}]", " ", value)

    parts = re.split(r"(\s+[-–—|:]\s+)", value)
    while len(parts) >= 3 and is_technical_label_block(parts[-1]):
        parts = parts[:-2]
    value = "".join(parts)

    value = re.sub(r"\s+", " ", value)
    return value.strip(" -_.:,")


def sanitize_book_title(value: str) -> str:
    """Remove technical and generic marketing text from a book title."""
    value = sanitize_technical_labels(value)
    if not value:
        return ""

    value = re.sub(
        r"\s*\((?:unabridged|audiobook)\)\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    if is_title_noise(value):
        return ""

    value = remove_trailing_title_noise(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -_.:,")


def normalize_for_match(value: str) -> str:
    value = sanitize_book_title(value).lower()
    value = re.sub(r"\[[^\]]+\]", " ", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[_\-:]+", " ", value)
    value = re.sub(r"\bbook\s+\d+\b", " ", value)
    value = re.sub(r"\bvolume\s+\d+\b", " ", value)
    value = re.sub(r"\bvol\.?\s+\d+\b", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def sanitize_tag(value: str) -> str:
    return sanitize_technical_labels(value)


def extract_first_parenthetical(value: str) -> str:
    match = re.search(r"\(([^)]{2,})\)", value or "")
    if not match:
        return ""
    return clean_text(match.group(1))


def remove_parenthetical(value: str) -> str:
    value = re.sub(r"\s*\([^)]*\)\s*", " ", value or "")
    value = re.sub(r"\s+", " ", value)
    return clean_text(value)


def clean_author_value(value: str) -> str:
    """Remove series hints from author-like tags, e.g. 'Aaron Crash (American Dragons)' -> 'Aaron Crash'."""
    return remove_parenthetical(value)


def canonicalize_author_credits(values: list[str] | str) -> str:
    if isinstance(values, str):
        values = [part.strip() for part in values.split(",")]

    aliases = {
        "リュート": "Ryuto",
        "cássio ferreira": "Cassio Ferreira",
        "cassio ferreira": "Cassio Ferreira",
        "mashton x x": "Mashton XX",
        "mashton x y": "Mashton XY",
        "mashton xx": "Mashton XX",
        "mashton xy": "Mashton XY",
    }
    people = []
    seen = set()
    order_keys = set()
    for value in values:
        value = clean_text(value)
        if not value or re.search(r"\s+-\s+editor\s*$", value, flags=re.IGNORECASE):
            continue
        canonical = aliases.get(value.casefold(), value)
        key = normalize_for_match(canonical)
        if key and key not in seen:
            people.append(canonical)
            seen.add(key)
            order_keys.add(re.sub(r"[^a-z0-9]+", " ", canonical.casefold()).strip())

    preferred_order = {
        frozenset({"j m clarke", "c j thompson"}): ["J.M. Clarke", "C.J. Thompson"],
        frozenset({"mashton xx", "mashton xy"}): ["Mashton XX", "Mashton XY"],
    }
    order = preferred_order.get(frozenset(order_keys))
    if order:
        return ", ".join(order)
    return ", ".join(people)


def looks_like_person_name(value: str) -> bool:
    value = clean_text(value)
    if not value:
        return False

    if re.search(
        r"[\[\]{}]|(?:19|20)\d{2}|"
        r"\b(?:book|vol(?:ume)?|unabridged|complete series|box ?set)\b",
        value,
        flags=re.IGNORECASE,
    ):
        return False

    tokens = [token for token in re.split(r"\s+", value) if token]
    if not 2 <= len(tokens) <= 5:
        return False

    cleaned_tokens = [
        re.sub(r"[^A-Za-z.'’-]", "", token)
        for token in tokens
    ]
    if not all(cleaned_tokens):
        return False

    return True


def should_prefer_path_author(current_author: str, candidate_author: str) -> bool:
    current_author = clean_author_value(current_author)
    candidate_author = clean_author_value(candidate_author)

    if not candidate_author:
        return False

    if not current_author:
        return True

    return looks_like_person_name(candidate_author) and not looks_like_person_name(current_author)


def extract_series_from_trailing_segment(value: str) -> str:
    value = sanitize_technical_labels(value)
    if not value:
        return ""

    value = re.sub(r"\bunabridged\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\bbook\s*#?\s*\d+(?:\.\d+)?\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\bvol(?:ume)?\.?\s*\d+(?:\.\d+)?\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\bv\.?\s*\d+(?:\.\d+)?\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[_\-:,]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return clean_series_value(value)


def clean_series_value(value: str) -> str:
    """Prefer the series-looking value inside parentheses when metadata is polluted.

    Example:
      'Aaron Crash (American Dragons)' -> 'American Dragons'
    """
    value = sanitize_technical_labels(value)
    if normalize_for_match(value) in {
        "audiobook",
        "complete",
        "retail",
        "unabridged",
    }:
        return ""

    parenthetical = extract_first_parenthetical(value)

    if parenthetical and not re.search(r"#|\d+\s*-\s*\d+", parenthetical):
        value = parenthetical

    if normalize_for_match(value) in {
        "audiobook",
        "complete",
        "retail",
        "unabridged",
    }:
        return ""

    return value


def read_file_tags(file_path: Path) -> dict:
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
        return {}

    if result.returncode != 0:
        print(f"  WARNING: ffprobe failed for: {file_path}")
        return {}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  WARNING: ffprobe returned invalid JSON for: {file_path}")
        return {}

    tags = data.get("format", {}).get("tags", {}) or {}

    return {
        str(key).lower(): str(value).strip()
        for key, value in tags.items()
        if str(value).strip()
    }


def read_file_duration_minutes(file_path: Path) -> float | None:
    """Return the local media duration in minutes using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
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
        print(f"  WARNING: ffprobe duration timed out for: {file_path}")
        return None

    if result.returncode != 0:
        return None

    try:
        seconds = float(result.stdout.strip())
    except ValueError:
        return None

    if seconds <= 0:
        return None

    return seconds / 60


def get_audible_duration_minutes(product: dict) -> float | None:
    """Return Audible runtime in minutes when available."""
    value = product.get("runtime_length_min")

    if value is None:
        return None

    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return None

    if minutes <= 0:
        return None

    return minutes


def compare_duration(
    local_minutes: float | None, audible_minutes: float | None
) -> dict:
    """Compare local and Audible durations.

    status values:
      perfect     <= 3%
      strong      <= 10%
      acceptable  <= 20%
      mismatch    > 20%
      unknown      one side is missing
    """
    if local_minutes is None or audible_minutes is None:
        return {
            "available": False,
            "local_minutes": (
                round(local_minutes, 2) if local_minutes is not None else None
            ),
            "audible_minutes": (
                round(audible_minutes, 2) if audible_minutes is not None else None
            ),
            "diff_minutes": None,
            "diff_percent": None,
            "status": "unknown",
        }

    diff_minutes = abs(local_minutes - audible_minutes)
    larger = max(local_minutes, audible_minutes)
    diff_percent = diff_minutes / larger if larger else 1.0

    if diff_percent <= 0.03:
        status = "perfect"
    elif diff_percent <= 0.10:
        status = "strong"
    elif diff_percent <= 0.20:
        status = "acceptable"
    else:
        status = "mismatch"

    return {
        "available": True,
        "local_minutes": round(local_minutes, 2),
        "audible_minutes": round(audible_minutes, 2),
        "diff_minutes": round(diff_minutes, 2),
        "diff_percent": round(diff_percent * 100, 2),
        "status": status,
    }


def first_existing_tag(tags: dict, keys: list[str]) -> str:
    for key in keys:
        value = tags.get(key.lower(), "").strip()

        if value:
            return value

    return ""


def roman_to_int(value: str) -> str:
    roman_map = {
        "I": 1,
        "II": 2,
        "III": 3,
        "IV": 4,
        "V": 5,
        "VI": 6,
        "VII": 7,
        "VIII": 8,
        "IX": 9,
        "X": 10,
        "XI": 11,
        "XII": 12,
        "XIII": 13,
        "XIV": 14,
        "XV": 15,
        "XVI": 16,
        "XVII": 17,
        "XVIII": 18,
        "XIX": 19,
        "XX": 20,
    }

    value = value.strip().upper()

    if value in roman_map:
        return str(roman_map[value])

    return ""


def normalize_book_number(value: str) -> str:
    value = str(value or "").strip()

    if not value:
        return ""

    try:
        if "." in value:
            left, right = value.split(".", 1)
            return f"{int(left)}.{right.rstrip('0') or '0'}"
        return str(int(value))
    except ValueError:
        return value


def extract_book_number_from_text(value: str) -> str:
    """Extract a strong book number from title/path text.

    Handles values like:
      All the Skills - Book 003
      Series - Book 003.5 - Side Story
      Aaron Crash - American Dragons, Book 8

    Avoids plural/range patterns like:
      Books 1-3
      #1-8
    """
    value = clean_text(value)

    if not value:
        return ""

    # Avoid collection/range hints.
    if re.search(
        r"\bbooks\s+\d+(?:\.\d+)?\s*(?:-|to|through|&)\s*\d+",
        value,
        flags=re.IGNORECASE,
    ):
        return ""

    patterns = [
        r"\bbook\s*#?\s*(\d+(?:\.\d+)?)\b",
        r",\s*book\s*(\d+(?:\.\d+)?)\b",
        r"\bvol(?:ume)?\.?\s*(\d+(?:\.\d+)?)\b",
        r"\bv\.?\s*(\d+(?:\.\d+)?)\b",
        r"#\s*(\d+(?:\.\d+)?)(?!\s*[-–—])\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return normalize_book_number(match.group(1))

    return ""


def extract_folder_book_number(value: str) -> str:
    number = extract_book_number_from_text(value)
    if number:
        return number

    value = clean_text(value)
    if not value:
        return ""

    leading = re.match(
        r"^\s*(\d{1,4}(?:\.\d+)?)(?!\s*%)\s*[-_.:]+\s*\S",
        value,
    )
    if leading and not re.fullmatch(r"(?:19|20)\d{2}", leading.group(1)):
        return normalize_book_number(leading.group(1))

    match = re.search(r"(?:^|[\s_-])(\d{1,3}(?:\.\d+)?)$", value)
    if not match:
        return ""

    candidate = match.group(1)
    if re.fullmatch(r"(?:19|20)\d{2}", candidate):
        return ""

    return normalize_book_number(candidate)


def extract_book_number_from_path(file_path: Path) -> str:
    """Extract a strong book number from nearby file/folder names."""
    candidates = [
        file_path.stem,
        file_path.parent.name,
        file_path.parent.parent.name if file_path.parent.parent else "",
    ]

    for index, candidate in enumerate(candidates):
        candidate = sanitize_technical_labels(candidate)
        number = extract_book_number_from_text(candidate)
        if number:
            return number
        number = extract_title_identity_number(candidate)
        if number:
            return number
        if index > 0:
            number = extract_folder_book_number(candidate)
            if number:
                return number

    return ""


def parse_structured_book_text(value: str, known_author: str = "") -> dict:
    """Parse structured file/folder names into series, number, and title.

    This is intentionally strict. It only trusts path names that look like:
      Series Name - Book 002 - Actual Title
      Series Name, Book 2 - Actual Title

    The goal is to let a manually corrected folder/file path override stale
    embedded tags, without guessing from loose text.
    """
    value = sanitize_technical_labels(value)

    if not value:
        return {}

    # A sequence-only folder does not identify the series. Preserve the
    # embedded series, and use the folder suffix only when it is a distinct
    # book title.
    sequence_folder = re.match(
        r"^(?:Book|Volume|Vol\.?)\s*(?P<number>\d{1,4}(?:\.\d+)?)"
        r"\s*-\s*(?P<title>.+)$",
        value,
        flags=re.IGNORECASE,
    )
    if sequence_folder:
        return {
            "raw_title": value,
            "series": "",
            "book_number": normalize_book_number(sequence_folder.group("number")),
            "title": sanitize_book_title(sequence_folder.group("title")),
        }

    # Omnibus paths need their embedded metadata. Do not reduce either
    # "Books 1-2" or "Series - Book 001, 002 - Titles" to a single book.
    if re.search(
        r"\b(?:Books?|Volumes?|Vols?\.?)\s*\d+(?:\.\d+)?"
        r"\s*(?:[-,&+]|\band\b)\s*\d+",
        value,
        flags=re.IGNORECASE,
    ):
        return {}

    three_part = re.match(
        r"^(?P<first>.+?)\s*-\s*(?P<series>.+?),\s*Book\s*"
        r"(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<last>.+)$",
        value,
        flags=re.IGNORECASE,
    )
    if three_part:
        first = clean_text(three_part.group("first"))
        last = clean_text(three_part.group("last"))
        known_author_norm = normalize_for_match(clean_author_value(known_author))
        first_norm = normalize_for_match(clean_author_value(first))
        last_norm = normalize_for_match(clean_author_value(last))
        last_looks_like_title = bool(
            re.search(
                r"\b(?:a|an|the|in|of|to|for|with|and)\b",
                last,
                flags=re.IGNORECASE,
            )
        )

        if known_author_norm and last_norm == known_author_norm and not last_looks_like_title:
            title, author = first, clean_author_value(last)
        elif known_author_norm and first_norm == known_author_norm:
            title, author = last, clean_author_value(first)
        elif looks_like_person_name(first) and not looks_like_person_name(last):
            title, author = last, clean_author_value(first)
        elif last_looks_like_title:
            title, author = last, clean_author_value(first)
        else:
            title, author = first, clean_author_value(last)

        return {
            "raw_title": value,
            "series": clean_series_value(three_part.group("series").strip()),
            "book_number": normalize_book_number(three_part.group("number")),
            "title": sanitize_book_title(title),
            "author": author,
        }

    title_series_author = re.match(
        r"^(?P<title>.+?)\s*-\s*(?P<series>.+?),\s*Book\s*"
        r"(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<author>.+)$",
        value,
        flags=re.IGNORECASE,
    )
    if title_series_author and looks_like_person_name(title_series_author.group("author")):
        return {
            "raw_title": value,
            "series": clean_series_value(title_series_author.group("series").strip()),
            "book_number": normalize_book_number(title_series_author.group("number")),
            "title": sanitize_book_title(title_series_author.group("title")),
        }

    series_number_title = re.match(
        r"^(?P<series>.+?)\s+(?P<number>\d{1,3}(?:\.\d+)?)\s*-\s*(?P<title>.+)$",
        value,
        flags=re.IGNORECASE,
    )
    trailing_title_norm = (
        normalize_for_match(series_number_title.group("title"))
        if series_number_title
        else ""
    )
    known_author_norm = normalize_for_match(clean_author_value(known_author))
    if (
        series_number_title
        and series_number_title.group("series").strip().lower()
        not in {"book", "books", "volume", "volumes", "vol", "vols", "side story"}
        and not (
            trailing_title_norm
            and known_author_norm
            and (
                trailing_title_norm in known_author_norm
                or known_author_norm in trailing_title_norm
            )
        )
    ):
        return {
            "raw_title": value,
            "series": clean_series_value(series_number_title.group("series").strip()),
            "book_number": normalize_book_number(series_number_title.group("number")),
            "title": sanitize_book_title(series_number_title.group("title")),
        }

    year_title = re.match(
        r"^(?:19|20)\d{2}\s*-\s*(?P<title>.+?)"
        r"(?:\s*\((?P<number>\d{1,3}(?:\.\d+)?)\))?$",
        value,
        flags=re.IGNORECASE,
    )
    if year_title:
        return {
            "raw_title": value,
            "series": "",
            "book_number": normalize_book_number(year_title.group("number") or ""),
            "title": sanitize_book_title(year_title.group("title")),
        }

    patterns = [
        r"^(?P<series>.+?)\s*-\s*Book\s*(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<title>.+)$",
        r"^(?P<series>.+?)\s*,\s*Book\s*(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<title>.+)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, value, flags=re.IGNORECASE)
        if match:
            matched_title = sanitize_book_title(match.group("title"))
            if (
                known_author_norm
                and normalize_for_match(clean_author_value(matched_title))
                in known_author_norm
            ):
                matched_title = sanitize_book_title(match.group("series"))
            return {
                "raw_title": value,
                "series": clean_series_value(match.group("series").strip()),
                "book_number": normalize_book_number(match.group("number")),
                "title": matched_title,
            }

    return {}


def parse_descriptive_book_text(value: str, known_author: str = "") -> dict:
    """Parse common author/title path names, using known author tags to orient them."""
    value = sanitize_technical_labels(value)

    if not value:
        return {}

    # Structured series/sequence names have already been handled by the stricter
    # parser and must not be reinterpreted as loose "title - author" names.
    if parse_structured_book_text(value, known_author=known_author):
        return {}

    identity_rich = parse_identity_rich_book_text(value)
    if identity_rich:
        return identity_rich

    segments = [clean_text(segment) for segment in value.split(" - ") if clean_text(segment)]
    if len(segments) >= 3:
        candidate_title = clean_text(segments[0])
        candidate_author = clean_author_value(segments[1])
        trailing = clean_text(" - ".join(segments[2:]))
        trailing_series = extract_series_from_trailing_segment(trailing)

        if (
            looks_like_person_name(candidate_author)
            and (extract_book_number_from_text(trailing) or trailing_series)
        ):
            return {
                "raw_title": value,
                "title": candidate_title,
                "author": candidate_author,
                "narrator": "",
                "year": "",
                "series": trailing_series,
                "book_number": extract_book_number_from_text(candidate_title) or extract_folder_book_number(trailing),
            }

    year_match = re.match(
        r"^(?P<author>.+?)\s*\((?P<year>\d{4})\)\s*(?P<title>.+?)"
        r"(?:\s*\((?P<narrator>[^)]{2,})\))?$",
        value,
        flags=re.IGNORECASE,
    )
    if year_match:
        title = clean_text(year_match.group("title"))
        author = clean_author_value(year_match.group("author"))
        narrator = clean_text(year_match.group("narrator") or "")
        if not looks_like_person_name(author) or is_generic_chapter_title(title):
            return {}
        if narrator.lower() == "unabridged":
            narrator = ""
        return {
            "raw_title": value,
            "title": title,
            "author": author,
            "narrator": narrator,
            "year": clean_text(year_match.group("year")),
            "series": "",
            "book_number": extract_book_number_from_text(title),
        }

    if len(segments) != 2:
        return {}

    left, right = segments
    known_norm = normalize_for_match(clean_author_value(known_author))
    left_norm = normalize_for_match(clean_author_value(left))
    right_norm = normalize_for_match(clean_author_value(right))

    left_author_score = SequenceMatcher(None, known_norm, left_norm).ratio() if known_norm else 0.0
    right_author_score = SequenceMatcher(None, known_norm, right_norm).ratio() if known_norm else 0.0

    if right_author_score >= 0.75 and right_author_score > left_author_score:
        title, author = left, clean_author_value(right)
    elif left_author_score >= 0.75 and left_author_score > right_author_score:
        title, author = right, clean_author_value(left)
    elif known_norm and looks_like_person_name(known_author):
        return {}
    elif (
        looks_like_person_name(right)
        and not looks_like_person_name(left)
        and not is_generic_chapter_title(left)
    ):
        title, author = left, clean_author_value(right)
    elif (
        looks_like_person_name(left)
        and not looks_like_person_name(right)
        and not is_generic_chapter_title(right)
    ):
        title, author = right, clean_author_value(left)
    else:
        return {}

    return {
        "raw_title": value,
        "title": clean_text(title),
        "author": author,
        "narrator": "",
        "year": "",
        "series": "",
        "book_number": extract_book_number_from_text(title),
    }


def parse_series_sequence_segment(
    value: str,
    *,
    require_label: bool = True,
) -> tuple[str, str]:
    label = r"(?:Books?|Volumes?|Vols?\.?)"
    pattern = (
        rf"^(?P<series>.+?)\s*,?\s*{label}\s*"
        rf"(?P<number>\d{{1,4}}(?:\.\d+)?)$"
    )
    match = re.match(pattern, value, flags=re.IGNORECASE)
    if not match and not require_label:
        match = re.match(
            r"^(?P<series>.+?)\s+(?P<number>\d{1,4}(?:\.\d+)?)$",
            value,
            flags=re.IGNORECASE,
        )
    if not match:
        return "", ""

    series = clean_series_value(match.group("series"))
    number = normalize_book_number(match.group("number"))
    if not series or not number:
        return "", ""
    return series, number


def parse_identity_rich_book_text(value: str) -> dict:
    """Parse explicit folder names containing distinct title, author, and series."""
    value = sanitize_technical_labels(value)
    if not value:
        return {}

    def plausible_author_credit(candidate: str) -> bool:
        candidate = clean_author_value(candidate)
        if looks_like_person_name(candidate):
            return True
        return bool(
            re.fullmatch(r"[A-Za-z][A-Za-z.'’-]{1,30}", candidate)
            and candidate.lower()
            not in {"book", "volume", "unknown", "audiobooks", "library"}
        )

    def looks_like_title_phrase(candidate: str) -> bool:
        return bool(
            re.search(
                r"\b(?:a|an|the|in|of|to|for|with|and|as|into|from|by)\b",
                candidate,
                flags=re.IGNORECASE,
            )
        )

    def has_strong_author_marker(candidate: str) -> bool:
        candidate = clean_author_value(candidate)
        return bool(
            re.search(r"(?:^|\s)(?:[A-Z]\.){1,4}(?:\s|$)", candidate)
            or re.search(r"\b[A-Z]\.[A-Z]\.", candidate)
        )

    segments = [
        clean_text(segment)
        for segment in re.split(r"\s+-\s+", value)
        if clean_text(segment)
    ]
    if len(segments) == 3:
        first, middle, last = segments
        first_is_author = looks_like_person_name(first)
        last_is_author = looks_like_person_name(last)
        first_author_credit = plausible_author_credit(first)
        last_author_credit = plausible_author_credit(last)
        labeled_middle_series, labeled_middle_number = parse_series_sequence_segment(
            middle
        )
        loose_middle_series, loose_middle_number = parse_series_sequence_segment(
            middle,
            require_label=False,
        )

        # Author - Series Book N - Title
        if first_author_credit and (
            not last_is_author
            or looks_like_title_phrase(last)
            or (loose_middle_series and not labeled_middle_series)
        ):
            series, number = loose_middle_series, loose_middle_number
            if series and number and not is_generic_chapter_title(last):
                return {
                    "raw_title": value,
                    "title": sanitize_book_title(last),
                    "author": clean_author_value(first),
                    "narrator": "",
                    "year": "",
                    "series": series,
                    "book_number": number,
                }

        # Title - Series Book N - Author
        if last_author_credit and (
            not first_is_author or looks_like_title_phrase(first)
        ):
            series, number = labeled_middle_series, labeled_middle_number
            if series and number and not is_generic_chapter_title(first):
                return {
                    "raw_title": value,
                    "title": sanitize_book_title(first),
                    "author": clean_author_value(last),
                    "narrator": "",
                    "year": "",
                    "series": series,
                    "book_number": number,
                }

            # Series Book N - Title - Author
            series, number = parse_series_sequence_segment(first)
            if series and number and not is_generic_chapter_title(middle):
                return {
                    "raw_title": value,
                    "title": sanitize_book_title(middle),
                    "author": clean_author_value(last),
                    "narrator": "",
                    "year": "",
                    "series": series,
                    "book_number": number,
                }

    # Author - Title (Series Book N)
    parenthetical = re.match(
        r"^(?P<author>.+?)\s+-\s*(?P<title>.+?)\s*"
        r"\((?P<series>.+?)\s*,?\s*(?:Books?|Volumes?|Vols?\.?)\s*"
        r"(?P<number>\d{1,4}(?:\.\d+)?)\)$",
        value,
        flags=re.IGNORECASE,
    )
    if parenthetical and looks_like_person_name(parenthetical.group("author")):
        return {
            "raw_title": value,
            "title": sanitize_book_title(parenthetical.group("title")),
            "author": clean_author_value(parenthetical.group("author")),
            "narrator": "",
            "year": "",
            "series": clean_series_value(parenthetical.group("series")),
            "book_number": normalize_book_number(parenthetical.group("number")),
        }

    # Series/title, Book N - Author
    trailing_author = re.match(
        r"^(?P<series>.+?)\s*,\s*(?:Books?|Volumes?|Vols?\.?)\s*"
        r"(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<author>.+)$",
        value,
        flags=re.IGNORECASE,
    )
    if trailing_author and plausible_author_credit(trailing_author.group("author")):
        series = clean_series_value(trailing_author.group("series"))
        return {
            "raw_title": value,
            "title": sanitize_book_title(series),
            "author": clean_author_value(trailing_author.group("author")),
            "narrator": "",
            "year": "",
            "series": series,
            "book_number": normalize_book_number(trailing_author.group("number")),
        }

    # Series/title N - Author, used by folders such as
    # "Rune Seeker 5 - J.M. Clarke".
    trailing_author_number = re.match(
        r"^(?P<series>.+?)\s+(?P<number>\d{1,4}(?:\.\d+)?)"
        r"\s*-\s*(?P<author>.+)$",
        value,
        flags=re.IGNORECASE,
    )
    if (
        trailing_author_number
        and plausible_author_credit(trailing_author_number.group("author"))
        and has_strong_author_marker(trailing_author_number.group("author"))
        and not looks_like_title_phrase(trailing_author_number.group("author"))
        and normalize_for_match(trailing_author_number.group("series"))
        not in {"book", "books", "volume", "volumes", "vol", "vols"}
    ):
        series = clean_series_value(trailing_author_number.group("series"))
        return {
            "raw_title": value,
            "title": sanitize_book_title(series),
            "author": clean_author_value(trailing_author_number.group("author")),
            "narrator": "",
            "year": "",
            "series": series,
            "book_number": normalize_book_number(
                trailing_author_number.group("number")
            ),
        }

    # Title, Author - Series N. The comma provides the otherwise missing
    # title/author boundary.
    title_author_series = re.match(
        r"^(?P<title>[^,]+),\s*(?P<author>.+?)\s*-\s*"
        r"(?P<series>.+?)\s+(?P<number>\d{1,4}(?:\.\d+)?)$",
        value,
        flags=re.IGNORECASE,
    )
    if (
        title_author_series
        and plausible_author_credit(title_author_series.group("author"))
    ):
        return {
            "raw_title": value,
            "title": sanitize_book_title(title_author_series.group("title")),
            "author": clean_author_value(title_author_series.group("author")),
            "narrator": "",
            "year": "",
            "series": clean_series_value(title_author_series.group("series")),
            "book_number": normalize_book_number(
                title_author_series.group("number")
            ),
        }

    return {}


def parse_structured_book_from_path(file_path: Path, known_author: str = "") -> dict:
    """Return structured metadata from the corrected folder/file path if available."""
    candidates = [
        file_path.parent.name,
        file_path.stem,
    ]

    for candidate in candidates:
        parsed = parse_structured_book_text(candidate, known_author=known_author)
        if parsed:
            parsed["source"] = candidate
            return parsed

    return {}


def parse_descriptive_book_from_path(file_path: Path, known_author: str = "") -> dict:
    candidates = [
        file_path.parent.name,
        file_path.stem,
        file_path.parent.parent.name if file_path.parent.parent else "",
    ]

    for candidate in candidates:
        parsed = parse_descriptive_book_text(candidate, known_author=known_author)
        if parsed:
            parsed["source"] = candidate
            return parsed

    return {}


def apply_structured_path_override(clues: dict, file_path: Path) -> dict:
    """Prefer a clearly structured path over stale embedded tags.

    This is a narrow fix for manually corrected libraries where the folder/file
    name is now accurate, but the embedded M4B tags still contain old bad
    title/series/track metadata.
    """
    path_meta = parse_structured_book_from_path(
        file_path,
        known_author=clues.get("author", ""),
    )

    if not path_meta:
        return clues

    original = {
        "raw_title": clues.get("raw_title", ""),
        "title": clues.get("title", ""),
        "series": clues.get("series", ""),
        "book_number": clues.get("book_number", ""),
        "book_number_source": clues.get("book_number_source", ""),
    }

    changes = []

    path_title_norm = normalize_for_match(path_meta.get("title", ""))
    current_title_norm = normalize_for_match(clues.get("title", ""))
    current_series_norm = normalize_for_match(clues.get("series", ""))
    path_title_is_series_label = bool(
        path_title_norm
        and current_series_norm
        and path_title_norm == current_series_norm
        and current_title_norm != current_series_norm
    )

    if (
        path_title_norm
        and not path_title_is_series_label
        and path_title_norm != current_title_norm
    ):
        changes.append("title")

    if (
        path_meta.get("series")
        and normalize_for_match(path_meta.get("series", "")) != normalize_for_match(
            clues.get("series", "")
        )
    ):
        changes.append("series")

    if path_meta.get("book_number") and not sequence_values_equal(
        path_meta.get("book_number", ""), clues.get("book_number", "")
    ):
        changes.append("number")

    path_author_norm = normalize_for_match(path_meta.get("author", ""))
    current_author_norm = normalize_for_match(clues.get("author", ""))
    if path_author_norm and path_author_norm != current_author_norm:
        changes.append("author")

    if not changes:
        return clues

    clues["embedded_before_path_override"] = original
    clues["path_override"] = {
        "applied": True,
        "source": path_meta.get("source", ""),
        "changed": sorted(set(changes)),
    }

    # From this point on, raw_title/title/series/number are the trusted search clues.
    if not path_title_is_series_label:
        clues["raw_title"] = path_meta.get("raw_title", clues.get("raw_title", ""))
        clues["title"] = path_meta.get("title", clues.get("title", ""))
    if path_meta.get("series"):
        clues["series"] = path_meta["series"]
    if path_meta.get("book_number"):
        clues["book_number"] = path_meta["book_number"]
        clues["book_number_source"] = "path"
    if path_meta.get("author"):
        clues["author"] = path_meta["author"]

    return clues


def parse_sequence_number(value: str) -> float | None:
    value = str(value or "").strip()

    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None

    try:
        return float(value)
    except ValueError:
        return None


def sequence_values_equal(left: str, right: str) -> bool:
    left_number = parse_sequence_number(left)
    right_number = parse_sequence_number(right)

    if left_number is None or right_number is None:
        return False

    return left_number == right_number


def parse_title_series_number_from_metadata(tags: dict) -> dict:
    raw_title = sanitize_book_title(first_existing_tag(tags, ["title"]))
    album = sanitize_technical_labels(first_existing_tag(tags, ["album"]))
    artist = first_existing_tag(tags, ["album_artist", "artist", "author"])
    narrator = first_existing_tag(tags, ["composer", "narrator", "performer"])
    track = first_existing_tag(tags, ["track", "tracknumber"])
    grouping = sanitize_technical_labels(
        first_existing_tag(tags, ["grouping", "contentgroup", "series"])
    )

    series = clean_series_value(grouping or album)
    title = raw_title
    book_number = ""
    book_number_source = ""

    # Pattern:
    # Unbound - Book 001 - Dissonance
    # 12 Miles Below - Book 004 - The Mite Forge
    # Also supports decimal side stories such as Book 003.5.
    match = re.match(
        r"^(?P<series>.+?)\s*-\s*Book\s*(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<title>.+)$",
        raw_title,
        flags=re.IGNORECASE,
    )

    if match:
        series = clean_series_value(match.group("series").strip())
        book_number = normalize_book_number(match.group("number"))
        book_number_source = "title"
        title = match.group("title").strip()

    # Pattern:
    # 12 Miles Below IV: The Mite Forge
    roman_match = re.match(
        r"^(?P<series>.+?)\s+(?P<roman>I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)\s*[:\-]\s*(?P<title>.+)$",
        raw_title,
        flags=re.IGNORECASE,
    )

    if roman_match:
        series = clean_series_value(roman_match.group("series").strip())
        title = roman_match.group("title").strip()
        book_number = roman_to_int(roman_match.group("roman"))
        book_number_source = "title"

    # Folder Forge also treats a trailing ": Series, Book N" segment as
    # structured identity rather than part of the display title.
    trailing_series = re.match(
        r"^(?P<title>.+?)\s*[:\-]\s*(?P<series>[^:]+?),\s*Book\s*"
        r"(?P<number>\d{1,4}(?:\.\d+)?)$",
        raw_title,
        flags=re.IGNORECASE,
    )
    if trailing_series:
        title = sanitize_book_title(trailing_series.group("title"))
        series = clean_series_value(trailing_series.group("series"))
        book_number = normalize_book_number(trailing_series.group("number"))
        book_number_source = "title"

    # Pattern:
    # All the Skills - Book 003
    # Amber the Cursed Berserker - Book 002
    # These do not have a title after the book number, but the number is still strong evidence.
    if not book_number:
        title_number = extract_book_number_from_text(raw_title)
        if title_number:
            book_number = title_number
            book_number_source = "title"

    # Track is weak fallback only.
    if not book_number and track:
        track_match = re.search(r"\d+", track)

        if track_match:
            book_number = normalize_book_number(track_match.group(0))
            book_number_source = "track"

    return {
        "raw_title": raw_title,
        "title": title,
        "series": series,
        "book_number": book_number,
        "book_number_source": book_number_source,
        "author": clean_author_value(artist),
        "narrator": narrator,
        "album": album,
    }


def is_invalid_local_title(value: str, author: str = "") -> bool:
    title_norm = normalize_for_match(value)
    author_norm = normalize_for_match(clean_author_value(author))

    if not title_norm or is_generic_chapter_title(title_norm):
        return True

    return bool(author_norm and title_norm == author_norm)


def recover_invalid_local_title(clues: dict, file_path: Path) -> dict:
    if not is_invalid_local_title(clues.get("title", ""), clues.get("author", "")):
        return clues

    candidates = [
        clues.get("album", ""),
        file_path.parent.name,
        file_path.stem,
    ]
    series_norm = normalize_for_match(clues.get("series", ""))
    author_norm = normalize_for_match(clues.get("author", ""))

    for candidate in candidates:
        candidate = sanitize_book_title(candidate)
        candidate_norm = normalize_for_match(candidate)
        if (
            candidate_norm
            and candidate_norm not in {series_norm, author_norm}
            and not is_invalid_local_title(candidate, clues.get("author", ""))
        ):
            clues["raw_title"] = candidate
            clues["title"] = candidate
            clues["title_recovery"] = {
                "applied": True,
                "source": "album" if candidate == sanitize_book_title(clues.get("album", "")) else "path",
            }
            break

    return clues


def build_search_clues_from_file(file_path: Path) -> dict:
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

    return recover_invalid_local_title(clues, file_path)


def build_search_queries_from_clues(clues: dict) -> list[str]:
    title = clues["title"]
    series = clues["series"]
    author = clues["author"]
    raw_title = clues["raw_title"]
    book_number = normalize_book_number(clues.get("book_number", ""))

    queries = []
    sequence_free_title = strip_leading_sequence_from_title(title)
    sequence_free_raw_title = strip_leading_sequence_from_title(raw_title)

    # Best first attempt:
    # exact book title + author. This helps cases like:
    # "Alaska Kingdom Aaron Crash"
    if title and author:
        queries.append(f"{title} {author}")

    # Folder Forge uses the same cleanup when deriving canonical titles. Keep
    # the sequence as ranking evidence, but do not force prefixes such as
    # "02 - When True Night Falls" into every Audible search.
    if sequence_free_title and sequence_free_title != title:
        queries.append(
            f"{sequence_free_title} {author}" if author else sequence_free_title
        )

    # If cleaned title failed, try raw title + author.
    if raw_title and author and raw_title != title:
        queries.append(f"{raw_title} {author}")

    if (
        sequence_free_raw_title
        and sequence_free_raw_title not in {raw_title, sequence_free_title}
    ):
        queries.append(
            f"{sequence_free_raw_title} {author}"
            if author
            else sequence_free_raw_title
        )

    # Broad series search only after title search fails to produce a strong match.
    if series and author:
        queries.append(f"{series} {author}")

    # When the local title is polluted or redundant, prefer a clean
    # series + book number search before broader fallbacks.
    if series and author and book_number:
        queries.append(f"{author} {series} Book {book_number}")
        queries.append(f"{author} {series} {book_number}")

    # Broader but still reasonable.
    if series and title and author:
        queries.append(f"{series} {title} {author}")

    # Wider fallbacks.
    if title:
        queries.append(title)

    if series:
        queries.append(series)

    clean_queries = []
    seen = set()

    for query in queries:
        query = re.sub(r"\((?:19|20)\d{2}\)", " ", query)
        query = re.sub(r"\([^)]{2,}\)$", " ", query)
        query = query.replace(",", " ")
        query = re.sub(r"[_\-:]+", " ", query)
        query = re.sub(r"[^\w\s'.]+", " ", query)
        query = re.sub(r"\s+", " ", query).strip()

        if query and query.lower() not in seen:
            clean_queries.append(query)
            seen.add(query.lower())

    return clean_queries


def strip_leading_sequence_from_title(value: str) -> str:
    """Remove an ordering prefix while preserving the separately stored number."""
    value = clean_text(value)
    if not value:
        return ""

    cleaned = re.sub(
        r"^\s*(?:books?|vol(?:ume)?s?\.?|v|side\s*story|novels?|#)?\s*"
        r"\d{1,4}(?:\.\d+)?(?!\s*%)"
        r"(?:\s*(?:[-–—]|,)\s*\d{1,4}(?:\.\d+)?)?"
        r"\s*[-_.: ]+\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return sanitize_book_title(cleaned)


def build_search_queries_from_metadata(file_path: Path) -> tuple[list[str], dict]:
    clues = build_search_clues_from_file(file_path)
    return build_search_queries_from_clues(clues), clues


def is_generic_chapter_title(value: str) -> bool:
    value = normalize_for_match(value)

    if not value:
        return True

    patterns = [
        r"^chapter\s+\d+$",
        r"^chapter\s+\d+\s+of\s+\d+$",
        r"^track\s+\d+$",
        r"^part\s+\d+$",
        r"^pt\s*0*\d+$",
        r"^disc\s+\d+\s+track\s+\d+$",
        r"^cd\s+\d+\s+track\s+\d+$",
        r"^\d+$",
        r"^file\s+\d+$",
    ]

    return any(re.fullmatch(pattern, value) for pattern in patterns)


def pick_most_common_value(values: list[str]) -> str:
    cleaned_values = [
        sanitize_technical_labels(value)
        for value in values
        if sanitize_technical_labels(value)
    ]

    if not cleaned_values:
        return ""

    counts = Counter(cleaned_values)
    return max(counts.items(), key=lambda item: (item[1], len(item[0])))[0]


def choose_group_book_number(clues_list: list[dict], folder_name: str) -> tuple[str, str]:
    priority_sources = ["path", "title"]

    for source in priority_sources:
        values = [
            normalize_book_number(clues.get("book_number", ""))
            for clues in clues_list
            if clues.get("book_number_source") == source and clues.get("book_number")
        ]
        chosen = pick_most_common_value(values)
        if chosen:
            return chosen, source

    folder_number = extract_folder_book_number(folder_name)
    if folder_number:
        return folder_number, "path"

    values = [
        normalize_book_number(clues.get("book_number", ""))
        for clues in clues_list
        if clues.get("book_number_source") == "track" and clues.get("book_number")
    ]
    chosen = pick_most_common_value(values)
    if chosen:
        return chosen, "track"

    return "", ""


def infer_group_identity_from_path(folder: Path) -> tuple[str, str]:
    """Recover author/series from an organized Author/Series/Book hierarchy."""
    folder_name = sanitize_technical_labels(folder.name)
    if not re.match(
        r"^(?:Book|Volume|Vol\.?)\s*\d+(?:\.\d+)?(?:\s*[-:,]|$)",
        folder_name,
        flags=re.IGNORECASE,
    ):
        return "", ""

    series = clean_series_value(folder.parent.name)
    author = clean_author_value(folder.parent.parent.name)
    generic_names = {
        "audiobooks",
        "books",
        "library",
        "media",
        "unorganized",
        "_unorganized",
        "unknown",
    }

    if normalize_for_match(series) in generic_names:
        series = ""
    if normalize_for_match(author) in generic_names or not looks_like_person_name(author):
        author = ""

    return author, series


def clean_group_folder_title(value: str, author: str) -> str:
    """Apply Folder Forge-style sequence and author cleanup to group folders."""
    cleaned = strip_leading_sequence_from_title(value) or sanitize_book_title(value)
    author = clean_author_value(author)
    if author:
        cleaned = re.sub(
            rf"[\s_-]+{re.escape(author)}\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" -_.:,")
    return sanitize_book_title(cleaned)


def build_multi_file_search_context(file_paths: list[Path]) -> tuple[list[str], dict]:
    clues_list = [build_search_clues_from_file(file_path) for file_path in file_paths]
    folder = file_paths[0].parent
    folder_name = sanitize_technical_labels(folder.name)
    folder_structured = parse_structured_book_text(folder_name)
    folder_descriptive = parse_descriptive_book_text(folder_name)
    folder_identity = parse_identity_rich_book_text(folder_name)
    path_author, path_series = infer_group_identity_from_path(folder)

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
        duration or 0.0 for duration in (read_file_duration_minutes(file) for file in file_paths)
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

        numeric_parts = numeric_part_sequence_files(group_files)
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
    file_path: Path, multi_part_group_map: dict[Path, list[Path]]
) -> tuple[list[str], dict, str]:
    group_files = multi_part_group_map.get(file_path.parent)

    if group_files and is_multi_part_audio_candidate(file_path):
        queries, clues = build_multi_file_search_context(group_files)
        cache_key = f"group::{file_path.parent}"
        return queries, clues, cache_key

    queries, clues = build_search_queries_from_metadata(file_path)
    clues["local_duration_minutes"] = read_file_duration_minutes(file_path)
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


def get_audible_number_candidates(product: dict) -> list[str]:
    """Return likely Audible book numbers from structured series, title, and subtitle.

    Series sequence is preferred, but some Audible products expose the book
    number only in the title/subtitle, e.g. "Casual Farming 3".
    Ranges/omnibus values such as "1-3" are intentionally ignored here.
    """
    candidates: list[str] = []

    _, sequence = get_primary_series(product)
    sequence = str(sequence or "").strip()

    if parse_sequence_number(sequence) is not None:
        candidates.append(normalize_book_number(sequence))

    title = product.get("title", "") or ""
    subtitle = product.get("subtitle", "") or ""

    for value in [title, subtitle]:
        number = extract_book_number_from_text(value)
        if number:
            candidates.append(number)

    # Fallback for Audible titles like "Casual Farming 3" or "All the Skills 5".
    # Only use this when the trailing number is not part of a range/collection marker.
    for value in [title, subtitle]:
        cleaned = clean_text(value)
        if re.search(
            r"\bbooks?\s+\d+\s*(?:-|to|through|&)\s*\d+", cleaned, flags=re.IGNORECASE
        ):
            continue

        match = re.search(r"(?:^|\s)(\d+(?:\.\d+)?)\s*(?:[:\-]|$)", cleaned)
        if match:
            candidates.append(normalize_book_number(match.group(1)))

    unique: list[str] = []
    seen = set()
    for candidate in candidates:
        candidate = normalize_book_number(candidate)
        if candidate and candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)

    return unique


def extract_title_identity_number(value: str) -> str:
    """Extract a title-identity number from names like "Series 3".

    This is intentionally separate from extract_book_number_from_text(). That
    function extracts explicit labels such as "Book 3". This one handles the
    common Audible naming pattern where the book number is part of the title:

      The Lost Bloodline 5
      Overpowered Wizard 3: A Progression LitRPG Epic
      All the Skills 6

    The number is treated as identity evidence only for comparing candidate
    Audible results; it is not used as a generic track number. Years, ranges,
    and percent values are ignored to avoid false rejects.
    """
    value = clean_text(value)

    if not value:
        return ""

    if re.search(
        r"\bbooks?\s+\d+(?:\.\d+)?\s*(?:-|to|through|&|and)\s*\d+",
        value,
        flags=re.IGNORECASE,
    ):
        return ""

    # Do not treat "1% Lifesteal" or similar as book one.
    if re.search(r"\d\s*%", value):
        return ""

    # Strip trailing author/source/date noise that is common in filenames.
    cleaned = re.sub(r"\s+by\s+.+$", "", value, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*\[(?:ASIN\.)?[A-Z0-9]{8,}\]\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\((?:19|20)\d{2}\)\s*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    patterns = [
        # "The Lost Bloodline 5: An Isekai Epic"
        r"(?:^|\s)(\d{1,3}(?:\.\d+)?)\s*[:\-–—]\s+\S+",
        # "The Lost Bloodline 5"
        r"(?:^|\s)(\d{1,3}(?:\.\d+)?)\s*$",
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue

        candidate = normalize_book_number(match.group(1))

        # Avoid obvious years if the cleanup did not remove them.
        if re.fullmatch(r"(?:19|20)\d{2}", candidate):
            continue

        return candidate

    return ""


def get_local_number_identity_candidates(clues: dict) -> list[str]:
    """Return trustworthy local book-number identity candidates.

    These candidates are used to reject same-series wrong-book results. Track
    numbers are excluded because they are often per-file chapter numbers in
    multi-file audiobooks.
    """
    candidates: list[str] = []

    local_number = normalize_book_number(clues.get("book_number", ""))
    local_number_source = str(clues.get("book_number_source", "")).strip()

    if local_number and local_number_source in {"title", "path"}:
        candidates.append(local_number)

    for key in ["title", "raw_title", "series", "album"]:
        value = clues.get(key, "")
        if not value:
            continue

        explicit_number = extract_book_number_from_text(value)
        if explicit_number:
            candidates.append(explicit_number)

        identity_number = extract_title_identity_number(value)
        if identity_number:
            candidates.append(identity_number)

    unique: list[str] = []
    seen = set()
    for candidate in candidates:
        candidate = normalize_book_number(candidate)
        if candidate and candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)

    return unique


def has_number_identity_conflict(clues: dict, product: dict) -> bool:
    """Reject wrong books in the same series when title numbers disagree.

    Duration and fuzzy title scoring can make adjacent books look perfect, e.g.:
      local "The Lost Bloodline 2" vs Audible "The Lost Bloodline 5"
      local "Overpowered Wizard 3" vs Audible "Overpowered Wizard"

    If both sides expose numeric identity evidence and none of the local numbers
    exists on the Audible candidate, the candidate is the wrong book.
    """
    local_numbers = get_local_number_identity_candidates(clues)
    audible_numbers = get_audible_number_candidates(product)

    if not local_numbers or not audible_numbers:
        return False

    return not bool(set(local_numbers) & set(audible_numbers))


def strong_identity_overrides_number_conflict(
    clues: dict,
    product: dict,
    local_duration_minutes: float | None,
) -> bool:
    """Allow side-story numbering differences only with independent confirmation."""
    if title_evidence_score(clues, product) < 0.85:
        return False

    duration = compare_duration(
        local_minutes=local_duration_minutes,
        audible_minutes=get_audible_duration_minutes(product),
    )
    if duration["status"] not in {"perfect", "strong"}:
        return False

    local_author = normalize_for_match(clues.get("author", ""))
    audible_authors = normalize_for_match(" ".join(get_people(product, "authors")))
    local_narrator = normalize_for_match(clues.get("narrator", ""))
    audible_narrators = normalize_for_match(" ".join(get_people(product, "narrators")))

    author_match = bool(
        local_author
        and audible_authors
        and (
            local_author in audible_authors
            or audible_authors in local_author
            or SequenceMatcher(None, local_author, audible_authors).ratio() >= 0.85
        )
    )
    narrator_match = bool(
        local_narrator
        and audible_narrators
        and (
            local_narrator in audible_narrators
            or audible_narrators in local_narrator
            or SequenceMatcher(None, local_narrator, audible_narrators).ratio() >= 0.85
        )
    )
    return author_match or narrator_match


def has_strong_local_number(clues: dict) -> bool:
    return str(clues.get("book_number_source", "")).strip() in {"title", "path"}


def has_sequence_conflict(
    clues: dict,
    product: dict,
    local_duration_minutes: float | None = None,
) -> bool:
    local_number = str(clues.get("book_number", "")).strip()
    number_source = str(clues.get("book_number_source", "")).strip()

    if not local_number:
        return False

    _, audible_sequence = get_primary_series(product)
    audible_sequence = str(audible_sequence).strip()

    if not is_single_numeric_sequence(audible_sequence):
        return False

    duration_result = compare_duration(
        local_minutes=local_duration_minutes,
        audible_minutes=get_audible_duration_minutes(product),
    )

    title_score = title_evidence_score(clues, product)

    local_author = normalize_for_match(clues.get("author", ""))
    local_narrator = normalize_for_match(clues.get("narrator", ""))

    audible_authors = normalize_for_match(" ".join(get_people(product, "authors")))
    audible_narrators = normalize_for_match(" ".join(get_people(product, "narrators")))

    author_good = bool(
        local_author and audible_authors and local_author in audible_authors
    )
    narrator_good = bool(
        local_narrator and audible_narrators and local_narrator in audible_narrators
    )

    # Track numbers are weak metadata.
    if number_source == "track":
        return False

    # If the title is a strong match and duration confirms it,
    # do not reject only because the local folder numbering differs from
    # Audible's sub-series sequence.
    #
    # This handles companion/parallel series like:
    # Local Book 003 - Of Dawn and Darkness
    # Audible The Elder Empire: Sea, Book 2
    if (
        title_score >= 0.85
        and duration_result["status"] in {"perfect", "strong", "acceptable"}
        and (author_good or narrator_good)
    ):
        return False

    try:
        return int(float(audible_sequence)) != int(local_number)
    except ValueError:
        return False


def get_year(product: dict) -> str:
    for key in ["release_date", "issue_date", "publication_datetime"]:
        value = product.get(key)

        if value and len(value) >= 4:
            return value[:4]

    return ""


def get_people(product: dict, key: str) -> list[str]:
    return [
        item.get("name", "").strip()
        for item in product.get(key, [])
        if item.get("name", "").strip()
    ]


def get_primary_series(product: dict) -> tuple[str, str]:
    series = product.get("series") or []

    if not series:
        return "", ""

    first = series[0] or {}

    series_name = first.get("title") or first.get("name") or ""
    sequence = first.get("sequence") or first.get("position") or ""

    return sanitize_tag(series_name), sanitize_tag(sequence)


def audible_search(client: audible.Client, query: str, limit: int) -> list[dict]:
    response = client.get(
        "catalog/products",
        params={
            "keywords": query,
            "num_results": limit,
            "response_groups": RESPONSE_GROUPS,
        },
    )

    return response.get("products", []) or []


def title_evidence_score(clues: dict, product: dict) -> float:
    local_title = normalize_for_match(clues.get("title", ""))
    local_raw_title = normalize_for_match(clues.get("raw_title", ""))
    local_sequence_free_title = normalize_for_match(
        strip_leading_sequence_from_title(clues.get("title", ""))
    )
    local_sequence_free_raw_title = normalize_for_match(
        strip_leading_sequence_from_title(clues.get("raw_title", ""))
    )
    audible_title = normalize_for_match(product.get("title", "") or "")
    audible_subtitle = normalize_for_match(product.get("subtitle", "") or "")

    if not local_title and not local_raw_title:
        return 0.0

    title_to_check = local_title or local_raw_title
    title_candidates = [
        candidate
        for candidate in {
            title_to_check,
            local_sequence_free_title,
            local_sequence_free_raw_title,
        }
        if candidate
    ]

    local_tokens = significant_title_tokens(clues.get("title", "") or clues.get("raw_title", ""))
    audible_token_sets = [
        set(significant_title_tokens(product.get("title", "") or "")),
        set(significant_title_tokens(product.get("subtitle", "") or "")),
    ]
    distinctive_containment = 0.0
    if local_tokens and any(len(token) >= 5 for token in local_tokens):
        local_token_set = set(local_tokens)
        if any(local_token_set <= token_set for token_set in audible_token_sets):
            distinctive_containment = 0.75

    audible_in_local = 0.0
    audible_title_tokens = significant_title_tokens(product.get("title", "") or "")
    if (
        audible_title
        and audible_title in title_to_check
        and len(audible_title_tokens) >= 2
    ):
        audible_in_local = 1.0

    return max(
        *[
            SequenceMatcher(None, candidate, audible_value).ratio()
            for candidate in title_candidates
            for audible_value in (audible_title, audible_subtitle)
            if audible_value
        ],
        (
            1.0
            if any(
                candidate in audible_value
                for candidate in title_candidates
                for audible_value in (audible_title, audible_subtitle)
                if audible_value
            )
            else 0.0
        ),
        distinctive_containment,
        audible_in_local,
    )


def product_title_equals_series(product: dict) -> bool:
    audible_title = normalize_for_match(product.get("title", "") or "")
    audible_series, _ = get_primary_series(product)
    audible_series_norm = normalize_for_match(audible_series)

    return bool(
        audible_title and audible_series_norm and audible_title == audible_series_norm
    )


def is_omnibus_product(product: dict) -> bool:
    title = normalize_for_match(product.get("title", "") or "")
    subtitle = normalize_for_match(product.get("subtitle", "") or "")
    _, sequence = get_primary_series(product)
    sequence = str(sequence or "").strip()

    if re.search(r"\bbooks?\s+\d+\s*(?:-|to|through|&)\s*\d+\b", title):
        return True

    if re.search(r"\bbooks?\s+\d+\s*(?:-|to|through|&)\s*\d+\b", subtitle):
        return True

    if re.fullmatch(r"\d+\s*-\s*\d+", sequence):
        return True

    return False


TITLE_ORDER_STOPWORDS = {
    "a",
    "an",
    "and",
    "of",
    "the",
    "to",
    "in",
    "on",
    "for",
    "with",
}


def significant_title_tokens(value: str) -> list[str]:
    """Return title tokens used only for detecting reordered-title conflicts.

    This is intentionally separate from normalize_for_match(), because we do
    not want fuzzy matching to treat these as equivalent:
      Of Dawn and Darkness
      Of Darkness and Dawn
    """
    value = clean_text(value).lower()
    value = re.sub(r"\[[^\]]+\]", " ", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = [token for token in value.split() if token not in TITLE_ORDER_STOPWORDS]
    return tokens


def has_reordered_title_conflict(clues: dict, product: dict) -> bool:
    """Detect same-keywords/different-order title mismatches.

    This catches dangerous companion-title cases such as:
      Local:   Of Dawn and Darkness
      Audible: Of Darkness and Dawn

      Local:   Of Shadow and Sea
      Audible: Of Sea and Shadow

    Those can score highly with simple fuzzy matching, but they are different
    books and should not be used for metadata edits.
    """
    if is_generic_series_number_title(clues):
        return False

    if product_title_equals_series(product):
        return False

    local_tokens = significant_title_tokens(clues.get("title", ""))
    audible_tokens = significant_title_tokens(product.get("title", "") or "")

    if len(local_tokens) < 2 or len(audible_tokens) < 2:
        return False

    if local_tokens == audible_tokens:
        return False

    return sorted(local_tokens) == sorted(audible_tokens)


def score_product_for_metadata(
    clues: dict,
    product: dict,
    local_duration_minutes: float | None = None,
) -> float:
    # Hard reject same-words/different-order titles.
    # Example: "Of Dawn and Darkness" is not "Of Darkness and Dawn".
    if has_reordered_title_conflict(clues, product):
        return 0.0

    # Hard reject same-series wrong-book candidates before fuzzy title/duration
    # bonuses can promote them to perfect matches.
    # Examples:
    #   local "The Lost Bloodline 2" must not match Audible "The Lost Bloodline 5"
    #   local "Overpowered Wizard 3" must not match Audible sequence 1
    if (
        has_number_identity_conflict(clues, product)
        and not strong_identity_overrides_number_conflict(
            clues,
            product,
            local_duration_minutes,
        )
    ):
        return 0.0

    # Hard reject only when the sequence conflict is trustworthy.
    # The has_sequence_conflict() function should ignore weak track-derived numbers,
    # especially when duration confirms the match.
    if has_sequence_conflict(clues, product, local_duration_minutes):
        return 0.0

    local_series = normalize_for_match(clues.get("series", ""))
    local_author = normalize_for_match(clues.get("author", ""))
    local_narrator = normalize_for_match(clues.get("narrator", ""))
    local_number = str(clues.get("book_number", "")).strip()
    local_number_source = str(clues.get("book_number_source", "")).strip()

    audible_authors = normalize_for_match(" ".join(get_people(product, "authors")))
    audible_narrators = normalize_for_match(" ".join(get_people(product, "narrators")))

    audible_series, audible_sequence = get_primary_series(product)
    audible_series_norm = normalize_for_match(audible_series)
    audible_sequence = str(audible_sequence).strip()

    duration_result = compare_duration(
        local_minutes=local_duration_minutes,
        audible_minutes=get_audible_duration_minutes(product),
    )

    score = 0.0

    # Duration is the strongest confirmation signal.
    if duration_result["status"] == "perfect":
        score += 0.38
    elif duration_result["status"] == "strong":
        score += 0.30
    elif duration_result["status"] == "acceptable":
        score += 0.18
    elif duration_result["status"] == "mismatch":
        score -= 0.35

    # Series match.
    series_match = False

    if local_series and audible_series_norm:
        series_score = SequenceMatcher(None, local_series, audible_series_norm).ratio()

        if local_series in audible_series_norm or audible_series_norm in local_series:
            series_score = 1.0

        if series_score >= 0.85:
            series_match = True

        score += series_score * 0.25

    # Sequence match.
    # Track-derived local numbers are weak, so they can boost only if they agree,
    # but they should not punish if they disagree.
    sequence_match = False

    if local_number and audible_sequence:
        local_sequence_number = parse_sequence_number(local_number)
        audible_sequence_number = parse_sequence_number(audible_sequence)

        if local_sequence_number is not None and audible_sequence_number is not None:
            if audible_sequence_number == local_sequence_number:
                sequence_match = True
                score += 0.18
            elif (
                local_number_source != "track"
                and not strong_identity_overrides_number_conflict(
                    clues,
                    product,
                    local_duration_minutes,
                )
            ):
                # Non-track-derived conflicts should already be blocked by
                # has_sequence_conflict(), but keep this as a safety fallback.
                return 0.0

    # Author match.
    author_good = False

    if local_author and audible_authors:
        author_score = SequenceMatcher(None, local_author, audible_authors).ratio()

        if local_author in audible_authors:
            author_score = 1.0

        if author_score >= 0.70:
            author_good = True

        score += author_score * 0.17

    # Narrator match.
    narrator_good = False

    if local_narrator and audible_narrators:
        narrator_score = SequenceMatcher(
            None, local_narrator, audible_narrators
        ).ratio()

        if local_narrator in audible_narrators:
            narrator_score = 1.0

        if narrator_score >= 0.70:
            narrator_good = True

        score += narrator_score * 0.10

    # Title evidence.
    title_score = title_evidence_score(clues, product)
    local_title = normalize_for_match(clues.get("title", ""))
    audible_title = normalize_for_match(product.get("title", "") or "")
    audible_subtitle = normalize_for_match(product.get("subtitle", "") or "")

    title_matches_audible = (
        title_score >= 0.55
        or (local_title and local_title in audible_title)
        or (local_title and local_title in audible_subtitle)
        or is_generic_series_number_title(clues)
    )
    score += title_score * 0.12

    # Strong identity bonus.
    if series_match and sequence_match:
        score += 0.10

    # Duration-confirmed matches should pass even when title formatting differs.
    if duration_result["status"] in {"perfect", "strong", "acceptable"}:
        if series_match and (author_good or narrator_good):
            score = max(score, 0.82)
        elif title_score >= 0.75 and (author_good or narrator_good):
            score = max(score, 0.80)

    # Extra safety for title + duration + author/narrator cases.
    # This helps cases like Alaska Kingdom where local track is wrong,
    # but title, author/narrator, and duration identify the correct book.
    if duration_result["status"] in {"perfect", "strong"} and title_score >= 0.80:
        if author_good or narrator_good:
            score = max(score, 0.90)

    # Series-grouping correction path.
    # Allows series_only correction even when duration/title/sequence are messy.
    if series_match and (author_good or narrator_good):
        score = max(score, 0.72)

    # Perfect confidence path:
    # duration <= 3% difference + title match + author match
    # should be considered extremely reliable.
    if (
        duration_result["status"] == "perfect"
        and title_score >= 0.80
        and (author_good or narrator_good)
    ):
        score = 1.0

    return round(min(max(score, 0.0), 1.0), 4)


def is_single_numeric_sequence(value: str) -> bool:
    value = str(value or "").strip()
    return bool(re.fullmatch(r"\d+(?:\.0)?", value))


def clean_sequence(value: str) -> str:
    value = str(value or "").strip()

    if not is_single_numeric_sequence(value):
        return ""

    return str(int(float(value)))


def preferred_audible_sequence(product: dict) -> str:
    """Use a unique title/subtitle book number when the series sequence is absent."""
    _series_name, sequence = get_primary_series(product)
    clean_seq = clean_sequence(sequence)
    if clean_seq:
        return clean_seq

    candidates = [
        clean_sequence(candidate)
        for candidate in get_audible_number_candidates(product)
    ]
    candidates = [candidate for candidate in candidates if candidate]
    return candidates[0] if len(set(candidates)) == 1 else ""


def pick_best_match_for_metadata(
    clues: dict,
    products: list[dict],
    local_duration_minutes: float | None = None,
) -> tuple[dict | None, float]:
    best_product = None
    best_score = 0.0

    for product in products:
        score = score_product_for_metadata(clues, product, local_duration_minutes)

        if score > best_score:
            best_score = score
            best_product = product

    return best_product, best_score


def is_generic_series_number_title(clues: dict) -> bool:
    title = normalize_for_match(clues.get("title", ""))
    series = normalize_for_match(clues.get("series", ""))
    number = str(clues.get("book_number", "")).strip()

    if not title or not series or not number:
        return False

    # Examples:
    # "All the Skills - Book 003"
    # "The Perfect Run - Book 003"
    # "Amber the Cursed Berserker - Book 002"
    generic_patterns = [
        rf"^{re.escape(series)}\s+book\s+0*{re.escape(number)}$",
        rf"^{re.escape(series)}\s+0*{re.escape(number)}$",
    ]

    return any(re.fullmatch(pattern, title) for pattern in generic_patterns)


def determine_edit_mode(
    product: dict,
    clues: dict,
    score: float,
    duration_result: dict | None = None,
) -> str:
    if score < AGGRESSIVE_SCORE_THRESHOLD:
        return "none"

    duration_status = (duration_result or {}).get("status", "unknown")
    title_score = title_evidence_score(clues, product)
    series_name, sequence = get_primary_series(product)

    local_title = normalize_for_match(clues.get("title", ""))
    audible_title = normalize_for_match(product.get("title", "") or "")
    audible_subtitle = normalize_for_match(product.get("subtitle", "") or "")

    title_matches_audible = (
        title_score >= 0.55
        or (local_title and local_title in audible_title)
        or (local_title and local_title in audible_subtitle)
        or is_generic_series_number_title(clues)
    )

    local_author = normalize_for_match(clues.get("author", ""))
    audible_authors = normalize_for_match(" ".join(get_people(product, "authors")))
    local_series = normalize_for_match(clues.get("series", ""))
    audible_series = normalize_for_match(series_name)
    author_identity_match = bool(
        local_author
        and audible_authors
        and (
            local_author == audible_authors
            or local_author in audible_authors
            or audible_authors in local_author
            or SequenceMatcher(None, local_author, audible_authors).ratio() >= 0.85
        )
    )
    series_identity_match = bool(
        local_series
        and audible_series
        and (
            local_series == audible_series
            or SequenceMatcher(None, local_series, audible_series).ratio() >= 0.88
        )
    )

    def safe_series_only() -> str:
        return (
            "series_only"
            if series_name and author_identity_match and series_identity_match
            else "none"
        )

    # Large runtime differences remain review-only even when other identity
    # evidence is strong. This protects incomplete or alternate recordings.
    diff_percent = (duration_result or {}).get("diff_percent")
    if duration_status == "mismatch" or (
        diff_percent is not None and float(diff_percent) > 10.0
    ):
        return safe_series_only()

    # Omnibus / box-set records can be useful for series grouping,
    # but should not overwrite individual book titles or track numbers.
    if is_omnibus_product(product):
        local_omnibus = bool(
            re.search(
                r"\b(?:complete collection|definitive collection|complete series|box set|books?\s+\d+\s*(?:-|to|through|&)\s*\d+)\b",
                clean_text(clues.get("title", "")),
                flags=re.IGNORECASE,
            )
        )
        if (
            local_omnibus
            and title_score >= 0.80
            and duration_status in {"perfect", "strong"}
        ):
            return "full"
        return safe_series_only()

    # Same-keywords/different-order titles are unsafe.
    # Example:
    #   Local:   Of Dawn and Darkness
    #   Audible: Of Darkness and Dawn
    # These should be skipped, not full or series_only.
    if has_reordered_title_conflict(clues, product):
        return "none"

    # Special case:
    # Some Audible entries use the series name as the product title.
    #
    # Example:
    #   Local title:   The Frozen Realm
    #   Audible title: 12 Miles Below
    #   Series:        12 Miles Below
    #
    # This can still be a valid full match when duration and sequence confirm it,
    # because choose_best_title() will preserve the local specific title.
    if product_title_equals_series(product):
        if (
            duration_status in {"perfect", "strong", "acceptable"}
            and series_name
            and is_single_numeric_sequence(sequence)
        ):
            return "full"

        return safe_series_only()

    # Main title-safety gate:
    # If the local title is meaningful and clearly does not match Audible,
    # do not allow a full rewrite, even if sequence/duration look good.
    #
    # This blocks cases like:
    #   Local:   Of Dawn and Darkness
    #   Audible: Of Kings and Killers
    #
    # But it still allows generic titles like:
    #   All the Skills - Book 003
    if clues.get("title") and not title_matches_audible:
        return safe_series_only()

    # If duration confirms the match, full edit is allowed when either title is
    # plausible or we have a clean series sequence.
    if duration_status in {"perfect", "strong", "acceptable"}:
        if title_score >= 0.45:
            return "full"

        if series_name and is_single_numeric_sequence(sequence):
            return "full"

    # If the local title clearly does not match the Audible title/subtitle,
    # only fix the series grouping fields.
    if clues.get("title") and title_score < 0.55:
        return safe_series_only()

    # If Audible gave a clean single sequence and the title is plausible, full edit is OK.
    if series_name and is_single_numeric_sequence(sequence):
        return "full"

    return safe_series_only()


def get_cover_url(product: dict) -> str:
    images = product.get("product_images") or {}

    if not isinstance(images, dict):
        return ""

    # Prefer larger covers when available.
    preferred_keys = [
        "2400",
        "1215",
        "1200",
        "500",
        "408",
        "300",
    ]

    for key in preferred_keys:
        if images.get(key):
            return images[key]

    for value in images.values():
        if value:
            return value

    return ""


def metadata_from_product(
    product: dict,
    clues: dict,
    score: float,
    requested_edit_mode: str = "",
) -> dict:
    audible_title = sanitize_tag(product.get("title", ""))
    subtitle = sanitize_tag(product.get("subtitle", ""))

    series_name, sequence = get_primary_series(product)
    clean_seq = preferred_audible_sequence(product)

    duration_result = compare_duration(
        local_minutes=clues.get("local_duration_minutes"),
        audible_minutes=get_audible_duration_minutes(product),
    )

    recommended_edit_mode = determine_edit_mode(
        product, clues, score, duration_result
    )
    if requested_edit_mode and requested_edit_mode not in {"full", "series_only"}:
        raise ValueError(f"unsupported edit mode: {requested_edit_mode}")
    edit_mode = requested_edit_mode or recommended_edit_mode

    authors = get_people(product, "authors")
    narrators = get_people(product, "narrators")

    author_text = canonicalize_author_credits(authors)
    narrator_text = ", ".join(narrators)

    year = get_year(product)
    summary = sanitize_tag(
        product.get("publisher_summary") or product.get("merchandising_summary") or ""
    )

    if edit_mode == "full":
        title = choose_best_title(
            audible_title=audible_title,
            audible_series=series_name,
            local_title=clues.get("title", ""),
        )
        album = title
        sequence_to_write = clean_seq
        narrator_to_write = narrator_text
        year_to_write = year
        summary_to_write = summary
    elif edit_mode == "series_only":
        # Preserve local book identity; fix only the grouping-critical fields and clean author.
        local_title = clues.get("title") or clues.get("raw_title")
        title = sanitize_tag(
            audible_title
            if is_invalid_local_title(local_title, clues.get("author", ""))
            else local_title
        )
        album = title
        sequence_to_write = ""
        narrator_to_write = sanitize_tag(clues.get("narrator", ""))
        year_to_write = ""
        summary_to_write = ""
    else:
        title = sanitize_tag(
            clues.get("title") or clues.get("raw_title") or audible_title
        )
        album = title
        sequence_to_write = ""
        narrator_to_write = sanitize_tag(clues.get("narrator", ""))
        year_to_write = ""
        summary_to_write = ""

    return {
        "asin": product.get("asin", ""),
        "title": title,
        "subtitle": subtitle,
        "author": author_text or sanitize_tag(clues.get("author", "")),
        "narrator": narrator_to_write,
        "series": series_name,
        "sequence": sequence_to_write,
        "year": year_to_write,
        "summary": summary_to_write,
        "album": album,
        "audible_title": audible_title,
        "audible_sequence": sequence,
        "audible_year": year,
        "cover_url": get_cover_url(product),
        "audible_duration_minutes": get_audible_duration_minutes(product),
        "audible_number_candidates": get_audible_number_candidates(product),
        "duration": duration_result,
        "edit_mode": edit_mode,
        "recommended_edit_mode": recommended_edit_mode,
    }


def choose_best_title(audible_title: str, audible_series: str, local_title: str) -> str:
    audible_title_clean = sanitize_book_title(audible_title)
    audible_series_clean = sanitize_tag(audible_series)
    local_title_clean = sanitize_book_title(local_title)

    if not local_title_clean:
        return audible_title_clean

    if not audible_title_clean:
        return local_title_clean

    # If Audible uses the series name as the title, the local title is usually more specific.
    if (
        audible_series_clean
        and normalize_for_match(audible_title_clean)
        == normalize_for_match(audible_series_clean)
        and normalize_for_match(local_title_clean)
        != normalize_for_match(audible_title_clean)
    ):
        return local_title_clean

    return audible_title_clean


def build_metadata_args(metadata: dict) -> list[str]:
    tag_map = {
        "title": metadata.get("title", ""),
        "artist": metadata.get("author", ""),
        "album_artist": metadata.get("author", ""),
        "album": metadata.get("title", ""),
        "grouping": metadata.get("series", ""),
        "mvnm": metadata.get("series", ""),
        "mvin": metadata.get("sequence", ""),
        "composer": metadata.get("narrator", ""),
        "date": metadata.get("year", ""),
        "genre": "Audiobook",
    }

    if metadata.get("sequence"):
        tag_map["track"] = metadata["sequence"]

    args = []
    for key, value in tag_map.items():
        value = sanitize_tag(value)
        if value:
            args.extend(["-metadata", f"{key}={value}"])

    return args


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
        "genre": "Audiobook",
    }

    if metadata.get("sequence"):
        preview["track"] = metadata["sequence"]

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


def print_plan(
    file_path: Path, query: str, score: float, metadata: dict, clues: dict
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

    print("AUDIBLE MATCH:")
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


def matches_skip_patterns(
    file_path: Path, clues: dict, patterns: list[str]
) -> tuple[bool, str]:
    """Return True when a file should be skipped by user supplied patterns.

    Patterns are case-insensitive plain substrings checked against the full path
    and the extracted local metadata fields. This keeps the option simple and
    safe for excluding known-problem folders/series such as Casual Farming.
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



def sequence_values_differ(left: str, right: str) -> bool:
    """Return True when two non-empty book sequence values disagree."""
    left = clean_sequence(str(left or ""))
    right = clean_sequence(str(right or ""))
    if not left or not right:
        return False
    try:
        return float(left) != float(right)
    except ValueError:
        return left != right


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
        "--skip-pattern",
        action="append",
        default=[],
        help=(
            "Skip files whose path or extracted metadata contains this case-insensitive "
            "text. Can be used multiple times, e.g. --skip-pattern 'Casual Farming'."
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
        "--cover-if-missing",
        action="store_true",
        help="Embed Audible cover art only when the file has no existing embedded cover.",
    )

    parser.add_argument(
        "--replace-cover",
        action="store_true",
        help="Replace existing embedded cover art with Audible cover art.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()

    if not root.exists():
        raise SystemExit(f"ERROR: path does not exist: {root}")

    files = collect_audio_files(root)
    multi_part_group_map = build_multi_part_group_map(files)

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
        auth = audible.Authenticator.from_file(args.auth_file, password=password)
    else:
        auth = audible.Authenticator.from_file(args.auth_file)

    client = audible.Client(auth=auth)

    print(f"Found {len(processing_items)} supported files.")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Minimum score: {args.min_score}")
    print(f"Writer: {args.writer}")
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
    search_cache: dict[tuple[str, int], list[dict]] = {}
    search_context_cache: dict[str, tuple[list[str], dict]] = {}
    match_cache: dict[str, dict] = {}

    for index, file_path in enumerate(processing_items, start=1):
        display_path = get_processing_display_path(file_path, multi_part_group_map)
        print(f"[{index}/{len(processing_items)}] Processing: {display_path}", flush=True)

        existing_marker = load_marker(file_path)

        if existing_marker:
            print(
                f"  Marker: applied={existing_marker.get('applied')} "
                f"aggressive={existing_marker.get('aggressive')} "
                f"score={existing_marker.get('score')}"
            )

        skip_due_to_marker, marker_reason = should_skip_due_to_marker(
            source=file_path,
            aggressive_run=args.aggressive,
            force=args.force,
            minimum_score=args.min_score,
        )

        if skip_due_to_marker:
            print(f"  SKIP: {marker_reason}")
            print()
            # Already-processed marker skips are idempotent no-ops, not match
            # discrepancies. Keep them out of Manual Review to avoid flooding
            # normal reruns.
            skipped += 1
            continue

        match_cache_key = get_search_context_cache_key(file_path, multi_part_group_map)
        if match_cache_key in search_context_cache:
            queries, clues = search_context_cache[match_cache_key]
        else:
            queries, clues, _ = build_search_context(file_path, multi_part_group_map)
            search_context_cache[match_cache_key] = (queries, clues)
        local_duration_minutes = clues.get("local_duration_minutes")

        skip_due_to_pattern, skip_pattern = matches_skip_patterns(
            file_path=file_path,
            clues=clues,
            patterns=args.skip_pattern,
        )

        if skip_due_to_pattern:
            reason = f"skipped: matched skip pattern: {skip_pattern}"
            print(f"  SKIP: matched skip pattern: {skip_pattern}")
            append_manual_review(
                manual_review,
                file_path,
                [reason],
                clues=clues,
                status="skipped",
            )
            print()
            skipped += 1
            continue

        if not queries:
            reason = "skipped: no useful embedded metadata to search from"
            print("  SKIP: no useful embedded metadata to search from")
            append_manual_review(
                manual_review,
                file_path,
                [reason],
                clues=clues,
                status="skipped",
            )
            print()
            skipped += 1
            continue

        try:
            if match_cache_key in match_cache:
                cached_match = match_cache[match_cache_key]
                product = cached_match["product"]
                score = cached_match["score"]
                used_query = cached_match["used_query"]
                print("  Reusing cached match for shared search context")
            else:
                product = None
                score = 0.0
                used_query = ""

                # Search in phases.
                # Each query is tested by itself.
                # If a query returns a strong enough match, we stop immediately
                # instead of letting broader fallback queries override it.
                for query in queries:
                    print(f"  Trying query: {query}")
                    cache_key = (query.lower(), args.limit)
                    if cache_key in search_cache:
                        query_products = search_cache[cache_key]
                        print(f"  Results: {len(query_products)} (cached)")
                    else:
                        query_products = audible_search(client, query, args.limit)
                        search_cache[cache_key] = query_products
                        print(f"  Results: {len(query_products)}")

                    if not query_products:
                        continue

                    candidate, candidate_score = pick_best_match_for_metadata(
                        clues,
                        query_products,
                        local_duration_minutes,
                    )

                    if candidate:
                        debug_metadata = metadata_from_product(
                            candidate, clues, candidate_score
                        )
                        print(
                            f"  Candidate: score={candidate_score} "
                            f"title={debug_metadata.get('audible_title')} "
                            f"sequence={debug_metadata.get('audible_sequence')} "
                            f"duration={debug_metadata.get('audible_duration_minutes')} "
                            f"mode={debug_metadata.get('edit_mode')} "
                            f"asin={debug_metadata.get('asin')}"
                        )

                    if not candidate:
                        continue

                    # Keep the best candidate found so far.
                    if candidate_score > score:
                        product = candidate
                        score = candidate_score
                        used_query = query

                    # Stop once this query produced a strong enough match.
                    # This lets "Alaska Kingdom Aaron Crash" win before trying
                    # broader queries like "American Dragons Series Aaron Crash".
                    if candidate_score >= args.min_score:
                        break

                match_cache[match_cache_key] = {
                    "product": product,
                    "score": score,
                    "used_query": used_query,
                }

            if not product:
                reason = "skipped: no usable Audible match"
                print("  SKIP: no usable Audible match")
                print(f"  Tried queries: {queries}")
                append_manual_review(
                    manual_review,
                    file_path,
                    [reason],
                    clues=clues,
                    query=" | ".join(queries),
                    status="skipped",
                )
                print()
                skipped += 1
                continue

            metadata = metadata_from_product(product, clues, score)
            metadata["file_type"] = get_file_type(file_path)

            print_plan(file_path, used_query, score, metadata, clues)

            edit_mode = metadata.get("edit_mode", "none") or "none"
            mode_counts[edit_mode] += 1

            duration = metadata.get("duration", {}) or {}
            duration_status = duration.get("status", "unknown") or "unknown"
            duration_counts[duration_status] += 1

            diff_percent = duration.get("diff_percent")
            if (
                diff_percent is not None
                and float(diff_percent) > args.duration_review_threshold
            ):
                duration_review.append(
                    {
                        "path": str(file_path),
                        "file_type": get_file_type(file_path),
                        "local_title": clues.get("title")
                        or clues.get("raw_title")
                        or "-",
                        "audible_title": metadata.get("audible_title")
                        or metadata.get("title")
                        or "-",
                        "mode": edit_mode,
                        "score": score,
                        "status": duration_status,
                        "diff_percent": diff_percent,
                        "local_minutes": duration.get("local_minutes"),
                        "audible_minutes": duration.get("audible_minutes"),
                    }
                )

            review_reasons = selected_match_review_reasons(
                metadata,
                clues,
                score,
                args.duration_review_threshold,
            )
            if review_reasons:
                append_manual_review(
                    manual_review,
                    file_path,
                    review_reasons,
                    clues=clues,
                    metadata=metadata,
                    score=score,
                    mode=edit_mode,
                    query=used_query,
                    status="selected",
                )

            if score < args.min_score:
                reason = f"skipped: score below minimum: {score} < {args.min_score}"
                print(f"  SKIP: score below minimum: {score} < {args.min_score}")
                append_manual_review(
                    manual_review,
                    file_path,
                    [reason],
                    clues=clues,
                    metadata=metadata,
                    score=score,
                    mode=edit_mode,
                    query=used_query,
                    status="skipped",
                )
                print()
                skipped += 1
                continue

            if not metadata["title"] or not metadata["author"]:
                reason = "skipped: missing title or author from Audible result"
                print("  SKIP: missing title or author from Audible result")
                append_manual_review(
                    manual_review,
                    file_path,
                    [reason],
                    clues=clues,
                    metadata=metadata,
                    score=score,
                    mode=edit_mode,
                    query=used_query,
                    status="skipped",
                )
                print()
                skipped += 1
                continue

            if metadata.get("edit_mode") == "none":
                reason = "skipped: match marked unsafe / no editable metadata action"
                print("  SKIP: match marked unsafe / no editable metadata action")
                append_manual_review(
                    manual_review,
                    file_path,
                    [reason],
                    clues=clues,
                    metadata=metadata,
                    score=score,
                    mode=edit_mode,
                    query=used_query,
                    status="skipped",
                )
                print()
                skipped += 1
                continue

            asin_matches.append(
                {
                    "asin": metadata.get("asin", ""),
                    "file_type": get_file_type(file_path),
                    "mode": metadata.get("edit_mode", ""),
                    "path": str(file_path),
                    "local_title": clues.get("title", ""),
                    "local_number": clues.get("book_number", ""),
                    "local_number_source": clues.get("book_number_source", ""),
                    "audible_title": metadata.get("audible_title", ""),
                    "audible_sequence": metadata.get("audible_sequence", ""),
                    "audible_number_candidates": metadata.get(
                        "audible_number_candidates", []
                    ),
                    "score": score,
                }
            )

            if args.apply:
                aggressive_edit = args.aggressive or score >= AGGRESSIVE_SCORE_THRESHOLD
                mode = "aggressive" if aggressive_edit else "normal"

                if should_write_json_sidecar(file_path, clues):
                    sidecar_path = write_m4b_tool_metadata_sidecar(
                        file_path, metadata, clues, score
                    )
                    write_marker(
                        source=file_path,
                        metadata=metadata,
                        clues=clues,
                        score=score,
                        mode=mode,
                        aggressive=aggressive_edit,
                        output_kind="json_sidecar",
                    )
                    print(f"  APPLIED ({mode}, json_sidecar={sidecar_path})")
                else:
                    writer_used = write_tags(
                        file_path,
                        metadata,
                        backup=args.backup,
                        writer=args.writer,
                        cover_if_missing=args.cover_if_missing,
                        replace_cover=args.replace_cover,
                    )

                    write_marker(
                        source=file_path,
                        metadata=metadata,
                        clues=clues,
                        score=score,
                        mode=mode,
                        aggressive=aggressive_edit,
                        output_kind="tags",
                    )

                    print(f"  APPLIED ({mode}, writer={writer_used})")
                print()

            matched += 1

        except Exception as error:
            print(f"  ERROR: {error}")
            print()
            failed += 1

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
    )

    if args.show_asin_report:
        print_asin_verification_report(asin_matches)

    if not args.apply:
        print()
        print("Dry-run only. Re-run with --apply to write tags.")


if __name__ == "__main__":
    main()
