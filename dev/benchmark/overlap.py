"""Keep only the books of an ffprobe tag dump that your library doesn't already have.

An ffprobe dump is a JSON list of {"path", "filename", "duration" (seconds), "tags"}, one
per audio file, e.g. another library's files before any matching. collect.py --import
turns the kept books into benchmark cases.

A dumped book overlaps a library book by the same author (the matcher's own author check)
when the titles agree and the book numbers don't conflict, or when the series and book
number agree and the titles don't contradict ("Book 1" folders, "The Land; Book 06" vs
"Chaos Seeds Saga/Book 6 - The Land Raiders"). File names in "Author; Series; Book NN;
Title" form give the series and number.

Runs inside a LibraForge image against your Audiobookshelf (abs.json in /app/config):

usage: overlap.py <dump.json> <kept.json> [<overlap-report.json>]
"""
import collections
import json
import os
import re
import sys
from difflib import SequenceMatcher

sys.path.insert(0, "/app")
from app import main  # noqa: E402
from app.fixer.parsing import _authors_compatible, normalize_for_match, sanitize_book_title, split_credit_names  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import BOOK_LABEL, book_number, parse_dump_name  # noqa: E402


def main_title(title):
    return normalize_for_match(re.split(r"\s*[:(\[]", sanitize_book_title(title or ""))[0])


def bare(text):
    return re.sub(r"^the ", "", normalize_for_match(text))


def similar(a, b, ratio):
    a, b = bare(a), bare(b)
    return bool(a and b) and (a in b or b in a or SequenceMatcher(None, a, b).ratio() >= ratio)


def name_keys(author):
    keys = set()
    for name in split_credit_names(author):
        n = normalize_for_match(name)
        keys |= {w for w in n.split() if len(w) > 2} | {n.replace(" ", "")}  # "pirate aba" = "pirateaba"
    return keys


def library_books():
    books, by_name = [], collections.defaultdict(list)
    for item in main.fetch_all_abs_book_items(main._abs_request):
        md = (item.get("media") or {}).get("metadata") or {}
        parts = (item.get("path") or "").split("/")[2:]  # Author/Series/Book N - Title
        leaf = parts[-1] if parts else ""
        m = re.match(rf"{BOOK_LABEL}\s*([\d.]+(?:\s*-\s*\d+)?)\s*(?:-\s*(.*))?$", leaf, re.I)
        book = {"path": item["path"], "author": md.get("authorName") or "",
                "series": [s for s in (re.sub(r"\s*#.*$", "", str(md.get("seriesName") or "")),
                                       parts[-2] if len(parts) > 2 else "") if s],
                "titles": {main_title(md.get("title")), main_title(m.group(2) if m else leaf)} - {""},
                "num": re.sub(r"\s", "", m.group(1)) if m else ""}
        books.append(book)
        for key in name_keys(book["author"]):
            by_name[key].append(book)
    return by_name


def find_overlap(entry, by_name):
    tags = entry.get("tags") or {}
    author = tags.get("artist") or tags.get("album_artist") or ""
    series, number, title = parse_dump_name(entry["filename"])
    titles = {main_title(tags.get("title") or ""), main_title(title)} - {""}
    own = {t for t in titles if bare(t) != bare(series)}  # titles that aren't just the series name
    for book in {id(b): b for k in name_keys(author) for b in by_name.get(k, [])}.values():
        if _authors_compatible(author, book["author"]) is False:
            continue
        if titles & book["titles"] and not (number and book["num"] and number != book["num"]):
            return book, "title"
        if not number or number != book["num"]:
            continue
        book_own = {t for t in book["titles"] if not any(bare(t) == bare(s) for s in book["series"])}
        titles_agree = not own or not book_own or any(similar(a, b, 0.5) for a in own for b in book_own)
        if titles_agree and any(similar(series, s, 0.85) for s in book["series"]):
            return book, "series and number"
        if bare(series) and any(bare(series) in bare(t) for t in book["titles"]):
            return book, "series in title and number"
    return None, ""


if __name__ == "__main__":
    dump = json.load(open(sys.argv[1], encoding="utf-8"))
    by_name = library_books()
    kept, report = [], []
    for entry in dump:
        book, why = find_overlap(entry, by_name)
        report.append({"path": entry["path"], "overlap": why, "library_path": book and book["path"]})
        if not book:
            kept.append(entry)
    json.dump(kept, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
    if len(sys.argv) > 3:
        json.dump(report, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(dump)} books, {len(dump) - len(kept)} already in the library, {len(kept)} kept -> {sys.argv[2]}",
          dict(collections.Counter(r["overlap"] for r in report if r["overlap"])))
