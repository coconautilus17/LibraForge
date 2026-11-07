"""Turn the hand-audit verdict files into the audit.json report.py reads with --audit.

usage: audit.py <books.json> <verdicts dir> <lf run.jsonl> <out.json>

Each verdict file line is `<book index> LF AS ABS GRM RMAB BO BEETS | note`, the index being
the book's position in books.json, one code per tool:

  C  correct: the book ends up with the right details
  E  the right book, but another recording's details (narrator, runtime) were written
  P  the right book, with a field damaged (title, series, narrator, author)
  W  the wrong book
  S  series-only write, right series      s  series-only write, wrong series
  H  held for review, the right pick      h  held for review, a wrong pick
  N  nothing written
"""
import glob
import json
import os
import re
import sys

books_path, verdict_dir, run_path, out_path = sys.argv[1:5]
books = json.load(open(books_path))
lf = {r["folder"]: r for r in map(json.loads, open(run_path, encoding="utf-8"))}
TOOLS = ["public_gr", "audiosilo", "absqm", "grimmory", "rmab", "bo", "beets"]

verdicts = {}
for path in sorted(glob.glob(os.path.join(verdict_dir, "verdicts_*.txt"))):
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        head, _, note = line.partition("|")
        parts = head.split()
        codes = parts[1:]
        if len(codes) != len(TOOLS) or not set(codes) <= set("CEPWSsHhN"):
            sys.exit(f"{path}: bad line {line!r}")
        verdicts[int(parts[0])] = (codes, note.strip())
missing = [i for i in range(len(books)) if i not in verdicts]
if missing:
    sys.exit(f"no verdict for {len(missing)} books, first {missing[:5]}")


# What went wrong when LibraForge wrote a book (its code is P, E or W), from the audit note.
ISSUES = [
    ("narrator_cleared", r"clears the .{0,40}narrator|narrator ends up empty"),
    ("narrator_field_author", r"narrator field,? (?:which )?holds the author|placeholder \"Misc\" as narrator"),
    ("series", r"dropped|drops (?:the )?(?:number )?\d|without (?:its |a )?number|nameless series|invents (?:a |the )?series"
               r"|taking the title as the number|writes \"#\d+\" from the listing|writes #23|umbrella"),
    ("title", r"title|subtitle"),
    ("author", r"author|publisher"),
]


def issue(code, note):
    if code == "W":
        return "wrong_book"
    if code == "E":
        return "other_recording"
    for name, pattern in ISSUES:
        if re.search(pattern, note):
            return name
    return "other"


out = {}
for i, book in enumerate(books):
    codes, note = verdicts[i]
    row = {"v": dict(zip(TOOLS, codes)), "note": note}
    if codes[0] in "PEW" and (lf.get(book["folder"]) or {}).get("status") == "matched":
        row["lf_issue"] = issue(codes[0], note)
    out[book["folder"]] = row
json.dump(out, open(out_path, "w"), ensure_ascii=False, indent=0)
print(f"{out_path}: {len(out)} books")
