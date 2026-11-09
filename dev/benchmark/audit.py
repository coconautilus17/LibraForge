"""Turn the hand-audit verdict files into the hand verdicts audit_check.py reads.

usage: audit.py [--manifest manifest.json]

Reads every verdicts_*.txt in the manifest's audit.verdicts folder and writes audit.hand.
Each verdict file line is `<book index> LF AS ABS GRM RMAB BO BEETS | note`, the index being
the book's position in the dataset, one code per tool:

  C  correct: the book ends up with the right details
  E  the right book, but another recording's details (narrator, runtime) were written
  P  the right book, with a field damaged (title, series, narrator, author)
  W  the wrong book
  S  series-only write, right series      s  series-only write, wrong series
  H  held for review, the right pick      h  held for review, a wrong pick
  N  nothing written

Every book needs a line; a missing book or an unknown code stops it.
"""
import argparse
import glob
import json
import os
import sys

from bench_data import TOOL_NAMES as TOOLS, Benchmark

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", default="manifest.json")
bench = Benchmark(ap.parse_args().manifest)
books = bench.books

verdicts = {}
for path in sorted(glob.glob(os.path.join(bench.file("audit", "verdicts"), "verdicts_*.txt"))):
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

out = {book["folder"]: {"v": dict(zip(TOOLS, verdicts[i][0])), "note": verdicts[i][1]} for i, book in enumerate(books)}
json.dump(out, open(bench.file("audit", "hand"), "w"), ensure_ascii=False, indent=0)
print(f"{bench.file('audit', 'hand')}: {len(out)} books")
