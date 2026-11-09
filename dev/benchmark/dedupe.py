"""One instance of each book search in a dataset.

Two books are the same search when the matcher would start from the same place: the
fixer's build_search_queries_from_metadata gives the same queries and the same title,
author, narrator, series, book number and embedded ASIN from their original tags (read
at one neutral path, so file and folder names don't count), and their runtimes are
within 1%. Of each such group only the first
is kept, preferring a book with a confirmed answer.

With --dump and --overlap, the books overlap.py set aside as already in the library
come back when they start from different original values than that library book: a
separate search for the same book. Within 3% of the library book's runtime it is the
same recording, and the library's confirmed match is its answer; otherwise its file
name is, as for any imported book.

Runs in a LibraForge image with app/ and scripts/ mounted at /app:
  dedupe.py <books.json> <out.json> [--dump output.json --overlap import_overlap.json]
  [--dry-run]
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import import_dump  # noqa: E402

spec = importlib.util.spec_from_file_location("fixer", "/app/scripts/audible-metadata-fixer-v5.py")
fixer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixer)
NEUTRAL = Path("/book/book.m4b")
# The clues a search and its scoring read; genre, publisher and the like don't change it.
SEARCH_CLUES = ("title", "author", "narrator", "series", "book_number", "existing_asin")


def search_key(book):
    tags = book["tags"]
    queries, clues = fixer.build_search_queries_from_metadata(NEUTRAL, tags=tags)
    clues = {k: clues.get(k) or "" for k in SEARCH_CLUES}
    return json.dumps([queries, clues], sort_keys=True, default=str)


def same_runtime(a, b, within):
    return bool(a and b) and abs(a - b) / max(a, b) <= within


def same_answer(a, b):
    """No conflicting answer: two confirmed ASINs, or two book numbers in the name,
    that differ ("Vesik; Book 01-03" and "Book 04-06" share their tags, not the book)."""
    if a["asin"] and b["asin"]:
        return a["asin"] == b["asin"]
    na, nb = ((x.get("expect") or {}).get("sequence") or "" for x in (a, b))
    return not (na and nb and na != nb)


def dedupe(books):
    kept, groups, dropped = [], {}, []
    for book in sorted(books, key=lambda b: not b["asin"]):  # a confirmed answer first
        key = search_key(book)
        twin = next((k for k in groups.get(key, [])
                     if same_runtime(k["minutes"], book["minutes"], 0.01) and same_answer(k, book)), None)
        if twin:
            dropped.append((book, twin))
        else:
            groups.setdefault(key, []).append(book)
            kept.append(book)
    order = {b["folder"]: i for i, b in enumerate(books)}
    return sorted(kept, key=lambda b: order[b["folder"]]), dropped


def returning_overlaps(books, dump_path, overlap_path):
    by_folder = {b["folder"]: b for b in books}
    overlap = {r["path"]: r["library_path"] for r in json.load(open(overlap_path)) if r["overlap"]}
    dump = {e["path"]: e for e in json.load(open(dump_path, encoding="utf-8"))}
    back = []
    for case in import_dump(dump_path):
        path = next((p for p in overlap if os.path.dirname(p).endswith("/" + case["folder"])), None)
        lib = by_folder.get("/".join(Path(overlap[path]).parts[2:])) if path else None
        if not lib or search_key(case) == search_key(lib):
            continue
        if lib["asin"] and same_runtime(case["minutes"], lib["minutes"], 0.03):
            case.update(asin=lib["asin"], final=lib["final"], expect=None)
        case["overlaps"] = lib["folder"]
        back.append(case)
    return back


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("books")
    ap.add_argument("out")
    ap.add_argument("--dump")
    ap.add_argument("--overlap")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    books = json.load(open(a.books, encoding="utf-8"))
    back = returning_overlaps(books, a.dump, a.overlap) if a.dump else []
    kept, dropped = dedupe(books + back)
    print(f"{len(books)} books + {len(back)} returning overlaps "
          f"({sum(bool(b['asin']) for b in back)} with the library's answer); "
          f"{len(dropped)} duplicates dropped -> {len(kept)}")
    for book, twin in dropped:
        print(f"  drop {book['folder']}  (same search as {twin['folder']})")
    for b in back:
        if b in kept:
            print(f"  back {b['folder']}  (overlaps {b['overlaps']})")
    if not a.dry_run:
        json.dump(kept, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
