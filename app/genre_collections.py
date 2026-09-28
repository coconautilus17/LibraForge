"""Audiobookshelf collections built from genres (Enrichment Forge).

One collection per chosen genre, holding every book whose ABS genres include
it (merged store names split, one spelling per genre, "Audiobook" never
counted). LibraForge marks the collections it creates in their description
and only ever changes those: a user's own collection with the same name is
reported as taken and left alone.
"""
from __future__ import annotations

from typing import Any, Callable

from app.fixer.scoring import GENRE_BLOCKLIST
from app.genre_taxonomy import NON_GENRES, normalize_label, split_compound_genres

MARKER = "Managed by LibraForge (genre collection)"


def genre_counts(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Genre -> ids of the items carrying it, from ABS's own genres field."""
    out: dict[str, list[str]] = {}
    for item in items:
        genres = ((item.get("media") or {}).get("metadata") or {}).get("genres") or []
        # A store umbrella shelf ("Science Fiction & Fantasy") says nothing
        # about which genre a book is: never a collection.
        genres = [g for g in genres if normalize_label(g) not in NON_GENRES]
        for genre in split_compound_genres(genres):
            if genre.lower() in GENRE_BLOCKLIST:
                continue
            ids = out.setdefault(genre, [])
            if item.get("id") and item["id"] not in ids:
                ids.append(item["id"])
    return out


def _book_ids(collection: dict[str, Any]) -> list[str]:
    return [b.get("id") if isinstance(b, dict) else str(b) for b in collection.get("books") or []]


def plan_collections(genres: list[str], counts: dict[str, list[str]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per genre: create / update / in_sync / name_taken / empty, with the
    books to add and remove and the full target list."""
    by_name = {str(c.get("name") or "").strip().lower(): c for c in existing}
    rows = []
    for genre in genres:
        books = list(counts.get(genre, []))
        current = by_name.get(genre.strip().lower())
        row = {"genre": genre, "collection_id": current.get("id") if current else None,
               "books": books, "book_count": len(books), "add": [], "remove": []}
        if current and MARKER not in str(current.get("description") or ""):
            row["action"] = "name_taken"
        elif not books:
            row["action"] = "empty"
        elif not current:
            row["action"], row["add"] = "create", books
        else:
            have = _book_ids(current)
            row["add"] = [b for b in books if b not in have]
            row["remove"] = [b for b in have if b not in books]
            row["action"] = "update" if row["add"] or row["remove"] else "in_sync"
        rows.append(row)
    return rows


def apply_collection_plan(
    rows: list[dict[str, Any]],
    *,
    library_id: str,
    post_fn: Callable[[str, dict], Any],
    patch_fn: Callable[[str, dict], Any],
) -> dict[str, Any]:
    """Create and update LibraForge-managed collections; everything else is
    skipped. One failure never stops the rest."""
    out: dict[str, Any] = {"created": 0, "updated": 0, "skipped": 0, "failed": []}
    for row in rows:
        try:
            if row["action"] == "create":
                post_fn("/api/collections", {"libraryId": library_id, "name": row["genre"],
                                             "description": MARKER, "books": row["books"]})
                out["created"] += 1
            elif row["action"] == "update":
                patch_fn(f"/api/collections/{row['collection_id']}", {"books": row["books"]})
                out["updated"] += 1
            else:
                out["skipped"] += 1
        except Exception as exc:
            out["failed"].append({"genre": row["genre"], "error": str(exc)})
    return out
