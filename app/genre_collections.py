"""Audiobookshelf collections built from genres (Enrichment Forge).

One collection per chosen genre, holding every book whose ABS genres include
it (merged store names split, one spelling per genre, "Audiobook" never
counted). LibraForge marks the collections it creates in their description
and only ever changes or deletes those: a user's own collection with the same
name is reported as taken and left alone.

Audiobookshelf has no paging inside a collection: opening one loads every book
in full (~20 KB each), and its Collections page loads the collections on
screen with all their books at once (#454). A 2,664-book Fantasy collection
was 49 MB and the page 184 MB, which ABS couldn't open. So:
- a genre over MAX_COLLECTION_BOOKS becomes numbered parts ("LitRPG 1",
  "LitRPG 2"), split by author so a series stays in one part;
- a book in a specific genre (LitRPG, Cultivation) isn't also put in the
  broad one it belongs to (Fantasy, Sci-Fi): those are its collections;
- Progression Fantasy is a subgenre, never a collection, and Non-Fiction is
  listed with the subgenres: its subjects are the useful shelves;
- SUGGESTED genres are the specific ones; ABS's Genre filter (paged) suits
  the broad ones at any size.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

from app.fixer.scoring import GENRE_BLOCKLIST
from app.genre_taxonomy import NON_GENRES, normalize_label, split_compound_genres

MARKER = "Managed by LibraForge (genre collection)"
MAX_COLLECTION_BOOKS = 600  # ~12 MB for ABS to open
NEVER_COLLECTIONS = {"Progression Fantasy"}  # a subgenre: LitRPG and Cultivation are its collections
# Too broad to browse as one shelf: listed with the subgenres, its own
# subjects (History, Philosophy...) are the collections.
SUBGENRE_COLLECTIONS = {"Non-Fiction"}
SUGGESTED = ("LitRPG", "Cultivation", "Harem", "Audio Drama", "Classics", "Young Adult", "Children's",
             "History", "Politics", "Philosophy", "Health", "Biography", "Psychology")
# Broad genre -> the specific genres whose books it leaves out.
SPECIFIC_FIRST = {"Fantasy": ("LitRPG", "Cultivation"), "Sci-Fi": ("LitRPG", "Cultivation")}


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


def book_order(items: list[dict[str, Any]]) -> dict[str, tuple[str, str, str]]:
    """Item id -> (author, series, title), the order parts are cut in."""
    out = {}
    for item in items:
        md = (item.get("media") or {}).get("metadata") or {}
        author = str(md.get("authorNameLF") or md.get("authorName") or "").strip().lower()
        out[str(item.get("id") or "")] = (author, str(md.get("seriesName") or "").lower(), str(md.get("title") or "").lower())
    return out


def split_parts(books: list[str], order: dict[str, tuple[str, str, str]], limit: int = MAX_COLLECTION_BOOKS) -> list[list[str]]:
    """Books in one part, or in even numbered parts of at most `limit`, cut
    between authors so a series is never split (unless one author alone is
    over the limit)."""
    if len(books) <= limit:
        return [list(books)]
    ranked = sorted(books, key=lambda b: (order.get(b, ("", "", "")), b))
    target = math.ceil(len(ranked) / math.ceil(len(ranked) / limit))
    groups: list[list[str]] = []
    for book in ranked:
        if groups and order.get(book, ("",))[0] == order.get(groups[-1][0], ("",))[0]:
            groups[-1].append(book)
        else:
            groups.append([book])
    parts: list[list[str]] = [[]]
    for group in groups:
        if parts[-1] and (len(parts[-1]) >= target or len(parts[-1]) + len(group) > limit):
            parts.append([])
        for start in range(0, len(group), limit):  # one author alone over the limit
            if start:
                parts.append([])
            parts[-1].extend(group[start:start + limit])
    return parts


def _book_ids(collection: dict[str, Any]) -> list[str]:
    return [b.get("id") if isinstance(b, dict) else str(b) for b in collection.get("books") or []]


def is_managed(collection: dict[str, Any] | None) -> bool:
    """A collection LibraForge created (its marker is in the description)."""
    return bool(collection) and MARKER in str(collection.get("description") or "")


def _names_genre(name: str, genre: str) -> bool:
    """"Fantasy" or one of its numbered parts ("Fantasy 2")."""
    return bool(re.fullmatch(re.escape(genre.strip().lower()) + r"( \d+)?", name.strip().lower()))


def plan_collections(
    genres: list[str],
    counts: dict[str, list[str]],
    existing: list[dict[str, Any]],
    order: dict[str, tuple[str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """One row per collection the chosen genres need (create / update /
    in_sync / name_taken / empty), plus "retire" rows for LibraForge
    collections of those genres the plan no longer has (an unsplit Fantasy
    replaced by its parts, a part no longer needed, Progression Fantasy).
    Each row: genre, name, part, parts, collection_id, books, add, remove."""
    order = order or {}
    by_name = {str(c.get("name") or "").strip().lower(): c for c in existing}
    rows = []
    for genre in genres:
        planned: set[str] = set()
        if genre not in NEVER_COLLECTIONS:
            books = list(counts.get(genre, []))
            covered = {b for g in SPECIFIC_FIRST.get(genre, ()) for b in counts.get(g, [])}
            books = [b for b in books if b not in covered]
            parts = split_parts(books, order) if books else [[]]
            for number, part in enumerate(parts, 1):
                name = genre if len(parts) == 1 else f"{genre} {number}"
                planned.add(name.lower())
                current = by_name.get(name.lower())
                row = {"genre": genre, "name": name, "part": number, "parts": len(parts),
                       "collection_id": current.get("id") if current else None,
                       "books": part, "book_count": len(part), "add": [], "remove": []}
                if current and not is_managed(current):
                    row["action"] = "name_taken"
                elif not part:
                    row["action"] = "empty"
                elif not current:
                    row["action"], row["add"] = "create", part
                else:
                    have = _book_ids(current)
                    row["add"] = [b for b in part if b not in have]
                    row["remove"] = [b for b in have if b not in part]
                    row["action"] = "update" if row["add"] or row["remove"] else "in_sync"
                rows.append(row)
        for collection in existing:
            name = str(collection.get("name") or "").strip()
            if is_managed(collection) and _names_genre(name, genre) and name.lower() not in planned:
                rows.append({"genre": genre, "name": name, "part": 0, "parts": 0, "action": "retire",
                             "collection_id": collection.get("id"), "books": [],
                             "book_count": len(_book_ids(collection)), "add": [], "remove": []})
    return rows


def apply_collection_plan(
    rows: list[dict[str, Any]],
    *,
    library_id: str,
    post_fn: Callable[[str, dict], Any],
    patch_fn: Callable[[str, dict], Any],
    delete_fn: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Create, update and retire LibraForge-managed collections; everything
    else is skipped. One failure never stops the rest."""
    out: dict[str, Any] = {"created": 0, "updated": 0, "removed": 0, "skipped": 0, "failed": []}
    for row in rows:
        try:
            if row["action"] == "create":
                post_fn("/api/collections", {"libraryId": library_id, "name": row["name"],
                                             "description": MARKER, "books": row["books"]})
                out["created"] += 1
            elif row["action"] == "update":
                # ABS only reorders on a PATCH books list; membership changes go
                # through the batch endpoints (verified against ABS 2.35).
                if row["add"]:
                    post_fn(f"/api/collections/{row['collection_id']}/batch/add", {"books": row["add"]})
                if row["remove"]:
                    post_fn(f"/api/collections/{row['collection_id']}/batch/remove", {"books": row["remove"]})
                out["updated"] += 1
            elif row["action"] == "retire" and delete_fn:
                delete_fn(f"/api/collections/{row['collection_id']}")
                out["removed"] += 1
            else:
                out["skipped"] += 1
        except Exception as exc:
            out["failed"].append({"genre": row["name"], "error": str(exc)})
    return out
