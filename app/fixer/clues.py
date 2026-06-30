"""Search-clue helpers: pure functions that build/transform search-clue dicts.

This module contains functions that construct and refine the ``clues`` dict used
to drive Audible search queries.  All functions here are pure (no IO); callers
that need to read file tags still live in the fixer script.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.debug_trace import trace, ALTER, CHOOSE
from app.publisher_policy import match_canonical_publisher, strip_publisher_noise
from app.fixer.parsing import (
    normalize_for_match,
    sequence_values_equal,
    parse_structured_book_from_path,
    extract_author_from_title,
    strip_title_search_noise,
    normalize_book_number,
    strip_leading_sequence_from_title,
    strip_publisher_search_noise,
    pick_most_common_value,
    extract_folder_book_number,
    sanitize_technical_labels,
    clean_series_value,
    clean_author_value,
    looks_like_person_name,
    sanitize_book_title,
)


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


@trace(ALTER, capture=[])
def capture_publisher_clue(clues: dict, tags: dict) -> dict:
    """Record the local publisher (before query sanitization) and clean leaks.

    The publisher is captured from its dedicated tag when present, otherwise from
    a canonical-publisher match in the author/narrator/album/comment fields (some
    libraries dump the imprint there). The captured value is preserved verbatim so
    it can be written back to the tag + metadata.json, while any publisher token
    that leaked into the author/narrator clues is stripped for cleaner searches and
    fallback writes. ``publisher_verified`` marks values confirmed against the
    canonical catalog (the rest are candidates for learning).
    """
    def is_descriptor(entry: dict | None) -> bool:
        # Catalog entries like "Unabridged"/"Audiobook" exist to strip query/author
        # noise; they are format descriptors, not real publishers to record.
        return bool(entry) and str(entry.get("id", "")).startswith("noise-")

    raw_publisher = str(tags.get("publisher", "") or "").strip()
    canonical = match_canonical_publisher(raw_publisher) if raw_publisher else None
    # A publisher tag that is only a format descriptor ("Unabridged") is not a publisher.
    if raw_publisher and is_descriptor(canonical) and not strip_publisher_noise(raw_publisher):
        raw_publisher, canonical = "", None

    if not raw_publisher:
        # Look for a recognized imprint hiding in adjacent fields.
        for field in ("album_artist", "comment", "album", "artist", "composer"):
            entry = match_canonical_publisher(str(tags.get(field, "") or ""))
            if entry and not is_descriptor(entry):
                canonical = entry
                raw_publisher = entry["name"]
                break

    if raw_publisher:
        clues["publisher"] = raw_publisher
        clues["publisher_verified"] = bool(canonical)

    # Strip any leaked publisher token from author/narrator without losing real data.
    for field in ("author", "narrator"):
        value = str(clues.get(field, "") or "")
        if not value:
            continue
        cleaned = strip_publisher_noise(value)
        if cleaned and cleaned != value:
            clues[field] = cleaned

    return clues


# Leading filler phrases some libraries prepend to title tags.
@trace(CHOOSE, capture=[])
def build_search_queries_from_clues(clues: dict) -> list[str]:
    # Strip search-only noise ("Listening to", trailing "by <author>") so the
    # query carries the real title; recover the author if it was only present
    # inside the title.
    author = clues["author"] or extract_author_from_title(clues["title"]) or extract_author_from_title(clues["raw_title"])
    series = clues["series"]
    title = strip_title_search_noise(clues["title"], author) or clues["title"]
    raw_title = strip_title_search_noise(clues["raw_title"], author) or clues["raw_title"]
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
        query = strip_publisher_search_noise(query)
        query = re.sub(r"\s+", " ", query).strip()

        if query and query.lower() not in seen:
            clean_queries.append(query)
            seen.add(query.lower())

    return clean_queries


@trace(CHOOSE, capture=["folder_name"])
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

    # Track numbers on individual chapter files are chapter positions, not book
    # numbers -- do not use them as a sequence fallback for the group.
    return "", ""


@trace(ALTER, capture=["folder"])
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


@trace(ALTER, capture=["value", "author"])
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
