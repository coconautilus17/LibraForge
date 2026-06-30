"""Tag-writing primitives and metadata-arg helpers.

Pure functions for constructing and writing individual audio tags. The heavy
IO writers (mutagen_write_mp4_tags, mutagen_write_mp3_tags) stay in the fixer
script since they depend on file-backup IO and cover-download HTTP helpers.
"""

from __future__ import annotations

from pathlib import Path

try:
    from mutagen.mp4 import MP4, MP4FreeForm, MP4Cover
except Exception:
    MP4 = None
    MP4FreeForm = None
    MP4Cover = None

try:
    from mutagen.id3 import (
        ID3,
        APIC,
        TXXX,
        TRCK,
    )
except Exception:
    ID3 = None
    APIC = None
    TXXX = None
    TRCK = None

from app.fixer.parsing import sanitize_tag, clean_sequence

# ---------------------------------------------------------------------------
# Extension constants
# ---------------------------------------------------------------------------

MUTAGEN_MP4_EXTENSIONS = {".m4b", ".m4a", ".mp4"}
MUTAGEN_MP3_EXTENSIONS = {".mp3"}

# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# MP4 tag setters
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ID3 tag setters
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# m4b-tool metadata args
# ---------------------------------------------------------------------------

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
        "genre": metadata.get("genre", ""),
        "publisher": metadata.get("publisher", ""),
        "subtitle": metadata.get("subtitle", ""),
    }

    if metadata.get("sequence"):
        tag_map["track"] = metadata["sequence"]

    if metadata.get("asin"):
        tag_map["asin"] = metadata["asin"]

    if metadata.get("write_summary") and metadata.get("summary"):
        tag_map["comment"] = metadata["summary"]

    if metadata.get("isbn"):
        tag_map["isbn"] = metadata["isbn"]

    args = []
    for key, value in tag_map.items():
        value = sanitize_tag(value)
        if value:
            args.extend(["-metadata", f"{key}={value}"])

    return args
