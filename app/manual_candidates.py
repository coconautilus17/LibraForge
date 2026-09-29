"""One Manual Review search-result row, shared by every provider.

The result cards and the apply flow read one shape (title/authors/series
for display, chosen_metadata_by_mode for what gets written); every provider
builds its rows here instead of repeating that shape.
"""
from __future__ import annotations

from typing import Any


def build_manual_candidate_row(
    *,
    provider: str,
    query: str,
    title: str = "",
    subtitle: str = "",
    author: str = "",
    narrator: str = "",
    series: str = "",
    sequence: str = "",
    year: str = "",
    cover_url: str = "",
    asin: str = "",
    summary: str = "",
    genre: str = "",
    duration_minutes: float | None = None,
    language: str | None = None,
    publisher: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A result row offering a full write and, when the match names a
    series, a series-only write. `extra` carries provider-specific keys
    (abs_agg_provider, isbn, display_key, ...). `language` and
    `publisher`, when the provider supplies them, are written in both modes."""
    full_meta = {
        "title": title, "subtitle": subtitle, "author": author,
        "narrator": narrator, "series": series, "sequence": sequence,
        "year": year, "cover_url": cover_url, "asin": asin, "summary": summary,
        "genre": genre,
    }
    series_only_meta = {
        "title": "", "subtitle": "", "author": "", "narrator": "",
        "series": series, "sequence": sequence, "year": "",
        "cover_url": "", "asin": asin, "summary": "",
        "genre": genre,
    }
    for key, value in (("language", language), ("publisher", publisher)):
        if value is not None:
            full_meta[key] = series_only_meta[key] = value
    return {
        "asin": asin,
        "query": query,
        "score": None,
        "edit_mode": "full",
        "recommended_edit_mode": "full",
        "allowed_edit_modes": ["full"] + (["series_only"] if series else []),
        "title": title,
        "subtitle": subtitle,
        "authors": [author] if author else [],
        "narrators": [narrator] if narrator else [],
        "series": series,
        "sequence": sequence,
        "duration_minutes": duration_minutes,
        "year": year,
        "cover_url": cover_url,
        "summary": summary,
        "chosen_metadata": full_meta,
        "chosen_metadata_by_mode": {"full": full_meta, "series_only": series_only_meta},
        "duration": {},
        "provider": provider,
        **extra,
    }
