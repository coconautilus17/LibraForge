"""Explicit-content evidence for Enrichment Forge.

Evidence for the user to judge, never a silent verdict (spec §3.6):
- The HaremLit Fiction wiki's per-series `explicit_sex` / `explicit` field is
  the only authoritative source: Yes/No becomes a suggestion.
- Audible's adult/Erotica flag, Goodreads readers shelving the book as
  erotica/smut/nsfw (when significant), and Open Library erotica subjects are
  supporting evidence only: shown, never pre-selected. Measured: Audible and
  Goodreads flags are positive-only and miss equally explicit books.
- "Harem" as a genre is not explicit evidence; it is a "check" hint.
"""
from __future__ import annotations

from typing import Any

_YES = {"yes", "explicit", "true", "y"}
_NO = {"no", "false", "n", "none", "clean"}


def _haremlit_verdict(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in _YES:
        return "explicit"
    if text in _NO:
        return "not_explicit"
    return None


def book_explicit_evidence(book_row: dict[str, Any], series_explicit: dict[str, str]) -> dict[str, Any]:
    """{"suggestion": explicit|not_explicit|unknown, "strength":
    authoritative|supporting|none, "evidence": [...], "check": bool}."""
    evidence: list[str] = []
    if book_row.get("flagged_explicit"):
        evidence.append("Audible: adult / Erotica")
    goodreads = book_row.get("goodreads_explicit") or {}
    if goodreads.get("significant"):
        evidence.append(f"Goodreads: explicit shelves ×{goodreads.get('votes', 0)}")
    if "erotica" in ((book_row.get("sources") or {}).get("openlibrary") or []):
        evidence.append("Open Library: erotica")

    verdict = _haremlit_verdict((series_explicit or {}).get("haremlit"))
    if verdict:
        label = "explicit" if verdict == "explicit" else "not explicit"
        return {"suggestion": verdict, "strength": "authoritative",
                "evidence": [f"HaremLit wiki: {label}"] + evidence, "check": False}
    return {
        "suggestion": "unknown",
        "strength": "supporting" if evidence else "none",
        "evidence": evidence,
        # Harem fiction is often explicit, but the genre alone proves nothing.
        "check": not evidence and "Harem" in (book_row.get("book_main") or []),
    }


def series_explicit_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Current flags vs suggestions across the rows (each with "explicit")."""
    total = len(rows)
    flagged_now = sum(1 for r in rows if r.get("existing_explicit"))
    suggestions = [((r.get("explicit") or {}).get("suggestion")) for r in rows]
    return {
        "flagged_now": flagged_now,
        "total": total,
        "inconsistent": 0 < flagged_now < total,
        "suggested_explicit": suggestions.count("explicit"),
        "suggested_not": suggestions.count("not_explicit"),
    }
