"""Enrichment Forge: series-wide genre/narrator/explicit-evidence compilation.

Pure aggregation logic plus thin network-calling helpers. Every function that
needs to make a network call (ABS API, Audible, abs-tract) takes the caller
as an injected parameter instead of importing app.main directly, so this
module has no import-time dependency on app.main and no circular-import risk
(mirrors the app/fixer/*.py rule of never importing the fixer script itself).
"""
from __future__ import annotations

import concurrent.futures
import json
import re
from pathlib import Path
from typing import Any, Callable

from app.genre_taxonomy import MAIN_ORDER, labels_from_genres, labels_from_text
from app.genre_voting import book_vote, vote_unit
from app.goodreads_shelves import shelves_explicit_evidence, shelves_to_genres

_SERIES_SEQUENCE_SUFFIX_RE = re.compile(r"\s*#\d+\s*$")
_SERIES_SEQUENCE_NUMBER_RE = re.compile(r"#(\d+(?:\.\d+)?)\s*$")


def strip_series_sequence_suffix(series_name: str) -> str:
    """Strip a trailing Audiobookshelf '#N' sequence marker, e.g.
    'Youngest Son of the Black-Hearted #1' becomes
    'Youngest Son of the Black-Hearted'.
    """
    return _SERIES_SEQUENCE_SUFFIX_RE.sub("", series_name or "").strip()


def extract_series_sequence(series_name: str) -> str | None:
    """Extract the trailing Audiobookshelf '#N' sequence number, e.g.
    'Scholomance #4' becomes '4', 'Scholomance #4.5' becomes '4.5'.
    Returns None when no sequence suffix is present.
    """
    match = _SERIES_SEQUENCE_NUMBER_RE.search(series_name or "")
    return match.group(1) if match else None


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


_SERIES_KEY_AUTHOR_SEP = "\x1f"
# Standalone units are keyed by item id; the prefix can't occur in a
# normalized series key.
STANDALONE_KEY_PREFIX = "\x1estandalone:"


def _has_audio(item: dict[str, Any]) -> bool:
    count = (item.get("media") or {}).get("numAudioFiles")
    return count is None or int(count or 0) > 0


def standalone_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Audio items with no series: each is its own Enrichment Forge unit."""
    return [it for it in items
            if not str(((it.get("media") or {}).get("metadata") or {}).get("seriesName") or "").strip() and _has_audio(it)]


def _item_authors(item: dict[str, Any]) -> list[str]:
    """Credited authors of an ABS item, minus role suffixes like
    'Ben Aaranovitch - introduction'."""
    raw = str(((item.get("media") or {}).get("metadata") or {}).get("authorName") or "")
    return [a.split(" - ")[0].strip() for a in raw.split(",") if a.split(" - ")[0].strip()]


def split_group_by_author(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split a same-named series group into separate works by primary author
    (LibraForge #305), e.g. Naomi Novik's and Logan Jacobs' "Scholomance".

    Splits only when 2+ primary authors each have 2+ books AND no book credits
    two of them together -- co-written/continuation series (Dune: Brian Herbert
    and Kevin J. Anderson) and a single stray book stay one group. Returns
    {"": items} when no split applies.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        authors = _item_authors(item)
        buckets.setdefault(authors[0] if authors else "", []).append(item)
    big = [a for a, group in buckets.items() if a and len(group) >= 2]
    if len(big) < 2:
        return {"": items}
    big_lower = {a.lower() for a in big}
    for item in items:
        if len(big_lower & {a.lower() for a in _item_authors(item)}) >= 2:
            return {"": items}
    return buckets


def list_series_summary(
    groups: dict[str, list[dict[str, Any]]],
    query: str = "",
    standalones: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return [{key, name, book_count}] sorted by book_count descending,
    filtered by a case-insensitive substring match on the display name.

    `key` is the group's own key (plus the author for a split group) and is
    what compile should look up -- re-normalizing a display name can land on
    a different key for odd series names (LibraForge #304).
    """
    query_lower = query.strip().lower()
    summary = []
    for group_key, group_items in groups.items():
        base_name = _display_series_name(group_items)
        for author, bucket in split_group_by_author(group_items).items():
            display_name = f"{base_name} [{author}]" if author else base_name
            if query_lower and query_lower not in display_name.lower():
                continue
            key = f"{group_key}{_SERIES_KEY_AUTHOR_SEP}{author}" if author else group_key
            summary.append({"key": key, "name": display_name, "book_count": len(bucket), "standalone": False})
    summary.sort(key=lambda row: (-row["book_count"], row["name"].lower()))
    rows = []
    for item in standalones or []:
        metadata = (item.get("media") or {}).get("metadata") or {}
        authors = _item_authors(item)
        title = str(metadata.get("title") or "").strip()
        display_name = f"{title} [{authors[0]}]" if authors else title
        if query_lower and query_lower not in display_name.lower() and query_lower not in str(metadata.get("authorName") or "").lower():
            continue
        rows.append({"key": STANDALONE_KEY_PREFIX + str(item.get("id") or ""), "name": display_name, "book_count": 1, "standalone": True})
    rows.sort(key=lambda row: row["name"].lower())
    return summary + rows


def get_series_books(
    groups: dict[str, list[dict[str, Any]]],
    series_name: str,
    normalize_series_fn: Callable[[str], str],
    by_key: bool = False,
    items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return the lightweight per-book dicts for a chosen series (matched by
    its display or normalized name), used to drive the compile step.
    """
    if by_key and series_name.startswith(STANDALONE_KEY_PREFIX):
        item_id = series_name[len(STANDALONE_KEY_PREFIX):]
        group_items = [it for it in items or [] if it.get("id") == item_id]
    elif by_key:
        group_key, _, author = series_name.partition(_SERIES_KEY_AUTHOR_SEP)
        group_items = groups.get(group_key, [])
        if author:
            group_items = split_group_by_author(group_items).get(author, [])
    else:
        query_key = normalize_abs_series_name(series_name, normalize_series_fn)
        group_items = groups.get(query_key, [])
    books = []
    for item in group_items:
        media = item.get("media") or {}
        metadata = media.get("metadata") or {}
        raw_series_name = str(metadata.get("seriesName") or "").strip()
        books.append({
            "id": item.get("id", ""),
            "path": item.get("path", ""),
            "is_file": bool(item.get("isFile", False)),
            "title": metadata.get("title", "") or "",
            "asin": str(metadata.get("asin", "") or "").strip().upper(),
            "author": metadata.get("authorName", "") or "",
            # The genres field is what Enrichment Forge overwrites, so that's
            # what "existing" shows (#300); tags carry historical genre data in
            # many libraries and stay a separate, still-contributing input.
            "existing_genres": list(metadata.get("genres") or []),
            "existing_tags": list(media.get("tags") or []),
            # Ebook-only / placeholder items have no audio and must not be
            # searched as audiobooks (#301). Unknown count = assume audio.
            "has_audio": _has_audio(item),
            "description": str(metadata.get("description") or ""),
            "series_name": strip_series_sequence_suffix(raw_series_name),
            "existing_narrator": metadata.get("narratorName", "") or "",
            "existing_explicit": bool(metadata.get("explicit", False)),
            "sequence": extract_series_sequence(raw_series_name),
        })
    books.sort(key=_book_sequence_sort_key)
    return books


def _book_sequence_sort_key(book: dict[str, Any]) -> float:
    """Sort books by their series sequence number ascending; books with no
    parseable sequence sort after every numbered one (float('inf')), in
    their original relative order among themselves (stable sort).
    """
    sequence = book.get("sequence")
    if not sequence:
        return float("inf")
    try:
        return float(sequence)
    except (TypeError, ValueError):
        return float("inf")


ENRICHMENT_SEARCH_WORKERS = 5


def search_series_audible(
    books: list[dict[str, Any]],
    audible_search_fn: Callable[[Any, str, int], list[dict]],
    audible_lookup_by_asin_fn: Callable[[Any, str], dict | None],
    client: Any,
    workers: int = ENRICHMENT_SEARCH_WORKERS,
) -> dict[str, dict | None]:
    """Search Audible for every book in a series, up to `workers` concurrently.

    Books with a known ASIN use the direct lookup; otherwise falls back to a
    text search on title + author and takes the first result (these books
    are already organized/identified, so no scoring is needed here, unlike
    the fixer's raw-scan matching problem). Returns a dict keyed by book id
    -> Audible product dict, or None if nothing was found or the call failed.
    """
    def _search_one(book: dict[str, Any]) -> tuple[str, dict | None]:
        if not book.get("has_audio", True):
            return book["id"], None  # #301: never match placeholders/ebooks to audiobooks
        try:
            if book.get("asin"):
                return book["id"], audible_lookup_by_asin_fn(client, book["asin"])
            query = f"{book.get('title', '')} {book.get('author', '')}".strip()
            if not query:
                return book["id"], None
            results = audible_search_fn(client, query, 3)
            return book["id"], (results[0] if results else None)
        except Exception:
            return book["id"], None

    results: dict[str, dict | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for book_id, product in pool.map(_search_one, books):
            results[book_id] = product
    return results


def search_series_goodreads(
    books: list[dict[str, Any]],
    fetch_fn: Callable[..., dict[str, Any]],
    pacer: Any,
    workers: int = ENRICHMENT_SEARCH_WORKERS,
) -> dict[str, dict[str, Any]]:
    """Look every audio book up on Goodreads directly (app/goodreads_shelves.py),
    up to `workers` concurrently, all sharing one pacer so the whole library
    stays under Meta Forge's Goodreads pacing (0.5 s global gap, breaker 2 -> 180 s).
    Runs after the Audible phase has finished (enforced by the caller). Returns
    book id -> {"status": found|not_found|failed|skipped, "title", "shelves"}.
    """
    def _search_one(book: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if not book.get("has_audio", True):
            return book["id"], {"status": "skipped", "title": None, "shelves": []}  # #301
        author = (str(book.get("author", "") or "").split(",")[0]).strip()
        try:
            return book["id"], fetch_fn(book.get("title", ""), author, pacer=pacer)
        except Exception:
            return book["id"], {"status": "failed", "title": None, "shelves": []}

    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for book_id, result in pool.map(_search_one, books):
            results[book_id] = result
    return results


def search_series_abs(
    books: list[dict[str, Any]],
    abs_search_fn: Callable[..., dict[str, Any]],
    provider: str = "audible",
    workers: int = ENRICHMENT_SEARCH_WORKERS,
) -> dict[str, dict | None]:
    """Search via Audiobookshelf's configured metadata providers.

    This is the no-Audible-auth fallback path. The caller supplies the existing
    app.main.search_abs_candidates function so Enrichment Forge reuses the same
    ABS search plumbing as the manual review and M4B flows.
    """
    def _search_one(book: dict[str, Any]) -> tuple[str, dict | None]:
        if not book.get("has_audio", True):
            return book["id"], None  # #301
        try:
            query = str(book.get("title", "") or "").strip()
            if not query:
                return book["id"], None
            data = abs_search_fn(
                title=query,
                author=str(book.get("author", "") or ""),
                provider=provider,
                limit=3,
            )
            results = data.get("results", []) if isinstance(data, dict) else []
            return book["id"], (results[0] if results else None)
        except Exception:
            return book["id"], None

    results: dict[str, dict | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for book_id, product in pool.map(_search_one, books):
            results[book_id] = product
    return results


_EROTICA_ROOT = "erotica"


# Audible's audience roots carry the only children's/teen signal, so they are
# kept; every other root is a broad store section. Generic umbrella nodes are
# dropped here (Enrichment Forge only -- Meta Forge's genre output is untouched).
_AUDIENCE_ROOTS = {"children's audiobooks", "teen & young adult"}
_UMBRELLA_NODES = {"literature & fiction", "genre fiction", "science fiction & fantasy"}


def audible_category_ladder_genres(product: dict[str, Any] | None) -> list[str]:
    """Every level of each of a product's category_ladders below its root,
    deduped in order (LibraForge #302), e.g. 'Science Fiction & Fantasy >
    Science Fiction > Space Opera' gives Science Fiction and Space Opera.
    Audience roots (Children's Audiobooks, Teen & Young Adult) are kept;
    generic umbrella nodes are dropped.
    """
    if not product:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for ladder in (product.get("category_ladders") or []):
        names = [str(n.get("name") or "").strip() for n in (ladder.get("ladder") or [])]
        names = [n for n in names if n]
        if not names:
            continue
        keep = names if names[0].lower() in _AUDIENCE_ROOTS else (names[1:] or names)
        for name in keep:
            key = name.lower()
            if key in _UMBRELLA_NODES or key in seen:
                continue
            seen.add(key)
            out.append(name)
    return out


def is_flagged_explicit(product: dict[str, Any] | None) -> bool:
    """True when Audible's own signals suggest explicit/adult content.

    This is a positive-only signal, see
    docs/design/2026-07-10-enrichment-forge-design.md and the
    reference_explicit_signal_reliability memory: False does NOT mean
    "confirmed clean", it only means neither signal happened to fire.
    """
    if not product:
        return False
    if product.get("is_adult_product"):
        return True
    for ladder in (product.get("category_ladders") or []):
        nodes = ladder.get("ladder") or []
        if nodes and nodes[0].get("name", "").strip().lower() == _EROTICA_ROOT:
            return True
    return False


def explicit_evidence_note(flagged_count: int, total_count: int, goodreads_count: int = 0) -> str:
    """Deterministic, count-only evidence sentence.

    Never names individual books (the per-book warning pills in the UI
    already do that, and it gets grammatically awkward at variable list
    lengths), and never a generated sentence, this is plain templating.
    `goodreads_count` = books whose Goodreads readers significantly shelve
    them as erotica/smut/nsfw.
    """
    if flagged_count == 0 and goodreads_count == 0:
        headline = "No book in this series returned a positive Erotica/adult signal from Audible or Goodreads."
    else:
        parts = []
        if flagged_count == total_count:
            parts.append(f"All {total_count} books in this series show a positive Erotica/adult signal from Audible.")
        elif flagged_count:
            parts.append(f"{flagged_count} of {total_count} books in this series show a positive "
                         "Erotica/adult signal from Audible (marked below).")
        if goodreads_count:
            parts.append(f"{goodreads_count} of {total_count} books are shelved as erotica/smut/nsfw by "
                         "Goodreads readers (marked below).")
        headline = " ".join(parts)
    caveat = (
        "That doesn't confirm the rest are clean, the same signal has missed equally "
        "explicit books before, so use your own judgment for the whole series."
    )
    return f"{headline} {caveat}"


def _format_sequence_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def _compute_sequence_range(books: list[dict[str, Any]]) -> str:
    """Summarize the series' sequence numbers as 'min to max', a single
    value when every book shares the same sequence, or blank when no book
    carries a sequence number at all.
    """
    numbers: list[float] = []
    for book in books:
        sequence = book.get("sequence")
        if not sequence:
            continue
        try:
            numbers.append(float(sequence))
        except (TypeError, ValueError):
            continue
    if not numbers:
        return ""
    low, high = min(numbers), max(numbers)
    if low == high:
        return _format_sequence_number(low)
    return f"{_format_sequence_number(low)} to {_format_sequence_number(high)}"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        stripped = value.strip()
        key = stripped.lower()
        if stripped and key not in seen:
            seen.add(key)
            out.append(stripped)
    return out


def _split_abs_genre(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [part.strip() for part in str(value or "").split(",")]


def build_book_voters(
    book: dict[str, Any],
    product: dict | None,
    abs_product: dict | None,
    goodreads_result: dict | None,
    audiosilo_result: dict | None,
    openlibrary_result: dict | None,
) -> dict[str, list[str]]:
    """Normalized labels per evidence source for one book; sources with
    nothing to say are left out. A no-audio item votes nothing (#301)."""
    if not book.get("has_audio", True):
        return {}
    voters: dict[str, list[str]] = {}
    audible = audible_category_ladder_genres(product) or _split_abs_genre((abs_product or {}).get("genre", ""))
    voters["audible"] = labels_from_genres(audible)
    if (goodreads_result or {}).get("status") == "found":
        voters["goodreads"] = labels_from_genres(shelves_to_genres(goodreads_result.get("shelves") or []))
    for name, result in (("audiosilo", audiosilo_result), ("openlibrary", openlibrary_result)):
        if (result or {}).get("status") == "found":
            voters[name] = list(result.get("labels") or [])
    voters["abs_existing"] = labels_from_genres(list(book.get("existing_genres") or []) + list(book.get("existing_tags") or []))
    text = " ".join(str(x or "") for x in (
        (product or {}).get("title"), (product or {}).get("subtitle"), (product or {}).get("publisher_summary"),
        (abs_product or {}).get("description"), book.get("description")))
    voters["keywords"] = labels_from_text(text)
    return {name: labels for name, labels in voters.items() if labels}


def compile_series_enrichment(
    books: list[dict[str, Any]],
    audible_results: dict[str, dict | None],
    goodreads_results: dict[str, list[dict]],
    clean_provider_genres_fn: Callable[[list[str]], list[str]],
    abs_results: dict[str, dict | None] | None = None,
    extra_results: dict[str, dict[str, dict]] | None = None,
    series_sources: dict[str, Any] | None = None,
    standalone: bool = False,
) -> dict[str, Any]:
    """Build the full compile payload: per-book rows, the voted main genres and
    subgenres with their evidence, the narrator union and the explicit note.

    `extra_results` holds the other book-level sources ({"audiosilo": {id:
    result}, "openlibrary": {...}}); `series_sources` the series-level labels
    ({"labels", "evidence", "pf_progression"}, app/enrichment_sources.py).
    """
    extra = extra_results or {}
    book_votes = []
    rows = []
    all_genres: list[str] = []
    all_narrators: list[str] = []
    flagged_count = 0
    goodreads_explicit_count = 0

    for book in books:
        product = audible_results.get(book["id"])
        abs_product = (abs_results or {}).get(book["id"])
        gr = goodreads_results.get(book["id"]) or {}
        gr_found = gr.get("status") == "found"

        audible_genres = clean_provider_genres_fn(
            audible_category_ladder_genres(product)
            or _split_abs_genre((abs_product or {}).get("genre", ""))
        )
        goodreads_genres = clean_provider_genres_fn(shelves_to_genres(gr.get("shelves") or [])) if gr_found else []
        goodreads_explicit = shelves_explicit_evidence(gr.get("shelves") or []) if gr_found else None
        if goodreads_explicit and goodreads_explicit["significant"] and book.get("has_audio", True):
            goodreads_explicit_count += 1
        flagged = is_flagged_explicit(product)
        if flagged:
            flagged_count += 1

        narrators = [n.get("name", "") for n in ((product or {}).get("narrators") or []) if n.get("name")]
        if not narrators:
            narrators.extend(str(n) for n in ((abs_product or {}).get("narrators") or []) if str(n).strip())

        has_audio = book.get("has_audio", True)
        voters = build_book_voters(book, product, abs_product, gr,
                                   (extra.get("audiosilo") or {}).get(book["id"]), (extra.get("openlibrary") or {}).get(book["id"]))
        vote = book_vote(voters)
        book_votes.append(vote)
        if has_audio:  # #301: a placeholder/ebook's genres are not evidence about the series
            all_genres.extend(audible_genres)
            all_genres.extend(goodreads_genres)
            all_genres.extend(clean_provider_genres_fn(book.get("existing_genres", []) + book.get("existing_tags", [])))
            all_narrators.extend(narrators)

        rows.append({
            "id": book["id"],
            "path": book.get("path", ""),
            "is_file": book.get("is_file", False),
            "title": book.get("title", ""),
            "audible_genres": audible_genres,
            "goodreads_genres": goodreads_genres,
            "goodreads_explicit": goodreads_explicit,
            "flagged_explicit": flagged,
            "existing_genres": book.get("existing_genres", []),
            "existing_tags": book.get("existing_tags", []),
            "has_audio": has_audio,
            "default_include": has_audio,
            "existing_narrator": book.get("existing_narrator", ""),
            "existing_explicit": book.get("existing_explicit", False),
            "sources": voters,
            "book_main": sorted(vote["main"], key=MAIN_ORDER.index),
        })

    series = series_sources or {}
    unit = vote_unit(book_votes, series_labels=series.get("labels") or [], series_evidence=series.get("evidence") or [],
                     pf_progression=bool(series.get("pf_progression")), standalone=standalone)
    voted = unit["main"] + unit["sub"]

    return {
        "books": rows,
        # The chips pre-fill with the vote; with no agreement, every genre any
        # source suggested, so the user still has something to pick from.
        "genre": voted or _dedupe_preserve_order(all_genres),
        # Every genre any source suggested, cleaned: "other suggestions" in the UI.
        "genre_union": _dedupe_preserve_order(all_genres),
        "main_genres": unit["main"],
        "sub_genres": unit["sub"],
        "genre_evidence": unit["evidence"],
        "series_evidence": unit["series_evidence"],
        "agreement": unit["agreement"],
        "narrator": ", ".join(_dedupe_preserve_order(all_narrators)),
        "explicit_flagged_count": flagged_count,
        "explicit_total_count": len(books),
        "explicit_goodreads_count": goodreads_explicit_count,
        "explicit_evidence_note": explicit_evidence_note(flagged_count, len(books), goodreads_explicit_count),
        "sequence_range": _compute_sequence_range(books),
    }


_METADATA_JSON_NAME = "metadata.json"


def resolve_metadata_json_path(item_path: str, is_file: bool) -> Path:
    """Resolve the metadata.json target for an already-organized ABS item.

    Simpler than the fixer's clues/alone_in_folder plumbing (meant for raw
    unorganized scans), ABS already tells us whether this item is a folder
    (the common case) or a single loose file it still indexed.
    """
    path = Path(item_path)
    if is_file:
        return path.with_name(path.name + "." + _METADATA_JSON_NAME)
    return path / _METADATA_JSON_NAME


def merge_metadata_json(
    existing: dict[str, Any],
    genre: list[str],
    narrator: str,
    explicit_checked: bool,
) -> dict[str, Any]:
    """Merge Enrichment Forge's edited fields onto an existing metadata.json
    dict. Blank genre/narrator means don't touch that field; non-blank means
    overwrite for every included book, even one that already had a value,
    same semantics as the Fix Series modal. explicit_checked=True writes
    true; False leaves whatever was already there untouched (v1 never writes
    false over an existing true).
    """
    merged = dict(existing)
    if genre:
        merged["genres"] = list(genre)
    if narrator.strip():
        merged["narrators"] = [n.strip() for n in narrator.split(",") if n.strip()]
    if explicit_checked:
        merged["explicit"] = True
    return merged


def write_metadata_json_partial(
    path: Path,
    genre: list[str],
    narrator: str,
    explicit_checked: bool,
) -> dict[str, Any]:
    """Read the existing metadata.json (or {} if absent), apply the partial
    merge, and write it back. Returns the merged dict that was written.

    A corrupt/unreadable existing file is never silently discarded: this
    is an enrichment feature layered on top of whatever the fixer or ABS
    already wrote, so a parse failure raises instead of falling back to
    {} and clobbering every other pre-existing field (title, isbn,
    summary, authors, etc.) with just the newly merged ones. Callers
    should catch this and skip/report that one book without touching the
    file.
    """
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Cannot read existing metadata.json at {path}: {exc}") from exc
    merged = merge_metadata_json(existing, genre, narrator, explicit_checked)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    try:
        path.write_text(content, encoding="utf-8")
    except PermissionError:
        # Matches the existing write_audiobookshelf_metadata_json's retry:
        # an existing file may be read-only.
        path.unlink()
        path.write_text(content, encoding="utf-8")
    return merged
