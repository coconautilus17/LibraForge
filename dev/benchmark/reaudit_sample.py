"""Draw a random sample of books for a second audit, and print a sheet per 25 books to judge.

usage: reaudit_sample.py <sample|validation> <books> <seed> [--manifest manifest.json]

The sample is drawn from the whole dataset with a fixed seed, so it can be drawn again;
"validation" leaves out the books "sample" already took. It is written to the manifest's
audit.reaudit folder as sample.json or validation_sample.json (book indexes), with sheets
<name>_NN.txt: per book its file's tags, the answer, every tool's result and current verdict
(with the field checks), and the hand note.

Each verdict the second audit finds wrong goes on its own line in findings.txt (for "sample")
or validation_findings.txt: `<index> <TOOL> <old code>-><new code> | why (rule|hand)`, "rule"
when a checking rule caused it and was fixed for all books, "hand" when one verdict was.
audit_check.py --write counts those lines into the page's error rates.
"""
import argparse
import json
import os
import random

from bench_data import TOOLS, Benchmark, pick

ap = argparse.ArgumentParser()
ap.add_argument("name", choices=["sample", "validation"])
ap.add_argument("count", type=int)
ap.add_argument("seed", type=int)
ap.add_argument("--manifest", default="manifest.json")
opts = ap.parse_args()
bench = Benchmark(opts.manifest)
books = bench.books
final = json.load(open(bench.file("audit", "final")))
folder_out = bench.file("audit", "reaudit")
os.makedirs(folder_out, exist_ok=True)

taken = set()
if opts.name == "validation":
    taken = set(json.load(open(os.path.join(folder_out, "sample.json"))))
random.seed(opts.seed)
idx = sorted(random.sample([i for i in range(len(books)) if i not in taken], opts.count))
json.dump(idx, open(os.path.join(folder_out, "sample.json" if opts.name == "sample" else "validation_sample.json"), "w"))


def fmt(m, keys=("title", "author", "narrator", "series", "sequence", "asin", "runtime_min")):
    return " | ".join(f"{k[:4]}={str(m.get(k) or '')[:60]}" for k in keys if m.get(k) not in (None, ""))


lf = bench.runs("public_gr")
for sheet in range(0, len(idx), 25):
    out = []
    for i in idx[sheet:sheet + 25]:
        b = books[i]
        f = b["folder"]
        own = (lf.get(f) or {}).get("local") or {}
        ref = (b.get("final") if b.get("asin") else b.get("expect")) or {}
        out.append(f"### {i}  {f}\n  FILE: {fmt(own, ('title', 'author', 'narrator', 'series', 'sequence', 'asin'))} | min={round(b['minutes'])}\n"
                   f"  REF({'conf' if b.get('asin') else 'name'} {b.get('asin') or ''}): {fmt(ref, ('title', 'author', 'narrator', 'series', 'sequence'))}")
        row = final[f]
        for tool, short, _, _ in TOOLS:
            r = bench.runs(tool).get(f) or {}
            if tool == "public_gr":
                m = r.get("match") or {}
                edition = r.get("different_edition")
                state = (f"{r.get('status')} {r.get('mode', '')} {r.get('provider') or ''} "
                         f"ed={'Y:' + str(edition.get('local_narrator')) if edition else 'n'} dur={m.get('duration_minutes')}")
            elif tool == "bo":
                m, state = r, "ids" if (pick(tool, r) or r.get("goodreads")) else "no-id"
            else:
                m, state = r.get("match") or {}, r.get("outcome") or r.get("status") or "missing"
            checks = row["f"].get(tool) or []
            out.append(f"  {short:5} [{row['v'][tool]}{' ' + ','.join(checks) if checks else ''}] ({state}) {fmt(m)}")
        out.append(f"  NOTE: {row['note'][:300]}")
    open(os.path.join(folder_out, f"{opts.name}_{sheet // 25:02}.txt"), "w").write("\n".join(out) + "\n")
print(f"{len(idx)} books drawn (seed {opts.seed}), {(len(idx) + 24) // 25} sheets in {folder_out}")
