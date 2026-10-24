"""Score benchmark runs against the library's own applied matches.

usage: score.py <books.json> <out.json> name=run.jsonl ... [bo=<bookorbit-library-id>]

Books without a reference ASIN are reported by outcome (applied/held/none),
not scored. bo= reads a BookOrbit library's results through bookorbit.py.

A pick is "correct" when it is the reference ASIN (the library's applied
match), or another listing of the same recording: Audible runtime within 3%
of the file AND a narrator shared with the reference narrator. Anything else
is "wrong". Each is split by whether the tool applied it or held it.
"""
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sample = {b["folder"]: b for b in json.load(open(sys.argv[1]))}
out_path = sys.argv[2]
cache_path = os.path.join(HERE, "data", "audible_cache.json")
cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}


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


def judge(book, asin, applied):
    if not asin:
        return "none"
    if not book["asin"]:  # no applied reference: report the outcome, don't score it
        return "noref" + ("" if applied else "-held")
    same = asin.upper() == book["asin"]
    if not same:
        p = product(asin.upper())
        ref_narr = names(book["final"].get("narrator"))
        narr_ok = not ref_narr or bool(ref_narr & names(p.get("narr")))
        # Same recording as the file (its runtime) or as the reference
        # listing (another ASIN of it, e.g. a US and a UK publisher).
        ref_min = product(book["asin"]).get("min")
        same = bool(p.get("min")) and narr_ok and any(
            m and abs(p["min"] - m) / m <= 0.03 for m in (book["minutes"], ref_min)
        )
    return ("correct" if same else "wrong") + ("" if applied else "-held")


def fields(book, title, author, narrator, series):
    f = book["final"]
    return {"title": norm(title) == norm(f.get("title")),
            "author": bool(names(f.get("author")) & names(author)),
            "narrator": bool(names(f.get("narrator")) & names(narrator)),
            "series": (norm(series) == norm(f.get("series"))) if f.get("series") else None}


results = {}
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
            book = sample.get(folder)
            if not book:
                continue
            asin = (d.get("providerIds") or {}).get("audible")
            narr = ", ".join(n["name"] for n in (d.get("audioMetadata") or {}).get("narrators", []))
            rows[folder] = {"class": judge(book, asin, True), "asin": asin,
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
            rows[it["folder"]] = {
                "class": judge(book, asin, applied), "asin": asin, "score": it.get("score"), "mode": it.get("mode"),
                "status": it.get("status"), "skip": it.get("skip_reason"), "error": it.get("error"),
                "different_edition": bool(it.get("different_edition")),
                "fields": fields(book, m.get("title"), m.get("author"), m.get("narrator"), m.get("series")) if m else None,
            }
    results[name] = rows

json.dump(cache, open(cache_path, "w"), indent=0)
json.dump(results, open(out_path, "w"), indent=1, ensure_ascii=False)

ORDER = ["correct", "correct-held", "wrong", "wrong-held", "none"]
print(f"{'':12}" + "".join(f"{k:>14}" for k in ORDER) + f"{'(of)':>8}" + "  no reference: applied/held/none")
for name, rows in results.items():
    ref = [r for f, r in rows.items() if sample[f]["asin"]]
    noref = [r for f, r in rows.items() if not sample[f]["asin"]]
    c = Counter(r["class"] for r in ref)
    nc = Counter(r["class"] for r in noref)
    print(f"{name:12}" + "".join(f"{c.get(k, 0):>14}" for k in ORDER) + f"{len(ref):>8}"
          + f"  {nc.get('noref', 0)}/{nc.get('noref-held', 0)}/{nc.get('none', 0)}")
    sm = Counter(r["class"] for r in rows.values() if r.get("mode") == "series_only")
    if sm:
        print(f"{'':12}series_only: " + ", ".join(f"{k} {v}" for k, v in sorted(sm.items())))
print()
for name, rows in results.items():
    applied = [r for r in rows.values() if r["class"] == "correct" and r.get("fields")]
    agg = {k: sum(1 for r in applied if r["fields"][k]) for k in ("title", "author", "narrator")}
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
