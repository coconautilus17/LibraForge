"""Score benchmark runs against the library's own applied matches.

usage: score.py <books.json> <out.json> name=run.jsonl ... [bo=<bookorbit-library-id>] [moved=<older dataset>]

Books without a reference ASIN are reported by outcome (applied/held/none),
not scored, unless collect.py --import gave them a file-name reference
("expect"): then a pick is correct when it is that book, by the same author
with the same series and number or the same title, whatever the recording.
bo= reads a BookOrbit library's results through bookorbit.py.

A run's total runtime is read from <run>.time (seconds, written by run.sh and
the other runners) or data/<name>.time, and saved under "_runtime".

A pick is "correct" when it is the reference ASIN (the library's applied
match), or another listing of the same recording: Audible runtime within 3%
of the file AND a narrator shared with the reference narrator. Anything else
is "wrong". Each is split by whether the tool applied it or held it.
A Goodreads pick (LibraForge's fallback) has no Audible listing, so it is correct
when it is the reference's book, by the same rule as a file-name reference.

Runs in a LibraForge image (it reuses the fixer's placeholder author list), e.g.
  docker run --rm --entrypoint /opt/venv/bin/python -v "$PWD/app:/app/app:ro" \
    -v "$PWD/dev/benchmark:/bench" -w /bench libraforge-libraforge score.py ...
"""
import json
import os
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
import urllib.request
from collections import Counter

sys.path.insert(0, "/app")
from app.fixer.parsing import _other_person_same_surname, normalize_for_match  # noqa: E402
from app.fixer.scoring import GENERIC_AUTHORS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sample = {b["folder"]: b for b in json.load(open(sys.argv[1]))}
out_path = sys.argv[2]
cache_path = os.path.join(HERE, "data", "audible_cache.json")
cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
unlisted_correct = [0]  # the current run's correct picks judged by the tool's own runtime


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def names(s):
    return {norm(n) for n in re.split(r",|&|;|/| and ", s or "") if norm(n)}


def product(asin):
    if asin not in cache:
        url = (f"https://api.audible.com/1.0/catalog/products/{asin}"
               "?response_groups=product_attrs,contributors")
        try:
            p = json.load(urllib.request.urlopen(url, timeout=20)).get("product", {})
            cache[asin] = {"min": p.get("runtime_length_min"),
                           "narr": ", ".join(n["name"] for n in p.get("narrators") or [])}
        except Exception as exc:
            cache[asin] = {"error": str(exc)}
        time.sleep(0.2)
    return cache[asin]


def number(s):
    return re.sub(r"(^|-)0+(?=\d)", r"\1", re.sub(r"\s", "", str(s or "")))


def fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def same_author(want, got):
    """Any shared author: by squashed name ("pirate aba" = "pirateaba"), by surname
    ("G. D. Penman" = "Graeme Penman"), or by a near spelling ("Atamonov")."""
    for w in names(fold(want)):
        for g in names(fold(got)):
            if (w.replace(" ", "") == g.replace(" ", "")
                    or (w.split()[-1] == g.split()[-1] and not _other_person_same_surname(w, g))
                    or SequenceMatcher(None, w, g).ratio() >= 0.85):
                return True
    return False


def same_book(expect, pick, folder="", minutes=0, own_numbering=False):
    """Is the pick the book a file-name reference names (any recording)?

    own_numbering: the pick's catalog numbers series its own way (Goodreads counts
    novellas Audible doesn't), so the same title by the same author is the book
    even when the numbers differ."""
    # The folder's author (the file name's first part) counts as well as the tag's;
    # a placeholder ("Misc", "Various") names no author.
    authors = [a for a in (expect["author"], folder.split("/")[0])
               if a and normalize_for_match(a) not in GENERIC_AUTHORS]
    if authors and not any(same_author(a, pick.get("author")) for a in authors):
        return False
    want, got = number(expect["sequence"]), number(pick.get("sequence"))
    a, b = norm(expect["series"]), norm(pick.get("series"))
    if "-" in want:  # "Book 01-03": an omnibus, whose listing rarely numbers it; its runtime decides
        listed = product(pick["asin"]).get("min") if pick.get("asin") else None
        if listed and minutes:
            return abs(listed - minutes) / minutes <= 0.03
        # No runtime to compare (a Goodreads pick): the listing names the same range.
        lo, hi = want.split("-", 1)
        named = f"{pick.get('title') or ''} {pick.get('subtitle') or ''}"
        return bool(re.search(rf"(?<!\d)0*{lo}\s*(?:-|–|to|through|&)\s*0*{hi}(?!\d)", named, re.I))
    if want and got and want != got and not (own_numbering and expect["title"]
                                              and norm(expect["title"]) == norm(pick.get("title"))):
        return False
    if want and want == got and a and b and (a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.8):
        return True
    # A first book with no title is named by its series ("Warbreaker; Book 01").
    t = norm(expect["title"] or (expect["series"] if want in ("", "1") else ""))
    p = norm(pick.get("title"))
    if not expect["title"] and set(re.findall(r"\d+", p)) - {"1", *re.findall(r"\d+", norm(expect["series"]))}:  # "Big Sneaky Barbarian 3" is not book 1
        return False
    if not (t and p):
        return False
    # With no author to check, the pick's title must start with the name, not just hold it.
    held = f"{p} ".startswith(f"{t} ") if not authors else f" {t} " in f" {p} " or f" {p} " in f" {t} "
    return held or SequenceMatcher(None, t, p).ratio() >= 0.9


def judge(book, asin, applied, pick=None, goodreads=False):
    # A book reviewed by hand (curated=): its verdict holds for every tool that picked
    # the same listing (an ASIN) or, for a Goodreads pick, the same title.
    cur = curation.get(book["folder"]) or {}
    if asin and asin.upper() in {a.upper() for a in cur.get("reject", [])}:
        return "wrong" + ("" if applied else "-held")
    if ((asin and asin.upper() in {a.upper() for a in cur.get("accept", [])})
            or (pick and norm(pick.get("title")) in {norm(t) for t in cur.get("titles", [])})):
        return "correct" + ("" if applied else "-held")
    if goodreads and pick and asin and book["asin"] and asin.upper() == book["asin"]:
        # It applied the book's own listing; a Goodreads title is a field to check, not the book.
        return "correct" + ("" if applied else "-held")
    if goodreads and pick:
        # Goodreads has no Audible listing or runtime (its id may be an ISBN): the
        # pick is judged as the book, by the reference's own title/author/series.
        ref = book["final"] if book["asin"] else book.get("expect")
        if not ref:
            return "noref" + ("" if applied else "-held")
        return ("correct" if same_book(ref, pick, book["folder"], book["minutes"], own_numbering=True) else "wrong") + ("" if applied else "-held")
    if not asin:
        return "none"
    if not book["asin"]:
        if book.get("expect") and pick:
            return ("correct" if same_book(book["expect"], pick, book["folder"], book["minutes"]) else "wrong") + ("" if applied else "-held")
        return "noref" + ("" if applied else "-held")  # no reference: report the outcome, don't score it
    same = asin.upper() == book["asin"]
    if not same:
        p = product(asin.upper())
        if not p.get("min") and pick and pick.get("runtime_min"):
            # Audible has no listing for it (AudioSilo's community data can hold an
            # ASIN the US store doesn't return): the tool's own runtime and
            # narrator for the recording stand in, and the row says so.
            p = {"min": pick["runtime_min"], "narr": pick.get("narrator") or "", "unlisted": True}
        ref_narr = names(book["final"].get("narrator"))
        narr_ok = not ref_narr or bool(ref_narr & names(p.get("narr")))
        # Same recording as the file (its runtime) or as the reference
        # listing (another ASIN of it, e.g. a US and a UK publisher).
        ref_min = product(book["asin"]).get("min")
        same = bool(p.get("min")) and narr_ok and any(
            m and abs(p["min"] - m) / m <= 0.03 for m in (book["minutes"], ref_min)
        )
    if same and not asin.upper() == book["asin"] and p.get("unlisted"):
        unlisted_correct[0] += 1
    if not same and pick:
        # Another recording of the same book (a US and a UK narration, a re-recording)
        # is the right match too: no tool can tell which narration a file is from its
        # tags. Not a translation, and not an abridgement, excerpt or omnibus.
        same = same_book(book["final"], pick, book["folder"], book["minutes"]) and same_content(book, asin, pick)
    return ("correct" if same else "wrong") + ("" if applied else "-held")


_TRANSLATION = re.compile(r"\((?:german|spanish|french|italian|danish|dutch|polish|portuguese|swedish)\s+edition\)", re.I)


def same_content(book, asin, pick):
    """The pick is the whole book in the file's language: not a translation, and
    between half and one and a half times the file's runtime."""
    if _TRANSLATION.search(f"{pick.get('title') or ''} {pick.get('subtitle') or ''}"):
        return False
    listed = product(asin.upper()).get("min") or pick.get("runtime_min")
    return not (listed and book["minutes"]) or 0.5 <= listed / book["minutes"] <= 1.5


def same_series(book, pick):
    """A series-only match writes only the series: right when it is the book's series,
    or the series the file already carried (kept, not overwritten)."""
    ref = book["final"] if book["asin"] else book.get("expect") or {}
    b = norm(pick.get("series"))
    return bool(b) and any(a and (a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.8)
                           for a in (norm(ref.get("series")), norm(book["tags"].get("series"))))


def fields(book, title, author, narrator, series):
    f = book["final"]
    return {"title": norm(title) == norm(f.get("title")),
            "author": bool(names(f.get("author")) & names(author)),
            "narrator": bool(names(f.get("narrator")) & names(narrator)) if f.get("narrator") else None,
            # None: no reference series, or the tool doesn't report one (ReadMeABook)
            "series": (norm(series) == norm(f.get("series"))) if f.get("series") and series is not None else None}


def identity(b):
    return json.dumps([b["tags"], round(b["minutes"], 3)], sort_keys=True)


# moved=<older dataset>: a tool that ran on an older copy of the library (before
# Folder Forge moved books out of _unorganized) reports the old folders; the same
# original tags and runtime find each book's folder now.
moved = {}
for arg in [a for a in sys.argv[3:] if a.startswith("moved=")]:
    now = {identity(b): f for f, b in sample.items()}
    moved = {b["folder"]: now[identity(b)] for b in json.load(open(arg.split("=", 1)[1]))
             if b["folder"] not in sample and identity(b) in now}
    sys.argv.remove(arg)

# curated=<file>: {folder: {"verdict", "note", "accept": [ASIN], "titles": [title], "reject": [ASIN]}},
# books reviewed one by one where the rules above misjudge them (a wrong library answer,
# a book Audible names by its subtitle, a publisher in the author's place).
curation = {}
for arg in [a for a in sys.argv[3:] if a.startswith("curated=")]:
    curation = json.load(open(arg.split("=", 1)[1]))
    sys.argv.remove(arg)

results, runtime = {}, {}
for arg in sys.argv[3:]:
    name, src = arg.split("=", 1)
    rows = {}
    if name == "bo":
        sys.path.insert(0, HERE)
        import bookorbit as bo  # noqa: E402
        tok = bo.login()
        page, items = 0, []  # BookQuery: 0-based page, size per page
        while True:
            st, r = bo.call("POST", f"/libraries/{src}/books", {"pagination": {"page": page, "size": 100}}, tok)
            items += r["items"]
            if len(items) >= r["total"] or not r["items"]:
                break
            page += 1
        for b in items:
            st, d = bo.call("GET", f"/books/{b['id']}", None, tok)
            folder = re.sub(r"^/[^/]+-books/", "", d["folderPath"])
            folder = moved.get(folder, folder)
            book = sample.get(folder)
            if not book:
                continue
            asin = (d.get("providerIds") or {}).get("audible")
            narr = ", ".join(n["name"] for n in (d.get("audioMetadata") or {}).get("narrators", []))
            pick = {"asin": asin, "title": d.get("title"), "author": ", ".join(a["name"] for a in d.get("authors", [])),
                    "series": d.get("seriesName"), "sequence": d.get("seriesIndex")}
            rows[folder] = {"class": judge(book, asin, True, pick), "asin": asin,
                            "goodreads": bool((d.get("providerIds") or {}).get("goodreads")),
                            "fields": fields(book, d.get("title"), ", ".join(a["name"] for a in d.get("authors", [])),
                                             narr, d.get("seriesName")) if asin else None}
    else:
        for line in open(src, encoding="utf-8"):
            it = json.loads(line)
            book = sample.get(it["folder"])
            if not book:
                continue
            m = it.get("match") or {}
            applied = it.get("status") == "matched"
            asin = (it.get("series_match_asin") or m.get("asin")
                    or (it.get("different_edition") or {}).get("match_asin"))
            if not applied and "below minimum" in (it.get("skip_reason") or ""):
                # Refused, not held: the row only carries the closest candidate it
                # turned down, which nobody is offered.
                asin = None
            if it.get("mode") == "series_only" and asin:
                cls = ("correct" if same_series(book, m) else "wrong") + ("" if applied else "-held")
            else:
                # A Goodreads or Audiobook Guild pick has no Audible listing of its own
                # (a guild match keeps the file's ASIN): it is judged as the book.
                cls = judge(book, asin, applied, m, it.get("provider") in {"goodreads", "audiobookguild"})
            rows[it["folder"]] = {
                "class": cls,
                "asin": asin,
                "goodreads": it.get("provider") == "goodreads", "score": it.get("score"), "mode": it.get("mode"),
                "status": it.get("status"), "skip": it.get("skip_reason"), "error": it.get("error"),
                "different_edition": bool(it.get("different_edition")),
                "fields": fields(book, m.get("title"), m.get("author"), m.get("narrator"), m.get("series")) if m else None,
            }
    # A book the tool left no result for is a book it didn't match, so every row
    # adds up to the whole dataset.
    for folder in sample.keys() - rows.keys():
        rows[folder] = {"class": "none", "asin": None, "missing": True, "fields": None}
    for folder in rows.keys() & curation.keys():
        rows[folder]["curated"] = curation[folder].get("note") or " ".join(curation[folder].get("others", []))
    results[name] = rows
    if unlisted_correct[0]:
        print(f"{name}: {unlisted_correct[0]} correct picks have an ASIN Audible's US store doesn't list (judged by the tool's own runtime and narrator)")
    unlisted_correct[0] = 0
    for path in (re.sub(r"\.jsonl$", ".time", src), os.path.join(HERE, "data", f"{name}.time")):
        if path.endswith(".time") and os.path.exists(path):
            runtime[name] = float(open(path).read().split()[0])
            break

json.dump(cache, open(cache_path, "w"), indent=0)
json.dump({**results, "_runtime": runtime}, open(out_path, "w"), indent=1, ensure_ascii=False)

ORDER = ["correct", "correct-held", "wrong", "wrong-held", "none"]
print(f"{'':12}" + "".join(f"{k:>14}" for k in ORDER) + f"{'(of)':>8}" + "  no reference: applied/held/none")
for name, rows in results.items():
    ref = [r for f, r in rows.items() if sample[f]["asin"] or sample[f].get("expect")]
    noref = [r for f, r in rows.items() if not sample[f]["asin"] and not sample[f].get("expect")]
    c = Counter(r["class"] for r in ref)
    nc = Counter(r["class"] for r in noref)
    took = f"  ({runtime[name] / 60:.0f} min)" if name in runtime else ""
    print(f"{name:12}" + "".join(f"{c.get(k, 0):>14}" for k in ORDER) + f"{len(ref):>8}"
          + f"  {nc.get('noref', 0)}/{nc.get('noref-held', 0)}/{nc.get('none', 0)}{took}")
    sm = Counter(r["class"] for r in rows.values() if r.get("mode") == "series_only")
    if sm:
        print(f"{'':12}series_only: " + ", ".join(f"{k} {v}" for k, v in sorted(sm.items())))
print()
for name, rows in results.items():
    applied = [r for r in rows.values() if r["class"] == "correct" and r.get("fields")]
    agg = {k: sum(1 for r in applied if r["fields"][k]) for k in ("title", "author", "narrator")}
    agg["narrator"] = f"{agg['narrator']}/{sum(1 for r in applied if r['fields']['narrator'] is not None)}"
    ser = [r for r in applied if r["fields"]["series"] is not None]
    print(f"{name:12} fields on correct applied ({len(applied)}): title {agg['title']}, author {agg['author']}, "
          f"narrator {agg['narrator']}, series {sum(1 for r in ser if r['fields']['series'])}/{len(ser)}")

if "bo" in results:
    for has in (True, False):
        sub = {f: r for f, r in results["bo"].items() if r.get("goodreads") is has}
        c = Counter(r["class"] for r in sub.values())
        print(f"bo goodreads={'yes' if has else 'no ':3} ({len(sub)}): " + ", ".join(f"{k} {c.get(k, 0)}" for k in ORDER))
        for name in results:
            if name != "bo":
                c2 = Counter(results[name][f]["class"] for f in sub if f in results[name])
                print(f"   same books, {name:10}: " + ", ".join(f"{k} {c2.get(k, 0)}" for k in ORDER))
