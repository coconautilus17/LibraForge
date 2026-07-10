"""Enrichment Forge: series-wide genre/narrator/explicit-evidence compilation.

Pure aggregation logic plus thin network-calling helpers. Every function that
needs to make a network call (ABS API, Audible, abs-tract) takes the caller
as an injected parameter instead of importing app.main directly, so this
module has no import-time dependency on app.main and no circular-import risk
(mirrors the app/fixer/*.py rule of never importing the fixer script itself).
"""
from __future__ import annotations

import concurrent.futures
import re
from pathlib import Path
from typing import Any, Callable

_SERIES_SEQUENCE_SUFFIX_RE = re.compile(r"\s*#\d+\s*$")


def strip_series_sequence_suffix(series_name: str) -> str:
    """Strip a trailing Audiobookshelf '#N' sequence marker, e.g.
    'Youngest Son of the Black-Hearted #1' becomes
    'Youngest Son of the Black-Hearted'.
    """
    return _SERIES_SEQUENCE_SUFFIX_RE.sub("", series_name or "").strip()


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


def list_series_summary(
    groups: dict[str, list[dict[str, Any]]],
    query: str = "",
) -> list[dict[str, Any]]:
    """Return [{name, book_count}] sorted by book_count descending, filtered
    by a case-insensitive substring match on the display name.
    """
    query_lower = query.strip().lower()
    summary = []
    for group_items in groups.values():
        display_name = _display_series_name(group_items)
        if query_lower and query_lower not in display_name.lower():
            continue
        summary.append({"name": display_name, "book_count": len(group_items)})
    summary.sort(key=lambda row: (-row["book_count"], row["name"].lower()))
    return summary


def get_series_books(
    groups: dict[str, list[dict[str, Any]]],
    series_name: str,
    normalize_series_fn: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Return the lightweight per-book dicts for a chosen series (matched by
    its display or normalized name), used to drive the compile step.
    """
    query_key = normalize_abs_series_name(series_name, normalize_series_fn)
    group_items = groups.get(query_key, [])
    books = []
    for item in group_items:
        metadata = ((item.get("media") or {}).get("metadata") or {})
        books.append({
            "id": item.get("id", ""),
            "path": item.get("path", ""),
            "is_file": bool(item.get("isFile", False)),
            "title": metadata.get("title", "") or "",
            "asin": str(metadata.get("asin", "") or "").strip().upper(),
            "author": metadata.get("authorName", "") or "",
            "existing_genres": list((item.get("media") or {}).get("tags") or []),
            "existing_narrator": metadata.get("narratorName", "") or "",
            "existing_explicit": bool(metadata.get("explicit", False)),
        })
    return books


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
    abs_tract_search_fn: Callable[..., list[dict]],
    abs_tract_url: str,
    workers: int = ENRICHMENT_SEARCH_WORKERS,
) -> dict[str, list[dict]]:
    """Search Goodreads (via abs-tract) for every book in a series, up to
    `workers` concurrently. Always called for every book, unlike the fixer's
    silent-fallback pattern used during batch runs. This phase only starts
    after search_series_audible() has fully completed for the whole series
    (enforced by the caller, see app/main.py), so Audible and Goodreads
    calls never interleave (abs-tract's upstream rate limit only trips under
    mixed Goodreads+Amazon load, not pure Goodreads).
    """
    def _search_one(book: dict[str, Any]) -> tuple[str, list[dict]]:
        try:
            return book["id"], abs_tract_search_fn(
                title=book.get("title", ""),
                author=book.get("author", ""),
                provider="goodreads",
                abs_tract_url=abs_tract_url,
                limit=3,
            )
        except Exception:
            return book["id"], []

    results: dict[str, list[dict]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for book_id, products in pool.map(_search_one, books):
            results[book_id] = products
    return results


_EROTICA_ROOT = "erotica"


def audible_category_ladder_genres(product: dict[str, Any] | None) -> list[str]:
    """Return the deepest (leaf) genre name from each of a product's
    category_ladders entries, e.g. 'Science Fiction & Fantasy > Fantasy >
    Epic' becomes 'Epic'.
    """
    if not product:
        return []
    genres = []
    for ladder in (product.get("category_ladders") or []):
        nodes = ladder.get("ladder") or []
        if nodes:
            name = nodes[-1].get("name", "")
            if name:
                genres.append(name)
    return genres


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


def explicit_evidence_note(flagged_count: int, total_count: int) -> str:
    """Deterministic, count-only evidence sentence.

    Never names individual books (the per-book warning pills in the UI
    already do that, and it gets grammatically awkward at variable list
    lengths), and never a generated sentence, this is plain templating.
    """
    if flagged_count == 0:
        headline = "No book in this series returned a positive Erotica/adult signal from Audible or Goodreads."
    elif flagged_count == total_count:
        headline = f"All {total_count} books in this series show a positive Erotica/adult signal from Audible."
    else:
        headline = (
            f"{flagged_count} of {total_count} books in this series show a positive "
            "Erotica/adult signal from Audible (marked below)."
        )
    caveat = (
        "That doesn't confirm the rest are clean, the same signal has missed equally "
        "explicit books before, so use your own judgment for the whole series."
    )
    return f"{headline} {caveat}"


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


def compile_series_enrichment(
    books: list[dict[str, Any]],
    audible_results: dict[str, dict | None],
    goodreads_results: dict[str, list[dict]],
    clean_provider_genres_fn: Callable[[list[str]], list[str]],
) -> dict[str, Any]:
    """Build the full compile payload: per-book rows plus series-level
    aggregate genre/narrator union and the explicit evidence note.
    """
    rows = []
    all_genres: list[str] = []
    all_narrators: list[str] = []
    flagged_count = 0

    for book in books:
        product = audible_results.get(book["id"])
        gr_products = goodreads_results.get(book["id"]) or []
        gr_product = gr_products[0] if gr_products else None

        audible_genres = clean_provider_genres_fn(audible_category_ladder_genres(product))
        goodreads_genres = clean_provider_genres_fn((gr_product or {}).get("_abs_genres") or [])
        flagged = is_flagged_explicit(product)
        if flagged:
            flagged_count += 1

        narrators = [n.get("name", "") for n in ((product or {}).get("narrators") or []) if n.get("name")]

        all_genres.extend(audible_genres)
        all_genres.extend(goodreads_genres)
        all_narrators.extend(narrators)

        rows.append({
            "id": book["id"],
            "path": book.get("path", ""),
            "is_file": book.get("is_file", False),
            "title": book.get("title", ""),
            "audible_genres": audible_genres,
            "goodreads_genres": goodreads_genres,
            "flagged_explicit": flagged,
            "existing_genres": book.get("existing_genres", []),
            "existing_narrator": book.get("existing_narrator", ""),
            "existing_explicit": book.get("existing_explicit", False),
        })

    return {
        "books": rows,
        "genre": _dedupe_preserve_order(all_genres),
        "narrator": ", ".join(_dedupe_preserve_order(all_narrators)),
        "explicit_flagged_count": flagged_count,
        "explicit_total_count": len(books),
        "explicit_evidence_note": explicit_evidence_note(flagged_count, len(books)),
    }
