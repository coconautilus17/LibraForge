"""Carry the hand audit over to a new LibraForge run: keep the verdict where the result is
unchanged, judge a changed result by rule where the evidence settles it, list the rest.

usage: reaudit_run.py <data dir> <old run.jsonl> <new run.jsonl> <out verdict dir>

The out dir gets a copy of data/audit/verdicts_*.txt with LibraForge's column replaced, plus
changed.tsv (every changed book and how it was settled) and to_review.tsv (by hand).
Identity rules for a changed result, in order:
  matched, full     its ASIN is the confirmed answer                            -> C
                    another tool's hand-judged right pick (C/P/E) is that ASIN  -> that tool's code's identity (C, or E)
  matched, series   the series is the book's own (the answer's or the file's)   -> S
  skipped           nothing written                                             -> N  (H/h only by hand)
The field checks (audit_check.py) then decide C versus P from what was written.
"""
import glob
import json
import os
import re
import shutil
import sys

D, old_path, new_path, out_dir = sys.argv[1:5]
TOOLS = ["public_gr", "audiosilo", "absqm", "grimmory", "rmab", "bo", "beets"]
books = json.load(open(os.path.join(D, "combined_4044.json")))
# The audit the old run was judged in (default the original; e.g. BASE_JSON=audit_final_nov4.json
# BASE_DIR=audit_nov4 to carry a later re-audit forward).
audit = json.load(open(os.path.join(D, os.environ.get("BASE_JSON", "audit.json"))))
old = {r["folder"]: r for r in map(json.loads, open(old_path, encoding="utf-8"))}
new = {r["folder"]: r for r in map(json.loads, open(new_path, encoding="utf-8"))}
others = {t: {r["folder"]: r for r in map(json.loads, open(os.path.join(D, f), encoding="utf-8"))}
          for t, f in [("audiosilo", "audiosilo.jsonl"), ("absqm", "plus_absqm.jsonl"), ("grimmory", "plus_grimmory.jsonl"),
                       ("rmab", "plus_rmab.jsonl"), ("beets", "plus_beets.jsonl")]}


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def key(r):
    m = r.get("match") or {}
    return (r.get("status"), r.get("mode") or "", (m.get("asin") or r.get("series_match_asin") or "").upper(),
            bool(r.get("different_edition")))


def judge(i, b, r):
    """(code, how) or (None, why) for a changed result."""
    m = r.get("match") or {}
    if r.get("status") != "matched":
        return "N", "nothing written"
    ref = (b.get("asin") or "").upper()
    asin = (m.get("asin") or "").upper()
    if r.get("mode") == "series_only":
        want = norm((b.get("final") or b.get("expect") or {}).get("series"))
        own = norm(((r.get("local") or {}).get("series")) or (r.get("clues") or {}).get("series"))
        got = norm(m.get("series"))
        if got and (got == want or (own and got in own)):
            return "S", "series-only, the book's own series"
        return None, f"series-only into {m.get('series')!r}"
    if r.get("different_edition"):
        return None, "kept the file's narrator: another recording"
    if asin and asin == ref:
        return "C", "the confirmed answer's ASIN"
    for tool in TOOLS[1:]:
        code = audit[b["folder"]]["v"].get(tool)
        pick = ((others.get(tool, {}).get(b["folder"]) or {}).get("match") or {}).get("asin", "").upper()
        if code in ("C", "P") and pick and pick == asin:
            return "C", f"{tool}'s hand-judged right pick"
        if code == "E" and pick and pick == asin:
            return "E", f"{tool}'s hand-judged other recording"
    return None, f"new pick {asin} {m.get('title')!r}"


os.makedirs(out_dir, exist_ok=True)
lf_code, changed, review = {}, [], []
for i, b in enumerate(books):
    f = b["folder"]
    o, n = old.get(f) or {}, new.get(f) or {}
    before = audit[f]["v"]["public_gr"]
    if key(o) == key(n):
        lf_code[i] = before
        continue
    code, how = judge(i, b, n)
    changed.append((i, f, before, code or "?", how))
    if code is None:
        review.append((i, f, before, how))
        code = before  # placeholder until reviewed by hand
    lf_code[i] = code

for path in sorted(glob.glob(os.path.join(D, os.environ.get("BASE_DIR", "audit"), "verdicts_*.txt"))):
    lines = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            lines.append(line)
            continue
        head, sep, note = line.partition("|")
        parts = head.split()
        parts[1] = lf_code[int(parts[0])]
        lines.append(" ".join(parts) + (f" | {note.strip()}" if sep else "") + "\n")
    open(os.path.join(out_dir, os.path.basename(path)), "w", encoding="utf-8").writelines(lines)
with open(os.path.join(out_dir, "changed.tsv"), "w", encoding="utf-8") as fh:
    for row in changed:
        fh.write("\t".join(map(str, row)) + "\n")
with open(os.path.join(out_dir, "to_review.tsv"), "w", encoding="utf-8") as fh:
    for row in review:
        fh.write("\t".join(map(str, row)) + "\n")
print(f"{len(books)} books: {len(books) - len(changed)} unchanged, {len(changed)} changed, "
      f"{len(changed) - len(review)} settled by rule, {len(review)} to review by hand")
