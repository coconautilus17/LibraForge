#!/usr/bin/env python3
"""
Organize audiobook files/folders into an Audiobookshelf-friendly layout.

Default target layout:
  Standalone book:
    <library>/<Author>/<Title>/<audio files>

  Series book:
    <library>/<Canonical Author>/<Series>/<Book|Volume|Vol.> 1 - <Title>/<audio files>

Design goals:
  - Support single-book folders and validated MP3/OPUS/M4A/M4B multi-file books.
  - Prefer metadata-fixer sidecars/markers when available.
  - Use a persistent structure cache so new books in _unorganized can be routed
    into existing series folders without rescanning the full library.
  - Canonicalize series folders by primary author, so co-authored side stories do
    not create a second author folder for the same series.
  - Support one-time structure consolidation of an existing messy library.
  - Preserve Book/Vol./Volume/Side Story folder prefixes when confidently detected, while cleaning redundant sequence text from book titles.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from app.title_noise_policy import (
        contains_title_noise,
        is_title_noise,
        remove_trailing_title_noise,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.title_noise_policy import (
        contains_title_noise,
        is_title_noise,
        remove_trailing_title_noise,
    )

AUDIO_EXTENSIONS = {".m4b", ".m4a", ".mp4", ".flac", ".ogg", ".opus", ".aac", ".mp3"}
# Keep in sync with the fixer's MULTI_PART_AUDIO_EXTENSIONS so a book the fixer
# grouped (e.g. a folder of per-chapter .ogg files) is recognized as one
# multi-file book here too.
MULTI_PART_AUDIO_EXTENSIONS = {".mp3", ".opus", ".ogg", ".m4a", ".m4b"}
CHAPTER_METADATA_EXTENSIONS = {".m4a", ".m4b", ".mp4"}
MAX_CHAPTERS_PER_MULTI_PART_FILE = 1
MAX_LOW_EMBEDDED_CHAPTERS_PER_NAMED_PART_FILE = 3
IGNORED_EXTENSIONS: set[str] = set()

IGNORED_DIR_NAMES = {"#recycle", "@eaDir"}
STAGING_DIR_NAMES = {"_unorganized"}
IGNORED_FILE_MARKERS = (".metadata-fixed.", ".metadata-restored.")

GENERIC_AUTHOR_KEYS = {
    "booktrack",
    "various",
    "variousauthors",
    "unknown",
    "unknownauthor",
    "multipleauthors",
    "narrator",
    # Production studios that tag themselves as the artist/author
    "graphicaudio",
    "soundbooththeatre",
    "soundbooththeater",
    "sbt",
}

# These are container/helper folders, not real audiobook authors or series.
# They commonly appear in chapterized dumps such as:
#   Spice and Wolf - Complete Series, Chapterized/Audio/<book folders>
# If trusted as Author/Series during consolidation they can route books to
# bad targets like /audiobooks/Spice/Audio/...
GENERIC_STRUCTURE_KEYS = {
    "audio",
    "audiobook",
    "audiobooks",
    "book",
    "books",
    "library",
    "collection",
    "collections",
    "chapter",
    "chapters",
    "chapterized",
    "complete",
    "completeseries",
    "seriescollection",
    "disc",
    "discs",
    "cd",
    "cds",
}

DEFAULT_STRUCTURE_CACHE = Path("/app/reports/organizer-structure-cache.json")
STRUCTURE_CACHE_SCHEMA_VERSION = 11

COMPANION_SUFFIXES = (
    ".libraforge.json",
    ".metadata-backup.json",
    ".audible-metadata-fixer.json",
    ".cover-backup.jpg",
    ".cover-backup.png",
    ".m4b-tool-metadata.json",
    ".metadata.json",
)

# Optional ebook/sidecar companions when they clearly share the audio stem.
COMPANION_SIDE_EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw3", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".txt"}

NON_AUTHOR_ROLE_RE = re.compile(
    r"\s+-\s+(?:translator|translations?|introduction|introductions?|editor|foreword|afterword|adapter|adapted by)\s*$",
    re.IGNORECASE,
)

# Broadcaster/studio prefixes that appear as "Studio - Author Name" in embedded tags.
# Strip the prefix; keep the actual author.
BROADCASTER_PREFIX_RE = re.compile(
    r"^(?:"
    r"BBC(?:\s+(?:Radio|Audio|Books|Worldwide))?|"
    r"Graphic[\s-]*Audio|"
    r"SoundBooth[\s-]*(?:Theatre|Theater)|"
    r"SBT"
    r")\s*[-–—]\s*",
    re.IGNORECASE,
)

GENERIC_TRACK_TITLE_PATTERNS = [
    r"^\d{1,3}\s*[-_.:]?\s*(?:prologue|epilogue|interlude|intermission)$",
    r"^\d{1,3}\s*[-_.:]?\s*chapter\s+\d+$",
    r"^\d{1,3}\s*[-_.:]?\s*(?:part|track)\s+\d+$",
    r"^chapter\s+\d+$",
    r"^chapter\s+\d+\s+of\s+\d+$",
    r"^track\s+\d+$",
    r"^part\s+\d+$",
    r"^disc\s+\d+\s+track\s+\d+$",
    r"^cd\s+\d+\s+track\s+\d+$",
    r"^\d+$",
]


NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}


@dataclass(frozen=True)
class NamingRenderResult:
    """What a naming template rendered for one book: where, what filename (if
    any), and any review reasons the renderer surfaced. A named result
    instead of a positional tuple so a caller can't silently misread which
    element is which as this type grows.
    """

    target_dir: Path
    filename: str | None
    review_reasons: list[str]


@dataclass(frozen=True)
class TargetResolution:
    """What build_cached_target_dir() resolved for one book: the destination
    folder, the filename a naming template wants for a true single-file book
    (None otherwise), the structure-cache routing status ("new"/"existing"/
    "ambiguous"), and the metadata as corrected by that routing.
    """

    target_dir: Path
    filename: str | None
    status: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BookItem:
    kind: str  # folder or loose_file
    source_path: Path
    audio_files: list[Path]
    representative: Path
    # True when this "folder" item's audio_files is a proper subset of every
    # audio file physically in source_path -- e.g. a recognized chapter-part
    # sequence sharing its folder with a separately merged single-file edition
    # of the same book. The move must relocate only audio_files (plus the
    # group's own folder-level companions), not sweep the whole directory.
    partial_group: bool = False
    # Audio files physically in source_path but outside this group when
    # partial_group is True (e.g. the separately merged single-file edition).
    # Excluded from the folder move -- each is planned as its own loose_file
    # item and must be left in place for that.
    leftover_files: tuple[Path, ...] = ()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: str) -> str:
    value = str(value or "")
    # Normalize uncommon colon variants seen in some Audible/file metadata so
    # title-noise and series/title cleanup rules can recognize subtitles.
    value = value.replace("꞉", ":").replace("：", ":")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def sanitize_path_name(name: str, fallback: str = "Unknown") -> str:
    name = clean_text(name)
    if not name:
        name = fallback
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', " - ", name)
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\s+-\s+-\s+", " - ", name)
    name = name.strip(" .-")
    return name or fallback


def normalize_for_compare(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(value).lower())


def is_generic_structure_name(value: str) -> bool:
    """Return True for helper/container names that must not become author/series folders."""
    raw = clean_text(value)
    key = normalize_for_compare(raw)
    if not key:
        return True
    if key in GENERIC_STRUCTURE_KEYS or key in GENERIC_AUTHOR_KEYS:
        return True
    if re.fullmatch(r"\d{1,4}(?:\s*[-–—]\s*\d{1,4})?", raw):
        return True
    # Treat descriptive collection wrappers as generic when they are clearly not
    # a person/series name by themselves.
    lowered = raw.lower()
    if any(word in lowered for word in ["chapterized", "complete series", "audiobook collection", "audio files"]):
        return True
    return False


def title_is_bad_after_cleanup(value: str) -> bool:
    value = sanitize_path_name(value, "")
    if not value:
        return True
    release_stripped = strip_release_bracket_tokens(value)
    release_stripped = strip_edition_descriptors(release_stripped)
    if not release_stripped:
        return True
    normalized_release = normalize_for_compare(release_stripped)
    if normalized_release in ARTICLE_ONLY_TITLE_KEYS:
        return True
    if normalized_release in GENERIC_PLACEHOLDER_TITLE_KEYS:
        return True
    if re.fullmatch(r"[\W_]+", value):
        return True
    if re.fullmatch(r"\d{1,4}(?:\.\d+)?", value):
        return True
    if value.startswith(","):
        return True
    if normalize_for_compare(value) in ARTICLE_ONLY_TITLE_KEYS:
        return True
    if is_marketing_descriptor(value):
        return True
    if re.fullmatch(r"(?:book|volume|vol\.?|v)\s*\d{1,4}(?:\.\d+)?", release_stripped, flags=re.IGNORECASE):
        return True
    return False


def normalize_series_key(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"\b(?:a|an|the)\b", " ", value)
    value = re.sub(r"\bseries\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def strip_leading_sort_prefix(value: str) -> str:
    """Remove ordering prefixes from folder-derived names.

    Examples:
      001 - Spellmonger -> Spellmonger
      029-033 - Side Story 013-017 -> Side Story 013-017
    """
    value = clean_text(value)
    value = re.sub(r"^\s*\d{1,4}(?:\s*[-–—]\s*\d{1,4})?\s*[-–—]\s*", "", value)
    return clean_text(value)


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
ARTICLE_ONLY_TITLE_KEYS = {"a", "an", "the"}
GENERIC_PLACEHOLDER_TITLE_KEYS = {"unknown", "unknowntitle", "untitled", "notitle"}


EDITION_DESCRIPTOR_RE = re.compile(
    r"(?:light\s+novel|web\s+novel|audio\s*book|audiobook|unabridged)",
    re.IGNORECASE,
)


def strip_edition_descriptors(value: str) -> str:
    """Remove generic edition/release descriptors, not story titles."""
    value = clean_text(value)
    if not value:
        return ""
    value = re.sub(
        r"\s*[\[(]\s*(?:light\s+novel|web\s+novel|audio\s*book|audiobook|unabridged)\s*[\])]\s*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"(?:\s*[-–—:,_]\s*|\s+)(?:light\s+novel|web\s+novel|audio\s*book|audiobook|unabridged)\s*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -_.:,")


# An ASIN (B0XXXXXXXX) or the fixer's "NOREALASIN" placeholder written for files
# with no real Audible ASIN. Neither may ever survive as a title or book name.
_NOREALASIN_RE = re.compile(r"no[\s._-]*real[\s._-]*asin", re.IGNORECASE)
_ASIN_TOKEN_RE = re.compile(r"(?:asin[\s._:-]*)?B0[A-Z0-9]{7,}", re.IGNORECASE)


def is_asin_like_token(value: str) -> bool:
    """True when the value is nothing but an ASIN or the NOREALASIN placeholder."""
    token = clean_text(value).strip("[](){} ")
    if not token:
        return False
    return bool(_NOREALASIN_RE.fullmatch(token) or _ASIN_TOKEN_RE.fullmatch(token))


def clean_asin_token(value: str) -> str:
    """Return a real ASIN as-is, or "" for the NOREALASIN placeholder/blank."""
    token = str(value or "").strip()
    if not token or _NOREALASIN_RE.fullmatch(token):
        return ""
    return token


def is_release_bracket_token(value: str) -> bool:
    """Return True for bracketed release metadata that should not become titles.

    Examples: [2025], [ENG], [ASIN.B0F94LCVMP], [128], [NOREALASIN].
    We intentionally keep meaningful edition labels such as [Booktrack Edition].
    """
    token = clean_text(value).strip("[](){} ")
    if not token:
        return True
    normalized = normalize_for_compare(token)
    if not normalized:
        return True
    if re.fullmatch(r"(?:19|20)\d{2}", token):
        return True
    if re.fullmatch(r"\d{2,4}", token):
        return True
    if re.fullmatch(r"\d+k(?:bps)?", token, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"(?:eng|en|english|heb|he|jpn|jp|ja|japanese)", token, flags=re.IGNORECASE):
        return True
    if _NOREALASIN_RE.fullmatch(token) or _ASIN_TOKEN_RE.fullmatch(token):
        return True
    if normalized in {
        "retail", "web", "webrip", "audible", "audiobook", "unabridged",
        "m4b", "m4a", "mp3", "opus", "flac", "eng", "english",
    }:
        return True
    return is_technical_label_block(token)


def strip_release_bracket_tokens(value: str) -> str:
    """Remove bracketed release tokens while preserving meaningful edition labels."""
    if not value:
        return ""

    def replace(match: re.Match) -> str:
        inner = match.group(1)
        return " " if is_release_bracket_token(inner) else match.group(0)

    value = re.sub(r"\[\s*([^\]]+?)\s*\]", replace, value)
    value = re.sub(r"\(\s*([^()]+?)\s*\)", replace, value)
    value = re.sub(r"\{\s*([^{}]+?)\s*\}", replace, value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -_.:,")


# Dramatized / full-cast special editions are shelved separately from the normal
# recordings of the same series ("Author / Series [Tag] / book") so the two
# editions never collide in one folder. The tag is the known imprint when one is
# identifiable, otherwise the generic "Dramatized" label.
_GRAPHICAUDIO_RE = re.compile(r"graphic\s*audio", re.IGNORECASE)
_SOUNDBOOTH_RE = re.compile(r"soundbooth(?:\s*theater)?", re.IGNORECASE)
_DRAMATIZED_RE = re.compile(r"dramati[sz]ed(?:\s+adaptation)?", re.IGNORECASE)
_EDITION_MARKER_RE = re.compile(
    r"\s*[\[(\{]\s*"
    r"(?:graphic\s*audio|soundbooth(?:\s*theater)?|dramati[sz]ed(?:\s+adaptation)?)"
    r"\s*[\])\}]",
    re.IGNORECASE,
)


def detect_edition_tag(*texts: str) -> str:
    """Return the special-edition tag for a dramatized/imprint production, or ''.

    Known imprints win over the generic label so GraphicAudio and Soundbooth
    Theater editions get their own named shelf; any other explicit "Dramatized
    Adaptation" marker falls back to "Dramatized".
    """
    blob = " ".join(t for t in texts if t)
    if not blob:
        return ""
    if _GRAPHICAUDIO_RE.search(blob):
        return "GraphicAudio"
    if _SOUNDBOOTH_RE.search(blob):
        return "Soundbooth Theater"
    if _DRAMATIZED_RE.search(blob):
        return "Dramatized"
    return ""


def strip_edition_marker(value: str) -> str:
    """Remove a bracketed imprint/dramatized marker so it does not pollute the
    series or title (it is carried separately as the edition tag)."""
    if not value:
        return value
    return clean_text(_EDITION_MARKER_RE.sub(" ", value))


GENERIC_MARKETING_DESCRIPTOR_RE = re.compile(
    r"^\s*(?:a|an|the)?\s*"
    r"(?:[a-z0-9’’]+[\s-]+){0,6}?"
    r"(?:"
    r"lit\s*rpg|litrpg|game\s*lit|gamelit|isekai|xianxia|wuxia|"
    r"cultivation|progression\s+fantasy|slice[\s-]*of[\s-]*life|"
    r"fantasy\s+adventure"
    r")\s*$",
    re.IGNORECASE,
)

# Trailing "special edition"-style tags with no real title content of their
# own, e.g. "(Swimsuit Edition)", "(Series Completion)", "(Director's Cut)".
# These convey a real fact about the release but aren't a distinct book
# title, so a bracketed group matching this should collapse the same way a
# repeated series name does.
GENERIC_EDITION_DESCRIPTOR_RE = re.compile(
    r"^\s*(?:the\s+)?(?:[a-z0-9']+[\s-]+){0,4}?"
    r"(?:edition|completion|cut|remaster(?:ed)?|version)\s*$",
    re.IGNORECASE,
)

# Matches the omnibus/collection label word(s) at the start of a title.
# Used to detect when a range-numbered book’s title is purely a collection
# descriptor (possibly followed by a redundant book-range suffix).
_OMNIBUS_LABEL_RE = re.compile(
    r"^\s*(?:the\s+)?"
    r"(?:"
    r"omnibus(?:es)?|"
    r"complete(?:\s+(?:series|collection|edition|works?))?|"
    r"publisher’?s?\s+pack|"
    r"box[\s-]*set|"
    r"bundle|"
    r"collect(?:ed(?:\s+(?:edition|works?))?|ion(?:\s+edition)?)?|"
    r"collector’?s?\s+edition"
    r")",
    re.IGNORECASE,
)


def strip_leading_sequence_for_noise(value: str) -> str:
    """Remove a leading sequence token only for descriptor/noise detection."""
    value = clean_text(value)
    return re.sub(
        r"^\s*(?:(?:book|books|vol\.?|volume|volumes|v)\s*)?"
        r"\d{1,4}(?:\.\d+)?\s*(?:[-–—:._]+\s*|\s+)",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(" -_.:,")


def is_marketing_descriptor(value: str) -> bool:
    value = clean_text(value)
    if not value:
        return False
    if is_title_noise(value):
        return True

    # Handles exposed leftovers such as "4 A Slice-of-Life LitRPG" after the
    # series and sequence are stripped. These should collapse to the series-only
    # title instead of becoming "Book 4 - 4 A Slice-of-Life LitRPG".
    candidate = strip_leading_sequence_for_noise(value)
    if candidate and candidate != value and is_title_noise(candidate):
        return True

    return bool(
        GENERIC_MARKETING_DESCRIPTOR_RE.fullmatch(value)
        or (candidate and candidate != value and GENERIC_MARKETING_DESCRIPTOR_RE.fullmatch(candidate))
    )


def _is_omnibus_descriptor(text: str, book_number: str) -> bool:
    """Return True when text is an omnibus/collection label, optionally followed
    by a book-range suffix that matches book_number.

    Used to detect titles like "Omnibus, Books 1-3" or "Complete Series, Books
    1-5" when book_number is already a range so the range is redundant in the
    folder name.  Only fires for range book numbers (those with '-') to avoid
    collapsing single-volume books that happen to have an omnibus-like label.
    """
    text = clean_text(text)
    if not text or "-" not in book_number:
        return False
    m = _OMNIBUS_LABEL_RE.match(text)
    if not m:
        return False
    remainder = text[m.end():].strip(" ,-_.:;")
    if not remainder:
        return True
    num_pat = number_match_pattern(book_number)
    if not num_pat:
        return False
    label_opt = r"(?:books?|vols?\.?|volumes?|v)?\s*"
    return bool(re.fullmatch(rf"{label_opt}{num_pat}", remainder, flags=re.IGNORECASE))


def remove_trailing_marketing_descriptor(value: str) -> str:
    return remove_trailing_title_noise(clean_text(value))


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

    value = strip_release_bracket_tokens(value)
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

    value = strip_edition_descriptors(value).strip(" -_.:,")
    if is_marketing_descriptor(value):
        return ""

    value = remove_trailing_marketing_descriptor(value)
    value = strip_edition_descriptors(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -_.:,")


def cleanup_title_artifacts(value: str) -> str:
    value = sanitize_book_title(value)
    if not value:
        return ""

    # Common release/file artifacts.
    value = value.replace("_", " ")
    value = strip_release_bracket_tokens(value)
    value = re.sub(r"\s*\[B0[A-Z0-9]{7,}\]\s*", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*\(B0[A-Z0-9]{7,}\)\s*", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*\{B0[A-Z0-9]{7,}\}\s*", " ", value, flags=re.IGNORECASE)
    # Curly-brace suffixes in release folders are usually narrator/uploader credits,
    # e.g. "Vol. 01 {John Patneaude}". They should not become book titles.
    value = re.sub(r"\s*\{[^{}]+\}\s*$", " ", value)
    value = strip_edition_descriptors(value)
    value = re.sub(r"\bM4B\b$", "", value, flags=re.IGNORECASE)
    # Strip common release-group bracket suffixes while preserving meaningful
    # edition labels such as [Booktrack Edition].
    value = re.sub(r"\s*\[(?:Seven Seas|Siren|Stick|Retail|WebRip|WEB|Audiobook|Unabridged)[^\]]*\]\s*", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+-\s+", " - ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -_.,")


def clean_series_name(value: str) -> str:
    value = sanitize_path_name(sanitize_book_title(value), "") if value else ""
    value = strip_leading_sort_prefix(value)
    value = re.sub(r"\s+series\s*$", "", value, flags=re.IGNORECASE)
    return sanitize_path_name(value, "") if value else ""


def clean_author_credit(value: str) -> str:
    value = clean_text(value)
    value = BROADCASTER_PREFIX_RE.sub("", value).strip()
    value = NON_AUTHOR_ROLE_RE.sub("", value).strip()
    aliases = {
        "リュート": "Ryuto",
        "cássio ferreira": "Cassio Ferreira",
        "cassio ferreira": "Cassio Ferreira",
        "mashton x x": "Mashton XX",
        "mashton x y": "Mashton XY",
        "mashton xx": "Mashton XX",
        "mashton xy": "Mashton XY",
    }
    value = aliases.get(value.casefold(), value)
    return sanitize_path_name(value, "")


def split_people(value: str) -> list[str]:
    value = clean_text(value)
    if not value:
        return []

    # Do not split author names on ampersands aggressively unless they are clear separators.
    value = re.sub(r"\s+(?:and|&)\s+", ", ", value, flags=re.IGNORECASE)
    parts = [clean_author_credit(part) for part in value.split(",")]
    people: list[str] = []
    seen = set()
    for person in parts:
        if not person:
            continue
        key = normalize_for_compare(person)
        if not key or key in seen:
            continue
        people.append(person)
        seen.add(key)
    return people


def clean_author_credits(value: str) -> str:
    value = re.sub(
        r"(?:^|,\s*)[^,]+?\s+-\s+editor\s*(?=,|$)",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(" ,")
    people = split_people(value)
    people_by_key = {
        re.sub(r"[^a-z0-9]+", " ", person.casefold()).strip(): person
        for person in people
    }
    if set(people_by_key) == {"j m clarke", "c j thompson"}:
        people = ["J.M. Clarke", "C.J. Thompson"]
    elif set(people_by_key) == {"mashton xx", "mashton xy"}:
        people = ["Mashton XX", "Mashton XY"]
    return ", ".join(people) if people else sanitize_path_name(value, "Unknown Author")



def parse_author_narrator_folder(value: str) -> tuple[str, str]:
    """Parse folders like 'Author - Narrator, Narrator'.

    This is intentionally conservative and is used only for path-derived
    author folders, not for legacy 'Series - Author - Narrator' containers.
    """
    cleaned = sanitize_path_name(cleanup_title_artifacts(value), "")
    if not cleaned:
        return "", ""
    parts = [part.strip() for part in re.split(r"\s+-\s+", cleaned) if part.strip()]
    if len(parts) >= 2:
        author = clean_author_credits(parts[0])
        narrator = sanitize_path_name(", ".join(parts[1:]), "")
        if author and not is_generic_structure_name(author):
            return author, narrator
        return "", ""
    return clean_author_credits(cleaned), ""


def author_is_probably_bad_for_series(author: str, series: str) -> bool:
    author_key = normalize_for_compare(primary_author(author))
    series_key = normalize_for_compare(series)
    if not author_key:
        return True
    if author_key in GENERIC_AUTHOR_KEYS or author_key in GENERIC_STRUCTURE_KEYS:
        return True
    if series_key and (author_key == series_key or keys_match(author_key, series_key)):
        return True
    # Bad sidecars sometimes set the author to a shortened series title, e.g.
    # author="Reborn as a Space Mercenary" for series="Reborn as a Space Mercenary - I Woke Up...".
    # Treat substantial prefix matches as bad so same-run/cache canonical author
    # information can repair them.
    if series_key and author_key and (series_key.startswith(author_key) or author_key.startswith(series_key)):
        shorter = min(len(author_key), len(series_key))
        if shorter >= 12:
            return True
    return False


def strip_metadata_suffixes_from_name(filename: str) -> str:
    value = filename
    for suffix in [
        ".audible-metadata-fixer.json",
        ".m4b-tool-metadata.json",
        ".metadata-backup.json",
    ]:
        if value.lower().endswith(suffix.lower()):
            value = value[: -len(suffix)]
    for ext in AUDIO_EXTENSIONS:
        if value.lower().endswith(ext.lower()):
            value = value[: -len(ext)]
    return sanitize_path_name(cleanup_title_artifacts(value), "")


def author_from_marker_filename(filename: str, series: str) -> str:
    """Recover author from marker filenames like 'G.D. Brooks - Dashing Devil 5 ...'.

    Some old markers have a bad author field equal to the series title.  When a
    marker filename clearly contains 'Author - Series ...', use that author as
    a higher-quality hint for the structure cache.
    """
    cleaned = strip_metadata_suffixes_from_name(filename)
    series = clean_series_name(series)
    if not cleaned or not series:
        return ""
    parts = [part.strip() for part in re.split(r"\s+-\s+", cleaned) if part.strip()]
    if len(parts) < 2:
        return ""
    left = parts[0]
    right = " - ".join(parts[1:])
    left_key = normalize_for_compare(left)
    series_key = normalize_for_compare(series)
    right_key = normalize_for_compare(right)
    if not left_key or not series_key:
        return ""
    if left_key == series_key or left_key in GENERIC_AUTHOR_KEYS or left_key in GENERIC_STRUCTURE_KEYS:
        return ""
    if right_key.startswith(series_key) or series_key in right_key[: max(len(series_key) + 8, len(series_key))]:
        return clean_author_credits(left)
    return ""

def primary_author(value: str) -> str:
    people = split_people(value)
    if people:
        for person in people:
            if normalize_for_compare(person) not in GENERIC_AUTHOR_KEYS:
                return person
        return people[0]
    return sanitize_path_name(value, "Unknown Author")


_SINGLE_INITIAL_RE = re.compile(r"[A-Za-z]\.?$")


def canonical_author_name(value: str) -> str:
    """Canonicalize initial spacing so name variants map to one author folder.

    Runs of consecutive single-letter initials are collapsed into a dotted,
    space-free cluster, so "J. R. R. Tolkien" and "J.R.R. Tolkien" both become
    "J.R.R. Tolkien" (and "George R. R. Martin" / "George R.R. Martin" both
    become "George R.R. Martin"). Non-initial tokens are left untouched.
    """
    if not value:
        return value
    parts = value.split()
    out: list[str] = []
    i = 0
    while i < len(parts):
        if _SINGLE_INITIAL_RE.fullmatch(parts[i]):
            run: list[str] = []
            while i < len(parts) and _SINGLE_INITIAL_RE.fullmatch(parts[i]):
                run.append(parts[i][0].upper())
                i += 1
            # Two or more adjacent initials collapse to "J.R.R."; a lone initial
            # just gets a normalizing dot ("J" -> "J.").
            out.append("".join(letter + "." for letter in run))
        else:
            out.append(parts[i])
            i += 1
    return " ".join(out)


def people_keys(value: str) -> list[str]:
    keys: list[str] = []
    for person in split_people(value):
        key = normalize_for_compare(person)
        if key and key not in keys:
            keys.append(key)
    if not keys:
        key = normalize_for_compare(value)
        if key:
            keys.append(key)
    return keys


def keys_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.92


def normalize_book_number(value: str, width: int = 3) -> str:
    value = clean_text(value)
    if not value:
        return ""

    # Ranges / omnibus books: 1-2, 1+2, or 1,2 -> 001-002.
    # Internally we normalize all range separators to '-' so folder names become
    # "Books 1-2" rather than the broken "Book 1 - +002" form.
    range_match = re.fullmatch(r"(\d{1,4})(?:\.0+)?\s*[-–—+,]\s*(\d{1,4})(?:\.0+)?", value)
    if range_match:
        return f"{int(range_match.group(1)):0{width}d}-{int(range_match.group(2)):0{width}d}"

    match = re.fullmatch(r"(\d{1,4})(\.\d+)?", value)
    if not match:
        return value

    whole, fraction = match.groups()
    if fraction:
        fraction = fraction.rstrip("0") or ".0"
    return f"{int(whole):0{width}d}{fraction or ''}"


def display_book_number(value: str) -> str:
    """Return the human-facing sequence number without leading zero padding.

    Internal metadata keeps normalized padded numbers for comparisons/cache keys,
    but folder names should be cleaner:
      001 -> 1
      003.5 -> 3.5
      001-002 -> 1-2
      001+002 -> 1+2
    """
    value = clean_text(str(value or ""))
    if not value:
        return ""

    def clean_part(part: str) -> str:
        part = clean_text(part)
        match = re.fullmatch(r"(\d+)(\.\d+)?", part)
        if not match:
            return part
        whole, fraction = match.groups()
        whole_clean = str(int(whole))
        if fraction:
            # Keep meaningful decimal side-story values, but remove useless
            # trailing zeroes. 003.50 -> 3.5, 003.0 -> 3.
            fraction = fraction.rstrip("0")
            if fraction == ".":
                fraction = ""
        return f"{whole_clean}{fraction or ''}"

    pieces = re.split(r"([-+])", value)
    return "".join(clean_part(piece) if piece not in {"-", "+"} else piece for piece in pieces)


def detect_number_from_text(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""

    range_patterns = [
        r"\bbooks?\s*#?\s*(\d{1,4})\s*[-–—+]\s*(\d{1,4})\b",
        r"\bbooks?\s*#?\s*(\d{1,4})\s*,\s*(\d{1,4})\b",
        r"\bvol(?:ume)?s?\.?\s*(\d{1,4})\s*[-–—+]\s*(\d{1,4})\b",
        r"\bvol(?:ume)?s?\.?\s*(\d{1,4})\s*,\s*(\d{1,4})\b",
        r"#\s*(\d{1,4})\s*[-–—+]\s*(\d{1,4})\b",
    ]
    for pattern in range_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            first, second = match.group(1), match.group(2)
            # Skip matches where either number has a leading zero (chapter/track
            # numbers like "01", "02") or the range is backwards — these are not
            # book ranges.  Example: "Book 3 - 01" is book 3, chapter 01, not
            # a range covering books 3 through 1.
            if first.startswith("0") or second.startswith("0"):
                continue
            if int(first) >= int(second):
                continue
            return normalize_book_number(f"{first}-{second}")

    word_pattern = r"\b(?:book|volume|vol\.?|novel|side\s*story)\s+(" + "|".join(NUMBER_WORDS) + r")\b"
    word_match = re.search(word_pattern, value, flags=re.IGNORECASE)
    if word_match:
        return normalize_book_number(NUMBER_WORDS[word_match.group(1).lower()])

    patterns = [
        r"\bside\s*story\s*#?\s*(\d{1,4}(?:\.\d+)?)\b",
        r"\bnovels?\s*#?\s*(\d{1,4}(?:\.\d+)?)\b",
        r"\bbook\s*#?\s*(\d{1,4}(?:\.\d+)?)\b",
        r"\bvol(?:ume)?\.?\s*(\d{1,4}(?:\.\d+)?)\b",
        r"\bv\s*(\d{1,4}(?:\.\d+)?)\b",
        r"#\s*(\d{1,4}(?:\.\d+)?)(?!\s*[-–—])\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return normalize_book_number(match.group(1))

    return ""

def normalize_sequence_label(value: str) -> str:
    """Normalize detected sequence wording for folder prefixes.

    Default ABS-friendly prefix remains "Book", but when the source/metadata
    explicitly says Vol./Volume/Side Story, keep that wording in the target
    book folder name.
    """
    value = clean_text(value).strip(" .:")
    if not value:
        return ""
    key = normalize_for_compare(value)
    if key in {"vol", "v"}:
        return "Vol."
    if key in {"volume", "volumes"}:
        return "Volume"
    if key in {"book", "books"}:
        return "Book"
    if key in {"sidestory", "sidestories"}:
        return "Side Story"
    if key in {"novel", "novels"}:
        return "Novel"
    return ""


def detect_sequence_label_from_text(value: str) -> str:
    """Detect whether a text used Book, Vol., Volume, or Side Story.

    This is intentionally conservative. It only returns a label when the label
    appears next to a sequence number/word, so ordinary words in titles do not
    accidentally change the target folder prefix.
    """
    value = clean_text(value)
    if not value:
        return ""

    number_word = "|".join(NUMBER_WORDS)
    checks = [
        (rf"\bside\s*stor(?:y|ies)\s*#?\s*(?:\d{{1,4}}(?:\.\d+)?|{number_word})\b", "Side Story"),
        (rf"\bnovels?\s*#?\s*(?:\d{{1,4}}(?:\.\d+)?|{number_word})\b", "Novel"),
        (rf"\bvol\.\s*(?:\d{{1,4}}(?:\.\d+)?|{number_word})\b", "Vol."),
        (rf"\bvols\.\s*(?:\d{{1,4}}(?:\.\d+)?|{number_word})\b", "Vol."),
        (rf"\bvol\s*(?:\d{{1,4}}(?:\.\d+)?|{number_word})\b", "Vol."),
        (rf"\bvolumes?\s*#?\s*(?:\d{{1,4}}(?:\.\d+)?|{number_word})\b", "Volume"),
        (rf"\bv\s*(?:\d{{1,4}}(?:\.\d+)?)\b", "Vol."),
        (rf"\bbooks?\s*#?\s*(?:\d{{1,4}}(?:\.\d+)?|{number_word})\b", "Book"),
    ]
    for pattern, label in checks:
        if re.search(pattern, value, flags=re.IGNORECASE):
            return label
    return ""


def choose_sequence_label(*values: str) -> str:
    """Choose a folder prefix from candidate labels/texts.

    Values are ordered by authority.  The first explicit label wins.  This is
    important during full-library consolidation: a folder named
    "Book 004 - Threads of Destiny Vol 1" should remain Book 004 because the
    leading folder label is the real ABS sequence.  The trailing "Vol 1" is
    part of the title, not the library sequence prefix.
    """
    for value in values:
        label = normalize_sequence_label(value) or detect_sequence_label_from_text(value)
        if label:
            return label
    return ""


def build_sequence_prefix(label: str, number: str) -> str:
    label = normalize_sequence_label(label) or "Book"
    if "-" in number:
        key = normalize_for_compare(label)
        if key == "book":
            label = "Books"
        elif key == "volume":
            label = "Volumes"
        elif key == "vol":
            label = "Vol."
        elif key == "novel":
            label = "Novels"
    return f"{label} {display_book_number(number)}"


def clean_title_from_number(title: str) -> str:
    title = clean_text(title)
    if not title:
        return ""

    title = re.sub(
        r"^\s*(?:books?|vol(?:ume)?s?\.?|v|side\s*story|novels?|#)?\s*\d{1,4}(?:\.\d+)?(?:\s*(?:[-–—]|,)\s*\d{1,4})?\s*[-_.: ]+\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    # Do not remove Book/Vol/Volume references from the middle/end of a title.
    # They can be legitimate subtitle information, e.g.
    # "Book 004 - Threads of Destiny Vol 1" should remain
    # "Threads of Destiny Vol 1" rather than "Threads of Destiny".
    word_pattern = r"^\s*(?:book|volume|vol\.?)\s+(?:" + "|".join(NUMBER_WORDS) + r")\b\s*[-:]*\s*"
    title = re.sub(word_pattern, "", title, flags=re.IGNORECASE)
    return clean_text(title).strip(" ,-:._")


def number_match_pattern(book_number: str) -> str:
    """Return a regex fragment that matches a normalized book number in source text."""
    number = clean_text(str(book_number or ""))
    if not number:
        return r""
    # Support normalized 001, 001.5, and ranges like 001-002 / 001+002.
    if "-" in number or "+" in number:
        parts = re.split(r"[-+]", number)
        sep = r"\s*[-+]\s*"
        return sep.join(rf"0*{int(part)}" if part.isdigit() else re.escape(part) for part in parts if part)
    whole, dot, frac = number.partition(".")
    if whole.isdigit():
        base = rf"0*{int(whole)}"
    else:
        base = re.escape(whole)
    if dot and frac:
        base += rf"(?:\.0*{re.escape(frac)})?"
    return base


def title_starts_with_series(title: str, series: str) -> bool:
    title_key = normalize_for_compare(title)
    series_key = normalize_for_compare(series)
    return bool(series_key and title_key.startswith(series_key))


def title_sequence_label_for_series(title: str, series: str, book_number: str) -> str:
    """Detect Vol./Volume only when it belongs to the main series title.

    This intentionally does NOT convert titles like "Threads of Destiny Vol 1"
    under series "Destiny Cycle" to Volume 004, because the source title does not
    start with the actual series folder name.
    """
    title = clean_text(title)
    series = clean_series_name(series)
    num_pat = number_match_pattern(book_number)
    if not title or not series or not num_pat:
        return ""
    base_title = strip_trailing_sequence_from_title(title, book_number)
    series_key = normalize_for_compare(series)
    base_key = normalize_for_compare(base_title)
    title_key = normalize_for_compare(title)
    if not title_starts_with_series(title, series) and not (base_key and base_key in series_key) and not (series_key and series_key in title_key):
        return ""

    # Prefer the exact spelling used in the title.
    if re.search(rf"\bvol\.\s*{num_pat}\b", title, flags=re.IGNORECASE):
        return "Vol."
    if re.search(rf"\bvolume\s*{num_pat}\b", title, flags=re.IGNORECASE):
        return "Volume"
    if re.search(rf"\bvol\s*{num_pat}\b", title, flags=re.IGNORECASE):
        return "Vol."
    if re.search(rf"\bv\s*{num_pat}\b", title, flags=re.IGNORECASE):
        return "Vol."
    return ""


def prefer_series_title_volume_label(current_label: str, title: str, series: str, book_number: str) -> str:
    """Keep Book when it is clearly the folder prefix, except for title==series+Vol cases.

    Light-novel titles often store the real sequence as "Vol." or "v02" inside
    the title while the existing folder was named "Book 01".  When the title is
    clearly the same as the series and contains the same number, prefer the
    volume wording.  Do not apply this to unrelated subtitles like
    "Destiny Cycle / Book 4 - Threads of Destiny Vol 1".
    """
    current = normalize_sequence_label(current_label) or current_label
    detected = title_sequence_label_for_series(title, series, book_number)
    if detected and (not current or normalize_for_compare(current) == "book"):
        return detected
    return current


def strip_redundant_series_sequence_title(title: str, series: str, book_number: str) -> str:
    """Collapse titles that are just '<Series> Book/Vol N' back to '<Series>'.

    Examples:
      All the Skills - Book 001 -> All the Skills
      Cinnamon Bun - Book 002 -> Cinnamon Bun
      Weaponsmith Volume 1 -> Weaponsmith
      Failure Frame ..., Vol. 1 -> Failure Frame ...
    """
    title = sanitize_path_name(cleanup_title_artifacts(title), "")
    series = clean_series_name(series)
    num_pat = number_match_pattern(book_number)
    if not title or not series or not num_pat:
        return title

    series_re = re.escape(series)
    label_re = r"(?:books?|vol(?:ume)?s?\.?|v|side\s*story|novels?|#)"
    # Exact/near-exact "series + sequence" forms.
    pattern = rf"^\s*(?:the\s+)?{series_re}\s*(?:[-_:,]\s*|\s+)?{label_re}\s*{num_pat}\s*$"
    if re.match(pattern, title, flags=re.IGNORECASE):
        return sanitize_path_name(series, title)

    # Same, but allow a comma before Vol./Volume.
    pattern = rf"^\s*(?:the\s+)?{series_re}\s*,\s*{label_re}\s*{num_pat}\s*$"
    if re.match(pattern, title, flags=re.IGNORECASE):
        return sanitize_path_name(series, title)

    # Punctuation-insensitive variant for titles like:
    #   "Reborn as a Space Mercenary I Woke Up..., Vol. 14 Light Novel"
    # where the canonical series uses a dash but the release title does not.
    title_key = normalize_for_compare(title)
    series_key = normalize_for_compare(series)
    if series_key and title_key.startswith(series_key):
        tail = title_key[len(series_key):]
        display_num = display_book_number(book_number)
        num_key = normalize_for_compare(display_num)
        if num_key:
            allowed_tail = re.compile(
                rf"^(?:book|books|vol|volume|volumes|v)?0*{re.escape(num_key)}(?:lightnovel|novel|audiobook)?$",
                re.IGNORECASE,
            )
            if allowed_tail.fullmatch(tail):
                return sanitize_path_name(series, title)

    return title



def strip_trailing_sequence_from_title(title: str, book_number: str) -> str:
    """Remove trailing Book/Vol/v sequence suffix from a title when it matches.

    Handles both bare suffixes ("Title - Book 2") and bracket/paren-wrapped
    ones ("Title (Book 2)"), since Audible/fixer titles use either form
    interchangeably to append a redundant sequence annotation that doesn't
    repeat the series name (so strip_series_sequence_parenthetical(), which
    requires the series name to appear inside the brackets, won't catch it).
    """
    title = sanitize_path_name(cleanup_title_artifacts(title), "")
    num_pat = number_match_pattern(book_number)
    if not title or not num_pat:
        return title
    label_re = r"(?:books?|vol(?:ume)?s?\.?|v|side\s*story|novels?|#)"
    pattern = (
        rf"\s*(?:[-_:,]\s*|\s+){label_re}\s*{num_pat}\s*$"
        rf"|\s*[\[(]\s*{label_re}\s*{num_pat}\s*[\])]\s*$"
    )
    candidate = re.sub(pattern, "", title, flags=re.IGNORECASE).strip(" -_:,.")
    if candidate and not title_is_bad_after_cleanup(candidate):
        return sanitize_path_name(candidate, title)
    return title

def strip_series_sequence_parenthetical(title: str, series: str, book_number: str) -> str:
    """Remove trailing parenthetical/bracketed series references from a title.

    Example:
      End of Trials (Paths of Akashic #2) -> End of Trials
    """
    title = sanitize_path_name(cleanup_title_artifacts(title), "")
    series = clean_series_name(series)
    if not title or not series:
        return title

    # Allow one level of nested "(...)"/"[...]" inside the trailing group so
    # doubled annotations like "Title 12 (Series (Completed Series))" are
    # recognized as a single trailing unit instead of leaking the inner
    # parenthetical into the cleaned title.
    match = re.search(
        r"\s*[\[(]((?:[^()\[\]]|\([^()]*\)|\[[^\[\]]*\])*)[\])]\s*$", title
    )
    if not match:
        return title

    inner = clean_text(match.group(1))
    inner_key = normalize_for_compare(inner)
    series_key = normalize_for_compare(series)
    if (not series_key or series_key not in inner_key) and not GENERIC_EDITION_DESCRIPTOR_RE.match(inner):
        return title

    inner_number = detect_number_from_text(inner)
    if book_number and inner_number and normalize_book_number(inner_number) != normalize_book_number(book_number):
        return title

    candidate = title[: match.start()].strip(" -_:,.")
    if candidate and not title_is_bad_after_cleanup(candidate):
        return sanitize_path_name(candidate, title)
    return title



def title_fragment_is_incomplete(value: str) -> bool:
    """Return True when a stripped title fragment is grammatically incomplete.

    This prevents false series-suffix stripping such as:
      Rise of the Shadow Rogue -> Rise of the

    while still allowing real redundant suffix cleanup such as:
      King of Shadows Shadow Rogue -> King of Shadows
    """
    value = clean_text(value).strip(" -_:,.")
    if not value:
        return True
    # A dangling connector symbol ("Carter &") is incomplete even though the
    # word tokenizer below ignores "&" entirely and would otherwise see a
    # single, unremarkable trailing word.
    if re.search(r"[&/+]\s*$", value):
        return True
    tokens = re.findall(r"[A-Za-z0-9']+", value.lower())
    if not tokens:
        return True
    if len(tokens) <= 2 and tokens[-1] in {"a", "an", "the"}:
        return True
    return tokens[-1] in {
        "a", "an", "the",
        "of", "to", "for", "from", "with", "without",
        "in", "on", "at", "by", "into", "onto", "over", "under",
        "and", "or", "but",
    }


def strip_trailing_series_from_title(title: str, series: str) -> str:
    """Remove a redundant trailing series name from a parsed title.

    This fixes MP3/OPUS folder names such as:
      Critical Failures IV The Phantom Pinas Caverns and Creatures
    when the containing folder/cache already proves the series is
    "Caverns and Creatures".
    """
    title = sanitize_path_name(cleanup_title_artifacts(title), "")
    series = clean_series_name(series)
    if not title or not series:
        return title
    if normalize_for_compare(title) == normalize_for_compare(series):
        return title
    pattern = re.compile(rf"(?:\s*[-_:,]\s*|\s+){re.escape(series)}\s*$", re.IGNORECASE)
    candidate = pattern.sub("", title).strip(" -_:,.")
    if (
        candidate
        and not title_is_bad_after_cleanup(candidate)
        and not title_fragment_is_incomplete(candidate)
    ):
        return sanitize_path_name(candidate, title)
    return title


def strip_series_prefix(title: str, series: str) -> str:
    title = sanitize_path_name(title, "Unknown Title")
    series = clean_series_name(series)
    if not series:
        return title
    # Only strip a leading series name when it is followed by a separator or by
    # a sequence number.  Do not strip possessive/title words such as
    # "Spellmongers wedding" or "The Spellmonger's Yule".
    series_re = re.escape(series)
    pattern = re.compile(
        rf"^\s*(?:the\s+)?{series_re}(?:\s*[-:._,]+\s*|\s+(?=(?:book|books|vol\.?|volume|v|#)?\s*(?:\d|[ivxlcdm]+\b)))",
        re.IGNORECASE,
    )
    stripped = pattern.sub("", title, count=1).strip(" -:._")
    if stripped != title:
        return stripped or title

    # Metadata-confirmed series names may be repeated without punctuation:
    # "Dashing Devil Bold Beginnings". Limit this form to substantial series
    # names so short legitimate title prefixes such as "It" are preserved.
    series_words = re.findall(r"[A-Za-z0-9]+", series)
    series_key = normalize_for_compare(series)
    if len(series_key) < 5 and len(series_words) < 2:
        return title
    flexible_series = r"[\W_]*".join(re.escape(word) for word in series_words)
    plain_pattern = re.compile(
        rf"^\s*(?:the\s+)?{flexible_series}\s+(?=\S)",
        re.IGNORECASE,
    )
    candidate = plain_pattern.sub("", title, count=1).strip(" -:._")
    # Require a multi-word remainder when there is no separator: a single bare
    # word after stripping (e.g. "The Bright Lord" → "Lord") means the series
    # name is part of the title itself, not a redundant prefix decoration.
    if candidate and not title_is_bad_after_cleanup(candidate) and " " in candidate:
        return candidate
    return title


def clean_book_title(title: str, series: str, book_number: str, fallback: str = "Unknown Title", trusted: bool = False) -> str:
    if trusted:
        # Trusted Audible titles skip cleanup_title_artifacts/sanitize_book_title
        # which wholesale-wipes titles containing genre keywords like "cultivation".
        # We still strip TRAILING marketing suffixes ("1% Lifesteal: A LitRPG
        # Adventure" → "1% Lifesteal") and series prefixes ("Dashing Devil 5 -
        # Bold Beginnings" → "Bold Beginnings"), but only when the result is
        # non-trivial so "The Bright Lord" (series "The Bright") stays intact.
        cleaned = sanitize_path_name(title, "") or fallback
        # Strip technical release tokens (bitrate, codec, year) that survive
        # sanitize_path_name.  cleanup_title_artifacts is intentionally skipped
        # for trusted titles to avoid wiping genre keywords, but release tokens
        # such as (128k) or [WEB] are never real title content.
        cleaned = strip_release_bracket_tokens(cleaned).strip(" -_.,") or cleaned
        # Strip trailing marketing descriptor suffix if present.
        without_suffix = remove_trailing_marketing_descriptor(cleaned)
        if without_suffix and without_suffix != cleaned:
            cleaned = without_suffix.strip(" -_.,")
        series_clean = clean_series_name(series)
        # Strip a trailing "(Series Book N)" annotation the same way the
        # untrusted cleanup path does (e.g. "Rebirth (Dread Knight Book 4)"
        # -> "Rebirth"). Trusted Audible/fixer titles occasionally bake this
        # redundant annotation directly into the chosen title.
        paren_stripped = strip_series_sequence_parenthetical(cleaned, series_clean, book_number)
        if paren_stripped and paren_stripped != cleaned and not title_is_bad_after_cleanup(paren_stripped):
            cleaned = paren_stripped
        # Strip a bare trailing "(Book N)"/"(Vol. N)" annotation even when it
        # doesn't repeat the series name, e.g. "The Subtle Knife (Book 2)"
        # -> "The Subtle Knife". strip_series_sequence_parenthetical() only
        # fires when the series name itself appears inside the brackets.
        sequence_stripped = strip_trailing_sequence_from_title(cleaned, book_number)
        if sequence_stripped and sequence_stripped != cleaned and not title_is_bad_after_cleanup(sequence_stripped):
            cleaned = sequence_stripped
        stripped = strip_series_prefix(cleaned, series_clean)
        _has_sep = bool(re.search(r"[-:,]|\d", cleaned))
        if stripped != cleaned and not title_is_bad_after_cleanup(stripped) and (_has_sep or " " in stripped):
            cleaned = stripped
            numbered = clean_title_from_number(cleaned)
            if numbered and not title_is_bad_after_cleanup(numbered):
                cleaned = numbered
        elif stripped != cleaned and title_is_bad_after_cleanup(stripped) and series_clean and book_number:
            # strip_series_prefix left only "Book N" or a similar bare label —
            # the full title is just <Series> + sequence. Collapse it to the
            # series name so build_book_folder_name() emits "Book 001" instead
            # of repeating the series name as the folder title.
            redundant = strip_redundant_series_sequence_title(cleaned, series_clean, book_number)
            if redundant and not title_is_bad_after_cleanup(redundant):
                cleaned = redundant
        # A trailing series name can be exposed only after the sequence
        # annotation above was removed, e.g. "Morningwood - Everybody Loves
        # Large Chests (Vol.1)" -> "Morningwood - Everybody Loves Large
        # Chests" -> "Morningwood".
        trailing_series_stripped = strip_trailing_series_from_title(cleaned, series_clean)
        if (
            trailing_series_stripped
            and trailing_series_stripped != cleaned
            and not title_is_bad_after_cleanup(trailing_series_stripped)
        ):
            cleaned = trailing_series_stripped
        return cleaned or fallback
    cleaned_seed = cleanup_title_artifacts(title)
    if not cleaned_seed and series:
        # If the only available title is a generic marketing subtitle, fall back
        # to the series title. build_book_folder_name() will then collapse
        # series+number entries to just "Book N" / "Vol. N" instead of
        # creating folders like "Book 1 - A Xianxia Progression Fantasy".
        cleaned_seed = clean_series_name(series)
    original = sanitize_path_name(cleaned_seed, fallback)
    original = strip_series_sequence_parenthetical(original, series, book_number)
    redundant = strip_redundant_series_sequence_title(original, series, book_number)
    cleaned = redundant if redundant and not title_is_bad_after_cleanup(redundant) else original

    # Remove the series prefix only when doing so leaves a useful book title.
    stripped = strip_series_prefix(cleaned, series)
    if not title_is_bad_after_cleanup(stripped):
        cleaned = stripped
    elif (
        stripped
        and stripped != cleaned
        and not re.fullmatch(r"[\W_]+", stripped)
        and not re.fullmatch(r"\d{1,4}(?:\.\d+)?", stripped)
        and not re.fullmatch(
            r"(?:book|volume|vol\.?|v)\s*\d{1,4}(?:\.\d+)?",
            stripped,
            flags=re.IGNORECASE,
        )
    ):
        # The subtitle after stripping the series prefix is a genre descriptor
        # (e.g. "A LitRPG Adventure") but is still better than repeating the
        # series name in the folder. Use it as long as it has real content.
        cleaned = stripped
    elif normalize_for_compare(cleaned) != normalize_for_compare(redundant):
        # If the only thing left after stripping the series is "Book 001" or
        # "Volume 001", keep the clean series title rather than duplicating the
        # sequence in the final folder.
        fallback_title = strip_redundant_series_sequence_title(cleaned, series, book_number)
        if fallback_title and not title_is_bad_after_cleanup(fallback_title):
            cleaned = fallback_title

    numbered = clean_title_from_number(cleaned)
    if numbered and not title_is_bad_after_cleanup(numbered):
        cleaned = numbered

    trailing_series_stripped = strip_trailing_series_from_title(cleaned, series)
    if trailing_series_stripped and not title_is_bad_after_cleanup(trailing_series_stripped):
        cleaned = trailing_series_stripped

    if book_number and re.fullmatch(r"\d{3}(?:\.\d+)?", book_number):
        whole, _dot, fraction = book_number.partition(".")
        number_pattern = rf"0*{int(whole)}"
        if fraction:
            number_pattern += rf"(?:\.0*{re.escape(fraction)})?"
        cleaned2 = re.sub(
            rf"^\s*(?:book\s*)?{number_pattern}(?!\s*%)(?:\b|\s*[-:._]+\s*)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" -:._")
        if cleaned2 and not title_is_bad_after_cleanup(cleaned2):
            cleaned = cleaned2

    trailing_stripped = strip_trailing_sequence_from_title(cleaned, book_number)
    if trailing_stripped and not title_is_bad_after_cleanup(trailing_stripped):
        cleaned = trailing_stripped

    # A trailing series name can be exposed only after the sequence
    # annotation above was removed (e.g. a bracket-wrapped "(Vol. N)" with
    # no series name inside it), so re-check for one now.
    trailing_series_stripped_again = strip_trailing_series_from_title(cleaned, series)
    if trailing_series_stripped_again and not title_is_bad_after_cleanup(trailing_series_stripped_again):
        cleaned = trailing_series_stripped_again

    final_redundant = strip_redundant_series_sequence_title(cleaned, series, book_number)
    if final_redundant and not title_is_bad_after_cleanup(final_redundant):
        cleaned = final_redundant

    if title_is_bad_after_cleanup(cleaned):
        # For trusted Audible titles, don't replace with the series name — the
        # title is canonical even if it matches a genre noise pattern
        # (e.g. "The Fifth Law of Cultivation" ends with "cultivation").
        cleaned = original if trusted else (clean_series_name(series) if series else original)

    # Final pass after all title transformations: remove any release/edition
    # fragments that were exposed by sequence/series stripping.
    cleaned = cleanup_title_artifacts(cleaned) or cleaned
    if title_is_bad_after_cleanup(cleaned) and series:
        cleaned = clean_series_name(series)

    return sanitize_path_name(cleaned, fallback)


def metadata_series_suffix_number(title: str, series: str) -> str:
    """Recover a number from a metadata title shaped like '<Series> 03'."""
    title = sanitize_path_name(cleanup_title_artifacts(title), "")
    series = clean_series_name(series)
    if not title or not series:
        return ""

    remainder = strip_series_prefix(title, series)
    if normalize_for_compare(remainder) == normalize_for_compare(title):
        return ""
    if not re.fullmatch(r"\d{1,4}(?:\.\d+)?", remainder):
        return ""
    if re.fullmatch(r"(?:19|20)\d{2}", remainder):
        return ""
    return normalize_book_number(remainder)



def small_series_suffix_number_from_text(value: str, series: str) -> str:
    """Recover a small bare suffix from text shaped like '<Series> 2'.

    This is intentionally narrower than detect_number_from_text().
    It exists for series where the title/path itself is the numbered title:
      Returner's Defiance 2
      Corruption Wielder 2
      System Overclocked 3

    It deliberately ignores 3+ digit suffixes so real titles/courses like:
      Dungeon Diving 204
      Dungeon Diving 301
    do not become Book 204 / Book 301.
    """
    value = sanitize_path_name(cleanup_title_artifacts(value), "")
    series = clean_series_name(series)
    if not value or not series:
        return ""

    remainder = strip_series_prefix(value, series)
    if normalize_for_compare(remainder) == normalize_for_compare(value):
        return ""
    if not re.fullmatch(r"\d{1,2}(?:\.\d+)?", remainder):
        return ""
    if re.fullmatch(r"(?:19|20)\d{2}", remainder):
        return ""
    return normalize_book_number(remainder)

def has_distinct_book_title(title: str, series: str, book_number: str) -> bool:
    """Return True when title contains content beyond series/sequence text."""
    title = sanitize_path_name(cleanup_title_artifacts(title), "")
    series = clean_series_name(series)
    number = normalize_book_number(book_number)
    if not title or title_is_bad_after_cleanup(title):
        return False
    if series and normalize_for_compare(title) == normalize_for_compare(series):
        return False

    remainder = strip_series_prefix(title, series) if series else title
    if series and normalize_for_compare(remainder) == normalize_for_compare(title):
        remainder = title

    if number:
        if (
            normalize_for_compare(remainder)
            == normalize_for_compare(display_book_number(number))
            or (
                re.fullmatch(r"\d{1,4}(?:\.\d+)?", remainder)
                and normalize_book_number(remainder) == number
            )
        ):
            return False
        if (
            detect_number_from_text(remainder) == number
            and re.fullmatch(
                r"(?:book|volume|vol\.?|v|novel|side\s*story)\s+"
                r"(?:" + "|".join(NUMBER_WORDS) + r"|\d{1,4}(?:\.\d+)?)",
                clean_text(remainder),
                flags=re.IGNORECASE,
            )
        ):
            return False

    return not title_is_bad_after_cleanup(remainder)


def person_segment_matches(segment: str, people: list[str]) -> bool:
    """Return True when a dash-separated title segment is probably a known author.

    This intentionally allows a small typo tolerance for cases such as a folder
    saying "Andre Rowe" while Audible metadata says "Andrew Rowe".
    """
    segment_key = normalize_for_compare(segment)
    if not segment_key:
        return False

    for person in people:
        person_key = normalize_for_compare(person)
        if not person_key:
            continue
        if segment_key == person_key:
            return True
        # Allow small spelling differences and initials, but do not treat a
        # long title segment as a person just because it contains a narrator
        # name in parentheses.
        if segment_key in person_key or person_key in segment_key:
            shorter = min(len(segment_key), len(person_key))
            longer = max(len(segment_key), len(person_key))
            if longer and shorter / longer >= 0.75:
                return True
        if SequenceMatcher(None, segment_key, person_key).ratio() >= 0.84:
            return True

    return False


def strip_author_narrator_noise_from_title(title: str, author: str, narrator: str = "", trusted: bool = False) -> str:
    """Remove common folder-name decorations once author/narrator are known.

    Handles examples like:
      Ryan Eisenhower - Starship Tigress
      How to Defeat ... - Andrew/Andre Rowe - Narrator
      Dan Raxor, Jace Cannon - Supers of Vault 12

    When trusted=True (Audible-matched metadata), skip cleanup_title_artifacts
    so genre-keyword titles like "The Fifth Law of Cultivation" are not wiped
    before the author/narrator stripping logic runs.
    """
    value = sanitize_path_name(title if trusted else cleanup_title_artifacts(title), "")
    if not value:
        return value

    people = split_people(author) + split_people(narrator)
    if not people:
        return value

    # Remove trailing " - Author - Narrator" or " - Author". This works even
    # when the folder has a minor typo in the author name.
    dash_parts = [part.strip() for part in re.split(r"\s+-\s+", value) if part.strip()]
    if len(dash_parts) >= 2:
        for index in range(1, len(dash_parts)):
            if person_segment_matches(dash_parts[index], people):
                candidate = " - ".join(dash_parts[:index]).strip(" -")
                if candidate and not title_is_bad_after_cleanup(candidate):
                    value = candidate
                break

    # Remove leading "Author - ". For co-author prefixes, remove all text up to
    # the first dash only when the known primary author appears before that dash.
    before_dash, sep, after_dash = value.partition(" - ")
    if sep and person_segment_matches(before_dash, people):
        candidate = after_dash.strip(" -")
        if candidate and not title_is_bad_after_cleanup(candidate):
            value = candidate

    # Remove trailing parenthetical narrator/performer credits when they match
    # known people.  Example: "The Grinding (Jeff Hays, Annie Ellicott)".
    paren_match = re.search(r"\s*\(([^()]+)\)\s*$", value)
    if paren_match:
        inner = paren_match.group(1)
        inner_people = split_people(inner)
        looks_like_person_credit = bool(re.search(r"[A-Z][a-z]+\s+[A-Z][A-Za-z]+", inner)) and not re.search(r"[#\d]", inner)
        if (inner_people and all(person_segment_matches(person, people) for person in inner_people)) or looks_like_person_credit:
            candidate = value[:paren_match.start()].strip(" -")
            if candidate and not title_is_bad_after_cleanup(candidate):
                value = candidate

    # Remove trailing "by Author" credits when they match the known author.
    by_match = re.search(r"\s+by\s+(.+?)\s*$", value, flags=re.IGNORECASE)
    if by_match and person_segment_matches(by_match.group(1), people):
        candidate = value[: by_match.start()].strip(" -")
        if candidate and not title_is_bad_after_cleanup(candidate):
            value = candidate

    # Some sidecars/filenames append the author without a dash, e.g.
    # "Feedback Dennis E. Taylor". If the suffix is an exact known person and
    # removing it leaves a real title, strip it.
    for person in sorted(people, key=len, reverse=True):
        person = clean_text(person)
        if not person:
            continue
        suffix_re = re.compile(rf"\s+{re.escape(person)}\s*$", re.IGNORECASE)
        candidate = suffix_re.sub("", value).strip(" -_.:,")
        if candidate != value and candidate and not title_is_bad_after_cleanup(candidate):
            value = candidate
            break

    return sanitize_path_name(value, title)


def parse_representative_track_name(name: str) -> dict[str, str]:
    """Parse a grouped track name only when its final segment is numeric."""
    cleaned = sanitize_path_name(cleanup_title_artifacts(name), "")
    if not cleaned:
        return {}

    parts = [part.strip() for part in re.split(r"\s+[-–—]\s+", cleaned) if part.strip()]
    if len(parts) == 3 and re.fullmatch(r"\d{1,4}", parts[2]):
        author, title, _track = parts
        looks_like_author = (
            "," in author
            or bool(re.search(r"\b[A-Z][a-z]+\s+[A-Z]", author))
            or bool(re.search(r"\b[A-Z]\.\s*[A-Z]", author))
            or bool(re.search(r"\b[A-Z]{2,}\s+[A-Z][a-z]+", author))
        )
        if looks_like_author and not re.search(r"\d", author):
            return {"author": author, "title": title}
    return {}


def parse_standalone_book_folder_name(name: str) -> dict[str, str]:
    """Parse root-level standalone folders, not representative filenames.

    Examples:
      Title - Author - Narrator
      Author - Title
      Author, Coauthor - Title
    """
    cleaned = sanitize_path_name(cleanup_title_artifacts(name), "")
    if not cleaned:
        return {}

    if re.match(r"^\s*\d{1,4}(?:\s*[-–—]\s*\d{1,4})?\s*[-–—]", cleaned):
        return {}

    representative = parse_representative_track_name(cleaned)
    if representative:
        return representative

    parts = [part.strip() for part in re.split(r"\s+[-–—]\s+", cleaned) if part.strip()]
    if len(parts) >= 3:
        # A bracket/paren-wrapped middle segment (e.g. "[Series-2]") is a
        # release/series-sequence tag, never a real author credit. Trusting
        # it here misassigns the real title text (the last segment) to
        # "narrator", which later gets stripped out of the title as noise.
        candidate_author = parts[1]
        if not re.fullmatch(r"[\[(].*[\])]", candidate_author):
            return {"title": parts[0], "author": candidate_author, "narrator": ", ".join(parts[2:])}

    if len(parts) == 2:
        left, right = parts
        # Treat "Name - Title" as author/title only when the left side looks like a person/credit,
        # not when it looks like a numbered series/title container.
        if not re.search(r"\d", left) and ("," in left or re.search(r"\b[A-Z][a-z]+\s+[A-Z]", left) or re.search(r"\b[A-Z]\.\s*[A-Z]", left)):
            return {"author": left, "title": right}

    return {}


def is_generic_track_title(value: str) -> bool:
    value = clean_text(value).lower()
    if not value:
        return True
    return any(re.fullmatch(pattern, value, flags=re.IGNORECASE) for pattern in GENERIC_TRACK_TITLE_PATTERNS)


def run_ffprobe(file_path: Path) -> dict[str, str]:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(file_path)]
    try:
        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}

    if result.returncode != 0:
        return {}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    tags = data.get("format", {}).get("tags", {}) or {}
    return {
        str(key).lower(): str(value).strip()
        for key, value in tags.items()
        if str(value).strip()
    }


def first_tag(tags: dict[str, str], keys: list[str], default: str = "") -> str:
    for key in keys:
        value = tags.get(key.lower(), "").strip()
        if value:
            return value
    return default


def is_supported_audio(file_path: Path) -> bool:
    suffix = file_path.suffix.lower()
    name_lower = file_path.name.lower()
    if suffix in IGNORED_EXTENSIONS:
        return False
    if suffix not in AUDIO_EXTENSIONS:
        return False
    if any(marker in name_lower for marker in IGNORED_FILE_MARKERS):
        return False
    return True


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
    except (subprocess.SubprocessError, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    return len(data.get("chapters", []) or [])


def normalize_part_filename(value: str) -> str:
    value = html.unescape(str(value or "")).lower()
    value = re.sub(r"\[[^\]]+\]", " ", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[_.\-–—:]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def looks_like_chapter_part_filename(file_path: Path) -> bool:
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
# "001 - ...", "001 Author - Book Title - Chapter ...". The punctuation
# separator is optional -- some release conventions (e.g. Eric Vall's Pocket
# Dungeon rips) use a bare space between the zero-padded index and the rest
# of the name. Leading zeros are tolerated; the captured value is the index.
_LEADING_ORDINAL_RE = re.compile(r"^\s*0*(\d{1,4})\s*[.)\]_-]?\s+(?=\S)")

MIN_LEADING_ORDINAL_PARTS = 3
MIN_SHARED_IDENTITY_TOKENS = 2


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


def _common_leading_tokens(token_lists: list[list[str]]) -> list[str]:
    """Longest run of tokens shared at the START of every token list."""
    if not token_lists:
        return []
    common = list(token_lists[0])
    for tokens in token_lists[1:]:
        shared = 0
        while shared < len(common) and shared < len(tokens) and common[shared] == tokens[shared]:
            shared += 1
        common = common[:shared]
        if not common:
            break
    return common


def leading_ordinal_sequence_files(file_paths: list[Path]) -> set[Path]:
    """Recognize ONE book split into many leading-ordinal-numbered parts.

    Example: "0. Opening Credits - The Book - Narrator", "1. Time Starts Now -
    The Book - Narrator", ... "71. ...". The varying part (chapter title) can
    sit at either end of the shared identity -- after the number and before
    the book/narrator suffix ("0. Opening Credits - The Book - Narrator"), or
    after the book/author identity and before the chapter title ("001 Author
    - The Book - Opening Credits"). Group them when:
      * every matched ordinal is unique and they form a contiguous run from 0/1,
      * there are at least MIN_LEADING_ORDINAL_PARTS of them,
      * the parts share a common identity at the front OR the back (whichever
        side isn't the varying chapter title).
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
    shared_identity = max(
        len(_common_trailing_tokens(token_lists)),
        len(_common_leading_tokens(token_lists)),
    )
    if shared_identity < MIN_SHARED_IDENTITY_TOKENS:
        return set()

    return {by_number[n][0] for n in numbers}


def part_sequence_files(file_paths: list[Path]) -> set[Path]:
    """Files that belong to a recognized numbered part sequence.

    Prefers an explicit part marker (Part N, Disc N, "N of M") found anywhere
    in the name; falls back to trailing "- 01" numbering (shared-prefix
    groups); falls back to leading-ordinal chapter splits.

    This only narrows *which files* are considered as a candidate sequence --
    it never overrides the embedded-chapter-count safety check. A filename
    marker alone cannot distinguish a real multi-part split from two separate
    (or duplicate) complete recordings that happen to share a naming token, so
    a file with a real high chapter count is still rejected as a likely
    complete audiobook regardless of what its name says.
    """
    return (
        marker_sequence_files(file_paths)
        or numeric_part_sequence_files(file_paths)
        or leading_ordinal_sequence_files(file_paths)
    )


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

    if chapter_count <= MAX_CHAPTERS_PER_MULTI_PART_FILE and suffix != ".m4b":
        return True, "no embedded chapters or one wrapper chapter"
    if (
        chapter_count <= MAX_LOW_EMBEDDED_CHAPTERS_PER_NAMED_PART_FILE
        and chapter_named
    ):
        return True, f"low embedded chapter count ({chapter_count}) with chapter-like filename"
    if suffix == ".m4b" and chapter_count <= MAX_CHAPTERS_PER_MULTI_PART_FILE:
        return False, "low chapter count M4B lacks a chapter-like filename"
    return False, f"embedded chapter count {chapter_count} suggests a complete audiobook"


def validate_multi_part_group_files(file_paths: list[Path]) -> dict[str, Any]:
    checked_files = []
    unsafe_files = []
    numeric_parts = part_sequence_files(file_paths)

    for file_path in sorted(file_paths, key=natural_audio_sort_key):
        if file_path.suffix.lower() not in CHAPTER_METADATA_EXTENSIONS:
            continue
        chapter_count = read_file_chapter_count(file_path)
        safe_as_part, reason = classify_multi_part_file_safety(
            file_path,
            chapter_count,
            numeric_part_sequence=file_path in numeric_parts,
        )
        result = {
            "file": str(file_path),
            "chapter_count": chapter_count,
            "safe_as_part": safe_as_part,
            "reason": reason,
        }
        checked_files.append(result)
        if not safe_as_part:
            unsafe_files.append(result)

    return {
        "safe": not unsafe_files,
        "checked_files": checked_files,
        "unsafe_files": unsafe_files,
    }


def matches_skip_patterns(
    source_path: Path, metadata: dict[str, Any], patterns: list[str]
) -> tuple[bool, str]:
    """Return True when a book should be skipped by user-supplied patterns.

    Patterns are case-insensitive plain substrings checked against the source
    path and the inferred metadata fields. Mirrors the fixer's
    ``matches_skip_patterns`` so the same skip list works consistently across
    both tools.
    """
    if not patterns:
        return False, ""

    haystack = " ".join(
        [
            str(source_path),
            metadata.get("title", ""),
            metadata.get("series", ""),
            metadata.get("author", ""),
            metadata.get("narrator", ""),
        ]
    ).lower()

    for pattern in patterns:
        needle = str(pattern or "").strip().lower()
        if needle and needle in haystack:
            return True, pattern

    return False, ""


def should_ignore_path(path: Path, root: Path) -> bool:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        relative_parts = path.parts
    ignored = {item.lower() for item in IGNORED_DIR_NAMES}
    return bool({part.lower() for part in relative_parts} & ignored)


def direct_supported_audio_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        (
            item
            for item in directory.iterdir()
            if item.is_file() and is_supported_audio(item)
        ),
        key=natural_audio_sort_key,
    )


def contains_nested_supported_audio(directory: Path) -> bool:
    for child in directory.iterdir():
        if not child.is_dir():
            continue
        for candidate in child.rglob("*"):
            if candidate.is_file() and is_supported_audio(candidate):
                return True
    return False


def has_track_number_prefix(file_path: Path) -> bool:
    return bool(re.match(r"^\s*\d{1,4}(?:\s*/\s*\d{1,4})?\s*[-_.: ]+\S", file_path.stem))


def looks_like_multi_file_book(audio_files: list[Path]) -> bool:
    if len(audio_files) <= 1:
        return True

    suffixes = {file_path.suffix.lower() for file_path in audio_files}
    if not suffixes or not suffixes <= MULTI_PART_AUDIO_EXTENSIONS:
        return False

    numeric_parts = part_sequence_files(audio_files)
    validation_files = (
        sorted(numeric_parts, key=natural_audio_sort_key)
        if len(numeric_parts) >= 2
        else audio_files
    )
    validation = validate_multi_part_group_files(validation_files)
    if validation["safe"]:
        return True

    print(
        "WARNING: not grouping multi-file folder with embedded chapters: "
        f"{audio_files[0].parent}",
        file=sys.stderr,
    )
    for unsafe in validation["unsafe_files"]:
        print(
            "  unsafe: "
            f"{unsafe['file']} "
            f"chapters={unsafe['chapter_count']} "
            f"reason={unsafe['reason']}",
            file=sys.stderr,
        )
    return False


def is_multi_part_audio_candidate(source: Path) -> bool:
    return source.suffix.lower() in MULTI_PART_AUDIO_EXTENSIONS


def build_multi_part_group_map(files: list[Path]) -> dict[Path, list[Path]]:
    """Ported from the fixer's build_multi_part_group_map: narrow each folder's
    files down to the recognized part-sequence subset and validate only that
    subset, so an unrelated extra file (e.g. a separately merged single-file
    edition left alongside its own un-cleaned-up source chapters) can't poison
    the whole folder's grouping decision.

    Returns {folder: candidate_files} only for folders where a safe group was
    found; the caller treats candidate_files as one book and anything else in
    that same folder as its own separate item (mirroring the fixer's
    build_processing_items).
    """
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
        validation = validate_multi_part_group_files(candidate_files)
        if not validation.get("safe", True):
            print(
                f"WARNING: not grouping multi-file folder with embedded chapters: {parent}",
                file=sys.stderr,
            )
            for unsafe in validation.get("unsafe_files", []):
                print(
                    "  unsafe: "
                    f"{unsafe.get('file')} "
                    f"chapters={unsafe.get('chapter_count')} "
                    f"reason={unsafe.get('reason', '-')}",
                    file=sys.stderr,
                )
            continue

        accepted[parent] = candidate_files

    return accepted


def build_book_items(root: Path, destination_root: Path, limit: int | None = None) -> list[BookItem]:
    """Scan `root` for book items.

    `limit` stops the walk early once at least that many items have been
    collected -- for a real run this should stay None (every item must be
    seen), but a caller that only wants a handful of representative samples
    (e.g. a live naming-template preview) can avoid the full per-item
    multi-file-group detection cost across the whole tree. The result is
    still sorted by source path, but since the walk itself may stop before
    covering every folder, a limited call isn't guaranteed to return the
    same items a full scan's first N (sorted) would be.
    """
    items: list[BookItem] = []
    ignored_dir_names = {name.lower() for name in IGNORED_DIR_NAMES}

    # When scanning the full library, do not organize the staging folder as part
    # of library consolidation. If the root itself is _unorganized, scan it.
    if root == destination_root:
        ignored_dir_names |= {name.lower() for name in STAGING_DIR_NAMES}

    for current_dir, dirnames, filenames in os.walk(root):
        if limit is not None and len(items) >= limit:
            break
        dirnames[:] = [dirname for dirname in dirnames if dirname.lower() not in ignored_dir_names]
        current_path = Path(current_dir)
        if should_ignore_path(current_path, root):
            continue

        audio_files = [
            current_path / filename
            for filename in filenames
            if is_supported_audio(current_path / filename)
        ]
        audio_files.sort(key=natural_audio_sort_key)
        if not audio_files:
            continue

        force_loose = current_path == root or contains_nested_supported_audio(current_path)
        group_files = None if force_loose else build_multi_part_group_map(audio_files).get(current_path)
        if group_files:
            # Mirrors the fixer's build_processing_items: the recognized group
            # collapses to one representative item; anything else physically
            # in this same folder (e.g. a separately merged single-file
            # edition of the same book) is left as its own individual item
            # instead of being silently swept in or silently dropped.
            leftover_files = tuple(f for f in audio_files if f not in group_files)
            items.append(BookItem(
                "folder", current_path, group_files, group_files[0],
                partial_group=bool(leftover_files), leftover_files=leftover_files,
            ))
            for audio_file in leftover_files:
                items.append(BookItem("loose_file", audio_file, [audio_file], audio_file))
            continue

        for audio_file in audio_files:
            items.append(BookItem("loose_file", audio_file, [audio_file], audio_file))

    return sorted(items, key=lambda item: str(item.source_path))


def parse_legacy_series_container(name: str) -> dict[str, str]:
    """Parse old collection folders.

    Supported forms:
      Series - Author - Narrator
      Author - Series (#1-6)
      Series (Book 1 & 2)
      Series (Books 1-3)
    """
    cleaned = sanitize_path_name(cleanup_title_artifacts(name), "")
    if not cleaned:
        return {}
    parts = [part.strip() for part in re.split(r"\s+-\s+", cleaned) if part.strip()]
    if len(parts) >= 3:
        return {
            "series": clean_series_name(parts[0]),
            "author": parts[1],
            "narrator": ", ".join(parts[2:]),
        }
    if len(parts) == 2:
        left, right = parts
        # Common legacy pack folder: "Author - Series (#1-6)".
        if re.search(r"\(#?\d{1,4}\s*[-–—+]\s*\d{1,4}\)", right) or re.search(r"\bbooks?\s*#?\d", right, flags=re.IGNORECASE):
            series = re.sub(r"\s*\(#?\d{1,4}\s*[-–—+]\s*\d{1,4}\)\s*$", "", right).strip()
            return {"series": clean_series_name(series), "author": left, "narrator": ""}
    if len(parts) == 1:
        # "Series Name (Book 1 & 2)" or "Series Name (Books 1-3)" collection container.
        book_range = re.search(r"\(books?\s+[^)]+\)", parts[0], flags=re.IGNORECASE)
        if book_range:
            series_part = parts[0][:book_range.start()].strip(" -_.,")
            if series_part:
                return {"series": clean_series_name(series_part), "author": "", "narrator": ""}
    return {}


def parse_explicit_identity_folder_name(name: str) -> dict[str, str]:
    """Parse folders with explicit title, author, series, and sequence fields."""
    cleaned = sanitize_path_name(cleanup_title_artifacts(name), "")
    if not cleaned:
        return {}

    def plausible_author_credit(candidate: str) -> bool:
        candidate = clean_author_credits(candidate)
        if not candidate or re.search(
            r"\b(?:book|volume|complete series|box ?set|unknown)\b",
            candidate,
            flags=re.IGNORECASE,
        ):
            return False
        tokens = [token for token in candidate.split() if token]
        return bool(
            1 <= len(tokens) <= 5
            and all(re.search(r"[A-Za-z]", token) for token in tokens)
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
        candidate = clean_author_credits(candidate)
        return bool(
            re.search(r"(?:^|\s)(?:[A-Z]\.){1,4}(?:\s|$)", candidate)
            or re.search(r"\b[A-Z]\.[A-Z]\.", candidate)
        )

    def series_sequence(value: str, require_label: bool = True) -> tuple[str, str]:
        label = r"(?:Books?|Volumes?|Vols?\.?)"
        match = re.match(
            rf"^(?P<series>.+?)\s*,?\s*{label}\s*"
            rf"(?P<number>\d{{1,4}}(?:\.\d+)?)$",
            value,
            flags=re.IGNORECASE,
        )
        if not match and not require_label:
            match = re.match(
                r"^(?P<series>.+?)\s+(?P<number>\d{1,4}(?:\.\d+)?)$",
                value,
                flags=re.IGNORECASE,
            )
        if not match:
            return "", ""
        return clean_series_name(match.group("series")), normalize_book_number(
            match.group("number")
        )

    def result(title: str, author: str, series: str, number: str) -> dict[str, str]:
        title = sanitize_book_title(title)
        author = clean_author_credits(author)
        series = clean_series_name(series)
        number = normalize_book_number(number)
        if not all([title, author, series, number]):
            return {}
        return {
            "title": title,
            "author": author,
            "series": series,
            "number": number,
            "sequence_label": "Book",
        }

    segments = [
        part.strip()
        for part in re.split(r"\s+[-–—]\s+", cleaned)
        if part.strip()
    ]
    if len(segments) == 3:
        first, middle, last = segments
        middle_series, middle_number = series_sequence(middle)
        loose_middle_series, loose_middle_number = series_sequence(
            middle, require_label=False
        )

        # Author - Series Book N - Title
        if plausible_author_credit(first) and (
            looks_like_title_phrase(last)
            or (loose_middle_series and not middle_series)
            or not plausible_author_credit(last)
        ):
            parsed = result(
                last,
                first,
                loose_middle_series,
                loose_middle_number,
            )
            if parsed:
                return parsed

        # Title - Series Book N - Author
        if plausible_author_credit(last) and (
            looks_like_title_phrase(first) or not plausible_author_credit(first)
        ):
            parsed = result(first, last, middle_series, middle_number)
            if parsed:
                return parsed

            # Series Book N - Title - Author
            first_series, first_number = series_sequence(first)
            parsed = result(middle, last, first_series, first_number)
            if parsed:
                return parsed

    # Author - Title (Series Book N)
    match = re.match(
        r"^(?P<author>.+?)\s+-\s*(?P<title>.+?)\s*"
        r"\((?P<series>.+?)\s*,?\s*(?:Books?|Volumes?|Vols?\.?)\s*"
        r"(?P<number>\d{1,4}(?:\.\d+)?)\)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match and plausible_author_credit(match.group("author")):
        return result(
            match.group("title"),
            match.group("author"),
            match.group("series"),
            match.group("number"),
        )

    # Series/title, Book N - Author
    match = re.match(
        r"^(?P<series>.+?)\s*,\s*(?:Books?|Volumes?|Vols?\.?)\s*"
        r"(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<author>.+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match and plausible_author_credit(match.group("author")):
        return result(
            match.group("series"),
            match.group("author"),
            match.group("series"),
            match.group("number"),
        )

    # Series/title N - Author
    match = re.match(
        r"^(?P<series>.+?)\s+(?P<number>\d{1,4}(?:\.\d+)?)"
        r"\s*-\s*(?P<author>.+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if (
        match
        and plausible_author_credit(match.group("author"))
        and has_strong_author_marker(match.group("author"))
        and not looks_like_title_phrase(match.group("author"))
        and normalize_for_compare(match.group("series"))
        not in {"book", "books", "volume", "volumes", "vol", "vols"}
    ):
        return result(
            match.group("series"),
            match.group("author"),
            match.group("series"),
            match.group("number"),
        )

    # Title, Author - Series N
    match = re.match(
        r"^(?P<title>[^,]+),\s*(?P<author>.+?)\s*-\s*"
        r"(?P<series>.+?)\s+(?P<number>\d{1,4}(?:\.\d+)?)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match and plausible_author_credit(match.group("author")):
        series_candidate = match.group("series")
        number_candidate = match.group("number")

        # Avoid false positives for co-author folders such as:
        #   Sebastian Wilde, Jamie Hawke - Happy Hunting Planet Kill, Book 2
        # and author/year folders such as:
        #   TheFirstDefier, J.F.Brink - Book 14 - ... - 2024
        #
        # In those cases this loose "Title, Author - Series N" parser would
        # treat the first author as a title and the last year as the sequence.
        # Let the more conservative fallback/path parsing handle them instead.
        if not (
            re.fullmatch(r"(?:19|20)\d{2}", number_candidate)
            or re.search(
                r"\b(?:book|books|vol\.?|vols\.?|volume|volumes)\s*$",
                series_candidate,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\b(?:book|books|vol\.?|vols\.?|volume|volumes)\s+\d{1,4}\b",
                series_candidate,
                flags=re.IGNORECASE,
            )
        ):
            return result(
                match.group("title"),
                match.group("author"),
                series_candidate,
                number_candidate,
            )

    return {}


def parse_book_folder_name(name: str) -> dict[str, str]:
    cleaned = sanitize_path_name(name, "")
    if not cleaned:
        return {}

    def finish(data: dict[str, str]) -> dict[str, str]:
        data = {key: sanitize_path_name(value, "") for key, value in data.items() if value}
        if data.get("label"):
            data["sequence_label"] = normalize_sequence_label(data["label"])
            data.pop("label", None)
        if data.get("number"):
            data["number"] = normalize_book_number(data["number"].replace(",", "-"))
        # A folder like "Book 01 - Failure Frame ..., Vol. 1" is usually a
        # light-novel volume whose existing folder was just normalized as Book.
        # Prefer Vol./Volume in that case.  Do not do this for series-first
        # folders like "Destiny Cycle - Book 004 - Threads of Destiny Vol 1",
        # where the trailing Vol belongs to the title/subtitle.
        if normalize_sequence_label(data.get("sequence_label", "")) == "Book" and not data.get("series") and data.get("title") and data.get("number"):
            title_label = detect_sequence_label_from_text(data["title"])
            if normalize_for_compare(title_label) in {"vol", "volume"}:
                data["sequence_label"] = title_label
        if data.get("series"):
            data["series"] = clean_series_name(data["series"])
        if data.get("author"):
            data["author"] = clean_author_credits(data["author"])
        if data.get("narrator"):
            data["narrator"] = sanitize_path_name(data["narrator"], "")
        if data.get("title"):
            data["title"] = clean_book_title(data["title"], data.get("series", ""), data.get("number", ""))
        elif data.get("number") and "-" in data.get("number", ""):
            prefix_label = data.get("sequence_label") or data.get("label") or "Book"
            data["title"] = build_sequence_prefix(prefix_label, data["number"])
        elif data.get("series"):
            data["title"] = clean_book_title(data["series"], data.get("series", ""), data.get("number", ""))
        return data

    explicit_identity = parse_explicit_identity_folder_name(cleaned)
    if explicit_identity:
        return finish(explicit_identity)

    # The title/series boundary is not explicit in names such as
    # "Shane Walker - Corporate Warfare All Trades, Book 3". Keep only the
    # reliable sequence clue so sidecar or embedded metadata remains primary.
    ambiguous_author_title_series = re.match(
        r"^[^-]+?\s+-\s*.+?,\s*(?P<label>Book|Books|Vol\.?|Volume|Volumes)\s*"
        r"(?P<number>\d{1,4}(?:\.\d+)?)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if ambiguous_author_title_series:
        return finish(ambiguous_author_title_series.groupdict(default=""))

    # Light-novel/chapterized folder form:
    #   Isuna Hasekura (2008) Spice and Wolf, Volume 8 - Town of Strife 1 (Narrator)
    # This must run before the generic "Series, Volume N" parser, otherwise the
    # author/year text leaks into the series folder.
    match = re.match(
        r"^(?P<author>.+?)\s+\((?P<year>\d{4})\)\s+(?P<series>.+?),\s*"
        r"(?P<label>Vol\.?|Volume|Volumes)\s*(?P<number>\d{1,4}(?:\.\d+)?)"
        r"(?:\s*-\s*(?P<title>[^()]+?))?"
        r"(?:\s*\((?P<narrator>[^()]+)\))?\s*$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        data = match.groupdict(default="")
        # If the volume has no subtitle, keep the series as the book title.
        if not data.get("title"):
            data["title"] = data.get("series", "")
        return finish(data)

    # Sorted folders often begin with a reading-order prefix, followed by the
    # real label.  Examples:
    #   048 - Novel 001 - The Talon and the Flame
    #   004 - Side Story 001 - The River Mists Of Talry
    #   029-033 - Side Story 013-017 - The Road to Vanador Travelogue
    match = re.match(
        r"^\d{1,4}\s*[-–—]\s*\d{1,4}\s*[-–—]\s*(?P<label>Side Story|Novel)\s*(?P<number>\d{1,4}\s*[-–—+]\s*\d{1,4})\s*[-–—]\s*(?P<title>.+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        return finish(match.groupdict(default=""))

    match = re.match(
        r"^\d{1,4}\s*[-–—]\s*(?P<label>Side Story|Novel)\s*(?P<number>\d{1,4}(?:\.\d+)?)\s*[-–—]\s*(?P<title>.+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        return finish(match.groupdict(default=""))

    # Series-first side story / novel forms.
    #   Mage Errant - Side Story 001 - The Gorgon Incident and Other Stories
    match = re.match(
        r"^(?P<series>.+?)\s+-\s*(?P<label>Side Story|Novel)\s*(?P<number>\d{1,4}(?:\.\d+)?)\s*[-–—]\s*(?P<title>.+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        return finish(match.groupdict(default=""))

    # Folder starts directly with the sequence label. These are the most
    # authoritative labels for ABS folder naming and must be checked before
    # series-first "..., Volume N" patterns. Otherwise
    # "Book 01 - Title, Volume 1" gets incorrectly parsed as series="Book 01 - Title".
    leading_patterns = [
        r"^(?P<label>Book|Books|Vol\.?|Vols\.?|Volume|Volumes)\s*(?P<number>\d{1,4}\s*[-–—+]\s*\d{1,4})$",
        r"^(?P<label>Book|Books|Vol\.?|Vols\.?|Volume|Volumes)\s*(?P<number>\d{1,4}\s*[-–—+]\s*\d{1,4})\s*[-–—]\s*(?P<title>.+)$",
        r"^(?P<label>Book|Books|Vol\.?|Vols\.?|Volume|Volumes)\s*(?P<number>\d{1,4}\s*[-–—+]\s*\d{1,4})\s+(?P<title>.+)$",
        r"^(?P<label>Side Story|Novel)\s*(?P<number>\d{1,4}\s*[-–—+]\s*\d{1,4})\s*-\s*(?P<title>.+)$",
        r"^(?P<label>Book|Books|Vol\.?|Vols\.?|Volume|Volumes|Side Story|Novel)\s*(?P<number>\d{1,4}\s*,\s*\d{1,4})\s*-\s*(?P<title>.+)$",
        r"^(?P<label>Book|Books|Vol\.?|Vols\.?|Volume|Volumes|Side Story|Novel)\s*(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<title>.+)$",
    ]
    for pattern in leading_patterns:
        match = re.match(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            return finish(match.groupdict(default=""))

    patterns = [
        # Series-first volume/book forms.
        r"^(?P<series>.+?)\s+-\s*(?P<label>Books?|Volumes?|Vols?\.?)\s*(?P<number>\d{1,4}\s*[-–—+]\s*\d{1,4})$",
        r"^(?P<series>.+?)\s+-\s*(?P<label>Books?|Volumes?|Vols?\.?)\s*(?P<number>\d{1,4}\s*[-–—+]\s*\d{1,4})\s*-\s*(?P<title>.+)$",
        r"^(?P<series>.+?),\s*(?P<label>Book|Books|Vol\.?|Vols\.?|Volume|Volumes)\s*(?P<number>\d{1,4}\s*[-–—+]\s*\d{1,4})(?:\s*[-–—]\s*(?P<title>.+))?$",
        r"^(?P<series>.+?)\s+-\s*(?P<label>Book|Books|Vol\.?|Vols\.?|Volume|Volumes)\s*(?P<number>\d{1,4}\s*,\s*\d{1,4})\s*-\s*(?P<title>.+)$",
        r"^(?P<series>.+?)\s+-\s*(?P<label>Vol\.?|Vols\.?|Volume|Volumes)\s*(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<title>.+)$",
        r"^(?P<series>.+?),\s*(?P<label>Vol\.?|Vols\.?|Volume|Volumes)\s*(?P<number>\d{1,4}(?:\.\d+)?)(?:\s*-\s*(?P<title>.+))?$",
        # Legacy author-first form, intentionally only for Book/Books labels.
        r"^(?P<author>[A-Za-z][^-]+?)\s+-\s*(?P<series>.+?),\s*(?P<label>Book|Books)\s*(?P<number>\d{1,4}(?:\.\d+)?)(?:\s*-\s*(?P<title>.+))?$",
        r"^(?P<series>.+?)\s+-\s*(?P<label>Book|Books)\s*(?P<number>\d{1,4}(?:\.\d+)?)\s*-\s*(?P<title>.+)$",
        r"^(?P<series>.+?),\s*(?P<label>Book|Books)\s*(?P<number>\d{1,4}(?:\.\d+)?)(?:\s*-\s*(?P<title>.+))?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            return finish(match.groupdict(default=""))

    number = detect_number_from_text(cleaned)
    title = clean_book_title(cleaned, "", number) if number else cleaned
    result = {"title": title, "number": number}
    label = detect_sequence_label_from_text(cleaned)
    if label:
        result["sequence_label"] = label
    return result

def metadata_from_sidecar(item: BookItem) -> dict[str, Any] | None:
    paths: list[Path] = []
    if item.kind == "folder":
        # Folder-level libraforge.json (alone-in-folder single-file books and
        # multi-file chapter groups) has no filename prefix — check it first.
        folder_lf = item.source_path / "libraforge.json"
        if folder_lf.is_file():
            paths.append(folder_lf)
        paths.extend(sorted(item.source_path.glob("*.m4b-tool-metadata.json")))
        paths.extend(sorted(item.source_path.glob("*.libraforge.json")))
        paths.extend(sorted(item.source_path.glob("*.audible-metadata-fixer.json")))
        paths.append(item.representative.with_name(item.representative.name + ".libraforge.json"))
        paths.append(item.representative.with_name(item.representative.name + ".audible-metadata-fixer.json"))
    else:
        # Loose file alone in its folder may have a folder-level libraforge.json.
        folder_lf = item.source_path.parent / "libraforge.json"
        if folder_lf.is_file():
            paths.append(folder_lf)
        paths.append(item.source_path.with_name(item.source_path.name + ".m4b-tool-metadata.json"))
        paths.append(item.source_path.with_name(item.source_path.name + ".libraforge.json"))
        paths.append(item.source_path.with_name(item.source_path.name + ".audible-metadata-fixer.json"))

    for path in paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if isinstance(payload.get("book"), dict):
            book = payload["book"]
            title = book.get("title", "")
            series = book.get("series", "")
            author = book.get("author", "")
            # Skip sidecars with no useful book data — they were written without
            # metadata and would shadow a better audible-fixer marker further
            # down the paths list.
            if not title and not author and not series:
                continue
            filename_author = author_from_marker_filename(path.name, series)
            if filename_author and author_is_probably_bad_for_series(author, series):
                author = filename_author
            return {
                "title": title,
                "author": author,
                "series": series,
                "book_number": normalize_book_number(str(book.get("sequence", ""))),
                "sequence_label": choose_sequence_label(str(book.get("sequence_label", "")), str(book.get("label", "")), str(title)),
                "narrator": book.get("narrator", ""),
                "asin": clean_asin_token(book.get("asin", "")),
                "publisher": book.get("publisher", "") or "",
                "genre": book.get("genre", "") or "",
                "year": str(book.get("year", "") or ""),
                "source": f"sidecar:{path.name}",
            }

        # New unified format: audible data is nested under marker.audible
        marker_section = payload.get("marker")
        audible_data = (
            marker_section.get("audible", {})
            if isinstance(marker_section, dict)
            else payload.get("audible", {})
        )
        audible_data = audible_data if isinstance(audible_data, dict) else {}
        if audible_data:
            title = audible_data.get("chosen_title") or audible_data.get("title") or ""
            series = audible_data.get("series", "")
            author = audible_data.get("author", "")
            # Skip skeletal markers that carry only an ASIN placeholder (e.g.
            # {"asin": "NOREALASIN"}) and no real book data. Returning them here
            # would shadow the correct embedded ffprobe tags with empty fields
            # and let the messy filename drive author/title inference.
            if not title and not author and not series:
                continue
            filename_author = author_from_marker_filename(path.name, series)
            if filename_author and author_is_probably_bad_for_series(author, series):
                author = filename_author
            return {
                "title": title,
                "author": author,
                "series": series,
                "book_number": normalize_book_number(str(audible_data.get("sequence", ""))),
                "sequence_label": choose_sequence_label(str(audible_data.get("sequence_label", "")), str(audible_data.get("label", "")), str(audible_data.get("title", "")), str(audible_data.get("chosen_title", ""))),
                "narrator": audible_data.get("narrator", ""),
                "asin": clean_asin_token(audible_data.get("asin", "")),
                "publisher": audible_data.get("publisher", "") or "",
                "genre": audible_data.get("genre", "") or "",
                "year": str(audible_data.get("year", "") or ""),
                "source": f"marker:{path.name}",
            }

    return None


def any_item_has_sidecar(items: list[BookItem]) -> bool:
    """True if at least one item in the scan has a usable fixer/marker sidecar.

    Used as a cheap library-wide signal, not a per-item check: multi-file
    book handling (grouping, title/author/series across chapters) leans on
    metadata the fixer script writes, so a scan root where nothing has ever
    been touched by the fixer is a sign the organizer is being run on raw,
    unprocessed audio rather than something to detect and reimplement here.
    """
    return any(metadata_from_sidecar(item) is not None for item in items)


def metadata_from_tags(item: BookItem) -> dict[str, Any]:
    tags = run_ffprobe(item.representative)
    filename_title = item.representative.stem
    source_name = item.source_path.name

    title = first_tag(tags, ["title", "album"], default=filename_title)
    author = first_tag(tags, ["album_artist", "album-artist", "artist", "author"], default="Unknown Author")
    narrator = first_tag(tags, ["composer", "narrator", "performer"], default="")
    series = first_tag(tags, ["mvnm", "series", "series title", "series-title", "grouping", "contentgroup", "content group"], default="")
    sequence = first_tag(tags, ["mvin", "series-part", "series_part", "series sequence", "series_sequence", "part", "track", "tracknumber", "trck", "disc", "discnumber"], default="")

    if item.kind == "folder" and is_generic_track_title(title):
        title = source_name

    return {
        "title": title,
        "author": author,
        "series": series,
        "book_number": normalize_book_number(detect_number_from_text(sequence)),
        "sequence_label": choose_sequence_label(title, source_name, filename_title, sequence),
        "narrator": narrator,
        "source": "ffprobe",
        "tags": tags,
    }


def path_clues(item: BookItem, root: Path) -> dict[str, str]:
    clues: dict[str, str] = {}
    source_name = item.source_path.name
    representative_name = item.representative.stem

    folder_data = parse_book_folder_name(source_name if item.kind == "folder" else representative_name)
    if folder_data.get("title"):
        clues["title"] = folder_data["title"]
    if folder_data.get("number"):
        clues["book_number"] = folder_data["number"]
    if folder_data.get("sequence_label"):
        clues["sequence_label"] = folder_data["sequence_label"]
    if folder_data.get("series"):
        clues["series"] = folder_data["series"]
    if folder_data.get("author"):
        clues["author"] = folder_data["author"]
    if folder_data.get("narrator"):
        clues["narrator"] = folder_data["narrator"]
    if folder_data.get("author") and folder_data.get("series"):
        # The actual book folder contains enough information to identify the
        # book.  Do not later override it with helper parents such as
        # "Audio" or "Complete Series, Chapterized".
        clues["book_folder_author_series"] = "1"

    # Root-level standalone folders often use "Title - Author - Narrator"
    # or "Author - Title".  Parse these only as fallback hints and only when
    # the book name did not already expose series/number structure.
    standalone = {}
    standalone_from_representative = False
    if not clues.get("series") and not clues.get("book_number"):
        standalone = parse_standalone_book_folder_name(source_name if item.kind == "folder" else representative_name)
        if not standalone and item.kind == "folder":
            # Representative filenames are weaker than their containing book
            # folder. Only use the narrow grouped-track form
            # "Author - Title - numeric track"; generic three-part parsing can
            # mistake "Author - Series - Subtitle" for title/author/narrator.
            standalone = parse_representative_track_name(representative_name)
            standalone_from_representative = bool(standalone)
    if standalone:
        if standalone_from_representative and standalone.get("title"):
            clues["title"] = standalone["title"]
        else:
            clues.setdefault("title", standalone.get("title", ""))
        clues.setdefault("author", standalone.get("author", ""))
        clues.setdefault("narrator", standalone.get("narrator", ""))

    # Nearby folders often carry series/author in legacy structure.
    parent = item.source_path.parent if item.kind == "folder" else item.source_path.parent
    try:
        relative_parts = item.source_path.relative_to(root).parts
    except ValueError:
        relative_parts = ()

    if len(relative_parts) >= 2:
        container = relative_parts[0]
        legacy = parse_legacy_series_container(container)
        if legacy:
            clues.setdefault("series", legacy.get("series", ""))
            clues.setdefault("author", legacy.get("author", ""))
            clues.setdefault("narrator", legacy.get("narrator", ""))

    if item.kind == "folder" and parent != root:
        legacy = parse_legacy_series_container(parent.name)
        if legacy and not clues.get("book_folder_author_series"):
            clues.setdefault("series", legacy.get("series", ""))
            clues.setdefault("author", legacy.get("author", ""))
            clues.setdefault("narrator", legacy.get("narrator", ""))
        elif parent.parent != root:
            # If this looks like a clean Author/Series/Book path, the parent is
            # the existing series folder. Keep it separately so full-library
            # consolidation can prefer it over stale sidecar metadata.
            #
            # Exception: for chapterized dumps, the real book folder may already
            # contain author+series information and the parent can be a generic
            # helper such as "Audio". In that case, do not let the helper parent
            # override the parsed book-folder data.
            if not is_generic_structure_name(parent.name) and not clues.get("book_folder_author_series"):
                clues.setdefault("parent_series", parent.name)
                if not clues.get("series"):
                    clues["series"] = parent.name
            if parent.parent and parent.parent != root and not is_generic_structure_name(parent.parent.name) and not clues.get("author"):
                parsed_author, parsed_narrator = parse_author_narrator_folder(parent.parent.name)
                if parsed_author and not is_generic_structure_name(parsed_author):
                    clues.setdefault("parent_author", parsed_author)
                    if parsed_narrator:
                        clues.setdefault("narrator", parsed_narrator)
        else:
            # Author/Book folder form, useful for MP3 folders such as
            # Matt Dinniman/Matt Dinniman - The Grinding (...)
            if not is_generic_structure_name(parent.name) and not clues.get("author"):
                parsed_author, parsed_narrator = parse_author_narrator_folder(parent.name)
                if parsed_author:
                    clues.setdefault("parent_author", parsed_author)
                    clues.setdefault("author", parsed_author)
                if parsed_narrator:
                    clues.setdefault("narrator", parsed_narrator)

    if not clues.get("book_number"):
        for value in [source_name, representative_name, parent.name if parent else ""]:
            number = detect_number_from_text(value)
            if number:
                clues["book_number"] = number
                label = detect_sequence_label_from_text(value)
                if label:
                    clues.setdefault("sequence_label", label)
                break

    return {key: value for key, value in clues.items() if value}


def metadata_source_is_trusted(source: str) -> bool:
    """Return True for metadata produced by the fixer/M4B sidecar workflow.

    Organizer runs normally happen after Metadata Forge, so marker/sidecar
    identity should be stronger than noisy folder names in _unorganized.
    """
    source = str(source or "")
    return source.startswith("marker:") or source.startswith("sidecar:")


def book_number_looks_like_year(value: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}", display_book_number(str(value or ""))))


def title_conflict_should_trigger_review(
    metadata_title: str,
    path_title: str,
    series: str,
    book_number: str,
    author: str = "",
    narrator: str = "",
) -> bool:
    """Return True only for meaningful title identity conflicts.

    Trusted marker/sidecar metadata often has a cleaner title than the path
    because paths include authors, series names, ASINs, years, release tags, or
    marketing subtitles. Those routine cleanups should not create review noise.
    Review only when both sides still have distinct book-title content and the
    cleaned values are genuinely different.
    """
    metadata_hint = strip_author_narrator_noise_from_title(
        metadata_title,
        author,
        narrator,
    )
    path_hint = strip_author_narrator_noise_from_title(
        path_title,
        author,
        narrator,
    )
    metadata_clean = clean_book_title(metadata_hint, series, book_number)
    path_clean = clean_book_title(path_hint, series, book_number)

    if not has_distinct_book_title(metadata_clean, series, book_number):
        return False
    if not has_distinct_book_title(path_clean, series, book_number):
        return False

    metadata_key = normalize_for_compare(metadata_clean)
    path_key = normalize_for_compare(path_clean)
    if not metadata_key or not path_key or metadata_key == path_key:
        return False

    # If one cleaned value simply contains the other, this is usually a path
    # decoration issue, not a true identity conflict.
    if metadata_key in path_key or path_key in metadata_key:
        return False

    return SequenceMatcher(None, metadata_key, path_key).ratio() < 0.72


def infer_metadata(item: BookItem, root: Path, prefer_path_structure: bool = False) -> dict[str, Any]:
    sidecar = metadata_from_sidecar(item)
    tag_meta = metadata_from_tags(item) if sidecar is None else sidecar
    clues = path_clues(item, root)
    review_reasons: list[str] = []

    def add_review_reason(reason: str) -> None:
        if reason not in review_reasons:
            review_reasons.append(reason)

    metadata_title = tag_meta.get("title") or item.representative.stem
    title = metadata_title
    author = tag_meta.get("author") or clues.get("author") or "Unknown Author"
    series = tag_meta.get("series") or clues.get("series", "")
    tag_book_number = tag_meta.get("book_number") or ""
    book_number = tag_book_number
    narrator = tag_meta.get("narrator") or clues.get("narrator", "")
    trusted_metadata = metadata_source_is_trusted(tag_meta.get("source", ""))

    # Prefer the sequence label from fixer/sidecar metadata. Path labels are
    # still useful when metadata has no sequence, but they should not turn
    # marker-confirmed Book 2 into Vol. 2 just because the staging folder was
    # named "v2".
    sequence_label = choose_sequence_label(
        tag_meta.get("sequence_label", ""),
        title,
        clues.get("sequence_label", ""),
        item.source_path.name,
        item.representative.stem,
    )

    # Prefer fixer/sidecar sequence metadata over folder-name numbers during
    # _unorganized runs. Folder names often contain batch folders, years, or
    # staging hints (for example "Dungeon Diving v2" or a trailing "2024").
    #
    # In full-library consolidation mode, path structure may still be safer
    # than raw ffprobe tags, but marker/sidecar metadata remains authoritative
    # unless the user explicitly corrects it.
    path_book_number = clues.get("book_number", "")
    metadata_title_number = metadata_series_suffix_number(metadata_title, series)

    # Some folder/file names expose a bare series suffix without the word
    # "Book", e.g. "Returner's Defiance 2". detect_number_from_text() is
    # intentionally conservative and does not treat every trailing number as a
    # sequence. Use this narrower check only when the text is literally shaped
    # like "<series> <small-number>".
    if not path_book_number and metadata_title_number:
        for suffix_source in (item.source_path.name, item.representative.stem):
            path_series_suffix_number = small_series_suffix_number_from_text(
                suffix_source,
                series,
            )
            if path_series_suffix_number == metadata_title_number:
                path_book_number = path_series_suffix_number
                break

    # When trusted sidecar metadata reports an omnibus range (e.g. "001-003")
    # but the book folder name is shaped like "<Series> N", the folder path is
    # the authoritative clue about which individual book this is.  The fixer
    # likely matched the omnibus Audible entry instead of the single book.
    if trusted_metadata and not path_book_number and "-" in str(tag_book_number) and series:
        for suffix_source in (item.source_path.name, item.representative.stem):
            p = small_series_suffix_number_from_text(suffix_source, series)
            if p and "-" not in p:
                try:
                    rng_parts = str(tag_book_number).split("-")
                    if int(rng_parts[0]) <= int(p) <= int(rng_parts[-1]):
                        book_number = p
                        tag_book_number = p
                        title = series
                        metadata_title = series
                        add_review_reason("omnibus range in sidecar overridden by single-book path number")
                        break
                except (ValueError, IndexError):
                    pass

    # Some Audible/fixer marker payloads can carry a bad sequence even though
    # the chosen title and path both clearly expose the real sequence, e.g.
    # title="Corruption Wielder 2", path="Corruption Wielder Book 2",
    # but marker sequence=1. When title+path agree, treat that as stronger
    # evidence than the single bad sequence value.
    if (
        trusted_metadata
        and tag_book_number
        and metadata_title_number
        and normalize_book_number(str(tag_book_number)) != metadata_title_number
        and path_book_number
        and normalize_book_number(str(path_book_number)) == metadata_title_number
        and not book_number_looks_like_year(path_book_number)
    ):
        book_number = metadata_title_number
        tag_book_number = metadata_title_number
    elif (
        trusted_metadata
        and tag_book_number
        and metadata_title_number
        and normalize_book_number(str(tag_book_number)) != metadata_title_number
        and not path_book_number
    ):
        add_review_reason("metadata title number differs from metadata sequence")

    if path_book_number:
        path_differs = (
            tag_book_number
            and normalize_book_number(str(tag_book_number))
            != normalize_book_number(str(path_book_number))
        )

        if path_differs:
            if book_number_looks_like_year(path_book_number):
                # A trailing release year should not create a generic mismatch
                # when metadata already has a real sequence. Keep a narrow
                # review reason only for the year-looking clue.
                add_review_reason("path book number looks like a year")
            else:
                add_review_reason("book number differs between metadata and path")
            if prefer_path_structure and not trusted_metadata and not book_number_looks_like_year(path_book_number):
                book_number = path_book_number
        elif not tag_book_number:
            if book_number_looks_like_year(path_book_number):
                add_review_reason("path book number looks like a year")
            else:
                book_number = path_book_number

    if clues.get("title"):
        path_title = clues["title"]
        path_title_differs = normalize_for_compare(path_title) != normalize_for_compare(title)
        use_path_title = False

        if is_generic_track_title(title):
            use_path_title = True
            add_review_reason("title inferred from path")
        elif prefer_path_structure and not trusted_metadata:
            use_path_title = True
            if path_title_differs:
                add_review_reason("title differs between metadata and path")
        elif (
            normalize_for_compare(title) == normalize_for_compare(series)
            and has_distinct_book_title(path_title, series, book_number)
            and not is_marketing_descriptor(path_title)
        ):
            # title == series: no distinct book title in metadata; collapse to
            # sequence only ("Book N") rather than using the noisy path title.
            add_review_reason("title matches series name; using sequence only")
        elif trusted_metadata and path_title_differs:
            if title_conflict_should_trigger_review(
                metadata_title=metadata_title,
                path_title=path_title,
                series=series,
                book_number=book_number,
                author=author,
                narrator=narrator,
            ):
                add_review_reason("title identity differs between metadata and path")

        if use_path_title:
            title = path_title

    if prefer_path_structure and clues.get("parent_series") and not clues.get("book_folder_author_series") and not is_generic_structure_name(clues["parent_series"]):
        if series and normalize_for_compare(series) != normalize_for_compare(clues["parent_series"]):
            add_review_reason("series differs between metadata and path")
        elif not series:
            add_review_reason("series inferred from path")
        series = clues["parent_series"]
    elif clues.get("series") and (not series or prefer_path_structure):
        if series and normalize_for_compare(series) != normalize_for_compare(clues["series"]):
            add_review_reason("series differs between metadata and path")
        elif not series:
            add_review_reason("series inferred from path")
        series = clues["series"]
    if prefer_path_structure and clues.get("parent_author") and not clues.get("book_folder_author_series") and not is_generic_structure_name(clues["parent_author"]):
        candidate_author = clues["parent_author"]
        # Do not let a folder named exactly like the series overwrite a better
        # sidecar/marker author.  Example: /Dashing Devil/Dashing Devil 5...
        if not (author and not author_is_probably_bad_for_series(author, series) and author_is_probably_bad_for_series(candidate_author, series)):
            if (
                author
                and author != "Unknown Author"
                and normalize_for_compare(author) != normalize_for_compare(candidate_author)
            ):
                add_review_reason("author differs between metadata and path")
            elif not author or author == "Unknown Author":
                add_review_reason("author inferred from path")
            author = candidate_author
    elif clues.get("author") and (prefer_path_structure or not author or author == "Unknown Author"):
        candidate_author = clues["author"]
        if not (author and not author_is_probably_bad_for_series(author, series) and author_is_probably_bad_for_series(candidate_author, series)):
            if (
                author
                and author != "Unknown Author"
                and normalize_for_compare(author) != normalize_for_compare(candidate_author)
            ):
                add_review_reason("author differs between metadata and path")
            elif not author or author == "Unknown Author":
                add_review_reason("author inferred from path")
            author = candidate_author
    if clues.get("narrator") and (prefer_path_structure or not narrator):
        narrator = clues["narrator"]

    # A path hint must not collapse a known title to the author name. Keep the
    # sidecar/ffprobe title when it differs; valid eponymous titles remain
    # untouched because their metadata title is the same value.
    if (
        normalize_for_compare(title) == normalize_for_compare(author)
        and normalize_for_compare(metadata_title) != normalize_for_compare(author)
        and not is_generic_track_title(metadata_title)
    ):
        title = metadata_title

    if clues.get("sequence_label"):
        path_sequence_label = clues["sequence_label"]
        tag_sequence_label = tag_meta.get("sequence_label", "")
        if (
            tag_book_number
            and tag_sequence_label
            and normalize_sequence_label(path_sequence_label) != normalize_sequence_label(tag_sequence_label)
        ):
            add_review_reason("sequence label differs between metadata and path")
        elif not tag_book_number or (prefer_path_structure and not trusted_metadata):
            # The path label is authoritative only when there is no trusted
            # metadata sequence. A trailing title phrase such as "Vol 1" must not
            # override a leading folder prefix like "Book 004" during raw
            # full-library cleanup, but marker/sidecar metadata wins for
            # post-fixer _unorganized runs.
            sequence_label = path_sequence_label

    if is_generic_structure_name(author) and clues.get("author") and not is_generic_structure_name(clues["author"]):
        author = clues["author"]
    if is_generic_structure_name(series) and clues.get("series") and not is_generic_structure_name(clues["series"]):
        series = clues["series"]

    author_full = clean_author_credits(author)
    author_primary = canonical_author_name(primary_author(author_full))

    # Dramatized adaptations (GraphicAudio, Soundbooth Theater, generic
    # dramatized editions) share a title and series with the normal recording,
    # so they must route to "Series [Imprint]" to avoid colliding with the
    # straight reading. Detect the imprint from every raw signal before the
    # series/title cleaners strip the marker parenthetical.
    edition_tag = detect_edition_tag(
        metadata_title,
        series,
        title,
        narrator,
        clues.get("series", ""),
        clues.get("parent_series", ""),
        clues.get("publisher", ""),
        item.source_path.name,
    )
    series = strip_edition_marker(series)
    title = strip_edition_marker(title)
    metadata_title = strip_edition_marker(metadata_title)
    clean_series = clean_series_name(series)

    if not book_number:
        book_number = (
            detect_number_from_text(metadata_title)
            or metadata_series_suffix_number(metadata_title, clean_series)
        )

    # Once the author is known, remove common release-folder decorations from titles.
    # Pass trusted_metadata so the function skips cleanup_title_artifacts for
    # Audible-confirmed titles — genre-keyword titles must not be wiped here.
    title = strip_author_narrator_noise_from_title(title, author_full, narrator, trusted=trusted_metadata)
    sequence_label = prefer_series_title_volume_label(sequence_label, title, clean_series, book_number)
    clean_title = clean_book_title(title, clean_series, book_number, trusted=trusted_metadata)
    metadata_clean_title = clean_book_title(
        metadata_title,
        clean_series,
        book_number,
        trusted=trusted_metadata,
    )
    path_title_hint = strip_author_narrator_noise_from_title(
        clues.get("title", ""),
        author_full,
        narrator,
    ) if clues.get("title") else ""
    path_clean_title = clean_book_title(
        path_title_hint,
        clean_series,
        book_number,
    ) if path_title_hint else ""
    if (
        not has_distinct_book_title(clean_title, clean_series, book_number)
        and has_distinct_book_title(
            metadata_clean_title,
            clean_series,
            book_number,
        )
    ):
        clean_title = metadata_clean_title
    if (
        not has_distinct_book_title(clean_title, clean_series, book_number)
        and has_distinct_book_title(path_clean_title, clean_series, book_number)
        and (not trusted_metadata or is_generic_track_title(metadata_title))
    ):
        clean_title = path_clean_title

    # Do not let placeholder values such as "Unknown Title" become real folder
    # names.  When series + sequence are known, use the series title so
    # build_book_folder_name() collapses the target to just "Book N"/"Vol. N".
    # For trusted Audible titles, keep the original title even when it matches a
    # genre noise pattern (e.g. "The Fifth Law of Cultivation" ends with "cultivation").
    if title_is_bad_after_cleanup(clean_title) and clean_series and not trusted_metadata:
        clean_title = clean_series

    return {
        "title": clean_title,
        "author": author_full,
        "author_primary": author_primary,
        "series": clean_series,
        "edition_tag": edition_tag,
        "book_number": book_number,
        "sequence_label": sequence_label,
        "narrator": sanitize_path_name(narrator, "") if narrator else "",
        "audio_count": len(item.audio_files),
        "kind": item.kind,
        "metadata_source": tag_meta.get("source", "unknown"),
        "review_reasons": review_reasons,
        "asin": tag_meta.get("asin", "") or "",
        "publisher": tag_meta.get("publisher", "") or "",
        "genre": tag_meta.get("genre", "") or "",
        "year": tag_meta.get("year", "") or "",
    }


def infer_metadata_from_library_path(item: BookItem, root: Path) -> dict[str, Any] | None:
    if item.kind != "folder":
        return None

    try:
        parts = item.source_path.relative_to(root).parts
    except ValueError:
        return None

    if len(parts) < 2:
        return None

    author = ""
    series = ""
    book_folder = parts[-1]

    # New ABS-friendly layout: Author/Series/Book folder or Author/Book folder.
    if len(parts) >= 3:
        author, _narrator = parse_author_narrator_folder(parts[-3])
        series = parts[-2]
    elif len(parts) == 2:
        container, book_folder = parts
        legacy = parse_legacy_series_container(container)
        if legacy:
            author = legacy.get("author", "")
            series = legacy.get("series", "")
        else:
            author, _narrator = parse_author_narrator_folder(container)
            series = ""

    parsed_book = parse_book_folder_name(book_folder)
    title = parsed_book.get("title") or book_folder
    number = parsed_book.get("number") or ""
    if parsed_book.get("series") and not series:
        series = parsed_book["series"]

    if not author:
        return None

    author_full = clean_author_credits(author)
    clean_series = clean_series_name(series)
    sequence_label = parsed_book.get("sequence_label") or choose_sequence_label(book_folder)
    sequence_label = prefer_series_title_volume_label(sequence_label, title, clean_series, number)
    return {
        "title": clean_book_title(title, clean_series, number),
        "author": author_full,
        "author_primary": canonical_author_name(primary_author(author_full)),
        "series": clean_series,
        "book_number": number,
        "sequence_label": sequence_label,
        "narrator": "",
        "audio_count": len(item.audio_files),
        "kind": item.kind,
        "metadata_source": "path",
    }


def series_dir_label(metadata: dict[str, Any]) -> str:
    """Series folder name, suffixed with the dramatized imprint when present.

    Dramatized adaptations route to "Series [GraphicAudio]" / "[Dramatized]"
    so they never merge into the straight-reading series folder.
    """
    series = sanitize_path_name(metadata.get("series", ""), "Unknown Series")
    tag = metadata.get("edition_tag", "")
    if tag:
        return sanitize_path_name(f"{series} [{tag}]", "Unknown Series")
    return series


def title_is_redundant_with_sequence(title: str, series: str, sequence_label: str, number: str) -> bool:
    """True when `title` carries no information beyond what series + sequence
    number already convey -- it's literally the sequence prefix ("Book 5"),
    the bare series name, an omnibus range restatement, or a bare-number/
    "Book N"-phrase repeat of the number. These are the cases where stating
    the title again next to the sequence prefix would be pure duplication
    (e.g. "Book 5 - Book 5"), so a consumer should treat the title as if it
    weren't there rather than render the redundant text.
    """
    if not series or not number:
        return False
    prefix = build_sequence_prefix(sequence_label, number)
    title_key = normalize_for_compare(title)
    if title_key in {normalize_for_compare(prefix), normalize_for_compare(series)}:
        return True
    series_remainder = strip_series_prefix(title, series)
    # Omnibus/collection label ± redundant range. The range in `number`
    # already captures the span; repeating it in the title adds no
    # information. Only fires for range book_numbers so individual books
    # inside a collection container (each with a single number) are never
    # treated as redundant.
    if _is_omnibus_descriptor(series_remainder, number):
        return True
    if (
        normalize_for_compare(series_remainder) == normalize_for_compare(display_book_number(number))
        or (
            re.fullmatch(r"\d{1,4}(?:\.\d+)?", series_remainder)
            and normalize_book_number(series_remainder) == normalize_book_number(number)
        )
    ):
        return True
    if (
        detect_number_from_text(series_remainder) == normalize_book_number(number)
        and re.fullmatch(
            r"(?:book|volume|vol\.?|v|novel|side\s*story)\s+"
            r"(?:" + "|".join(NUMBER_WORDS) + r"|\d{1,4}(?:\.\d+)?)",
            clean_text(series_remainder),
            flags=re.IGNORECASE,
        )
    ):
        return True
    return False


def build_book_folder_name(metadata: dict[str, Any]) -> str:
    raw_title = metadata.get("title", "")
    series = metadata.get("series", "")
    if is_asin_like_token(raw_title):
        # An ASIN / NOREALASIN must never become a book folder name on its own.
        # Fall back to the series so the sequence logic below collapses it to
        # "Book N"; otherwise leave it blank for the Unknown Title placeholder.
        raw_title = series
    title = sanitize_path_name(raw_title, "Unknown Title")
    number = metadata.get("book_number", "")
    sequence_label = metadata.get("sequence_label", "")

    if series and number:
        prefix = build_sequence_prefix(sequence_label, number)
        if title_is_redundant_with_sequence(title, series, sequence_label, number):
            return sanitize_path_name(prefix, "Unknown Title")
        return sanitize_path_name(f"{prefix} - {title}", "Unknown Title")
    return title


def build_default_target_dir(destination_root: Path, metadata: dict[str, Any]) -> Path:
    author_dir = sanitize_path_name(
        canonical_author_name(metadata.get("author_primary") or metadata.get("author")),
        "Unknown Author",
    )
    series = metadata.get("series", "")
    book_folder = build_book_folder_name(metadata)
    if series:
        return destination_root / author_dir / series_dir_label(metadata) / book_folder
    if metadata.get("edition_tag"):
        # No series: ride the imprint tag on the book folder itself rather than
        # inventing a bare "[Imprint]" folder level (e.g.
        # "The Hobbit [Dramatized]", not "[Dramatized]/The Hobbit").
        tagged = sanitize_path_name(f"{book_folder} [{metadata['edition_tag']}]", book_folder)
        return destination_root / author_dir / tagged
    return destination_root / author_dir / book_folder


DEFAULT_NAMING_TEMPLATE = "{author}/{series}/{order} - {title},{edition}/"


def naming_template_filename_for_item(item: BookItem, template_filename: str | None) -> str | None:
    """A template's filename segment only ever applies to true single-file books.

    Multi-file (multi-chapter/track) books keep their existing filenames
    untouched regardless of what the filename template contains -- those
    files typically already carry meaningful structure (chapter/track
    numbers) that a single generic template can't safely reconstruct
    per-file without destroying it. This is deliberately unconditional: it
    doesn't matter whether Fixer has already run or the names look messy,
    multi-file internals are simply out of scope for this feature.

    `template_filename` is an extension-less stem -- the naming template
    DSL has no concept of a file extension, tokens only ever produce text.
    The item's own audio file's extension is appended here so the caller
    always gets a real, playable filename back, never a bare stem that
    would silently drop the file's type.
    """
    if len(item.audio_files) != 1:
        return None
    if template_filename is None:
        return None
    return f"{template_filename}{item.representative.suffix}"


def resolve_naming_tokens(metadata: dict[str, Any]) -> dict[str, str]:
    """Build the {token} -> value map a naming template renders against.

    One flat token per real-world concept -- no distinction between a "raw"
    field and a "composite" one; that split existed in an earlier version of
    this feature and was scrapped as unnecessary complexity. `order` still
    carries the same auto-detected "Book"/"Vol."/"Side Story" labeling the
    app has always had.

    `title` here is always the full value -- it is NOT pre-emptied for
    redundancy with `order`. Redundancy (avoiding "Book 5 - Book 5") is only
    meaningful *within a segment that uses both {order} and {title}
    together*; a segment like a standalone {title},{asin} filename never
    contains {order} at all, so there's nothing for the title to be
    redundant against there, and a title that happens to look like
    "Crystal Core 2" is a perfectly legitimate filename component.
    render_naming_template() applies the redundancy check itself, per
    segment, using title_redundant_with_order (see build_target_dir_for_template()).

    Author defaults to the literal "Unknown Author" when missing (an
    author-less book still needs *some* folder to land in); every other
    token is simply empty when absent, and it's the renderer's job -- not
    this function's -- to decide what an empty token means for the segment
    it's in.
    """
    author = canonical_author_name(metadata.get("author_primary") or metadata.get("author")) or "Unknown Author"
    series = metadata.get("series", "") or ""
    number = metadata.get("book_number", "") or ""
    sequence_label = metadata.get("sequence_label", "") or ""

    raw_title = metadata.get("title", "") or ""
    if is_asin_like_token(raw_title):
        raw_title = series
    title = raw_title

    order = build_sequence_prefix(sequence_label, number) if series and number else ""
    number_display = display_book_number(number) if series and number else ""

    return {
        "author": author,
        "narrator": metadata.get("narrator", "") or "",
        "series": series,
        "title": title,
        "order": order,
        "number": number_display,
        "publisher": metadata.get("publisher", "") or "",
        "year": metadata.get("year", "") or "",
        "asin": metadata.get("asin", "") or "",
        "edition": metadata.get("edition_tag", "") or "",
    }


NAMING_TEMPLATE_TOKEN_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_EMPTY_BRACKET_RE = re.compile(r"[\(\[]\s*[\)\]]")


class UnknownNamingTokenError(ValueError):
    """A naming template referenced a token with no known value source."""

    def __init__(self, token: str):
        super().__init__(f"Unknown naming template token: {{{token}}}")
        self.token = token


# Only the "core" identity tokens (author, series, title, order, number --
# the fields the app's own hardcoded default scheme has always treated as
# a book's identity) count toward "how many significant tokens does this
# segment have". Everything else (narrator, publisher, year, asin,
# edition) is decoration: a segment where a non-core token is the only
# other token besides one core field behaves as if that field were alone
# (collapsing silently when empty, like a bare {series} always has), and
# non-core tokens never contribute toward the "2+ tokens all empty"
# review-flag either. This reflects that a book can legitimately have no
# known narrator/publisher/year/ASIN/edition without that being a
# data-quality problem worth flagging -- unremarkable, not insufficient.
_NAMING_SIGNIFICANCE_EXCLUDED_TOKENS = frozenset({"narrator", "publisher", "year", "asin", "edition"})


def _significant_tokens(tokens: set[str]) -> set[str]:
    return tokens - _NAMING_SIGNIFICANCE_EXCLUDED_TOKENS


def _render_naming_segment(segment: str, token_values: dict[str, str]) -> tuple[str, bool]:
    """Render one literal/token segment. Returns (rendered, needs_review).

    needs_review is set only when the segment references two or more
    *significant* tokens (see _significant_tokens()) and every one of them
    resolved to an empty value -- there's genuinely not enough data to
    build that path part, as opposed to a single missing optional field
    (which the caller collapses silently) or a partially-populated segment
    (which renders as-is).
    """
    tokens = NAMING_TEMPLATE_TOKEN_RE.findall(segment)
    for token in tokens:
        if token not in token_values:
            raise UnknownNamingTokenError(token)

    rendered = NAMING_TEMPLATE_TOKEN_RE.sub(lambda m: token_values.get(m.group(1), ""), segment)

    significant = _significant_tokens(set(tokens))
    all_empty = bool(significant) and all(not token_values.get(t) for t in significant)
    needs_review = len(significant) >= 2 and all_empty
    return rendered, needs_review


NAMING_TOKEN_NAMES = frozenset(
    {
        "author",
        "narrator",
        "series",
        "title",
        "order",
        "number",
        "publisher",
        "year",
        "asin",
        "edition",
    }
)


def validate_naming_template(template: str) -> list[str]:
    """Static, pre-run checks for a naming template. Returns human-readable problems."""
    problems: list[str] = []
    stripped = NAMING_TEMPLATE_TOKEN_RE.sub("", template)
    if "{" in stripped or "}" in stripped:
        problems.append("Unbalanced or malformed curly brace in template.")
    for token in NAMING_TEMPLATE_TOKEN_RE.findall(template):
        if token not in NAMING_TOKEN_NAMES:
            problems.append(f"Unknown token: {{{token}}}")
    if "/" not in template:
        problems.append("Template has no '/' -- nothing would build a destination folder.")
    return problems


def preview_naming_template_for_root(
    root: Path, destination_root: Path, naming_template: str, limit: int = 3
) -> list[dict[str, Any]]:
    """Render a naming template against a few real sample books for a live preview.

    Scans up to `limit` items from `root` and infers their metadata the same
    way main()'s real run does, then renders each through the template
    without planning moves or touching the structure cache -- purely for
    showing the user what a template would produce before they run it.
    """
    items = build_book_items(root, destination_root, limit=limit)[:limit]
    previews: list[dict[str, Any]] = []
    for item in items:
        metadata = infer_metadata(item, root)
        result = build_target_dir_for_template(destination_root, metadata, naming_template)
        filename = naming_template_filename_for_item(item, result.filename)
        previews.append(
            {
                "source": str(item.source_path),
                "target_dir": str(result.target_dir),
                "filename": filename,
                "review_reasons": result.review_reasons,
            }
        )
    return previews


def folder_name_matches_naming_template(source_name: str, target_leaf_name: str) -> bool:
    """Fuzzy-compare a folder's own current name against what the active
    naming template would produce for it, ignoring case/punctuation/spacing
    (normalize_for_compare(), the same fuzzy-match primitive already used
    for author/series comparisons elsewhere in this file). A close-but-not-
    byte-identical match still counts -- the folder already looks organized
    per the current scheme even if its exact formatting differs slightly.
    """
    return normalize_for_compare(source_name) == normalize_for_compare(target_leaf_name)


def is_likely_existing_book_folder(item: BookItem, computed_target_dir: Path, root: Path) -> bool:
    """True when `item`'s own enclosing folder name already matches what the
    naming template computed for it -- it looks like it's already organized
    under the current scheme, wherever it currently sits.

    For a folder-kind item that's the item's own source folder. For a
    loose-file item -- the common shape build_book_items() gives a
    single-file book, with source_path pointing at the audio *file* itself,
    not a folder -- it's the file's parent folder, unless that parent is
    the scan root itself (a bare loose file with no wrapper folder has
    nothing meaningful to compare).
    """
    if item.kind == "folder":
        folder_name = item.source_path.name
    else:
        if item.source_path.parent == root:
            return False
        folder_name = item.source_path.parent.name
    return folder_name_matches_naming_template(folder_name, computed_target_dir.name)


def build_target_dir_for_template(
    destination_root: Path, metadata: dict[str, Any], naming_template: str
) -> NamingRenderResult:
    """Render a naming template into a destination folder path and filename.

    Delegates straight to the existing, unchanged build_default_target_dir()
    when the template is the shipped default -- zero behavioral risk to the
    hardcoded logic and its full existing test coverage. A custom template
    goes through resolve_naming_tokens()/render_naming_template() instead.

    The caller is responsible for merging review_reasons into whatever
    metadata dict it carries forward, same as every other review-reason
    source in this file.
    """
    if naming_template == DEFAULT_NAMING_TEMPLATE:
        return NamingRenderResult(build_default_target_dir(destination_root, metadata), None, [])

    tokens = resolve_naming_tokens(metadata)
    redundant = title_redundant_with_order(metadata)
    folder_segments, filename, reasons = render_naming_template(naming_template, tokens, redundant)
    return NamingRenderResult(destination_root.joinpath(*folder_segments), filename, reasons)


def title_redundant_with_order(metadata: dict[str, Any]) -> bool:
    """Whether this book's title is redundant with its series + sequence
    number (see title_is_redundant_with_sequence()) -- computed once here
    so render_naming_template() can apply it only within segments that
    actually use {order} and {title} together, not globally.
    """
    title = metadata.get("title", "") or ""
    series = metadata.get("series", "") or ""
    if is_asin_like_token(title):
        title = series
    if not title:
        return False
    number = metadata.get("book_number", "") or ""
    sequence_label = metadata.get("sequence_label", "") or ""
    return title_is_redundant_with_sequence(title, series, sequence_label, number)


def _naming_segment_is_effectively_empty(value: str) -> bool:
    """Whether a rendered segment has no real content once bracket/paren
    pairs and stray separators are accounted for -- used only to decide
    whether a segment should collapse (be dropped). Deliberately does NOT
    share _sanitize_naming_segment()'s never-return-empty safety net: that
    net exists to protect the *value actually written into the path* for a
    segment that's being kept (e.g. one flagged for review), which is a
    different question from "is there content here at all."
    """
    if not value:
        return True
    cleaned = sanitize_path_name(value, value)
    without_brackets = _EMPTY_BRACKET_RE.sub("", cleaned)
    return without_brackets.strip(" ,-") == ""


def _sanitize_naming_segment(value: str) -> str:
    """Strip illegal filesystem characters from a rendered segment/filename.

    Every token used to get this for free only when it happened to be a
    composite that delegated to a function which sanitized internally --
    a plain token like {title} never did, which was a real bug (a title
    containing "/" could inject an unintended extra directory level).
    Applied here, once, to every rendered segment and the filename alike,
    regardless of which tokens built it.

    Also removes an empty bracket/paren pair left over when e.g.
    "{series} [{edition}]" renders with edition empty ("Dao of Magic []"
    otherwise), and trims leading/trailing separator noise (spaces, commas,
    hyphens) left over when an edge token in a multi-token segment is empty
    -- e.g. "{order} - {title},{edition}" with title and edition both empty
    otherwise renders "Book 1 - ,". sanitize_path_name() already strips
    " .-" but never comma. The strip only applies when it leaves something
    behind: a segment that's *entirely* separator characters (the
    all-tokens-empty, flagged-for-review case) must never collapse to a
    true empty string, since Path silently drops empty components -- that
    would make a flagged item vanish from its own directory level instead
    of staying visible.
    """
    if not value:
        return value
    cleaned = sanitize_path_name(value, value)
    without_brackets = _EMPTY_BRACKET_RE.sub("", cleaned)
    stripped = without_brackets.strip(" ,-")
    if stripped:
        return stripped
    # Bracket removal and/or edge trimming fully consumed the value (e.g.
    # two bracket-wrapped empty tokens like "[][]") -- fall back a tier at
    # a time rather than return true emptiness, which Path would silently
    # drop as a path component.
    if without_brackets:
        return without_brackets
    return cleaned


def _token_values_for_segment(
    raw_segment: str, token_values: dict[str, str], distinct_tokens: set[str], title_redundant_with_order: bool
) -> dict[str, str]:
    """Title-redundancy collapsing only makes sense *within a segment that
    uses {order} and {title} together* -- a segment like a standalone
    {title},{asin} filename never contains {order} at all, so there's
    nothing for the title to be redundant against there. Returns
    token_values unchanged, or a shallow copy with title blanked out, for
    this one segment's render only.
    """
    if title_redundant_with_order and "order" in distinct_tokens and "title" in distinct_tokens:
        return dict(token_values, title="")
    return token_values


def render_naming_template(
    template: str, token_values: dict[str, str], title_redundant_with_order: bool = False
) -> tuple[list[str], str | None, list[str]]:
    """Render a user-defined naming template against resolved token values.

    Splits `template` on its final "/" into a folder-path part and a
    filename part. Each "/"-delimited folder segment collapses (is
    dropped) when it renders empty from at most one distinct token --
    covering both an absent optional field (e.g. no series) and a purely
    literal empty segment (e.g. an accidental "//"). A segment built from
    two or more distinct tokens that are all empty is kept as rendered but
    flagged for review instead of silently guessing. The filename segment
    follows the same rules, except an empty result falls back to `None`
    (the caller should keep the original filename) rather than being
    dropped outright.

    Returns (folder_segments, filename_or_None, review_reasons).
    """
    if "/" in template:
        folder_template, _, filename_template = template.rpartition("/")
    else:
        folder_template, filename_template = "", template

    review_reasons: list[str] = []
    folder_segments: list[str] = []
    if folder_template:
        for raw_segment in folder_template.split("/"):
            distinct_tokens = set(NAMING_TEMPLATE_TOKEN_RE.findall(raw_segment))
            significant = _significant_tokens(distinct_tokens)
            segment_values = _token_values_for_segment(raw_segment, token_values, distinct_tokens, title_redundant_with_order)
            rendered, needs_review = _render_naming_segment(raw_segment, segment_values)
            if needs_review:
                review_reasons.append(f"not enough data to build path segment '{raw_segment}'")
                folder_segments.append(_sanitize_naming_segment(rendered))
            elif len(significant) <= 1 and _naming_segment_is_effectively_empty(rendered):
                continue
            else:
                folder_segments.append(_sanitize_naming_segment(rendered))

    filename: str | None = None
    if filename_template:
        distinct_tokens = set(NAMING_TEMPLATE_TOKEN_RE.findall(filename_template))
        segment_values = _token_values_for_segment(filename_template, token_values, distinct_tokens, title_redundant_with_order)
        rendered, needs_review = _render_naming_segment(filename_template, segment_values)
        if needs_review:
            review_reasons.append(f"not enough data to build filename '{filename_template}'")
        elif not _naming_segment_is_effectively_empty(rendered):
            filename = _sanitize_naming_segment(rendered)

    return folder_segments, filename, review_reasons


def empty_structure_cache(
    destination_root: Path, naming_template: str = DEFAULT_NAMING_TEMPLATE
) -> dict[str, Any]:
    return {
        "schema_version": STRUCTURE_CACHE_SCHEMA_VERSION,
        "destination_root": str(destination_root),
        "naming_template": naming_template,
        "generated_at": utc_now(),
        "entries": [],
    }


def load_structure_cache(
    cache_path: Path, destination_root: Path, naming_template: str = DEFAULT_NAMING_TEMPLATE
) -> dict[str, Any]:
    if not cache_path.is_file():
        return empty_structure_cache(destination_root, naming_template)
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_structure_cache(destination_root, naming_template)
    if cache.get("schema_version") != STRUCTURE_CACHE_SCHEMA_VERSION:
        return empty_structure_cache(destination_root, naming_template)
    if cache.get("destination_root") != str(destination_root):
        return empty_structure_cache(destination_root, naming_template)
    # A cache written before this feature existed has no naming_template key
    # at all -- treat that as "built under the default template" rather than
    # an automatic mismatch, so upgrading to this feature doesn't invalidate
    # every existing user's cache the moment they update.
    if cache.get("naming_template", DEFAULT_NAMING_TEMPLATE) != naming_template:
        return empty_structure_cache(destination_root, naming_template)
    cache.setdefault("entries", [])
    return cache


def save_structure_cache(cache_path: Path, cache: dict[str, Any]) -> None:
    cache["generated_at"] = utc_now()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(json.dumps(cache, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    temporary.replace(cache_path)


def register_structure_entry(cache: dict[str, Any], entry: dict[str, Any]) -> None:
    for existing in cache.setdefault("entries", []):
        if existing.get("series_key") == entry.get("series_key") and existing.get("path") == entry.get("path"):
            for key in ["series_aliases", "author_aliases", "author_keys", "source_paths"]:
                values = set(existing.setdefault(key, []))
                values.update(entry.get(key, []))
                existing[key] = sorted(values)
            existing["book_count"] = int(existing.get("book_count", 0)) + int(entry.get("book_count", 0))
            return
    cache["entries"].append(entry)


def build_structure_cache(
    destination_root: Path,
    cache_path: Path,
    progress_every: int = 100,
    naming_template: str = DEFAULT_NAMING_TEMPLATE,
) -> dict[str, Any]:
    items = build_book_items(destination_root, destination_root)
    book_items = [item for item in items if item.kind == "folder"]
    raw_records: list[dict[str, Any]] = []
    total = len(book_items)

    for index, item in enumerate(book_items, start=1):
        if progress_every > 0 and (index == 1 or index % progress_every == 0 or index == total):
            print(f"Indexing structure {index}/{total}: {item.source_path}", file=sys.stderr)

        path_meta = infer_metadata_from_library_path(item, destination_root)
        meta = infer_metadata(item, destination_root, prefer_path_structure=True)

        # Prefer tag/sidecar metadata for series/author, but retain path aliases.
        metadata = meta
        if metadata.get("author") == "Unknown Author" and path_meta:
            metadata = path_meta
        if not metadata.get("series") and path_meta and path_meta.get("series"):
            metadata["series"] = path_meta["series"]

        series = metadata.get("series", "")
        if not series:
            continue

        primary = primary_author(metadata.get("author", ""))
        if not primary or primary == "Unknown Author":
            continue

        aliases = {series, item.source_path.parent.name}
        if path_meta and path_meta.get("series"):
            aliases.add(path_meta["series"])

        raw_records.append({
            "series": series,
            "series_key": normalize_series_key(series),
            "author": metadata.get("author", ""),
            "primary_author": primary,
            "author_keys": people_keys(metadata.get("author", "")),
            "series_aliases": sorted(alias for alias in aliases if alias),
            "source_path": str(item.source_path),
        })

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in raw_records:
        if record["series_key"]:
            grouped[record["series_key"]].append(record)

    cache = empty_structure_cache(destination_root, naming_template)
    for series_key, records in grouped.items():
        series_counts = Counter(record["series"] for record in records if record.get("series"))
        canonical_series = series_counts.most_common(1)[0][0]
        good_author_records = [
            record for record in records
            if record.get("primary_author") and not author_is_probably_bad_for_series(record.get("primary_author", ""), canonical_series)
        ]
        primary_counts = Counter(record["primary_author"] for record in (good_author_records or records) if record.get("primary_author"))
        canonical_author = primary_counts.most_common(1)[0][0]
        series_dir = destination_root / sanitize_path_name(canonical_author, "Unknown Author") / sanitize_path_name(canonical_series, "Unknown Series")

        author_aliases = sorted({record["author"] for record in records if record.get("author")})
        author_keys_set: set[str] = set()
        series_aliases_set: set[str] = set()
        source_paths = []
        for record in records:
            author_keys_set.update(record.get("author_keys", []))
            author_keys_set.update(people_keys(record.get("primary_author", "")))
            series_aliases_set.update(record.get("series_aliases", []))
            source_paths.append(record["source_path"])

        entry = {
            "series": canonical_series,
            "series_key": series_key,
            "path": str(series_dir),
            "canonical_author": canonical_author,
            "author_aliases": author_aliases,
            "author_keys": sorted(author_keys_set),
            "series_aliases": sorted(series_aliases_set),
            "book_count": len(records),
            "source_paths": sorted(source_paths),
        }
        register_structure_entry(cache, entry)

    cache["entries"].sort(key=lambda entry: (entry.get("series_key", ""), -int(entry.get("book_count", 0)), entry.get("path", "")))
    save_structure_cache(cache_path, cache)
    return cache


def entry_matches_series(entry: dict[str, Any], series: str) -> bool:
    series_key = normalize_series_key(series)
    if not series_key:
        return False
    if entry.get("series_key") == series_key:
        return True
    for alias in entry.get("series_aliases", []):
        alias_key = normalize_series_key(alias)
        if alias_key == series_key:
            return True
        if alias_key and SequenceMatcher(None, alias_key, series_key).ratio() >= 0.94:
            return True
    return False


def authors_compatible(local_author: str, other_author: str) -> bool:
    """Loose author-identity check used to veto cross-author cache merges.

    Returns True when the two author strings plausibly refer to the same
    person (shared normalized name key, containment, or high similarity), and
    False only when they are clearly different people. Empty/generic authors
    are treated as compatible so we never block on missing data.
    """
    local_norm = normalize_for_compare(local_author)
    other_norm = normalize_for_compare(other_author)
    if not local_norm or not other_norm:
        return True
    generic = {"unknown", "unknownauthor", "various", "variousauthors", "anonymous"}
    if local_norm in generic or other_norm in generic:
        return True
    local_keys = people_keys(local_author)
    other_keys = people_keys(other_author)
    if any(keys_match(a, b) for a in local_keys for b in other_keys):
        return True
    if local_norm in other_norm or other_norm in local_norm:
        return True
    return SequenceMatcher(None, local_norm, other_norm).ratio() >= 0.70


def resolve_series_directory(cache: dict[str, Any], metadata: dict[str, Any]) -> tuple[Path | None, str, dict[str, Any] | None]:
    series = metadata.get("series", "")
    if not series:
        return None, "new", None

    candidates = [entry for entry in cache.get("entries", []) if entry_matches_series(entry, series)]
    if not candidates:
        return None, "new", None

    author_keys = people_keys(metadata.get("author", ""))
    primary_key = normalize_for_compare(metadata.get("author_primary", ""))
    if primary_key and primary_key not in author_keys:
        author_keys.append(primary_key)

    author_matches = []
    for entry in candidates:
        cached_keys = entry.get("author_keys", [])
        if any(keys_match(local_key, cached_key) for local_key in author_keys for cached_key in cached_keys):
            author_matches.append(entry)

    ranked = sorted(
        author_matches or candidates,
        key=lambda entry: (-int(entry.get("book_count", 0)), entry.get("path", "")),
    )

    # If the series name matched but no cached entry shares this author, do not
    # blindly merge into a same-named series owned by a clearly different
    # author (e.g. Arthur C. Clarke's "Cradle" vs Will Wight's "Cradle").
    local_author = metadata.get("author", "")
    if (
        author_keys
        and not author_matches
        and not author_is_probably_bad_for_series(metadata.get("author_primary", "") or local_author, series)
        and not authors_compatible(local_author, ranked[0].get("canonical_author", ""))
    ):
        return None, "new", None

    if len(ranked) > 1:
        top_count = int(ranked[0].get("book_count", 0))
        second_count = int(ranked[1].get("book_count", 0))
        if top_count == second_count and not author_matches:
            return None, "ambiguous", None

    return Path(ranked[0]["path"]), "existing", ranked[0]


def apply_cache_to_metadata(metadata: dict[str, Any], cache_entry: dict[str, Any] | None) -> dict[str, Any]:
    metadata = dict(metadata)
    if not cache_entry:
        return metadata
    if cache_entry.get("canonical_author"):
        canonical_author = sanitize_path_name(cache_entry["canonical_author"], "Unknown Author")
        metadata["author_primary"] = canonical_author
        if author_is_probably_bad_for_series(metadata.get("author", ""), metadata.get("series", cache_entry.get("series", ""))):
            reasons = list(metadata.get("review_reasons", []))
            reason = "author corrected from existing library structure"
            if reason not in reasons:
                reasons.append(reason)
            metadata["review_reasons"] = reasons
            metadata["author"] = canonical_author
    if cache_entry.get("series"):
        metadata["series"] = clean_series_name(cache_entry["series"])
    return metadata


def build_cached_target_dir(
    destination_root: Path,
    metadata: dict[str, Any],
    cache: dict[str, Any],
    naming_template: str = DEFAULT_NAMING_TEMPLATE,
) -> TargetResolution:
    # Dramatized adaptations never merge into an existing straight-reading
    # series folder; they always route to their own "Series [Imprint]" bucket.
    if metadata.get("edition_tag"):
        result = build_target_dir_for_template(destination_root, metadata, naming_template)
        if result.review_reasons:
            metadata = dict(metadata, review_reasons=_merged_review_reasons(metadata, result.review_reasons))
        return TargetResolution(result.target_dir, result.filename, "new", metadata)

    series_dir, status, entry = resolve_series_directory(cache, metadata)
    effective_metadata = apply_cache_to_metadata(metadata, entry)
    if series_dir is not None:
        # Known limitation: a book routed into an already-indexed series
        # folder always uses build_book_folder_name() for its leaf, not the
        # naming_template -- the structure cache only stores author/series
        # path aliases, not a per-book rendered leaf. Since the cache is
        # invalidated whenever naming_template changes (see
        # load_structure_cache), this branch only fires once a rebuild has
        # already happened, at which point book_folder still reflects the
        # built-in logic rather than the active template's own book-level
        # segment definition. Filename customization is scoped out of this
        # branch for the same reason -- it's cache-routed, not rendered.
        book_folder = build_book_folder_name(effective_metadata)
        return TargetResolution(series_dir / book_folder, None, status, effective_metadata)
    result = build_target_dir_for_template(destination_root, effective_metadata, naming_template)
    if result.review_reasons:
        effective_metadata = dict(
            effective_metadata, review_reasons=_merged_review_reasons(effective_metadata, result.review_reasons)
        )
    return TargetResolution(result.target_dir, result.filename, status, effective_metadata)


def _merged_review_reasons(metadata: dict[str, Any], reasons: list[str]) -> list[str]:
    existing = list(metadata.get("review_reasons", []))
    for reason in reasons:
        if reason not in existing:
            existing.append(reason)
    return existing



def _series_aliases_for_entry(entry: dict[str, Any]) -> list[str]:
    aliases = [str(entry.get("series", ""))]
    aliases.extend(str(alias) for alias in entry.get("series_aliases", []) if str(alias).strip())
    cleaned: list[str] = []
    seen = set()
    for alias in aliases:
        alias = clean_series_name(alias)
        key = normalize_for_compare(alias)
        if alias and key and key not in seen:
            cleaned.append(alias)
            seen.add(key)
    return sorted(cleaned, key=len, reverse=True)


def apply_cache_prefix_fallback(metadata: dict[str, Any], item: BookItem, cache: dict[str, Any]) -> dict[str, Any]:
    """Use existing cached series when metadata is incomplete but the folder name clearly starts with a known series.

    This fixes cases like:
      /audiobooks/Dashing Devil/Dashing Devil 9 Immortal's Intent
    where ffprobe lacks series tags, but the source folder name obviously belongs to an
    existing cached series.
    """
    if metadata.get("series"):
        return metadata

    source_text = sanitize_path_name(cleanup_title_artifacts(item.source_path.name), "")
    if not source_text:
        return metadata

    best: tuple[int, dict[str, Any], str, str] | None = None
    source_norm = normalize_for_compare(source_text)

    for entry in cache.get("entries", []):
        for alias in _series_aliases_for_entry(entry):
            alias_norm = normalize_for_compare(alias)
            if not alias_norm or not source_norm.startswith(alias_norm):
                continue

            # Ensure this is a real prefix, not a coincidental substring.
            prefix_re = re.compile(rf"^\s*{re.escape(alias)}(?:\b|\s|[-_:,])", re.IGNORECASE)
            if not prefix_re.search(source_text):
                continue

            rest = prefix_re.sub("", source_text, count=1).strip(" -_:,")
            score = len(alias_norm) + int(entry.get("book_count", 0))
            if best is None or score > best[0]:
                best = (score, entry, alias, rest)

    if best is None:
        return metadata

    _score, entry, _alias, rest = best

    # Do not adopt a cached series whose canonical author clearly differs from a
    # known local author. The prefix match alone is not enough to overwrite a
    # real author (e.g. Arthur C. Clarke's "Cradle" must not become Will Wight).
    local_author = metadata.get("author", "")
    local_primary = metadata.get("author_primary", "") or local_author
    if (
        people_keys(local_author)
        and not author_is_probably_bad_for_series(local_primary, str(entry.get("series", "")))
        and not authors_compatible(local_author, str(entry.get("canonical_author", "")))
    ):
        return metadata

    metadata = dict(metadata)
    reasons = list(metadata.get("review_reasons", []))
    reason = "series inferred from existing library prefix"
    if reason not in reasons:
        reasons.append(reason)
    metadata["review_reasons"] = reasons
    metadata["series"] = clean_series_name(str(entry.get("series") or _alias))
    if entry.get("canonical_author"):
        metadata["author_primary"] = sanitize_path_name(str(entry["canonical_author"]), metadata.get("author_primary", "Unknown Author"))

    if rest:
        match = re.match(r"^(?:(book|volume|vol\.?|v|#)\s*)?(\d{1,4}(?:\.\d+)?)(?:\s*[-_:,]\s*|\s+)?(.*)$", rest, flags=re.IGNORECASE)
        if match:
            metadata.setdefault("book_number", "")
            if not metadata.get("book_number"):
                metadata["book_number"] = normalize_book_number(match.group(2))
            label = normalize_sequence_label(match.group(1) or "") or detect_sequence_label_from_text(rest)
            if label:
                metadata["sequence_label"] = choose_sequence_label(label, metadata.get("sequence_label", ""))
            remainder = clean_text(match.group(3))
            if remainder and not title_is_bad_after_cleanup(remainder):
                metadata["title"] = clean_book_title(remainder, metadata["series"], metadata.get("book_number", ""))
        elif not title_is_bad_after_cleanup(rest):
            metadata["title"] = clean_book_title(rest, metadata["series"], metadata.get("book_number", ""))

    return metadata


def title_matches_author_name(title: str, author: str) -> bool:
    title_key = normalize_for_compare(title)
    if not title_key:
        return False
    return any(title_key == key for key in people_keys(author))


def normalize_metadata_title_for_target(metadata: dict[str, Any]) -> dict[str, Any]:
    """Final target-title cleanup after author/series have stabilized."""
    metadata = dict(metadata)
    series = clean_series_name(metadata.get("series", ""))
    number = metadata.get("book_number", "")
    title = metadata.get("title", "")
    author = metadata.get("author", "")
    source = metadata.get("metadata_source", "")
    trusted = metadata_source_is_trusted(source)

    cleaned_title = clean_book_title(title, series, number, trusted=trusted)
    if (
        series
        and (
            title_is_bad_after_cleanup(cleaned_title)
            or is_marketing_descriptor(cleaned_title)
            or title_matches_author_name(cleaned_title, author)
        )
        and not trusted
    ):
        cleaned_title = clean_book_title(series, series, number)

    metadata["title"] = sanitize_path_name(cleaned_title, "Unknown Title")
    metadata["series"] = series
    metadata["author"] = clean_author_credits(author)
    metadata["author_primary"] = primary_author(metadata["author"])
    return metadata


def build_run_author_corrections(metadata_items: list[dict[str, Any]]) -> dict[str, str]:
    """Infer canonical authors from the same dry-run batch.

    This fixes grouped chapterized volumes where a few sidecars incorrectly set
    author=series, while sibling volumes in the same run have the real author.
    It only produces a correction when at least one good author is present for
    that exact series key.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metadata in metadata_items:
        series = clean_series_name(metadata.get("series", ""))
        key = normalize_series_key(series)
        if key:
            grouped[key].append(metadata)

    corrections: dict[str, str] = {}
    for key, records in grouped.items():
        series_counts = Counter(clean_series_name(record.get("series", "")) for record in records if record.get("series"))
        canonical_series = series_counts.most_common(1)[0][0] if series_counts else ""
        good_authors = []
        for record in records:
            author = clean_author_credits(record.get("author", ""))
            primary = primary_author(author)
            primary_key = normalize_for_compare(primary)
            if (
                primary
                and primary != "Unknown Author"
                and primary_key not in GENERIC_AUTHOR_KEYS
                and primary_key not in GENERIC_STRUCTURE_KEYS
                and not author_is_probably_bad_for_series(primary, canonical_series)
            ):
                good_authors.append(primary)
        if good_authors:
            corrections[key] = Counter(good_authors).most_common(1)[0][0]
    return corrections


def apply_run_author_correction(metadata: dict[str, Any], corrections: dict[str, str]) -> dict[str, Any]:
    metadata = dict(metadata)
    series = clean_series_name(metadata.get("series", ""))
    key = normalize_series_key(series)
    canonical_author = corrections.get(key, "")
    if canonical_author and author_is_probably_bad_for_series(metadata.get("author", ""), series):
        reasons = list(metadata.get("review_reasons", []))
        reason = "author inferred from other books in this run"
        if reason not in reasons:
            reasons.append(reason)
        metadata["review_reasons"] = reasons
        metadata["author"] = canonical_author
        metadata["author_primary"] = canonical_author
    return metadata


def load_overrides(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def override_for_series(overrides: dict[str, Any], series: str) -> dict[str, Any]:
    if not overrides or not series:
        return {}

    series_map = overrides.get("series", {})
    if not isinstance(series_map, dict):
        return {}

    keys_to_try = [series, normalize_series_key(series), normalize_for_compare(series)]
    for key in keys_to_try:
        value = series_map.get(key)
        if isinstance(value, dict):
            return value

    series_key = normalize_series_key(series)
    for key, value in series_map.items():
        if isinstance(value, dict) and normalize_series_key(str(key)) == series_key:
            return value

    return {}


def apply_overrides_to_cache(cache: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    if not overrides:
        return cache

    cache = dict(cache)
    entries = []
    for entry in cache.get("entries", []):
        entry = dict(entry)
        override = override_for_series(overrides, entry.get("series", ""))
        if override:
            if override.get("series"):
                entry["series"] = sanitize_path_name(str(override["series"]), entry.get("series", ""))
            if override.get("canonical_author"):
                entry["canonical_author"] = sanitize_path_name(str(override["canonical_author"]), entry.get("canonical_author", ""))
            if entry.get("canonical_author") and entry.get("series"):
                entry["path"] = str(
                    Path(cache.get("destination_root", "")) /
                    sanitize_path_name(entry["canonical_author"], "Unknown Author") /
                    sanitize_path_name(entry["series"], "Unknown Series")
                )
            aliases = override.get("series_aliases", [])
            if isinstance(aliases, list):
                current_aliases = set(entry.setdefault("series_aliases", []))
                current_aliases.update(str(alias) for alias in aliases if str(alias).strip())
                entry["series_aliases"] = sorted(current_aliases)
        entries.append(entry)

    cache["entries"] = entries
    return cache


def apply_overrides_to_metadata(metadata: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    if not overrides:
        return metadata

    metadata = dict(metadata)

    author_aliases = overrides.get("author_aliases", {})
    if isinstance(author_aliases, dict):
        for key, value in author_aliases.items():
            if normalize_for_compare(str(key)) == normalize_for_compare(metadata.get("author_primary", "")):
                metadata["author_primary"] = sanitize_path_name(str(value), metadata.get("author_primary", ""))
            if normalize_for_compare(str(key)) == normalize_for_compare(metadata.get("author", "")):
                metadata["author"] = sanitize_path_name(str(value), metadata.get("author", ""))

    override = override_for_series(overrides, metadata.get("series", ""))
    if override:
        if override.get("series"):
            metadata["series"] = clean_series_name(str(override["series"]))
        if override.get("canonical_author"):
            metadata["author_primary"] = sanitize_path_name(str(override["canonical_author"]), "Unknown Author")
        if override.get("sequence_label"):
            metadata["sequence_label"] = normalize_sequence_label(str(override["sequence_label"]))

    return metadata


def unique_target_path(target_dir: Path, filename: str, reserved_targets: set[Path] | None = None) -> Path:
    reserved_targets = reserved_targets or set()
    target_path = target_dir / filename
    if not target_path.exists() and target_path not in reserved_targets:
        return target_path

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = target_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists() and candidate not in reserved_targets:
            return candidate
        counter += 1


def plan_folder_move(
    item: BookItem,
    target_dir: Path,
    reserved_targets: set[Path] | None = None,
    merge_existing: bool = False,
    reserved_target_dirs: set[Path] | None = None,
) -> tuple[bool, str]:
    reserved_targets = reserved_targets or set()
    reserved_target_dirs = reserved_target_dirs or set()
    source_dir = item.source_path
    if source_dir == target_dir:
        return False, "already in target folder"
    if target_dir in reserved_targets:
        return False, "target folder already planned"
    if target_dir in reserved_target_dirs:
        # A different book item (folder or loose file) already claimed this same
        # destination directory this run -- e.g. a chapter-split multi-part book
        # and a separately merged single-file edition of the same book, sitting
        # in different source locations but resolving to the identical target.
        # Neither file would literally overwrite the other, but landing both in
        # the same destination is a real duplicate-content conflict, not a safe
        # automatic merge -- surface it for review instead of moving either.
        return False, "target folder already used by another book this run"
    if target_dir.exists() and target_dir != source_dir and not merge_existing:
        return False, "target folder already exists"
    if source_dir in target_dir.parents:
        return False, "target would move folder into its own subtree"
    return True, ""


FILENAME_RELEASE_JUNK_RE = re.compile(
    r"(?:"
    r"\[[^\]]*(?:ASIN\.?B0[A-Z0-9]+|B0[A-Z0-9]{7,}|ENG|ENGLISH|"
    r"\d{4}|(?:64|96|128|192|256|320)|RYUTO)[^\]]*\]"
    r"|"
    r"\{[^{}]+\}"
    r"|"
    r"\b(?:light\s+novel|audiobook|unabridged)\b"
    r")",
    re.IGNORECASE,
)


def filename_has_cleanup_noise(filename: str) -> bool:
    """Return True when a loose audio filename contains release/metadata junk.

    Folder titles were already being cleaned, but loose-file targets preserved
    the original audio filename. That left ugly targets such as:
      .../Vol. 5/Series, Vol. 5 - vol_05 [2025] [ASIN...] [ENG].m4b
    The folder is the ABS identity; when the filename is noisy, use a clean
    filename derived from the target book folder instead.
    """
    stem = Path(filename).stem
    if FILENAME_RELEASE_JUNK_RE.search(stem):
        return True
    if contains_title_noise(stem):
        return True
    # Common release names for single volumes: vol_05, track dumps, etc.
    if re.search(r"(?:^|[\s._-])vol[\s._-]*\d{1,4}(?:$|[\s._-])", stem, re.IGNORECASE):
        return True
    return False


def clean_loose_audio_filename(source_file: Path, target_dir: Path) -> str:
    """Choose the target filename for a loose audio file.

    By default preserve the original filename. If it contains release junk,
    replace it with the already-clean target folder name plus the original
    audio extension. Companion sidecars are renamed consistently during apply
    because their target is based on the final audio target name.
    """
    if not filename_has_cleanup_noise(source_file.name):
        return source_file.name

    folder_name = sanitize_path_name(target_dir.name, source_file.stem)
    if re.match(r"^(?:Book|Books|Vol\.|Volume|Volumes|Novel|Novels|Side Story)\s+\d", folder_name, flags=re.IGNORECASE):
        series_name = sanitize_path_name(target_dir.parent.name, "")
        stem = f"{series_name} - {folder_name}" if series_name else folder_name
    else:
        stem = folder_name

    if not stem:
        stem = sanitize_path_name(cleanup_title_artifacts(source_file.stem), source_file.stem)
    return f"{stem}{source_file.suffix}"


def plan_loose_file_move(
    item: BookItem,
    target_dir: Path,
    reserved_targets: set[Path] | None = None,
    reserved_target_dirs: set[Path] | None = None,
    template_filename: str | None = None,
) -> tuple[bool, Path | None, str]:
    """Choose the loose file's target filename.

    A naming template's filename takes precedence when the item qualifies
    (true single-file book -- always the case for a loose_file item, but
    routed through naming_template_filename_for_item() for one shared rule
    with the folder-kind path). Falls back to the existing noise-cleanup
    behavior via clean_loose_audio_filename() when no template filename
    applies, so the default template changes nothing here.
    """
    reserved_target_dirs = reserved_target_dirs or set()
    source_file = item.source_path
    filename = naming_template_filename_for_item(item, template_filename) or clean_loose_audio_filename(
        source_file, target_dir
    )
    if source_file.parent == target_dir and source_file.name == filename:
        return False, None, "already in target folder"
    if target_dir in reserved_target_dirs:
        # Same rationale as plan_folder_move: a different book item already
        # claimed this destination directory this run. Uniquifying this file's
        # name and nesting it alongside would silently mix two representations
        # of what is likely the same book -- flag it instead.
        return False, None, "target folder already used by another book this run"
    target_path = unique_target_path(target_dir, filename, reserved_targets)
    return True, target_path, ""


def companion_files_for(audio_path: Path) -> list[Path]:
    companions: list[Path] = []
    for suffix in COMPANION_SUFFIXES:
        companion = audio_path.with_name(audio_path.name + suffix)
        if companion.exists() and companion.is_file():
            companions.append(companion)

    for ext in COMPANION_SIDE_EXTENSIONS:
        companion = audio_path.with_suffix(ext)
        if companion.exists() and companion.is_file():
            companions.append(companion)

    return sorted(set(companions))


def remove_empty_parents(start_dir: Path, root: Path) -> None:
    current = start_dir
    while current != root and root in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def move_folder_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if destination.exists():
            raise FileExistsError(f"merge target already exists: {destination}")
        shutil.move(str(child), str(destination))
    source.rmdir()


def execute_planned_move(
    move: dict[str, Any],
    *,
    merge_existing_targets: bool,
    remove_empty_dirs: bool,
    root: Path,
) -> None:
    """Execute one planned move: relocate the book (folder or loose file) and
    its companions, then optionally clean up now-empty source parents.

    Raises on any filesystem error so the caller can count the move as
    failed and continue with the rest of the batch instead of aborting the
    whole run on one bad move.
    """
    source: Path = move["source"]
    target: Path = move["target"]
    original_parent = source.parent

    if move["kind"] == "folder":
        if move.get("partial_group"):
            # This folder holds a recognized group *and* file(s) outside it
            # (e.g. a separately merged single-file edition of the same book,
            # planned as its own loose_file item) -- relocate everything
            # except those leftover files and their own companions, and leave
            # the source folder in place holding them.
            excluded: set[Path] = set()
            for leftover in move.get("leftover_files", []):
                excluded.add(leftover)
                excluded.update(companion_files_for(leftover))
            target.mkdir(parents=True, exist_ok=True)
            for child in sorted(source.iterdir()):
                if child in excluded:
                    continue
                destination = target / child.name
                if destination.exists():
                    raise FileExistsError(f"target already exists: {destination}")
                shutil.move(str(child), str(destination))
        elif target.exists() and merge_existing_targets:
            move_folder_contents(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        # Companions inside the folder moved with it; strip per-file prefix
        # from .metadata.json and .libraforge.json so ABS and the fixer
        # can locate them without the audio filename prefix.
        for companion in move.get("companions", []):
            if companion.name.endswith(".metadata.json"):
                moved = target / companion.name
                final = target / "metadata.json"
                if moved.exists() and not final.exists():
                    moved.rename(final)
            elif companion.name.endswith(".libraforge.json") and companion.name != "libraforge.json":
                moved = target / companion.name
                final = target / "libraforge.json"
                if moved.exists() and not final.exists():
                    moved.rename(final)
        # A naming template's filename for a true single-file book (see
        # naming_template_filename_for_item()) is applied here, after the
        # folder itself has already landed at `target` -- multi-file books
        # never set rename_audio_to, so this is a no-op for them.
        rename_audio_to = move.get("rename_audio_to")
        if rename_audio_to:
            original_audio = target / move["original_audio_name"]
            renamed_audio = target / rename_audio_to
            if original_audio.exists() and not renamed_audio.exists():
                original_audio.rename(renamed_audio)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        for companion in move.get("companions", []):
            if companion.stem == source.stem:
                # Side-extension companion (e.g. Book.jpg alongside Book.m4b):
                # keep the same stem, just change the extension.
                companion_target = target.with_suffix(companion.suffix)
            else:
                # Suffix companion (e.g. Book.m4b.libraforge.json):
                # append the suffix after the full audio filename.
                suffix = companion.name.removeprefix(source.name)
                companion_target = target.with_name(target.name + suffix)
            shutil.move(str(companion), str(companion_target))
            if companion_target.name.endswith(".metadata.json"):
                final = companion_target.parent / "metadata.json"
                if not final.exists():
                    companion_target.rename(final)
            elif companion_target.name.endswith(".libraforge.json") and companion_target.name != "libraforge.json":
                final = companion_target.parent / "libraforge.json"
                if not final.exists():
                    companion_target.rename(final)

    if remove_empty_dirs:
        remove_empty_parents(original_parent, root)


def count_audio_extension(root: Path, extension: str) -> int:
    count = 0
    for audio_file in root.rglob(f"*{extension}"):
        if not should_ignore_path(audio_file, root):
            count += 1
    return count



def add_metadata_review_reason(metadata: dict[str, Any], reason: str) -> dict[str, Any]:
    metadata = dict(metadata)
    reasons = list(metadata.get("review_reasons", []))
    if reason not in reasons:
        reasons.append(reason)
    metadata["review_reasons"] = reasons
    return metadata


def make_skipped_review_move(
    *,
    item: BookItem,
    metadata: dict[str, Any],
    target: Path,
    reason: str,
    structure: str,
) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "source": item.source_path,
        "target": target,
        "metadata": add_metadata_review_reason(metadata, reason),
        "companions": [],
        "audio_count": len(item.audio_files),
        "structure": structure,
        "skipped": True,
        "skip_reason": reason,
    }


def print_skipped_review(move: dict[str, Any]) -> None:
    print_move(move)
    print(f"  SKIPPED: {move.get('skip_reason', 'skipped')}")
    print()


def print_move(move: dict[str, Any]) -> None:
    metadata = move["metadata"]
    print("BOOK:")
    print(f"  Kind:   {move['kind']}")
    print(f"  Title:  {metadata['title']}")
    print(f"  Author: {metadata['author']}")
    if metadata.get("author_primary") and metadata.get("author_primary") != metadata.get("author"):
        print(f"  Folder Author: {metadata['author_primary']}")
    print(f"  Files:  {move['audio_count']}")
    print(f"  Metadata Source: {metadata.get('metadata_source', 'unknown')}")
    if metadata.get("review_reasons"):
        print(f"  Review Reasons: {' | '.join(metadata['review_reasons'])}")
    print(f"  Structure: {move.get('structure', 'new')}")
    if metadata.get("series"):
        print(f"  Series: {metadata['series']}")
    if metadata.get("book_number"):
        label = normalize_sequence_label(metadata.get("sequence_label", "")) or "Book"
        print(f"  Number: {label} {display_book_number(metadata['book_number'])}")
    # Folder moves and skipped-review moves show the bare directory (a
    # skipped review never reaches plan_loose_file_move to append a
    # filename). An *accepted* loose-file move's target is the full file
    # path -- shown in full, not truncated to its parent directory, so a
    # naming template's filename half (asin/title/etc. in the actual
    # filename, not just the folder) is visible in the report instead of
    # silently hidden.
    source_display = move["source"]
    target_display = move["target"]
    print("  MOVE:")
    print(f"    {source_display}")
    print("  TO:")
    print(f"    {target_display}")
    print()


def print_failed_move(move: dict[str, Any]) -> None:
    metadata = move["metadata"]
    print("FAILED BOOK:")
    print(f"  Kind:   {move['kind']}")
    print(f"  Title:  {metadata['title']}")
    print(f"  Author: {metadata['author']}")
    print(f"  Files:  {move['audio_count']}")
    source_display = move["source"]
    target_display = move["target"] if move["kind"] == "folder" else move["target"].parent
    print("  MOVE:")
    print(f"    {source_display}")
    print("  TO:")
    print(f"    {target_display}")
    print(f"  Error: {move.get('error', 'unknown error')}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Organize audiobook files/folders into Audiobookshelf-friendly folders using metadata and a structure cache."
    )
    parser.add_argument("root", help="Source directory to scan, e.g. /audiobooks/_unorganized or /audiobooks")
    parser.add_argument("--destination-root", help="Destination library root. Defaults to parent when root is _unorganized; otherwise root.")
    parser.add_argument("--apply", action="store_true", help="Actually move files/folders. Default is dry-run.")
    parser.add_argument("--m4b-only", action="store_true", help="Only process items whose audio files are all .m4b.")
    parser.add_argument("--allow-unknown-author", action="store_true", help="Allow moves whose metadata has no author. Disabled by default.")
    parser.add_argument(
        "--include-existing-book-folders",
        action="store_true",
        help=(
            "Include folders whose own name already matches what the naming "
            "template would produce for them. Disabled by default, in which "
            "case they're skipped and counted separately. When included, "
            "they're moved into place with their current folder name kept "
            "as-is rather than renamed to the template's own rendering."
        ),
    )
    parser.add_argument(
        "--skip-pattern",
        action="append",
        default=[],
        help=(
            "Skip books whose source path or inferred metadata contains this "
            "case-insensitive text. Can be used multiple times, e.g. "
            "--skip-pattern 'Casual Farming'."
        ),
    )
    parser.add_argument(
        "--acknowledge-no-sidecars",
        action="store_true",
        help=(
            "Proceed even though no scanned item has a fixer/marker sidecar. "
            "Without this flag, a scan root where nothing has ever been "
            "processed by the fixer prints NO_SIDECARS_FOUND and exits "
            "before planning any moves, since multi-file book handling "
            "leans on metadata the fixer writes."
        ),
    )
    parser.add_argument("--no-companions", action="store_true", help="Do not move known companion files with loose audio files.")
    parser.add_argument("--remove-empty-dirs", action="store_true", help="After applying moves, remove empty source directories up to the scan root.")
    parser.add_argument("--structure-cache", default=str(DEFAULT_STRUCTURE_CACHE), help="Persistent library structure cache JSON.")
    parser.add_argument("--rebuild-structure-cache", action="store_true", help="Rebuild the structure cache from the destination library before planning.")
    parser.add_argument("--index-only", action="store_true", help="Rebuild/load the structure cache and exit without planning moves.")
    parser.add_argument("--consolidate-structures", action="store_true", help="Consolidate existing book folders into the cached canonical ABS structure.")
    parser.add_argument("--no-structure-cache", action="store_true", help="Do not use the persistent structure cache for target resolution.")
    parser.add_argument("--merge-existing-targets", action="store_true", help="When applying folder moves, merge into an existing target folder instead of skipping. Safer default is skip.")
    parser.add_argument("--max-items", type=int, default=0, help="Limit scanned book items. 0 means no limit.")
    parser.add_argument("--progress-every", type=int, default=25, help="Print progress every N items. 0 disables progress.")
    parser.add_argument("--override-file", help="Optional JSON file for manual canonical series/author overrides. Useful for cases like co-authored series where metadata order is not the desired folder author.")
    parser.add_argument(
        "--naming-template",
        default=DEFAULT_NAMING_TEMPLATE,
        help=(
            "Destination folder/filename template. '/' marks a folder level, "
            "everything after the last '/' is the filename (applies only to "
            "single-file books). Default reproduces the built-in scheme."
        ),
    )
    args = parser.parse_args()

    naming_template_problems = validate_naming_template(args.naming_template)
    if naming_template_problems:
        parser.error("Invalid --naming-template: " + "; ".join(naming_template_problems))

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"ERROR: root does not exist or is not a directory: {root}")

    destination_root = Path(args.destination_root).resolve() if args.destination_root else (root.parent if root.name == "_unorganized" else root)
    if not destination_root.is_dir():
        raise SystemExit(f"ERROR: destination root does not exist or is not a directory: {destination_root}")
    if root in destination_root.parents:
        raise SystemExit("ERROR: destination root cannot be inside the scan root")

    cache_path = Path(args.structure_cache).resolve()
    overrides = load_overrides(Path(args.override_file).resolve() if args.override_file else None)
    if args.no_structure_cache:
        cache = empty_structure_cache(destination_root, args.naming_template)
    elif args.rebuild_structure_cache or args.index_only or not cache_path.is_file():
        cache = build_structure_cache(destination_root, cache_path, args.progress_every, args.naming_template)
    else:
        cache = load_structure_cache(cache_path, destination_root, args.naming_template)

    if overrides:
        cache = apply_overrides_to_cache(cache, overrides)

    if args.index_only:
        print(f"Source root: {root}")
        print(f"Destination root: {destination_root}")
        print(f"Structure cache: {cache_path}")
        print(f"Structure cache entries: {len(cache.get('entries', []))}")
        print("Mode: INDEX ONLY")
        return

    items = build_book_items(root, destination_root)
    if args.m4b_only:
        items = [item for item in items if all(audio_file.suffix.lower() == ".m4b" for audio_file in item.audio_files)]
    if args.max_items > 0:
        items = items[:args.max_items]

    if items and not args.acknowledge_no_sidecars and not any_item_has_sidecar(items):
        print(f"Found book items: {len(items)}")
        print("NO_SIDECARS_FOUND")
        return

    planned_moves: list[dict[str, Any]] = []
    skipped_reviews: list[dict[str, Any]] = []
    reserved_targets: set[Path] = set()
    # Tracks destination directories claimed by any book item this run (folder
    # or loose file), separately from reserved_targets' exact file/folder paths.
    # A second, unrelated item resolving to the same destination directory --
    # e.g. a chapter-split multi-part book and a separately merged single-file
    # edition of the same book -- is a real duplicate-content conflict even
    # though their exact file paths never collide.
    reserved_target_dirs: set[Path] = set()

    skipped_unknown_author = 0
    skipped_already_target = 0
    skipped_conflicts = 0
    skipped_ambiguous_structure = 0
    skipped_pattern_match = 0
    skipped_existing_book_folders = 0
    matched_existing_structure = 0
    ambiguous_structure = 0

    total = len(items)
    inferred_items: list[tuple[int, BookItem, dict[str, Any]]] = []
    for index, item in enumerate(items, start=1):
        if args.progress_every > 0 and (index == 1 or index % args.progress_every == 0 or index == total):
            print(f"Scanning {index}/{total}: {item.source_path}", file=sys.stderr)

        metadata = infer_metadata(item, root, prefer_path_structure=args.consolidate_structures and root == destination_root)
        metadata = apply_overrides_to_metadata(metadata, overrides)
        metadata = apply_cache_prefix_fallback(metadata, item, cache)
        inferred_items.append((index, item, metadata))

    run_author_corrections = build_run_author_corrections([metadata for _index, _item, metadata in inferred_items])

    for index, item, metadata in inferred_items:
        metadata = apply_run_author_correction(metadata, run_author_corrections)
        metadata = normalize_metadata_title_for_target(metadata)

        skip_due_to_pattern, skip_pattern = matches_skip_patterns(
            source_path=item.source_path,
            metadata=metadata,
            patterns=args.skip_pattern,
        )
        if skip_due_to_pattern:
            skipped_pattern_match += 1
            target_dir = build_target_dir_for_template(destination_root, metadata, args.naming_template).target_dir
            reason = f"skipped: matched skip pattern: {skip_pattern}"
            skipped_reviews.append(make_skipped_review_move(
                item=item,
                metadata=metadata,
                target=target_dir,
                reason=reason,
                structure="skipped_pattern_match",
            ))
            print(f"SKIP: matched skip pattern: {skip_pattern} | {item.source_path}", file=sys.stderr)
            continue

        if metadata["author"] == "Unknown Author" and not args.allow_unknown_author:
            skipped_unknown_author += 1
            target_dir = build_target_dir_for_template(destination_root, metadata, args.naming_template).target_dir
            reason = "skipped unknown author"
            skipped_reviews.append(make_skipped_review_move(
                item=item,
                metadata=metadata,
                target=target_dir,
                reason=reason,
                structure="skipped_unknown_author",
            ))
            print(f"SKIP: unknown author | {item.source_path}", file=sys.stderr)
            continue

        resolution = build_cached_target_dir(
            destination_root, metadata, cache, naming_template=args.naming_template
        )
        target_dir = resolution.target_dir
        structure_status = resolution.status
        metadata = resolution.metadata
        if structure_status == "existing":
            matched_existing_structure += 1
        elif structure_status == "ambiguous":
            ambiguous_structure += 1
            skipped_ambiguous_structure += 1
            reason = "skipped ambiguous structure match"
            skipped_reviews.append(make_skipped_review_move(
                item=item,
                metadata=metadata,
                target=target_dir,
                reason=reason,
                structure="skipped_ambiguous_structure",
            ))
            print(f"SKIP: ambiguous structure | {item.source_path}", file=sys.stderr)
            continue

        if is_likely_existing_book_folder(item, target_dir, root):
            if not args.include_existing_book_folders:
                skipped_existing_book_folders += 1
                reason = "skipped: folder name already matches the naming template"
                skipped_reviews.append(make_skipped_review_move(
                    item=item,
                    metadata=metadata,
                    target=target_dir,
                    reason=reason,
                    structure="skipped_existing_book_folders",
                ))
                print(f"SKIP: likely existing book folder | {item.source_path}", file=sys.stderr)
                continue
            # Included: keep the folder's own current name rather than
            # renaming it to the template's rendering -- it already looks
            # organized under this scheme, so trust what's there. For a
            # loose-file item this is its wrapper folder's name (the file's
            # own name is decided separately, unaffected, by
            # plan_loose_file_move below).
            existing_folder_name = item.source_path.name if item.kind == "folder" else item.source_path.parent.name
            target_dir = target_dir.parent / existing_folder_name

        if item.kind == "folder":
            can_move, reason = plan_folder_move(
                item, target_dir, reserved_targets,
                merge_existing=args.merge_existing_targets,
                reserved_target_dirs=reserved_target_dirs,
            )
            if not can_move:
                if reason == "already in target folder":
                    skipped_already_target += 1
                else:
                    skipped_conflicts += 1
                    skipped_reviews.append(make_skipped_review_move(
                        item=item,
                        metadata=metadata,
                        target=target_dir,
                        reason=f"skipped conflict: {reason}",
                        structure="skipped_conflict",
                    ))
                print(f"SKIP: {reason} | {item.source_path} -> {target_dir}", file=sys.stderr)
                continue
            reserved_targets.add(target_dir)
            reserved_target_dirs.add(target_dir)
            folder_companions: list[Path] = []
            if not args.no_companions:
                meta_sidecar = item.representative.with_name(
                    item.representative.name + ".metadata.json"
                )
                if meta_sidecar.exists():
                    folder_companions.append(meta_sidecar)
            planned_move = {
                "kind": item.kind,
                "source": item.source_path,
                "target": target_dir,
                "metadata": metadata,
                "companions": folder_companions,
                "audio_count": len(item.audio_files),
                "structure": structure_status,
                "partial_group": item.partial_group,
                "leftover_files": list(item.leftover_files),
            }
            rename_audio_to = naming_template_filename_for_item(item, resolution.filename)
            if rename_audio_to:
                planned_move["original_audio_name"] = item.representative.name
                planned_move["rename_audio_to"] = rename_audio_to
            planned_moves.append(planned_move)
            continue

        can_move, target_path, reason = plan_loose_file_move(
            item, target_dir, reserved_targets, reserved_target_dirs=reserved_target_dirs,
            template_filename=resolution.filename,
        )
        if not can_move:
            if reason == "already in target folder":
                skipped_already_target += 1
            else:
                skipped_conflicts += 1
                skipped_reviews.append(make_skipped_review_move(
                    item=item,
                    metadata=metadata,
                    target=target_dir,
                    reason=f"skipped conflict: {reason}",
                    structure="skipped_conflict",
                ))
            print(f"SKIP: {reason} | {item.source_path} -> {target_dir}", file=sys.stderr)
            continue
        companions = [] if args.no_companions else companion_files_for(item.source_path)
        reserved_targets.add(target_path)
        reserved_target_dirs.add(target_dir)
        planned_moves.append({
            "kind": item.kind,
            "source": item.source_path,
            "target": target_path,
            "metadata": metadata,
            "companions": companions,
            "audio_count": 1,
            "structure": structure_status,
        })

    mode = "APPLY" if args.apply else "DRY RUN"
    mp3_files = count_audio_extension(root, ".mp3")
    opus_files = count_audio_extension(root, ".opus")
    print(f"Source root: {root}")
    print(f"Destination root: {destination_root}")
    print(f"Found book items: {total}")
    print(f"MP3 files included: {mp3_files}")
    print(f"OPUS files included: {opus_files}")
    print(f"Skipped unknown author: {skipped_unknown_author}")
    print(f"Skipped by pattern: {skipped_pattern_match}")
    print(f"Skipped already in target folder: {skipped_already_target}")
    print(f"Skipped conflicts: {skipped_conflicts}")
    print(f"Structure cache entries: {len(cache.get('entries', []))}")
    print(f"Matched existing structure: {matched_existing_structure}")
    print(f"Ambiguous structure matches: {ambiguous_structure}")
    print(f"Skipped ambiguous structure: {skipped_ambiguous_structure}")
    print(f"Skipped likely existing book folders: {skipped_existing_book_folders}")
    print(f"Skipped review items: {len(skipped_reviews)}")
    print(f"Planned moves: {len(planned_moves)}")
    print(f"Mode: {mode}")
    print()

    if not planned_moves and not skipped_reviews:
        print("No moves needed.")
        return

    moves_succeeded = 0
    failed_moves: list[dict[str, Any]] = []
    for move in planned_moves:
        print_move(move)
        if not args.apply:
            continue

        try:
            execute_planned_move(
                move,
                merge_existing_targets=args.merge_existing_targets,
                remove_empty_dirs=args.remove_empty_dirs,
                root=root,
            )
        except Exception as exc:  # noqa: BLE001
            failed_moves.append({**move, "error": str(exc)})
            print(f"FAILED: {move['source']} -> {move['target']} | {exc}", file=sys.stderr)
            continue
        moves_succeeded += 1

    if args.apply:
        print(f"Moves succeeded: {moves_succeeded}")
        print(f"Moves failed: {len(failed_moves)}")
        if failed_moves:
            print("Failed moves:")
            print()
            for move in failed_moves:
                print_failed_move(move)

    if skipped_reviews:
        print("Skipped review items:")
        print()
        for move in skipped_reviews:
            print_skipped_review(move)

    if args.apply and not args.no_structure_cache:
        # Rebuild after apply so future _unorganized runs do not need a full ffprobe scan.
        print("Rebuilding structure cache...", flush=True)
        build_structure_cache(destination_root, cache_path, args.progress_every)
        print("Structure cache rebuild complete.", flush=True)

    if not args.apply:
        print("Dry-run only. Re-run with --apply to move files.")


if __name__ == "__main__":
    main()
