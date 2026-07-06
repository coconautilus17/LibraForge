"""Scoring, selection, and metadata-assembly helpers.

All functions here are pure (no IO, no HTTP).  They transform and score dicts
produced by search providers and the clues module.

Public API consumed by the fixer script:
  score_product_for_metadata, pick_best_match_for_metadata,
  metadata_from_product, get_primary_series, clean_provider_genres,
  is_generic_series_number_title, AGGRESSIVE_SCORE_THRESHOLD
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from app.debug_trace import trace, ALTER, CHOOSE, SCORE
from app.publisher_policy import SPECIAL_PROVIDERS
from app.fixer.parsing import (
    normalize_for_match,
    parse_sequence_number,
    extract_book_number_from_text,
    clean_text,
    normalize_book_number,
    sanitize_tag,
    sanitize_book_title,
    clean_author_value,
    get_local_book_number_range,
    get_local_number_identity_candidates,
    is_single_numeric_sequence,
    clean_sequence,
    extract_title_identity_number,
    sequence_values_equal,
    normalize_book_label_for_match,
    _authors_compatible,
    canonicalize_author_credits,
    is_invalid_local_title,
    strip_title_search_noise,
    strip_leading_sequence_from_title,
    parse_book_number_range,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGGRESSIVE_SCORE_THRESHOLD = 0.70
GENRE_BLOCKLIST = {"audiobook", "audiobooks"}

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

# Tie-break configuration for multiple top-scoring candidates.
# Scores within TIE_SCORE_EPSILON of the maximum are treated as tied at the top.
TIE_SCORE_EPSILON = 0.02
# Duration-status preference: a perfect-duration candidate beats a strong one, etc.
DURATION_STATUS_RANK = {
    "perfect": 4,
    "strong": 3,
    "acceptable": 2,
    "unknown": 1,
    "mismatch": 0,
}
# Same-status tie: the closer candidate must beat the other by at least this many
# minutes of duration difference (30 seconds) to count as a clear winner.
TIE_DURATION_MARGIN_MINUTES = 0.5


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------

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


@trace(SCORE, capture=["local_minutes", "audible_minutes"])
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


# ---------------------------------------------------------------------------
# Product accessors
# ---------------------------------------------------------------------------

def get_year(product: dict) -> str:
    for key in ["release_date", "issue_date", "publication_datetime"]:
        value = product.get(key)

        if value and len(value) >= 4:
            return value[:4]

    return ""


@trace(ALTER, capture=["key"])
def get_people(product: dict, key: str) -> list[str]:
    return [
        item.get("name", "").strip()
        for item in product.get(key, [])
        if item.get("name", "").strip()
    ]


@trace(ALTER, capture=[])
def get_primary_series(product: dict) -> tuple[str, str]:
    series = product.get("series") or []

    if not series:
        return "", ""

    first = series[0] or {}

    series_name = first.get("title") or first.get("name") or ""
    sequence = first.get("sequence") or first.get("position") or ""

    return sanitize_tag(series_name), sanitize_tag(sequence)


# ---------------------------------------------------------------------------
# Genre helper
# ---------------------------------------------------------------------------

def clean_provider_genres(genres: Any) -> list[str]:
    """Return real provider genres, excluding generic format labels."""
    if isinstance(genres, str):
        raw = [genres]
    elif isinstance(genres, list):
        raw = genres
    else:
        raw = []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in raw:
        text = sanitize_tag(str(value or "")).strip()
        key = text.lower()
        if not text or key in GENRE_BLOCKLIST or key in seen:
            continue
        cleaned.append(text)
        seen.add(key)
    return cleaned


def split_genre_string(value: str) -> list[str]:
    """Split a comma-joined genre string into separate cleaned genre values.

    The internal "genre" field is a single comma-joined display string
    everywhere (clues, marker, report, UI) -- e.g. "Fantasy, LitRPG". Only
    the final write targets (the embedded multi-value tag, metadata.json's
    genres array) need real separate entries, so this is called at write
    time only, not used to change the internal representation.
    """
    if not value:
        return []
    return clean_provider_genres(re.split(r"\s*,\s*", value))


# ---------------------------------------------------------------------------
# Number / sequence helpers
# ---------------------------------------------------------------------------

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


def get_audible_book_number_range(product: dict) -> tuple[int, int] | None:
    _, sequence = get_primary_series(product)
    found = parse_book_number_range(str(sequence or ""))
    if found:
        return found
    for key in ("title", "subtitle"):
        found = parse_book_number_range(product.get(key, "") or "")
        if found:
            return found
    return None


@trace(SCORE, capture=[])
def omnibus_range_relation(clues: dict, product: dict) -> str:
    """Compare local and Audible omnibus spans.

    Returns:
      "match"    both sides express the same exact range (e.g. 11-12 vs 11-12)
      "conflict" both sides express ranges but they differ (11-12 vs 13-14)
      "none"     at least one side has no range to compare
    """
    local_range = get_local_book_number_range(clues)
    audible_range = get_audible_book_number_range(product)
    if not local_range or not audible_range:
        return "none"
    return "match" if local_range == audible_range else "conflict"


def has_matching_omnibus_range(clues: dict, product: dict) -> bool:
    return omnibus_range_relation(clues, product) == "match"


# ---------------------------------------------------------------------------
# Title evidence helpers
# ---------------------------------------------------------------------------

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


def title_evidence_score(clues: dict, product: dict) -> float:
    # Strip search-only noise ("Listening to ...", trailing "by <author>") so a
    # polluted local title still scores against the clean Audible title.
    local_author = clues.get("author", "")
    clean_title = strip_title_search_noise(clues.get("title", ""), local_author) or clues.get("title", "")
    clean_raw_title = strip_title_search_noise(clues.get("raw_title", ""), local_author) or clues.get("raw_title", "")

    local_title = normalize_for_match(clean_title)
    local_raw_title = normalize_for_match(clean_raw_title)
    local_sequence_free_title = normalize_for_match(
        strip_leading_sequence_from_title(clean_title)
    )
    local_sequence_free_raw_title = normalize_for_match(
        strip_leading_sequence_from_title(clean_raw_title)
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

    local_tokens = significant_title_tokens(clean_title or clean_raw_title)
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
    if (
        audible_title
        and audible_title in title_to_check
        # Count tokens of the *normalized* title (after book-N stripping), not the
        # raw Audible title. "Arena Book 4" normalizes to "arena" (1 token) -- that
        # single word being contained in "arena road 4" should NOT score 1.0.
        and len(significant_title_tokens(audible_title)) >= 2
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


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

@trace(SCORE, capture=[])
def has_number_identity_conflict(clues: dict, product: dict) -> bool:
    """Reject wrong books in the same series when title numbers disagree.

    Duration and fuzzy title scoring can make adjacent books look perfect, e.g.:
      local "The Lost Bloodline 2" vs Audible "The Lost Bloodline 5"
      local "Overpowered Wizard 3" vs Audible "Overpowered Wizard"

    If both sides expose numeric identity evidence and none of the local numbers
    exists on the Audible candidate, the candidate is the wrong book.
    """
    # Omnibus spans are compared exactly: an identical range (e.g. local
    # "Books 11-12" vs an Audible Pack covering 11-12) is the right record even
    # though the Pack's own number differs; a different range (11-12 vs 13-14)
    # is the wrong box set.
    relation = omnibus_range_relation(clues, product)
    if relation == "match":
        return False
    if relation == "conflict":
        return True

    local_numbers = get_local_number_identity_candidates(clues)
    audible_numbers = get_audible_number_candidates(product)

    if not local_numbers or not audible_numbers:
        return False

    return not bool(set(local_numbers) & set(audible_numbers))


@trace(SCORE, capture=["local_duration_minutes"])
def strong_identity_overrides_number_conflict(
    clues: dict,
    product: dict,
    local_duration_minutes: float | None,
) -> bool:
    """Allow side-story numbering differences only with independent confirmation.

    This is designed for parallel-series cases where a book legitimately carries
    different numbers in different numbering systems (e.g. Book 3 in the main
    series is Book 2 in a sub-series). It must NOT fire when both the local title
    and the Audible title explicitly encode different numbers -- in that case the
    numbers are the identity of two different books in the same series.
    """
    if title_evidence_score(clues, product) < 0.85:
        return False

    # If the local title and the Audible title both carry explicit trailing
    # series numbers and those numbers differ, this is a wrong-book match
    # within the same series, not a parallel-numbering difference.
    # Example: local "Super Sales on Super Heroes 4" vs Audible
    #          "Super Sales on Super Heroes 6" -- high title similarity masks
    #          the fact that these are different books.
    # Note: Book 02 is NOT rejected here because both sides have title "Super
    # Sales on Super Heroes 2" (same number) despite Audible sequence = 1.
    local_title_number = extract_title_identity_number(
        clues.get("title", "") or clues.get("raw_title", "")
    )
    audible_title_number = extract_title_identity_number(
        product.get("title", "") or ""
    )
    if (
        local_title_number
        and audible_title_number
        and local_title_number != audible_title_number
    ):
        # Both titles carry explicit series numbers and they disagree -- not a
        # parallel-series case (e.g. local "Series 4" vs Audible "Series 6").
        return False

    if local_title_number and not audible_title_number:
        # Local title carries an explicit series number but the Audible title
        # is the base series title with no number (e.g. local "Series 2" vs
        # Audible "Series" sequence=1). If the local number and the Audible
        # sequence disagree, the candidate is a different book.
        # Exception: fractional prequel/novella numbers within 1 of the catalog
        # sequence are compatible (e.g. local "0.5 - Dominion" vs Audible seq "0").
        _, audible_seq = get_primary_series(product)
        audible_seq_norm = normalize_book_number(str(audible_seq or ""))
        if audible_seq_norm and local_title_number != audible_seq_norm:
            try:
                if abs(float(local_title_number) - float(audible_seq_norm)) >= 1.0:
                    return False
            except (ValueError, TypeError):
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


def local_number_unconfirmed_by_candidate(clues: dict, product: dict) -> bool:
    """True when local has a confident, explicit book number but the candidate
    carries no sequence data at all to confirm or refute it.

    A candidate missing sequence entirely is not evidence it's the right
    book -- it's frequently an incomplete catalog entry, a different book in
    the series, or the series landing page. High title/author/duration
    agreement alone must not promote this to a confident, auto-write score;
    without a number to compare, the identity is genuinely unconfirmed.
    """
    if not has_strong_local_number(clues):
        return False
    _series, audible_sequence = get_primary_series(product)
    return not str(audible_sequence).strip()


@trace(SCORE, capture=["local_duration_minutes"])
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

    # When both the local title and the Audible title carry explicit, differing
    # trailing numbers (e.g. local "Power Mage 5" vs Audible "Power Mage 6"),
    # the numbers ARE the identity of two different books in the same series.
    # High title similarity (they share the base series name) must not be allowed
    # to mask this as a parallel-numbering case.
    local_title_number = extract_title_identity_number(
        clues.get("title", "") or clues.get("raw_title", "")
    )
    audible_title_number = extract_title_identity_number(product.get("title", "") or "")
    explicit_title_number_conflict = bool(
        local_title_number
        and audible_title_number
        and local_title_number != audible_title_number
    )

    # If the title is a strong match and duration confirms it,
    # do not reject only because the local folder numbering differs from
    # Audible's sub-series sequence.
    #
    # This handles companion/parallel series like:
    # Local Book 003 - Of Dawn and Darkness
    # Audible The Elder Empire: Sea, Book 2
    #
    # It must NOT fire when the titles themselves carry conflicting numbers.
    #
    # Gated to a small (<=1) gap: a genuine numbering-scheme difference (e.g.
    # a local omnibus count vs. a sub-series count) is a consistent, small
    # offset. A larger gap in high title-similarity territory is usually a
    # recurring saga tagline the series reuses across several volumes (e.g.
    # "From Human to Dragon to God" appearing in multiple Dragon Emperor
    # books) rather than evidence of a different numbering scheme -- title
    # agreement there does not identify which specific book this is.
    try:
        sequence_gap = abs(int(float(audible_sequence)) - int(local_number))
    except ValueError:
        sequence_gap = None

    if (
        not explicit_title_number_conflict
        and sequence_gap is not None
        and sequence_gap <= 1
        and title_score >= 0.85
        and duration_result["status"] in {"perfect", "strong", "acceptable"}
        and (author_good or narrator_good)
    ):
        return False

    try:
        return int(float(audible_sequence)) != int(local_number)
    except ValueError:
        return False


@trace(SCORE, capture=[])
def has_author_identity_conflict(clues: dict, product: dict) -> bool:
    """Detect a confidently-different author between the local book and product.

    Used as a HARD reject: a title can collide across unrelated books (Arthur C.
    Clarke's "Cradle" vs Will Wight's "Cradle" series), but the author cannot.
    A different author means it is not the same book, so no duration/title/series
    coincidence may promote it. ASIN identity is the only bypass (handled by the
    caller).

    Deliberately conservative -- returns False whenever the comparison is
    uncertain, so legitimate matches are never blocked:
      - missing author on either side,
      - generic/placeholder author values,
      - high whole-string similarity (formatting differences),
      - substring containment ("Clarke" vs "Arthur C. Clarke"; co-authors),
      - any shared name token (co-authors, middle-name variants, translators).
    Only a complete absence of overlap counts as a conflict.
    """
    local_author = normalize_for_match(clean_author_value(clues.get("author", "")))
    product_author = normalize_for_match(" ".join(get_people(product, "authors")))

    if not local_author or not product_author:
        return False

    generic = {
        "unknown",
        "unknown author",
        "various",
        "various authors",
        "anonymous",
        "n a",
        "na",
    }
    if local_author in generic or product_author in generic:
        return False

    # "Audio Versee", "Audio Version", etc. are garbled production-format labels
    # that sometimes end up in the embedded author tag. Treat them as unknown.
    _format_tokens = {"audio", "audiobook", "unabridged", "narrated"}
    if set(local_author.split()) & _format_tokens:
        return False

    # Same author allowing for formatting differences
    # ("J R R Tolkien" vs "John Ronald Reuel Tolkien").
    if SequenceMatcher(None, local_author, product_author).ratio() >= 0.70:
        return False

    # Containment covers short-vs-full names and co-author lists where one side
    # is a subset of the other ("arthur c clarke gentry lee" contains
    # "arthur c clarke").
    if local_author in product_author or product_author in local_author:
        return False

    # Any shared meaningful name token (>= 3 chars, skipping initials) means we
    # cannot be sure the authors differ -- shared co-author, alternate spelling,
    # etc. Only block when there is zero overlap.
    def name_tokens(value: str) -> set[str]:
        return {token for token in value.split() if len(token) >= 3}

    if name_tokens(local_author) & name_tokens(product_author):
        return False

    # No similarity, no containment, no shared name token: confidently different.
    return True


@trace(SCORE, capture=[])
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


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------

@trace(SCORE, capture=["local_duration_minutes"])
def score_product_for_metadata(
    clues: dict,
    product: dict,
    local_duration_minutes: float | None = None,
) -> float:
    # ASIN identity: embedded ASIN + title + author is bullet-proof confirmation.
    # When all three match, skip hard-reject guards designed for wrong-book
    # false positives and guarantee a floor score above the min_score gate.
    # Duration mismatch still contributes normally (and triggers review), but
    # sequence/series conflicts cannot veto a directly identified book.
    _existing_asin = (clues.get("existing_asin") or "").upper().strip()
    _product_asin  = (product.get("asin") or "").upper().strip()
    _asin_identity = False
    if _existing_asin and _product_asin and _existing_asin == _product_asin:
        _lt = normalize_for_match(clues.get("title", ""))
        _pt = normalize_for_match(product.get("title", "") or "")
        _la = normalize_for_match(clues.get("author", ""))
        _pa = normalize_for_match(" ".join(get_people(product, "authors")))
        _title_ok = bool(_lt and (_lt == _pt or _lt in _pt or _pt in _lt))
        _auth_ok  = bool(_la and _pa and SequenceMatcher(None, _la, _pa).ratio() >= 0.75)
        _asin_identity = _title_ok and _auth_ok

    if not _asin_identity:
        # Hard reject a clearly different author. A title can collide across
        # unrelated books (Arthur C. Clarke's "Cradle" vs Will Wight's "Cradle"
        # series), but the author cannot -- a different author is never the same
        # book, regardless of any duration/title/series coincidence.
        if has_author_identity_conflict(clues, product):
            return 0.0

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
    _series_token_jaccard = 0.0  # set in series block, reused for sequence gating

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
            # Only boost to 1.0 when the series names substantially overlap by
            # token content. "Arena" being a substring of "Arena Road" does NOT
            # mean they are the same series -- Logan Jacobs has both.
            _ls_toks = set(significant_title_tokens(local_series))
            _as_toks = set(significant_title_tokens(audible_series_norm))
            _union = _ls_toks | _as_toks
            _series_token_jaccard = len(_ls_toks & _as_toks) / len(_union) if _union else 1.0
            if _series_token_jaccard >= 0.65:
                series_score = 1.0
            else:
                # Not confirmed as the same series. The character-based
                # SequenceMatcher ratio is mechanically inflated by substring
                # containment regardless of true similarity (e.g. "Summoner"
                # vs "Summoner School" scores ~0.7 despite being different,
                # unrelated series by the same author). A coincidental
                # substring relationship is not evidence of a real match, so
                # it earns no series credit here -- other genuine signals
                # (title, author, duration) still apply on their own merits.
                series_score = 0.0

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
                # Only credit the sequence bonus when the series names are
                # compatible. Book 3 in "Arena Road" matching Book 3 in "Arena"
                # is a coincidence (same author, different series); the shared
                # number should not boost the score.
                _seq_series_ok = (
                    not local_series
                    or not audible_series_norm
                    or series_match
                    or _series_token_jaccard >= 0.65
                )
                if _seq_series_ok:
                    sequence_match = True
                    score += 0.18
            elif (
                not _asin_identity
                and local_number_source != "track"
                and not strong_identity_overrides_number_conflict(
                    clues,
                    product,
                    local_duration_minutes,
                )
            ):
                # Non-track-derived conflicts should already be blocked by
                # has_sequence_conflict(), but keep this as a safety fallback.
                # ASIN identity bypasses this: a confirmed ASIN+title+author match
                # should not be vetoed by a stale or subseries book number.
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

    # A candidate missing sequence entirely cannot confirm or refute a
    # confident local book number -- title/author/duration agreement alone
    # must not promote it to an auto-write floor. See
    # local_number_unconfirmed_by_candidate() docstring.
    _number_unconfirmed = local_number_unconfirmed_by_candidate(clues, product)

    # Duration-confirmed matches should pass even when title formatting differs.
    if duration_result["status"] in {"perfect", "strong", "acceptable"}:
        if series_match and (author_good or narrator_good):
            score = max(score, 0.82)
        elif title_score >= 0.75 and (author_good or narrator_good) and not _number_unconfirmed:
            score = max(score, 0.80)

    # Extra safety for title + duration + author/narrator cases.
    # This helps cases like Alaska Kingdom where local track is wrong,
    # but title, author/narrator, and duration identify the correct book.
    if duration_result["status"] in {"perfect", "strong"} and title_score >= 0.80:
        if (author_good or narrator_good) and not _number_unconfirmed:
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
        and not _number_unconfirmed
    ):
        score = 1.0

    # ASIN identity floor: ASIN+title+author confirmed above -- guarantee this
    # clears the min_score gate even when duration or series penalised the score.
    if _asin_identity:
        score = max(score, 0.75)

    # Language penalty: non-English products score lower for English-language
    # libraries. Prevents foreign-language editions (French, Spanish, etc.)
    # from being chosen over English matches via duration coincidence.
    product_language = str(product.get("language", "") or "").lower()
    if product_language and product_language != "english":
        score -= 0.30

    return round(min(max(score, 0.0), 1.0), 4)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

@trace(CHOOSE, capture=[])
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


def _candidate_duration(
    product: dict, local_duration_minutes: float | None
) -> dict:
    return compare_duration(
        local_minutes=local_duration_minutes,
        audible_minutes=get_audible_duration_minutes(product),
    )


@trace(CHOOSE, capture=["local_duration_minutes"], show_result=False)
def pick_best_match_for_metadata(
    clues: dict,
    products: list[dict],
    local_duration_minutes: float | None = None,
) -> tuple[dict | None, float, dict | None]:
    """Pick the best Audible product for the local book.

    Returns (best_product, best_score, ambiguity). When two or more products
    tie at the top score, fallbacks decide the winner:
      1. duration status (perfect > strong > acceptable > ...), picked silently;
      2. for the same status, the candidate that is at least 30 seconds closer
         on exact duration wins; otherwise there is no clear winner.

    ambiguity is None for an unambiguous single winner. When several candidates
    tie at the top it is a dict describing the contest:
      {"count", "resolved", "reason", "chosen", "alternatives"}
    where resolved=False means the fallbacks could not separate the top two and
    the caller should route the book to manual review.
    """
    scored = [
        (score, product)
        for product in products
        for score in (
            score_product_for_metadata(clues, product, local_duration_minutes),
        )
        if score > 0.0
    ]

    if not scored:
        return None, 0.0, None

    best_score = max(score for score, _ in scored)
    top = [item for item in scored if best_score - item[0] <= TIE_SCORE_EPSILON]

    def sort_key(item: tuple[float, dict]):
        score, product = item
        duration = _candidate_duration(product, local_duration_minutes)
        status_rank = DURATION_STATUS_RANK.get(duration.get("status", "unknown"), 1)
        diff = duration.get("diff_minutes")
        # Higher score, then better duration status, then smaller exact diff.
        return (
            round(score, 4),
            status_rank,
            -(diff if diff is not None else float("inf")),
        )

    top.sort(key=sort_key, reverse=True)
    best_score_value, best_product = top[0]

    if len(top) == 1:
        return best_product, best_score_value, None

    # Multiple candidates tied at the top score: try to resolve with fallbacks.
    second_product = top[1][1]
    best_dur = _candidate_duration(best_product, local_duration_minutes)
    second_dur = _candidate_duration(second_product, local_duration_minutes)
    best_rank = DURATION_STATUS_RANK.get(best_dur.get("status", "unknown"), 1)
    second_rank = DURATION_STATUS_RANK.get(second_dur.get("status", "unknown"), 1)

    resolved = False
    if best_rank > second_rank:
        # e.g. perfect beats strong -- clear winner, resolved silently.
        resolved = True
    elif best_rank == second_rank:
        best_diff = best_dur.get("diff_minutes")
        second_diff = second_dur.get("diff_minutes")
        if best_diff is not None and second_diff is not None:
            if (second_diff - best_diff) >= TIE_DURATION_MARGIN_MINUTES:
                resolved = True

    def label(product: dict) -> str:
        title = product.get("title", "") or "?"
        asin = product.get("asin", "") or "?"
        return f"{title} [{asin}]"

    ambiguity = {
        "count": len(top),
        "resolved": resolved,
        "chosen": label(best_product),
        "alternatives": [label(product) for _score, product in top[1:]],
        "reason": (
            f"ambiguous match: {len(top)} candidates at score {best_score_value} "
            + (
                f"(chose {label(best_product)} on duration)"
                if resolved
                else "with no clear duration winner"
            )
        ),
    }

    return best_product, best_score_value, ambiguity


# ---------------------------------------------------------------------------
# Edit-mode decision
# ---------------------------------------------------------------------------

@trace(CHOOSE, capture=[])
def determine_edit_mode(
    product: dict,
    clues: dict,
    score: float,
    duration_result: dict | None = None,
) -> str:
    # Dedicated catalog sources (GraphicAudio, SoundBooth Theater) don't expose
    # runtime data via abs-agg so duration is always "unknown". Their scores are
    # structurally low even for perfect matches, so evaluate them before the
    # general score gate. Verify via the local file's composer (©wrt) tag that
    # the production company matches, then confirm title+author before writing.
    _sp = product.get("_abs_provider")
    if _sp in SPECIAL_PROVIDERS:
        _COMPOSER_MARKERS: dict[str, str] = {
            "graphicaudio": "graphicaudio",
            "soundbooththeater": "soundbooth",
        }
        _expected = _COMPOSER_MARKERS.get(_sp, "")
        _raw_tags = clues.get("_raw_tags") or {}
        _composer_text = ""
        for _tag_key in ("©wrt", "\xa9wrt"):
            for _val in (_raw_tags.get(_tag_key) or []):
                try:
                    _composer_text = (
                        bytes(_val).decode("utf-8", "ignore")
                        if hasattr(_val, "__bytes__") else str(_val)
                    )
                except Exception:
                    pass
                break
            if _composer_text:
                break
        if not _composer_text:
            _composer_text = str(_raw_tags.get("composer", "") or "")
        composer_confirmed = bool(_expected and _expected in _composer_text.lower())
        if composer_confirmed:
            local_title_n  = normalize_for_match(clues.get("title", ""))
            abs_title_n    = normalize_for_match(product.get("title", "") or "")
            local_author_n = normalize_for_match(clues.get("author", ""))
            abs_author_n   = normalize_for_match(" ".join(get_people(product, "authors")))
            title_ok  = bool(local_title_n and (
                local_title_n == abs_title_n
                or local_title_n in abs_title_n
                or abs_title_n in local_title_n
            ))
            author_ok = bool(
                local_author_n and abs_author_n
                and SequenceMatcher(None, local_author_n, abs_author_n).ratio() >= 0.75
            )
            if title_ok and author_ok:
                return "full"

    # Goodreads (abs-tract) fallback: no narrator, no duration, no composer
    # signal, and scores are structurally low. Accept only on a strong title +
    # author identity match -- that is the "enough metadata was found" bar -- and
    # write full; otherwise reject (leave as a manual-review miss).
    if product.get("_abs_provider") == "goodreads":
        gr_local_title = normalize_for_match(clues.get("title", ""))
        gr_title = normalize_for_match(product.get("title", "") or "")
        gr_local_title_bookless = normalize_book_label_for_match(clues.get("title", ""))
        gr_title_bookless = normalize_book_label_for_match(product.get("title", "") or "")
        gr_title_ok = bool(gr_local_title and (
            gr_local_title == gr_title
            or gr_local_title_bookless == gr_title_bookless
            or gr_local_title in gr_title
            or gr_title in gr_local_title
        ))
        # Series + sequence identity is an alternative to title-string identity:
        # Goodreads often titles a book by its series ("Beast Shifter 3") while
        # the local title is the actual book name ("The Primal Talisman").
        gr_cand_series, gr_cand_seq = get_primary_series(product)
        gr_local_series = normalize_for_match(clues.get("series", ""))
        gr_cand_series_n = normalize_for_match(gr_cand_series)
        gr_series_ok = bool(gr_local_series and gr_cand_series_n and (
            gr_local_series == gr_cand_series_n
            or gr_local_series in gr_cand_series_n
            or gr_cand_series_n in gr_local_series
        ))
        gr_seq_ok = sequence_values_equal(clues.get("book_number", ""), gr_cand_seq)
        gr_identity_ok = gr_title_ok or (gr_series_ok and gr_seq_ok)

        # Author check, tolerant of multi-author credits and ordering. Goodreads
        # frequently lists only the primary author of a co-authored book, so
        # match per-name (subset), not on the whole concatenated string.
        gr_author_compat = _authors_compatible(
            clues.get("author", ""), " ".join(get_people(product, "authors"))
        )
        if gr_author_compat is True:
            gr_author_ok = True
        elif gr_author_compat is None:
            # Author unknown on one side (e.g. a missing local author tag). Only
            # safe to accept on an exact title match, not a loose containment.
            gr_author_ok = bool(gr_local_title and gr_local_title == gr_title)
        else:
            gr_author_ok = False
        return "full" if (gr_identity_ok and gr_author_ok) else "none"

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
            or audible_series in local_series
            or local_series in audible_series
            or SequenceMatcher(None, local_series, audible_series).ratio() >= 0.88
        )
    )

    def safe_series_only() -> str:
        return (
            "series_only"
            if series_name and author_identity_match and series_identity_match
            else "none"
        )

    # Only gate to series_only when duration is a genuine mismatch.
    # "acceptable" status already means the duration difference is within
    # tolerable range -- adding a separate 10% hard cap was redundant and
    # overrode confirmed ASIN + title + author + narrator evidence.
    if duration_status == "mismatch":
        return safe_series_only()

    # Omnibus / box-set records can be useful for series grouping,
    # but should not overwrite individual book titles or track numbers.
    if is_omnibus_product(product):
        local_omnibus_text = clean_text(
            " ".join(
                str(clues.get(key, "") or "")
                for key in ("title", "raw_title", "album", "series")
            )
        )
        local_omnibus = bool(
            re.search(
                r"\b(?:omnibus|complete collection|definitive collection|complete series|complete trilogy|complete duology|complete saga|trilogy|duology|box set|books?\s+\d+\s*(?:-|to|through|&)\s*\d+)\b",
                local_omnibus_text,
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


# ---------------------------------------------------------------------------
# Metadata assembly
# ---------------------------------------------------------------------------

@trace(ALTER, capture=[])
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


@trace(ALTER, capture=[], show_result=False)
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

    raw_genres = product.get("_abs_genres") or []
    genre_text = ", ".join(clean_provider_genres(raw_genres)[:3])

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
        "publisher": sanitize_tag(clues.get("publisher", "")),
        "genre": genre_text,
        "isbn": product.get("_abs_isbn", "") or "",
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


@trace(CHOOSE, capture=["audible_title", "audible_series", "local_title"])
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
