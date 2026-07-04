"""Text normalization, number parsing, and book-text parsing for the Audible fixer.

Extracted from audible-metadata-fixer-v5.py so the logic is unit-testable and
readable without loading the full 9k-line monolith.

Import constraint: this module must be importable both as ``app.fixer.parsing``
(inside the container) and after a sys.path.insert of the repo root (standalone
fixer run). All names listed at the bottom __all__ are re-imported into the
fixer's top-level namespace so they remain accessible as
``fixer_module.<name>`` via load_fixer_module().
"""

from __future__ import annotations

import html
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from app.title_noise_policy import is_title_noise, remove_trailing_title_noise
from app.publisher_policy import (
    SPECIAL_PROVIDERS,
    match_canonical_publisher,
    special_provider_for,
    strip_publisher_noise,
)
from app.debug_trace import trace, ALTER, CHOOSE

# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

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
    r"dolby[\s._-]*digital(?:[\s._-]*plus)?|"
    r"audio[\s._-]*immersion(?:[\s._-]*tunnel)?"
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


@trace(ALTER, capture=["value"])
def sanitize_technical_labels(value: str) -> str:
    """Remove codec/release noise without deleting ambiguous title words."""
    value = clean_text(value)
    if not value:
        return ""

    value = UNAMBIGUOUS_TECHNICAL_LABEL_RE.sub(" ", value)

    def strip_bracketed(match: re.Match) -> str:
        inner = match.group(1)
        if is_technical_label_block(inner):
            return " "
        # Strip "[Series N - PartN]" part-indicator brackets.
        if re.search(r"-\s*\d+\s*$", inner):
            return " "
        return match.group(0)

    value = re.sub(r"[\[({]\s*([^])}]+?)\s*[\])}]", strip_bracketed, value)
    value = re.sub(r"[\[({]\s*[\])}]", " ", value)
    value = re.sub(r"\s+-\s+-\s+", " - ", value)

    parts = re.split(r"(\s+[-–—|:]\s+)", value)
    while len(parts) >= 3 and is_technical_label_block(parts[-1]):
        parts = parts[:-2]
    value = "".join(parts)

    value = re.sub(r"\s+", " ", value)
    return value.strip(" -_.:,")


@trace(ALTER, capture=["value"])
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


@trace(ALTER, capture=["value"])
def normalize_for_match(value: str) -> str:
    value = sanitize_book_title(value).lower()
    value = re.sub(r"\[[^\]]+\]", " ", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[_\-:]+", " ", value)
    value = re.sub(r"\bbook\s+#?\d+\b", " ", value)
    value = re.sub(r"\bvolume\s+#?\d+\b", " ", value)
    value = re.sub(r"\bvol\.?\s+#?\d+\b", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


@trace(ALTER, capture=["value"])
def sanitize_tag(value: str) -> str:
    return sanitize_technical_labels(value)


# ---------------------------------------------------------------------------
# Parenthetical helpers
# ---------------------------------------------------------------------------

def extract_first_parenthetical(value: str) -> str:
    match = re.search(r"\(([^)]{2,})\)", value or "")
    if not match:
        return ""
    return clean_text(match.group(1))


def remove_parenthetical(value: str) -> str:
    value = re.sub(r"\s*\([^)]*\)\s*", " ", value or "")
    value = re.sub(r"\s+", " ", value)
    return clean_text(value)


# ---------------------------------------------------------------------------
# Author helpers
# ---------------------------------------------------------------------------

@trace(ALTER, capture=["value"])
def clean_author_value(value: str) -> str:
    """Remove series hints from author-like tags, e.g. 'Aaron Crash (American Dragons)' -> 'Aaron Crash'."""
    return remove_parenthetical(value)


def _split_author_names(value: str) -> list[str]:
    """Split a credit string into individual normalized author names."""
    value = clean_author_value(value or "")
    parts = re.split(r"\s*(?:,|;|&|/|\band\b|\bwith\b)\s*", value, flags=re.IGNORECASE)
    return [n for n in (normalize_for_match(p) for p in parts) if n]


def _authors_compatible(local: str, candidate: str) -> bool | None:
    """Whether two author credits refer to the same author(s).

    Returns True/False, or None when either side has no usable name (the caller
    decides how to treat 'unknown'). Tolerant of multi-author ordering and of one
    source listing only the primary author of a co-authored book: a single shared
    author name is enough. Containment is length-guarded to avoid tiny matches.
    """
    local_names = _split_author_names(local)
    cand_names = _split_author_names(candidate)
    if not local_names or not cand_names:
        return None
    for c in cand_names:
        for l in local_names:
            if c == l:
                return True
            shorter, longer = (c, l) if len(c) <= len(l) else (l, c)
            if len(shorter) >= 6 and shorter in longer:
                return True
            if SequenceMatcher(None, c, l).ratio() >= 0.85:
                return True
    return False


def _initials_dedup_key(name: str) -> str:
    """Dedup key that collapses initial-format variants.
    'L.M. Kerr', 'L. M. Kerr', 'L M Kerr' all map to 'l m kerr'."""
    expanded = re.sub(r"\.(?=[A-Za-z])", " ", name)
    return re.sub(r"\s+", " ", expanded.replace(".", "")).strip().lower()


@trace(ALTER, capture=["values"])
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
        # Production studios / broadcasters that appear as artist/author tags — strip them
        "graphic audio": "",
        "graphicaudio": "",
        "soundbooth theatre": "",
        "soundbooth theater": "",
        "soundboththeatre": "",
        "soundbooththeater": "",
        "sbt": "",
        "bbc": "",
        "bbc radio": "",
        "bbc radio 4": "",
        "bbc radio 4 extra": "",
        "bbc audio": "",
        "bbc books": "",
        "bbc radio drama": "",
        "audible studios": "",
        "audible original": "",
        "audible originals": "",
        "brilliance audio": "",
        "podium audio": "",
        "tantor audio": "",
        "tantor media": "",
        "macmillan audio": "",
        "full cast audio": "",
        "blackstone audio": "",
        "blackstone publishing": "",
        "dreamscape media": "",
        "dreamscape audio": "",
        "l.a. theatre works": "",
        "la theatre works": "",
    }
    people = []
    seen = set()
    order_keys = set()
    for value in values:
        value = clean_text(value)
        if not value or re.search(r"\s+-\s+editor\s*$", value, flags=re.IGNORECASE):
            continue
        canonical = aliases.get(value.casefold(), value)
        if canonical == "":
            continue
        key = _initials_dedup_key(canonical)
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


_NAME_FUNCTION_WORDS = frozenset({
    "a", "an", "the", "of", "in", "on", "at", "for",
    "with", "by", "and", "or", "from", "to", "as",
})


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

    if tokens[0].lower() in {"the", "a", "an"}:
        return False
    if any(token.lower() in _NAME_FUNCTION_WORDS for token in tokens[1:-1]):
        return False

    cleaned_tokens = [
        re.sub(r"[^A-Za-z.''-]", "", token)
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


# ---------------------------------------------------------------------------
# Series helpers
# ---------------------------------------------------------------------------

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


@trace(ALTER, capture=["value"])
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


# ---------------------------------------------------------------------------
# Tag utilities
# ---------------------------------------------------------------------------

def first_existing_tag(tags: dict, keys: list[str]) -> str:
    for key in keys:
        value = tags.get(key.lower(), "").strip()

        if value:
            return value

    return ""


# ---------------------------------------------------------------------------
# Number helpers
# ---------------------------------------------------------------------------

@trace(ALTER, capture=["value"])
def roman_to_int(value: str) -> str:
    roman_map = {
        "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
        "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
        "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
        "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
    }

    value = value.strip().upper()

    if value in roman_map:
        return str(roman_map[value])

    return ""


@trace(ALTER, capture=["value"])
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


@trace(ALTER, capture=["value"])
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


@trace(ALTER, capture=["value"])
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


# ---------------------------------------------------------------------------
# Title identity number
# ---------------------------------------------------------------------------

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

    if re.search(r"\d\s*%", value):
        return ""

    cleaned = re.sub(r"\s+by\s+.+$", "", value, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*\[(?:ASIN\.)?[A-Z0-9]{8,}\]\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\((?:19|20)\d{2}\)\s*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    patterns = [
        r"(?:^|\s)(\d{1,3}(?:\.\d+)?)\s*[:\-–—]\s+\S+",
        r"(?:^|\s)(\d{1,3}(?:\.\d+)?)\s*$",
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue

        candidate = normalize_book_number(match.group(1))

        if re.fullmatch(r"(?:19|20)\d{2}", candidate):
            continue

        prefix = cleaned[: match.start(1)]
        if re.search(r"\b(?:chapter|ch|episode|ep)\b\.?\s*$", prefix, re.IGNORECASE):
            continue

        return candidate

    return ""


# ---------------------------------------------------------------------------
# Sequence helpers
# ---------------------------------------------------------------------------

def is_single_numeric_sequence(value: str) -> bool:
    value = str(value or "").strip()
    return bool(re.fullmatch(r"\d+(?:\.0)?", value))


@trace(ALTER, capture=["value"])
def clean_sequence(value: str) -> str:
    value = str(value or "").strip()

    if not is_single_numeric_sequence(value):
        return ""

    return str(int(float(value)))


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


# ---------------------------------------------------------------------------
# Path book number
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Number identity candidates
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Book number range
# ---------------------------------------------------------------------------

def parse_book_number_range(text: str) -> tuple[int, int] | None:
    """Parse an omnibus book-number range like "Books 11-12", "11 to 12", or
    "Books 011 012" into an (low, high) tuple. Returns None when there is no
    range. Implausibly wide spans are ignored to avoid matching noise.
    """
    if not text:
        return None

    value = clean_text(str(text))

    match = re.search(
        r"\b(?:books?\s+)?(\d{1,4})\s*(?:-|–|—|to|through|&)\s*(\d{1,4})\b",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\bbooks?\s+(\d{1,4})\s+(\d{1,4})\b", value, flags=re.IGNORECASE
        )

    if not match:
        return None

    low, high = int(match.group(1)), int(match.group(2))
    if high < low or (high - low) > 50:
        return None
    return (low, high)


def get_local_book_number_range(clues: dict) -> tuple[int, int] | None:
    for key in ("title", "raw_title", "series", "album"):
        found = parse_book_number_range(clues.get(key, ""))
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# Book text parsers
# ---------------------------------------------------------------------------

@trace(ALTER, capture=["value", "known_author"])
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

    title_series_bare_number = re.match(
        r"^(?P<title>.+?)\s*-\s*(?P<series>[^,]+?)\s*,\s*(?P<number>\d{1,3})$",
        value,
        flags=re.IGNORECASE,
    )
    if title_series_bare_number:
        _ts_series = title_series_bare_number.group("series").strip()
        _ts_title = title_series_bare_number.group("title").strip()
        if (
            _ts_title
            and _ts_series
            and _ts_series.lower() not in {
                "book", "books", "vol", "vols", "volume", "volumes", "part", "parts"
            }
        ):
            return {
                "raw_title": value,
                "series": clean_series_value(_ts_series),
                "book_number": normalize_book_number(title_series_bare_number.group("number")),
                "title": sanitize_book_title(_ts_title),
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
    # If the generic regex captured a trailing label word ("- Book", "- Volume") as
    # part of the series, let the explicit "Series - Book N - Title" patterns below
    # handle the string instead of returning a mangled series here.
    _series_candidate = series_number_title.group("series").strip() if series_number_title else ""
    _series_ends_with_label = bool(
        re.search(r"\b(?:book|volume|vol\.?|part)$", _series_candidate, re.IGNORECASE)
    )
    series_number_series_ok = bool(
        series_number_title
        and not _series_ends_with_label
        and _series_candidate.lower()
        not in {"book", "books", "volume", "volumes", "vol", "vols", "side story"}
    )
    if (
        series_number_series_ok
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

    if (
        series_number_series_ok
        and trailing_title_norm
        and known_author_norm
        and (
            trailing_title_norm == known_author_norm
            or trailing_title_norm in known_author_norm
        )
        and looks_like_person_name(series_number_title.group("title"))
    ):
        return {
            "raw_title": value,
            "series": clean_series_value(series_number_title.group("series").strip()),
            "book_number": normalize_book_number(series_number_title.group("number")),
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


@trace(ALTER, capture=["value", "known_author"])
def parse_descriptive_book_text(value: str, known_author: str = "") -> dict:
    """Parse common author/title path names, using known author tags to orient them."""
    value = sanitize_technical_labels(value)

    if not value:
        return {}

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


@trace(ALTER, capture=["value"])
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
            re.fullmatch(r"[A-Za-z][A-Za-z.''-]{1,30}", candidate)
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


@trace(ALTER, capture=["file_path", "known_author"])
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


@trace(ALTER, capture=["file_path", "known_author"])
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


# ---------------------------------------------------------------------------
# Metadata parsers
# ---------------------------------------------------------------------------

@trace(ALTER, capture=[])
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

    if not book_number:
        title_number = extract_book_number_from_text(raw_title)
        if title_number:
            book_number = title_number
            book_number_source = "title"

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


# Scan-root/staging folder names a loose file can sit directly inside --
# never a real book title, so title-recovery must not pick these up as a
# fallback candidate.
GENERIC_TITLE_RECOVERY_FOLDER_NAMES = {
    "audiobooks",
    "books",
    "library",
    "media",
    "unorganized",
    "_unorganized",
    "unknown",
}


def is_invalid_local_title(value: str, author: str = "") -> bool:
    title_norm = normalize_for_match(value)
    author_norm = normalize_for_match(clean_author_value(author))

    if not title_norm or is_generic_chapter_title(title_norm):
        return True

    if author_norm and title_norm == author_norm:
        return True

    if author_norm and len(author_norm) >= 4 and title_norm.startswith(author_norm):
        remainder = title_norm[len(author_norm):].strip()
        if remainder:
            return True

    return False


@trace(ALTER, capture=["file_path"])
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
            and candidate_norm not in GENERIC_TITLE_RECOVERY_FOLDER_NAMES
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


# ---------------------------------------------------------------------------
# Query noise helpers
# ---------------------------------------------------------------------------

SEARCH_TITLE_PREFIX_NOISE = [
    "listening to",
]

_TRAILING_BY_AUTHOR_RE = re.compile(
    r"\s+by\s+([A-Z][\w.'\-]*(?:\s+[A-Z][\w.'\-]*){0,3})(\s*\d{1,3})?\s*$"
)


@trace(ALTER, capture=["text"])
def strip_publisher_search_noise(text: str) -> str:
    """Remove known publisher/imprint/source tokens from a search string.

    Word-boundary, case-insensitive. Backed by the shared, editable canonical
    publisher catalog (``app.publisher_policy``). Used for search queries and for
    cleaning author/narrator clues -- never for the dedicated publisher field.
    """
    if not text:
        return text
    return strip_publisher_noise(text)


@trace(ALTER, capture=["text", "author"])
def strip_title_search_noise(text: str, author: str = "") -> str:
    """Strip search-only title noise: a leading "Listening to" and a trailing
    "by <Author Name>" baked into the title tag. Used for queries and
    title-evidence scoring only -- never for written tags.

    The trailing "by <Name>" is only removed when it is clearly filename
    pollution: it is followed by a book/part number (e.g. "by Douglas Adams 1")
    or the name matches the known author. This protects legitimate titles such
    as "Death by Black Hole".

    Example:
        "Listening to Dirk Gently's Holistic Detective Agency by Douglas Adams 1"
        -> "Dirk Gently's Holistic Detective Agency"
    """
    if not text:
        return text

    result = clean_text(text)

    for prefix in SEARCH_TITLE_PREFIX_NOISE:
        result = re.sub(
            r"^\s*" + re.escape(prefix) + r"\s+", "", result, flags=re.IGNORECASE
        )

    match = _TRAILING_BY_AUTHOR_RE.search(result)
    if match:
        has_trailing_number = bool(match.group(2))
        name_matches_author = bool(
            author
            and normalize_for_match(match.group(1)) == normalize_for_match(author)
        )
        if has_trailing_number or name_matches_author:
            result = result[: match.start()]

    return re.sub(r"\s+", " ", result).strip()


@trace(ALTER, capture=["text"])
def extract_author_from_title(text: str) -> str:
    """Recover an author name baked into a title as "... by <Name> <number>".

    A trailing book/part number is required so legitimate titles like
    "Death by Black Hole" are not misread as having author "Black Hole".
    Returns "" when no such pattern is present.
    """
    if not text:
        return ""

    match = _TRAILING_BY_AUTHOR_RE.search(clean_text(text))
    if match and match.group(2):
        return match.group(1).strip()
    return ""


@trace(CHOOSE, capture=["title"])
def goodreads_title_query_variants(title: str) -> list[str]:
    """Return Goodreads-friendly title query variants.

    abs-tract/Goodreads often ranks "Series 1" correctly while "Series Book 1"
    drifts to omnibuses or unrelated subtitle matches.
    """
    variants: list[str] = []
    title = clean_text(title)
    if title:
        no_book_label = re.sub(
            r"\bbook\s+0*(\d+(?:\.\d+)?)\b",
            r"\1",
            title,
            flags=re.IGNORECASE,
        )
        no_book_label = no_book_label.replace(",", " ")
        no_book_label = re.sub(r"\s+", " ", no_book_label).strip(" ,")
        if no_book_label and no_book_label != title:
            variants.append(no_book_label)
        variants.append(title)

    seen = set()
    unique: list[str] = []
    for variant in variants:
        key = normalize_for_match(variant)
        if key and key not in seen:
            unique.append(variant)
            seen.add(key)
    return unique


@trace(ALTER, capture=["value"])
def normalize_book_label_for_match(value: str) -> str:
    value = clean_text(value)
    value = re.sub(
        r"\bbook\s+0*(\d+(?:\.\d+)?)\b",
        r"\1",
        value,
        flags=re.IGNORECASE,
    )
    value = value.replace(",", " ")
    return normalize_for_match(re.sub(r"\s+", " ", value).strip())


@trace(ALTER, capture=["value"])
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


# ---------------------------------------------------------------------------
# Generic chapter title and misc utilities
# ---------------------------------------------------------------------------

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
        r"^credits?$",
        r"^(opening|end|ending|outro|intro|closing|beginning)\s+credits?$",
        r"^(intro|outro)$",
        r"^episode\s+\d+(\s+.*)?$",
        r"^episode\s+(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)(\s+.*)?$",
        r"^lecture\s+\d+(\s+.*)?$",
        r"^chapter\s+[a-z][\w\s-]*$",
        r"^bloopers?$",
        r"^bonus\s+(content|material|chapter|story|stories)$",
        r"^the\s+story\s+continues(\s+.*)?$",
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
