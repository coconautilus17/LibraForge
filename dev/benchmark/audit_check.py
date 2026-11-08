"""The final verdicts: which book each tool chose, and every field it left on the book.

usage: audit_check.py [--manifest manifest.json] [--write] [--judge to_judge.tsv]

Which book a choice is comes from one place per book and listing:
  - the confirmed listing's own ASIN is the right book, by rule;
  - any other listing is what the hand audit judged it, on whichever tool chose it (the
    manifest's audit.hand, with audit.judged_runs naming the run a verdict was made on when
    a tool's current run is newer), or what audit.extra says ("<folder>\\t<listing>\\t
    right|other|wrong", other = another recording of the right book).
A choice nobody judged yet is listed in --judge for the hand audit and gets "?".

What a tool left on the book is rebuilt by its own way of writing (bench_data.result) and
checked against the right answer, the listing's own record, by the same rules for every
tool. So two tools that leave a book with the same listing and the same fields always get
the same verdict; the run fails if they don't.

Verdicts: C right book, every field right; P right book, a field wrong or missing; E another
recording; W wrong book; S/s series-only write into the right/wrong series (LibraForge);
H/h held with a right/wrong pick; N nothing written; U no right answer (reported, not scored).
--write saves them to the manifest's audit.final, which the page shows.
"""
import argparse
import json
import os
import re
import unicodedata
import difflib
from collections import Counter, defaultdict

from bench_data import FIELDS, TOOL_NAMES as TOOLS, Benchmark, choice, pick, result, rows_of

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", default="manifest.json")
ap.add_argument("--write", action="store_true", help="write the final verdicts")
ap.add_argument("--judge", default="", help="write the choices nobody judged yet to this file")
opts = ap.parse_args()
bench = Benchmark(opts.manifest)
audit_spec = bench.m["audit"]
hand = json.load(open(bench.file("audit", "hand")))
runs = {tool: bench.runs(tool) for tool in TOOLS}


def norm(x):
    x = unicodedata.normalize("NFKD", str(x or "").replace("’", "'")).encode("ascii", "ignore").decode().replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()


ROLE = re.compile(r"\s*[-–—]\s*(translator|introduction|foreword|illustrator|adaptor|editor|afterword|preface)\b.*$"
                  r"|\s*\((aka|translator|editor)[^)]*\)", re.I)
PLACEHOLDER = {"misc", "unknown", "various", "various artists", "audiobook", "full cast", "uncredited", "unknown author",
               "virtual voice", "blackstone audio", "soundbooth theater", "actors everywhere"}
# Store categories, not series a tag should carry.
CATEGORY = re.compile(r"^(litrpg|gamelit|the great courses\b.*|audible original stories|audible originals)$")
STOP = {"the", "a", "an", "of", "and", "book", "books", "in", "to", "on", "for", "series", "vol", "volume", "part",
        "saga", "trilogy", "novel", "edition"}
# Words that mark a listing's title segment as a tagline rather than the book's own name.
TAGLINE = {"novel", "novella", "adventure", "litrpg", "gamelit", "fantasy", "epic", "saga", "series", "book", "books",
           "volume", "vol", "part", "thriller", "story", "stories", "collection", "edition", "dramatized", "dramatised",
           "adaptation", "original", "drama", "introduction", "guide", "memoir", "cultivation", "progression", "harem",
           "isekai", "slice", "narrated", "unabridged", "box", "set", "omnibus", "pack", "publisher", "romance",
           "mystery", "comedy", "bbc", "radio", "production", "short", "classic", "anthology"}
TITLE_JUNK = re.compile(r"\(unabridged\)|\bunabridged\b|\b(book|bk)\.?\s*#?\s*0\d|\s-\s+[A-Z][a-z]+ [A-Z][a-z]+$", re.I)


def people(x):
    """The credited people, without roles (a translator or an introduction writer is not an author)."""
    parts = re.split(r",|;|&| and ", str(x or ""))
    return [p for p in (norm(re.sub(r"\([^)]*\)", " ", ROLE.sub("", n))) for n in parts
                        if not re.search(r"\b(translator|introduction|foreword|preface|editor|adaptor)\b", n, re.I))
            if p and p not in ("translator", "editor", "phd")]


def surname(name):
    words = [w for w in name.split() if len(w) > 1 and w not in ("jr", "sr", "phd", "md", "dr", "ii", "iii")]
    return words[-1] if words else name


def words(x):
    """Comparable words: plurals and leading zeros folded ("Plays"/"play", "01"/"1")."""
    return {w.lstrip("0") or "0" if w.isdigit() else w.rstrip("s") for w in norm(x).split() if w not in STOP}


def one_edit(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def same_name(a, b):
    """One person's surname, allowing a one-letter slip ("Bouche"/"Boucher", "Neal"/"Neil")."""
    return a == b or min(len(a), len(b)) >= 4 and one_edit(a, b)


def among(name, names):
    return any(same_name(name, n) for n in names)


def same_number(a, b):
    a, b = norm(a).replace(" ", "."), norm(b).replace(" ", ".")
    try:
        return float(a) == float(b)
    except ValueError:
        return a.replace(".", "") == b.replace(".", "")


def same_series_name(written, listed):
    """The listing's series, also with a prefix or suffix ("VeilVerse: Cultivating Chaos", "... Spinoff");
    a listing's own qualifier ("[chronological order]", "(radio plays)", ": A ... LitRPG Series") need not
    be written. A number stuck on the name ("042 - Spellmonger") is not the series."""
    plain = re.sub(r"\[[^]]*\]|\([^)]*\)", " ", listed)
    cores = [c for c in (words(plain), words(plain.split(":")[0])) if c] or [words(listed)]
    got = words(written)
    return any(c <= got and not any(w.isdigit() for w in got - c) for c in cores)


# "Series #3" or "Series, Book #3" in a series tag: the convention for a number inside the series text.
SERIES_NUMBER = re.compile(r",?\s*(?:book\s*)?#\s*(\d+(?:\.\d+)?(?:\s*-\s*\d+)?)\s*$", re.I)
NOT_A_PERSON = re.compile(r"\b(press|publishing|llc|studios?|audio|books)\b")


def title_options(answer):
    """The word sets a written title must cover: the listing's title proper, without its tagline segments
    ("A LitRPG Adventure", "Series, Book 3") or the series name it may lead with, and the series-name head
    itself; a listing titled only with its series name also offers its subtitle."""
    names = [n for n, _ in answer["series"]]
    segs = [g.strip(" )") for g in re.split(r":| - |\(", answer["title"]) if g.strip(" )")]
    nums = {n for _, n in answer["series"]}

    def is_series(seg):
        return any(words(n) and words(n) <= words(seg) and all(re.fullmatch(r"[\divxlc.]+", w) for w in words(seg) - words(n))
                   for n in names)

    def is_tag(seg):
        return bool(set(norm(seg).split()) & TAGLINE) or is_series(seg)

    core = [g for i, g in enumerate(segs) if not is_series(g) and not any(is_tag(h) for h in segs[1:i + 1])]
    options = [words(" ".join(core))] if core else []
    if core and len(words(core[0])) >= 3:
        options.append(words(core[0]))  # a long first segment is the title; what follows a subtitle
    if segs and is_series(segs[0]) and (not core or words(segs[0]) - {w for n in names for w in words(n)}):
        options.append(words(segs[0]))  # "Battle Mage 5", not the bare series name for "DEAD: Fortunes & Failures"
        if len(segs) == 1 and answer["subtitle"] and not is_tag(answer["subtitle"]):
            options.append(words(re.split(r":|\(", answer["subtitle"])[0]))
    return [o - nums for o in options or [words(answer["title"])]]


def field_problems(res, answer, file, folder_series=""):
    """Each field the book ends up with that the listing's record doesn't support. file: the book's own tags."""
    out = []
    title = res["title"]
    allowed = words(answer["title"]) | words(answer["subtitle"]) | {w for s, _ in answer["series"] for w in words(s)} \
        | {w for _, n in answer["series"] for w in norm(n).split()}
    options = title_options(answer)
    suffix = re.search(r"\(([^)]*)\)\s*$", title or "")
    if not title:
        out.append("title_missing")
    elif TITLE_JUNK.search(title) and not TITLE_JUNK.search(answer["title"]) or title.count("(") != title.count(")") \
            or suffix and (set(norm(suffix.group(1)).split()) & {"series"} or any(same_series_name(SERIES_NUMBER.sub("", suffix.group(1)), n) for n, _ in answer["series"])) \
            and suffix.group(0) not in answer["title"]:
        out.append("title_wrong")  # file-name noise, "(Unabridged)", or the series tacked on
    elif not any(o <= words(title) for o in options):
        out.append("title_wrong")
    # Nothing the listing doesn't say, except a subtitle after a colon (another listing of the book words it its own way).
    elif not words(title) - TAGLINE <= allowed and not (":" in title and any(o <= words(title.split(":")[0]) for o in options)):
        out.append("title_wrong")
    names = people(res["author"])
    want = {surname(p) for p in people(answer["author"]) if not NOT_A_PERSON.search(p)} - {"courses"}
    got = {surname(p) for p in names if not NOT_A_PERSON.search(p)} - {"courses"}
    if not names:
        out.append("author_missing")
    elif len(names) != len(set(names)):
        out.append("author_doubled")
    elif want and any(not among(g, want) for g in got):
        out.append("author_wrong")
    elif any(not among(w, got) for w in want):
        out.append("author_missing")
    # A narrator the listing doesn't credit is wrong; a cast listed in part is not.
    want_n = {surname(p) for p in people(answer["narrator"]) if p not in PLACEHOLDER}
    got_n = {surname(p) for p in people(res["narrator"]) if p not in PLACEHOLDER}
    if want_n:
        if not got_n:
            out.append("narrator_missing")
        elif any(not among(g, want_n) for g in got_n):
            out.append("narrator_wrong")
    series, number = res["series"], str(res["sequence"] or "").strip()
    inside = SERIES_NUMBER.search(series or "")
    if inside:
        series, number = series[:inside.start()].strip(), inside.group(1).replace(" ", "")
    listed = [(s, n) for s, n in answer["series"] if not CATEGORY.match(norm(s))]
    if listed:
        match = [n for s, n in listed if same_series_name(series, s)]
        if not series:
            out.append("series_missing")
        elif not match:
            out.append("series_wrong")
        elif any(match):
            # A range ("1-3") is no single number: leaving the number blank is not missing one.
            if not number and not all(re.search(r"\d\s*-\s*\d", n) for n in match if n):
                out.append("number_missing")
            elif not number:
                pass
            elif not any(same_number(number, n) for n in match if n):
                out.append("number_wrong")
    elif series and words(series) == words(title):
        out.append("series_invented")  # the listing names no series: the title is not one
    elif series and not any(same_series_name(series, n) for n, _ in answer["series"]) \
            and not words(series) <= words(answer["title"]) | words(answer["subtitle"]) \
            | words(SERIES_NUMBER.sub("", file.get("series") or "")) | words(folder_series):
        # The listing names none (or only a store category): a series it, the file or the folder doesn't
        # name is invented.
        out.append("series_wrong")
    if number and not series:
        out.append("number_without_series")
    return out


# Which book each judged listing is, per book: from the hand audit, on the run it judged.
IDENTITY = {"C": "right", "P": "right", "H": "right", "E": "other", "W": "wrong", "h": "wrong"}
judged_runs = {t: rows_of(n) for t, n in (audit_spec.get("judged_runs") or {}).items()}
known = defaultdict(dict)
conflicts = []
for b in bench.books:
    f = b["folder"]
    for tool in TOOLS:
        code = (hand.get(f) or {}).get("v", {}).get(tool)
        row = (judged_runs.get(tool) or runs[tool]).get(f)
        key = choice(tool, {k: ((runs["public_gr"].get(f) or {}).get("local") or {}).get(k) or "" for k in FIELDS}, row)
        if tool == "public_gr" and (row or {}).get("different_edition"):
            continue  # it kept the file's own recording: says nothing about which book that listing is
        if code in IDENTITY and key:
            kind = IDENTITY[code]
            if known[f].get(key, kind) != kind:
                conflicts.append((f, key, tool, known[f][key], kind))
            known[f].setdefault(key, kind)
settled = {}
extra_path = bench.file("audit", "extra") if audit_spec.get("extra") else ""
if extra_path and os.path.exists(extra_path):
    for line in open(extra_path, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            f, key, kind = line.rstrip("\n").split("\t")[:3]
            known[f][key] = kind  # a later hand judgment settles a conflict too
            settled.setdefault(f, set()).add(key)


def identity(b, key):
    if not key:
        return None
    if key in b["ids"]:
        return "right"
    return known[b["folder"]].get(key)


final, to_judge = {}, []
for b in bench.books:
    f = b["folder"]
    lf = runs["public_gr"].get(f) or {}
    file = {k: (lf.get("local") or {}).get(k) or "" for k in FIELDS}
    row = final[f] = {"v": {}, "f": {}, "note": (hand.get(f) or {}).get("note", "")}
    for tool in TOOLS:
        rec = runs[tool].get(f)
        res, _ = result(tool, file, rec)
        key = choice(tool, file, rec)
        wrote = (rec or {}).get("status") == "matched" if tool == "rmab" else res is not None
        if not b["answer"]:
            row["v"][tool] = "U"
            continue
        kind = identity(b, key)
        if tool == "public_gr" and (rec or {}).get("different_edition") and wrote:
            kind = "right"
        if key and kind is None:
            to_judge.append((f, tool, key, res, b["answer"]))
            row["v"][tool] = "?"
            continue
        if not wrote:
            row["v"][tool] = "N" if not key else "h" if kind == "wrong" else "H"
            continue
        if tool == "public_gr" and (rec or {}).get("different_edition"):
            kind = "right"  # the book's details from another recording, its own narrator and ASIN kept
        if tool == "public_gr" and (rec or {}).get("mode") == "series_only":
            row["v"][tool] = "S" if kind == "right" else "s"
        elif kind == "wrong":
            row["v"][tool] = "W"
        elif kind == "other":
            row["v"][tool] = "E"
        elif tool == "rmab":
            row["v"][tool] = "C"  # it writes nothing; only its pick is checked
        else:
            problems = field_problems(res, b["answer"], file, f.split("/")[-2] if f.count("/") > 1 else "")
            row["v"][tool] = "P" if problems else "C"
            if problems:
                row["f"][tool] = problems

for c in conflicts:
    if c[1] not in settled.get(c[0], ()) and bench.by_folder[c[0]]["answer"]:  # an unscored book needs none
        print("hand audit judged one listing two ways:", *c)
print("final:", {tool: dict(Counter(r["v"][tool] for r in final.values())) for tool in TOOLS})
print(len(to_judge), "choices to judge by hand")
if opts.judge:
    with open(opts.judge, "w", encoding="utf-8") as fh:
        for f, tool, key, res, answer in to_judge:
            fh.write("\t".join([f, key, tool, json.dumps(res, ensure_ascii=False),
                                json.dumps({k: answer[k] for k in ("asin", "title", "author", "narrator", "series", "minutes")},
                                           ensure_ascii=False)]) + "\n")


# The same listing and the same fields on the same book get the same verdict.
broken = 0
for b in bench.books:
    seen = {}
    for tool in TOOLS:
        if tool == "rmab":
            continue
        res, written = result(tool, {k: ((runs["public_gr"].get(b["folder"]) or {}).get("local") or {}).get(k) or "" for k in FIELDS},
                              runs[tool].get(b["folder"]))
        v = final[b["folder"]]["v"][tool]
        if res is None or v in "SsU?":
            continue
        sig = ((written or "").upper(), tuple(norm(res[k]) for k in FIELDS))  # the ASIN it left on the book
        if seen.setdefault(sig, v) != v:
            broken += 1
            print("same result, different verdict:", b["folder"], tool, v, seen[sig])
if broken:
    raise SystemExit(f"{broken} verdicts differ for the same result")


def tally_findings(name, books_in_sample):
    """How many verdicts a second audit found wrong: one 'idx TOOL a->b | why (rule|hand)' per line."""
    path = os.path.join(bench.file("audit", "reaudit"), name)
    if not os.path.exists(path):
        return {}
    lines = [l for l in open(path) if re.match(r"\d+ \w+ \S->\S", l)]
    return {"books": books_in_sample, "verdicts": books_in_sample * len(TOOLS), "wrong": len(lines),
            "rule": sum("(rule" in l for l in lines), "hand": sum("(rule" not in l for l in lines)}


if opts.write:
    if to_judge:
        raise SystemExit("judge every listed choice first (audit.extra), then write")
    reaudit = bench.file("audit", "reaudit")
    meta = {}
    for name, sample in (("reaudit", "sample.json"), ("validation", "validation_sample.json")):
        s = os.path.join(reaudit, sample)
        meta[name] = tally_findings(sample.replace("sample.json", "findings.txt"),
                                    len(json.load(open(s))) if os.path.exists(s) else 0)
    final["_meta"] = meta
    json.dump(final, open(bench.file("audit", "final"), "w"), ensure_ascii=False, indent=0)
    print("wrote", bench.file("audit", "final"))
