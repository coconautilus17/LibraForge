"""Every book's right answer: its confirmed edition, as its own catalog records it.

An edition is confirmed when it was applied to the book (in the library, or in the review
library: the dataset's "asin") or confirmed by hand from a candidate. An Audible edition's
record is read from Audible's public catalog by ASIN, which no market hides: title,
subtitle, every author, every narrator, every series it is listed in with its number, and
runtime. An edition Audible doesn't have (a publisher's own, the community database's, or
none) is the fields the owner confirmed on the review page, with every ID it carries. A
book with no confirmed edition has no right answer: it is reported, not scored.

usage: answers.py records [--manifest manifest.json]
           read the record of every confirmed listing into the manifest's "answers"
       answers.py candidates <out.tsv> [--manifest manifest.json]
           for each book with no confirmed listing, the listings the tools chose, with their
           records beside what the file name states, to confirm by hand
       answers.py reviews <folder of review JSON files> [--manifest manifest.json]
           record the owner's reviews from the review page (saved with ArtifactData's out_dir):
           "correct" or "edited" confirms that edition with its fields, "none" with typed fields
           confirms those fields, "none" without them leaves the book unscored
       answers.py confirm <decisions.tsv> [--manifest manifest.json]
           record the lines "<folder>\t<ASIN>" as confirmed by hand, then read their records;
           "<folder>\t-" removes a confirmed listing found to be another book or recording

The answers file: {folder: {"asin", "source": "applied" | "hand" | "removed", "record": {...} | null,
"fields": {...}}}; "fields" (the owner's own, from a review) makes the record and is kept over a reread.
"""
import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request

from bench_data import TOOL_NAMES, Benchmark, pick

GROUPS = "contributors,series,product_attrs,media"


def fetch(asins):
    """{ASIN: record} for every listing the catalog returns, 50 per request."""
    out = {}
    asins = sorted(set(asins))
    for i in range(0, len(asins), 50):
        batch = asins[i:i + 50]
        url = "https://api.audible.com/1.0/catalog/products?" + urllib.parse.urlencode(
            {"asins": ",".join(batch), "num_results": len(batch), "response_groups": GROUPS})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=60) as r:
                    products = json.load(r).get("products", [])
                break
            except OSError:
                time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit(f"the catalog didn't answer for {batch[0]}..")
        for p in products:
            if not p.get("title"):
                continue  # an ASIN the catalog doesn't list any more comes back empty
            out[p["asin"].upper()] = {
                "asin": p["asin"].upper(),
                "title": p.get("title") or "",
                "subtitle": p.get("subtitle") or "",
                "authors": [a["name"] for a in p.get("authors") or []],
                "narrators": [n["name"] for n in p.get("narrators") or []],
                "series": [[s.get("title") or "", str(s.get("sequence") or "")] for s in p.get("series") or []],
                "minutes": p.get("runtime_length_min"),
            }
        time.sleep(0.6)
    return out


def load(bench):
    name = bench.m.get("answers")
    return json.load(open(bench.file("answers"))) if name and os.path.exists(bench.file("answers")) else {}


def records(bench, answers):
    for b in bench.books:
        asin = (b.get("asin") or "").upper()
        if asin and b["folder"] not in answers:
            answers[b["folder"]] = {"asin": asin, "source": "applied", "record": None}
    got = fetch(a["asin"] for a in answers.values() if a["asin"])
    for a in answers.values():
        a["record"] = from_fields(a["fields"], got.get(a["asin"])) if a.get("fields") else got.get(a["asin"])
    json.dump(answers, open(bench.file("answers"), "w"), ensure_ascii=False, indent=0)
    gone = sorted(f for f, a in answers.items() if not a["record"] and a["asin"])
    print(f"{len(answers) - len(gone)} answers read, {len(gone)} listings the catalog no longer returns -> {bench.file('answers')}")
    for f in gone:
        print("  no record:", answers[f]["asin"], f)


def from_fields(fields, listing=None):
    """A record from the owner's fields (a review): its title, people, "Name #N; Other #M" series and IDs;
    the runtime is the Audible listing's when the fields name one."""
    people = lambda x: [p.strip() for p in str(x or "").split(",") if p.strip()]
    series = []
    for part in str(fields.get("series") or "").split(";"):
        m = re.fullmatch(r"\s*(.*?)\s*(?:#\s*([\d.\-]+))?\s*", part)
        if m and (m.group(1) or m.group(2)):
            series.append([m.group(1), m.group(2) or ""])
    asin = str(fields.get("asin") or "").strip().upper()
    return {"asin": asin if re.fullmatch(r"[A-Z0-9]{10}", asin) else "", "title": fields.get("title") or "",
            "subtitle": fields.get("subtitle") or "", "authors": people(fields.get("authors")),
            "narrators": people(fields.get("narrators")), "series": series,
            "minutes": (listing or {}).get("minutes"), "ids": fields.get("ids") or []}


def reviews(bench, answers, folder):
    """The owner's review-page decisions as answers."""
    n = {}
    for root, _, files in os.walk(folder):
        for name in files:
            if not name.endswith(".json"):
                continue
            doc = json.load(open(os.path.join(root, name), encoding="utf-8"))
            doc = doc.get("data", doc)  # a saved document's fields, or the fields themselves
            f, status = doc.get("folder"), doc.get("status")
            if f not in bench.by_folder or status not in ("correct", "edited", "none"):
                continue
            fields = dict(doc.get("fields") or {})
            pick, asin = doc.get("pick") or "", (fields.get("asin") or "").strip().upper()
            if status == "none" and not fields.get("title"):
                answers.pop(f, None) if (answers.get(f) or {}).get("source") == "hand" else None
                n["left unscored"] = n.get("left unscored", 0) + 1
                continue
            # The edition chosen keeps its ID unless the owner replaced the ASIN with another.
            keep = status != "none" and pick and not pick.startswith("fields:") and "asin" not in (doc.get("changed") or [])
            ids = {pick} if keep else set()
            if re.fullmatch(r"[A-Z0-9]{10}", asin):
                ids.add(asin)
            if status == "correct" and re.fullmatch(r"[A-Z0-9]{10}", pick):
                answers[f] = {"asin": pick, "source": "hand", "record": None}  # as Audible lists it
            else:
                answers[f] = {"asin": asin if re.fullmatch(r"[A-Z0-9]{10}", asin) else "", "source": "hand",
                              "record": None, "fields": {**fields, "ids": sorted(ids)}}
            n[status] = n.get(status, 0) + 1
    print("reviews:", n)


def words(x):
    return set(re.findall(r"[a-z0-9]+", str(x or "").lower()))


def candidates(bench, answers, out_path):
    """Per book with no confirmed listing: what its file name states, and each listing a tool chose."""
    open_books = [b for b in bench.books if not (answers.get(b["folder"]) or {}).get("record")
                  and (answers.get(b["folder"]) or {}).get("source") != "removed"]
    picks = {}
    for tool in TOOL_NAMES:
        runs = bench.runs(tool)
        for b in open_books:
            asin = pick(tool, runs.get(b["folder"]))
            if re.fullmatch(r"[A-Z0-9]{10}", asin or ""):
                picks.setdefault(b["folder"], {}).setdefault(asin, []).append(tool)
    got = fetch(a for p in picks.values() for a in p)
    with open(out_path, "w", encoding="utf-8") as out:
        out.write("folder\tminutes\tfile name says\tasin\ttools\tagrees\trecord\n")
        for b in open_books:
            said = b.get("expect") or b.get("final") or {}
            for asin, tools in sorted((picks.get(b["folder"]) or {}).items(), key=lambda kv: -len(kv[1])):
                r = got.get(asin)
                if not r:
                    continue
                # A hint only: confirming is a hand decision.
                agrees = []
                if words(said.get("author")) & words(" ".join(r["authors"])):
                    agrees.append("author")
                if said.get("sequence") and any(s[1] == str(said["sequence"]).lstrip("0") or s[1] == said["sequence"] for s in r["series"]):
                    agrees.append("number")
                if said.get("title") and words(said["title"]) <= words(r["title"] + " " + r["subtitle"]):
                    agrees.append("title")
                if r["minutes"] and abs(r["minutes"] - b["minutes"]) <= max(3, 0.03 * b["minutes"]):
                    agrees.append("runtime")
                out.write("\t".join([b["folder"], f"{b['minutes']:.0f}",
                                     f"{said.get('author', '')} | {said.get('series', '')} #{said.get('sequence', '')} | {said.get('title', '')}",
                                     asin, ",".join(tools), ",".join(agrees),
                                     f"{', '.join(r['authors'])} | {'; '.join(f'{s} #{n}' for s, n in r['series'])} | {r['title']}"
                                     f"{': ' + r['subtitle'] if r['subtitle'] else ''} | {', '.join(r['narrators'])} | {r['minutes']} min"]) + "\n")
    print(f"{len(open_books)} books with no confirmed listing, {len(picks)} with a candidate -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["records", "candidates", "confirm", "reviews"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--manifest", default="manifest.json")
    opts = ap.parse_args()
    bench = Benchmark(opts.manifest, answers=False)
    answers = load(bench)
    if opts.step == "records":
        records(bench, answers)
    elif opts.step == "candidates":
        candidates(bench, answers, opts.file)
    elif opts.step == "reviews":
        reviews(bench, answers, opts.file)
        records(bench, answers)
    else:
        for line in open(opts.file, encoding="utf-8"):
            folder, asin = line.rstrip("\n").split("\t")[:2]
            if folder in bench.by_folder:
                asin = asin.strip().upper()
                answers[folder] = {"asin": "", "source": "removed", "record": None} if asin == "-" else \
                    {"asin": asin, "source": "hand", "record": None}
        records(bench, answers)
