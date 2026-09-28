"""Is this search result the same book? Enrichment Forge asks Metadata Forge.

Glue only, no matching rules of its own: a source's results go through the
fixer's ABS-provider normalizer (app/fixer/search._abs_match_to_product), the
library book through Manual Review's clue builder (app.main.build_context_clues),
and the decision is exactly the fixer's Goodreads-fallback decision:
pick_best_match_for_metadata, then metadata_from_product's edit mode, accepted
unless it is "none". Sparse sources (Goodreads, Open Library: title and authors
only) are judged by determine_edit_mode's sparse-provider branch.
"""
from __future__ import annotations

from typing import Any

import app.fixer.parsing as fixer_parsing
from app.fixer.scoring import metadata_from_product, pick_best_match_for_metadata
from app.fixer.search import _abs_match_to_product
from app.goodreads_shelves import clean_query_title


def provider_product(match: dict[str, Any], provider: str, asin: str = "") -> dict[str, Any]:
    """A result in the ABS custom-provider format ({title, author, series:
    [{series, sequence}], ...}) as the Audible-shaped product the matcher reads."""
    return _abs_match_to_product(match, provider, asin)


def book_clues(book: dict[str, Any]) -> dict[str, Any]:
    from app.main import build_context_clues  # the Manual Review builder; lazy: main imports this module

    return build_context_clues(fixer_parsing, {
        "title": clean_query_title(str(book.get("title") or "")),
        "series": book.get("series_name") or "",
        "sequence": book.get("sequence") or "",
        "author": str(book.get("author") or "").split(",")[0].split(" - ")[0].strip(),
        "narrator": book.get("existing_narrator") or "",
        "local_duration_minutes": book.get("duration_minutes"),
    })


def best_candidate(book: dict[str, Any], candidates: list[tuple[dict[str, Any], Any]]) -> Any:
    """The payload of the result Metadata Forge would accept for `book`, or None."""
    if not candidates:
        return None
    clues = book_clues(book)
    # As in the fixer's Goodreads fallback, the best candidate is taken even
    # when others tie with it (Open Library returns several editions of one book).
    best, score, _ambiguity = pick_best_match_for_metadata(clues, [p for p, _ in candidates], clues.get("local_duration_minutes"))
    if best is None:
        return None
    if metadata_from_product(best, clues, score).get("edit_mode", "none") == "none":
        return None
    return next(payload for product, payload in candidates if product is best)
