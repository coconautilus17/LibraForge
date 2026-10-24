"""Turn beets-audible import databases into lf_bench.py-shaped rows for score.py.

usage: beets_rows.py <books.json> <out.jsonl> <beets.db> [<beets.db> ...]

A book beets imported (a strong match, applied in quiet mode) is "matched" with
the album's ASIN and fields; every other book was skipped. beets/config.yaml holds
the settings; run each import with `beet import -q -C -W` (nothing copied or written).
"""
import json
import os
import sqlite3
import sys

ROOT = "/audiobooks/"
books, out_path, dbs = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3:]

found = {}
for db in dbs:
    con = sqlite3.connect(db)
    attrs = {}
    for album_id, key, value in con.execute("select entity_id, key, value from album_attributes"):
        attrs.setdefault(album_id, {})[key] = value
    for album_id, asin, album, artist in con.execute("select id, asin, album, albumartist from albums"):
        path, narrator = con.execute("select path, composers from items where album_id = ? limit 1", (album_id,)).fetchone()
        path = path.decode() if isinstance(path, bytes) else path
        folder = os.path.dirname(path)[len(ROOT):]
        a = attrs.get(album_id, {})
        # beets keeps a multi-valued field as one string joined by "\␀".
        narrators = [n for n in str(narrator or "").split("\\␀") if n]
        found[folder] = {"asin": asin or "", "title": album or "", "subtitle": a.get("subtitle", ""), "author": artist or "",
                         "narrator": ", ".join(narrators), "series": a.get("series_name", ""),
                         "sequence": a.get("series_position", "")}

with open(out_path, "w", encoding="utf-8") as out:
    for book in books:
        match = found.get(book["folder"])
        row = {"folder": book["folder"], "status": "matched" if match else "skipped"}
        if match:
            row["match"] = match
        else:
            row["skip_reason"] = "no strong match (skipped in quiet mode)"
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
print(f"{out_path}: {len(found)} matched of {len(books)}")
