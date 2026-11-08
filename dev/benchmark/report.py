"""Build the standalone comparison page and its downloadable book list.

usage: report.py <out.html> [--manifest manifest.json] [--public] [--mock-url URL]

Everything comes from the manifest (bench_data.py): the dataset, every tool's run, the final
audit verdicts (audit_check.py --write), the geo summary (geo.py) and the LibraForge build.
The page embeds its book list gzipped and needs no server. Beside it, benchmark-books.json
holds the same books for download: each book's tags, the right answer and every tool's
verdict, pick and what it left on the book.

--public  for publishing: list only the tags a matcher reads (bench_data.MATCHING_TAGS)
--mock-url  where the mock files can be downloaded (a link on the page when given)
"""
import argparse
import base64
import datetime
import gzip
import html
import json
import os
import re
import urllib.parse
from collections import Counter

import bench_data
from bench_data import TOOLS as TOOL_ROWS, Benchmark, pick, result

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--manifest", default="manifest.json")
ap.add_argument("--title", default="LibraForge matching benchmark")
ap.add_argument("--public", action="store_true", help="for publishing: list only the tags a matcher reads")
ap.add_argument("--repo", default="coconautilus17/LibraForge", help="GitHub repo for the open-an-issue links")
ap.add_argument("--mock-url", default="", help="where the mock files can be downloaded")
opts = ap.parse_args()
bench = Benchmark(opts.manifest)
opts.run_name = "public_gr"
opts.commit = bench.m.get("commit", "")
audit = json.load(open(bench.file("audit", "final")))
audit_meta = audit.pop("_meta", {})
# Each final verdict (audit_check.py): its class on the page and its words.
VERDICT = {"C": ("correct", "Fully correct"), "S": ("correct", "Series only, the right series"),
           "P": ("partial", "Right book, a field off"), "E": ("recording", "Another recording"),
           "W": ("wrong", "Wrong book"), "s": ("wrong", "Series only, the wrong series"),
           "H": ("held", "Held, right pick"), "h": ("held-wrong", "Held, wrong pick"),
           "N": ("none", "Nothing written"), "U": ("unscored", "Not scored")}
VERDICT_MEANING = {
    "C": "the right book, and every field it ends up with is the listing's", "S": "a series-only write into the book's own series",
    "P": "the right book, with a field wrong or missing", "E": "another recording of the book (another narrator or edition)",
    "W": "the wrong book", "s": "a series-only write into the wrong series", "H": "held for review; the held pick is the right book",
    "h": "held for review; the held pick is the wrong book", "N": "nothing written",
    "U": "not scored: the book has no confirmed edition to check against"}

books = bench.by_folder
runs = bench.runs(opts.run_name)
LABELS = {t: f"{name}, {how}" if t == opts.run_name else name for t, _, name, how in TOOL_ROWS}
LABELS.update({"absqm": "Audiobookshelf Quick Match", "beets": "beets (audible plugin)"})
opts.label = LABELS[opts.run_name]
others = [(t, LABELS[t]) for t in bench_data.TOOL_NAMES if t != opts.run_name]  # [name, label]

# Lines of the matcher's trace that repeat what the page already shows as fields.
_SKIP_BLOCKS = ("FILE:", "FINAL METADATA PREVIEW:")
_CONTAINER_TAGS = {"major_brand", "minor_version", "compatible_brands", "encoder", "creation_time",
                   "handler_name", "vendor_id", "gapless_playback", "itunsmpb", "itunnorm"}


def trace(log):
    out, skipping = [], False
    for line in log or []:
        text = line.replace("/mock/", "")
        stripped = text.strip()
        if stripped in _SKIP_BLOCKS:
            skipping = True  # the heading and its indented lines
            continue
        if skipping and text.startswith("  "):
            continue
        skipping = False
        if re.match(r"^\[\d+/\d+\] Processing:", stripped):
            continue
        out.append(text.rstrip())
    while out and not out[-1].strip():
        out.pop()
    return out


def searches(log):
    """[(kind, query, results)] from the trace."""
    found, pending = [], None
    for line in log or []:
        s = line.strip()
        m = re.match(r"Trying (title\+author query|query|ASIN direct lookup|Graphic Audio source[^:]*): (.*)", s)
        if m:
            kind = {"title+author query": "title + author", "query": "keywords"}.get(m.group(1), m.group(1))
            if kind.startswith("ASIN"):
                kind = "ASIN lookup"
            elif kind.startswith("Graphic Audio"):
                kind = "Graphic Audio"
            pending = [kind, m.group(2), None]
            found.append(pending)
            continue
        m = re.match(r"(?:Results|Graphic Audio results|ASIN lookup): (.*)", s)
        if m and pending is not None and pending[2] is None:
            pending[2] = m.group(1)
    return found


def candidates(log):
    out = []
    for line in log or []:
        m = re.match(r"\s*(?:Graphic Audio )?[Cc]andidate: (.*)", line)
        if m:
            fields = dict(re.findall(r"(\w+)=(.*?)(?= \w+=|$)", m.group(1)))
            out.append(fields)
    return out


# The clues the matcher parsed from the tags and the folder path, in reading order.
_CLUE_LABELS = {"raw_title": "raw title", "title": "title", "author": "author", "credit_names": "credits",
                "narrator": "narrator", "series": "series", "book_number": "book", "book_number_source": "book from",
                "album": "album", "existing_asin": "embedded ASIN", "isbn": "embedded ISBN", "publisher": "publisher",
                "year": "year", "language": "language", "local_duration_minutes": "runtime (min)"}


# --public keeps only the tags a matcher reads. The rest (comments, descriptions, encoder,
# DRM and store fields) say nothing about matching and can say where a file came from.
_MATCHING_TAGS = bench_data.MATCHING_TAGS


def clean_tags(tags):
    out = {}
    for key, value in (tags or {}).items():
        if key.lower() in _CONTAINER_TAGS or value in (None, ""):
            continue
        if opts.public and key.lower() not in _MATCHING_TAGS:
            continue
        text = str(value)
        out[key] = text if len(text) <= 400 else text[:400] + "\u2026"
    return out


# What the field checks found (audit_check.field_problems), in words, and the field each is about.
PROBLEM = {
    "title_missing": "no title", "title_wrong": "a title that isn't the listing's",
    "author_missing": "an author missing", "author_doubled": "the authors doubled",
    "author_wrong": "an author the listing doesn't credit", "narrator_missing": "no narrator",
    "narrator_wrong": "a narrator the listing doesn't credit", "series_missing": "no series",
    "series_wrong": "a series the listing doesn't name", "series_invented": "a series made from the title",
    "number_missing": "no book number", "number_wrong": "the wrong book number",
    "number_without_series": "a book number with no series",
}
FIELD_OF = {"title": "title", "author": "author", "narrator": "narrator", "series": "series", "number": "series"}
SHORT = dict(bench_data.SHORT)


NAMES = {"LF": "LibraForge", "AS": "AudioSilo", "ABS": "Audiobookshelf", "GRM": "Grimmory", "RMAB": "ReadMeABook",
         "BO": "BookOrbit", "BEETS": "beets"}


def readable(note):
    """A note as a reader of the page reads it: tool names in full, no tracker references."""
    note = re.sub(r"\s*\(#\d{3}\)", "", note or "")
    return re.sub(r"\b(LF|AS|ABS|GRM|RMAB|BO|BEETS)\b", lambda m: NAMES[m.group(1)], note)


def answer_view(a):
    """The right answer as the page and the download show it."""
    if not a:
        return None
    return {"asin": a["asin"], "title": a["title"], "subtitle": a["subtitle"], "author": a["author"],
            "narrator": a["narrator"], "series": "; ".join(f"{n} #{q}" if q else n for n, q in a["series"]),
            "minutes": a["minutes"], "ids": [i for i in a["ids"] if i != a["asin"]]}


def series_text(res):
    if not res:
        return ""
    return f"{res['series']} #{res['sequence']}" if res.get("series") and res.get("sequence") else \
        res.get("series") or (f"#{res['sequence']}" if res.get("sequence") else "")


rows, download = [], []
for folder, book in books.items():
    run = runs.get(folder) or {}
    match = run.get("match") or {}
    own = {k: (run.get("local") or {}).get(k) or "" for k in bench_data.FIELDS}
    own_asin = ((run.get("local") or {}).get("asin") or "").upper()
    row_audit = audit.get(folder) or {"v": {}, "f": {}, "note": ""}
    answer = answer_view(book["answer"])
    tools, tools_out = {}, {}
    for t, short, name, _ in TOOL_ROWS:
        rec = bench.runs(t).get(folder)
        code = row_audit["v"].get(t, "")
        problems = (row_audit.get("f") or {}).get(t, [])
        res, written = result(t, own, rec)
        if t == "rmab":
            res = None  # it writes nothing; only its pick is judged
        left = {"title": res["title"], "author": res["author"], "narrator": res["narrator"],
                "series": series_text(res), "asin": (written or "").upper()} if res else None
        # Which fields are off, for the marks on the page: the field checks' own findings.
        bad = sorted({FIELD_OF[p.split("_")[0]] for p in problems})
        tools[t] = [code, pick(t, rec), left, bad, [PROBLEM.get(p, p) for p in problems]]
        tools_out[name] = {"verdict": code, "verdict_words": VERDICT.get(code, ("", ""))[1], "pick": pick(t, rec),
                           "left_on_book": None if t == "rmab" else (
                               {**{k: res[k] for k in bench_data.FIELDS}, "asin": (written or "").upper()} if res else None),
                           "field_problems": problems}
    file_view = {"title": own["title"], "author": own["author"], "narrator": own["narrator"],
                 "series": series_text(own), "asin": own_asin}
    rows.append({
        "f": folder, "file": book.get("file", ""), "min": round(book.get("minutes") or 0, 1),
        "tags": clean_tags(book.get("tags")), "own": file_view, "a": answer, "src": book["answer_source"],
        "note": readable(row_audit.get("note", "")), "t": tools,
        # How LibraForge got there.
        "clues": {_CLUE_LABELS.get(k, k): ", ".join(v) if isinstance(v, list) else v
                  for k, v in (run.get("clues") or {}).items() if k in _CLUE_LABELS},
        "planned": run.get("planned_queries") or [], "status": run.get("status", "not run"),
        "skip": run.get("skip_reason", ""), "score": run.get("score"), "mode": run.get("mode", ""),
        "dur": run.get("duration_status", ""), "listing_min": match.get("duration_minutes"),
        "edition": run.get("different_edition") or None, "series_asin": run.get("series_match_asin", ""),
        "q": searches(run.get("log")), "cand": candidates(run.get("log")), "trace": trace(run.get("log")),
    })
    download.append({
        "folder": folder, "file": book.get("file", ""), "minutes": round(book.get("minutes") or 0, 1),
        "tags": bench_data.public_tags(book.get("tags")) if opts.public else book.get("tags"),
        "answer": {"source": book["answer_source"], **{k: book["answer"][k] for k in ("asin", "title", "subtitle")},
                   "authors": book["answer"]["author"], "narrators": book["answer"]["narrator"],
                   "series": book["answer"]["series"], "minutes": book["answer"]["minutes"],
                   "other_ids": [i for i in book["answer"]["ids"] if i != book["answer"]["asin"]]} if book["answer"] else None,
        "note": readable(row_audit.get("note", "")), "tools": tools_out})

# The downloadable book list: the same books as the page, so anyone can recount it.
RUNS_META = {name: {"version": bench.m["runs"][t].get("version", ""), "date": bench.m["runs"][t].get("date", ""),
                    "run_time_s": bench.runtime(t), "online_run_time_s": bench.runtime(t, online=True)}
             for t, _, name, _ in TOOL_ROWS}
DOWNLOAD_NAME = "benchmark-books.json"
json.dump({"commit": opts.commit, "date": datetime.date.today().isoformat(), "runs": RUNS_META,
           "verdicts": VERDICT_MEANING, "field_problems": PROBLEM, "books": download},
          open(os.path.join(os.path.dirname(os.path.abspath(opts.out)), DOWNLOAD_NAME), "w"),
          ensure_ascii=False, separators=(",", ":"))

RUNTIME = {t: bench.runtime(t) for t in bench_data.TOOL_NAMES}
RUNTIME["audiosilo_online"] = bench.runtime("audiosilo", online=True)
payload = base64.b64encode(gzip.compress(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode())).decode()
today = datetime.date.today().isoformat()


def pct(n, d):
    return f"{n:,} ({n / d * 100:.1f}%)" if d else "0"


def took(seconds):
    if seconds is None:
        return "n/a"
    if seconds < 600:  # short runs to the second
        m, sec = divmod(round(seconds), 60)
        return f"{m} min {sec:02d} s" if m else f"{sec} s"
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


# How many books each tool searches at once, and whether that can be changed, from each
# tool's source. LibraForge's is run.sh's workers argument (4 in these runs, 5 with Goodreads).
CONCURRENCY = {
    "public": ("4", "yes, Search workers 1 to 30"),
    "public_gr": ("5", "yes, Search workers 1 to 30"),
    "public_gr_old": ("5", "yes, Search workers 1 to 30"),
    "audiosilo": ("6", "no, a match run checks 6 books at once"),
    "abs": ("4", "yes, Search workers 1 to 30"),
    "abs_gr": ("5", "yes, Search workers 1 to 30"),
    "absqm": ("1", "no, Match All goes one book at a time"),
    "grimmory": ("1", "no, one book at a time, providers in turn"),
    "rmab": ("1", "no, 1.5 s pause between searches"),
    "beets": ("1 per import (4 run)", "only by running several imports"),
    "bo": ("1", "no, 2 to 5 s pause between books"),
}


# How each tool matches, from its source and docs, and our take after running it. Keyed by run
# name; a run without an entry gets a row with its label only.
TOOLS = {
    "public_gr": {
        "source": "Audible public catalog (no login), with Goodreads when Audible has no good listing",
        "how": "Reads the tags, the folder path and the runtime together, runs several searches (the file's ASIN, "
               "title and author, keywords) and scores every candidate on title, author, narrator, series, book "
               "number and runtime.",
        "review": "Applies confident matches and holds the rest for review, with the reason",
        "note": "Works best with the Goodreads fallback on, which finds books Audible lists badly or not at all. "
                "When the runtime or narrator says a file is another recording of the book, it keeps the file's own "
                "narrator instead of writing the listing's."},
    "audiosilo": {
        "source": "Its own community database (audiosilo-meta, CC0), not Audible",
        "how": "Sends the path, the tags and the runtime together; a file's ASIN or ISBN is a hint it checks, not a "
               "match by itself. Applies a match at score 90 or more, clearly ahead of the next candidate, with the "
               "runtime close enough; since 2.6 also without an ASIN or ISBN when the author, series position and "
               "runtime agree.",
        "review": "Holds everything else for review",
        "note": "Part of its own metadata project. The whole database can be downloaded locally (mirror mode, a "
                "download of about 500 MB, refreshed daily), so matching is fast and never polls their service. Coverage is only what the "
                "community has added, and it fills only blank fields, so a file's wrong title or series stays."},
    "absqm": {
        "source": "Audible (Audiobookshelf's provider, US store)",
        "how": "Quick Match per book: the file's ASIN when it has one, else one search and its first result. No "
               "runtime check.",
        "review": "None, applies the first result",
        "note": "A match is only as good as Audible's first result, so later books of a series often get another "
                "book's listing."},
    "bo": {
        "source": "Its default providers",
        "how": "Library bulk metadata fetch.",
        "review": "None",
        "note": "Slow by design: 2 to 5 seconds between books. Titles often differ from the book's own."},
    "grimmory": {
        "source": "Audible (switched on and put first), then Goodreads, then Google",
        "how": "Per provider, one keyword search and its first result; the file's ASIN when its tags carry one "
               "(it reads the iTunes copies of the tags, which carry none here).",
        "review": "None",
        "note": "Audible is off by default. No runtime check, so later books in a series often get Book 1."},
    "rmab": {
        "source": "Audible",
        "how": "Bulk Import scan: one search on the album, album artist and composer tags, first result.",
        "review": "None",
        "note": "Groups folders by their tags, so a series sharing one album tag is folded into a single book. "
                "Reads no series."},
    "beets": {
        "source": "Audible (beets-audible plugin)",
        "how": "beet import -q with the plugin's recommended settings, scoring candidates on track length.",
        "review": "Quiet mode skips anything that isn't a strong match",
        "note": "Cautious: most of what it writes is the right book, but it writes under half the library. It "
                "can't read a file's ASIN from the iTunes tags."},
}




RERUN_BODY = ("Which tool and test should be run again?\n\n"
              "What changed since the last run (version, setting, provider)?\n\n"
              "Anything that looked wrong in the current results (book folders from the page welcome)?\n")
REPORT_BODY = ("Book (its folder, as shown on the page):\n\n"
               "Which tool's result is wrong (or is the expected answer itself wrong)?\n\n"
               "What the page shows:\n\n"
               "What it should be, and how you know (a store link, the book's cover or credits):\n")
ADD_BODY = ("Tool name and link:\n\nVersion:\n\n"
            "How it matches (bulk or per book, which provider, does it hold matches for review?):\n\n"
            "Can it run self-hosted without calling a shared service for every book?\n")


def issue_url(title, body):
    return html.escape(f"https://github.com/{opts.repo}/issues/new?"
                       + urllib.parse.urlencode({"title": title, "body": body}, quote_via=urllib.parse.quote))


def display(label):
    """("LibraForge", "public catalog + Goodreads") from "LibraForge, public catalog + Goodreads"."""
    m = re.match(r"(.+?)\s*\((.+)\)$", label) or re.match(r"(.+?),\s*(.+)$", label)
    return (m.group(1), m.group(2)) if m else (label, "")


ALL_TOOLS = [(opts.run_name, opts.label)] + others

# How each tool writes what it matched, which sets what a correct result is for it.
WRITES = {
    "public_gr": "Writes the listing's fields to the files. When the runtime or the narrator says the file is another "
                 "recording, keeps the file's narrator, ASIN, year and ISBN. A series-only match writes the series alone.",
    "audiosilo": "A confident match attaches the ASIN and fills only blank fields, so the file's title, narrator and series "
                 "stay. Everything else waits in review.",
    "absqm": "Replaces the book's details with the listing's, in Audiobookshelf's database.",
    "grimmory": "Fills or replaces each field from the provider's top result, field by field.",
    "rmab": "Picks a listing per book and writes nothing, to files or a library. Judged only on whether the pick is the book.",
    "bo": "Fetches the listing into its own records (title, authors, narrators, series), not into the files.",
    "beets": "Writes the listing's fields to the files when it accepts the match; skips the rest.",
}
# LibraForge's misses that are no field: the identity of what it wrote.
MISS = {"other_recording": "Another recording's details written", "wrong_book": "The wrong book written",
        "wrong_series": "The wrong series written in a series-only match"}


def audit_counts(name):
    """A tool's verdicts over the scored books (a book with no right answer is not scored)."""
    c = Counter(audit[f]["v"][name] for f in audit if audit[f]["v"].get(name, "U") != "U")
    s = {"books": sum(c.values()), "correct": c["C"] + c["S"], "recording": c["E"], "partial": c["P"],
         "wrong": c["W"] + c["s"], "held_right": c["H"], "held_wrong": c["h"], "none": c["N"]}
    s["written"] = s["correct"] + s["recording"] + s["partial"] + s["wrong"]
    s["right"] = s["correct"] + s["recording"] + s["partial"]
    s["held"] = s["held_right"] + s["held_wrong"]
    return s


def share(n, d):
    return n / d * 100 if d else 0.0


def run_time(name):
    """A tool's run time; AudioSilo's with its local copy and, when measured, its online service."""
    online = RUNTIME.get(f"{name}_online")
    if online is None:
        return took(RUNTIME.get(name))
    return f"{took(RUNTIME.get(name))} local copy<small>{took(online)} online</small>"


def glance():
    """One stacked bar per tool over all its books, best fully-correct share first."""
    stats = [(name, label, audit_counts(name)) for name, label in ALL_TOOLS]
    stats.sort(key=lambda x: -share(x[2]["correct"], x[2]["books"]))
    segments = [("correct", "ok", "Fully correct"), ("off", "warn", "Right book, a field off"),
                ("wrong", "bad", "Wrong book"), ("held", "held", "Held for review"), ("none", "none", "Nothing written")]
    legend = "".join(f'<span class=key><i class="sw s-{css}"></i>{text}</span>' for _, css, text in segments)
    rows_html = ""
    for name, label, s in stats:
        n = s["books"]
        parts = {"correct": s["correct"], "off": s["recording"] + s["partial"], "wrong": s["wrong"],
                 "held": s["held"], "none": s["none"]}
        bar = "".join(
            f'<span class="seg s-{css}" style="width:{share(parts[key], n):.2f}%" title="{text}: {parts[key]:,} '
            f'({share(parts[key], n):.1f}%)"></span>' for key, css, text in segments if parts[key])
        title, sub = display(label)
        mine_ = " is-lf" if name == opts.run_name else ""
        rows_html += f"""<div class="row{mine_}">
  <div class=who><b>{html.escape(title)}</b>{f'<span>{html.escape(sub)}</span>' if sub else ''}</div>
  <div class=bar role=img aria-label="{html.escape(title)}: {share(s['correct'], n):.1f}% fully correct, {share(s['wrong'], n):.1f}% wrong book">{bar}</div>
  <dl class=figs>
    <div><dt>Writes</dt><dd>{share(s['written'], n):.0f}%</dd></div>
    <div><dt>Fully correct</dt><dd>{share(s['correct'], s['written']):.1f}%</dd></div>
    <div><dt>Right book</dt><dd>{share(s['right'], s['written']):.1f}%</dd></div>
  </dl>
</div>"""
    return f'<div class=legend>{legend}</div><div class=glance>{rows_html}</div>'


def numbers_table():
    head = ("<tr><th>Tool</th><th>Books</th><th>Writes</th><th>Fully correct</th><th>Other recording</th>"
            "<th>A field off</th><th>Wrong book</th><th>Held, right</th><th>Held, wrong</th><th>Nothing written</th>"
            "<th>Run time</th><th>Searches at once</th></tr>")
    body = ""
    for name, label in ALL_TOOLS:
        s = audit_counts(name)
        n = s["books"]
        cells = "".join(f"<td>{s[k]:,}<small>{share(s[k], n):.1f}%</small></td>"
                        for k in ("written", "correct", "recording", "partial", "wrong", "held_right", "held_wrong", "none"))
        conc = CONCURRENCY.get(name, ("n/a", "n/a"))[0]
        body += (f"<tr><th scope=row>{html.escape(display(label)[0])}</th><td>{n:,}</td>{cells}"
                 f"<td>{run_time(name)}</td><td>{html.escape(conc)}</td></tr>")
    return f"<div class=scroll><table class=nums><thead>{head}</thead><tbody>{body}</tbody></table></div>"


def speed(name, books_n, conc, editable):
    online = RUNTIME.get(f"{name}_online")
    if online is None:
        return f"{took(RUNTIME.get(name))} for {books_n:,} books, {html.escape(conc)} at once ({html.escape(editable)})"
    return (f"{took(RUNTIME.get(name))} for {books_n:,} books with its local copy of the database, "
            f"{took(online)} against its online service; {html.escape(conc)} at once ({html.escape(editable)})")


def tool_cards():
    cards = ""
    for name, label in ALL_TOOLS:
        t = TOOLS.get(name, {})
        title, sub = display(label)
        conc, editable = CONCURRENCY.get(name, ("n/a", "n/a"))
        s = audit_counts(name)
        held = (f"{s['held_wrong']:,} of the {s['held']:,} books it held for review were the wrong pick."
                if s["held"] else "")
        cards += f"""<article class=card>
  <header><h3>{html.escape(title)}</h3>{f'<span>{html.escape(sub)}</span>' if sub else ''}</header>
  <dl>
    <dt>Matches against</dt><dd>{html.escape(t.get('source', ''))}</dd>
    <dt>How</dt><dd>{html.escape(t.get('how', ''))}</dd>
    <dt>Review</dt><dd>{html.escape(t.get('review', ''))}</dd>
    <dt>Writes</dt><dd>{html.escape(WRITES.get(name, ''))}</dd>
    <dt>Speed</dt><dd>{speed(name, len(books), conc, editable)}</dd>
  </dl>
  <p class=take>{html.escape(t.get('note', ''))}{(' ' + held) if held else ''}</p>
</article>"""
    return f"<div class=cards>{cards}</div>"


def lf_findings():
    """What LibraForge got wrong, most common first."""
    issues = Counter()
    for row in audit.values():
        code = row["v"].get(opts.run_name)
        if code == "P":
            issues.update(set(row.get("f", {}).get(opts.run_name) or []))
        elif code in "EWs":
            issues[{"E": "other_recording", "W": "wrong_book", "s": "wrong_series"}[code]] += 1
    s = audit_counts(opts.run_name)
    items = "".join(f"<li><b>{n:,}</b><span>{html.escape(MISS.get(k) or PROBLEM.get(k, k).capitalize())}</span></li>"
                    for k, n in issues.most_common())
    return (f"<p>Of the {s['written']:,} books LibraForge wrote, {s['correct']:,} came out fully correct and "
            f"{s['wrong']:,} were the wrong book. The rest were the right book with something off:</p>"
            f"<ul class=findings>{items}</ul>")


lf_title = display(opts.label)[0]
geo = json.load(open(bench.file("geo"))) if bench.m.get("geo") and os.path.exists(bench.file("geo")) else None
GEO_HTML = ""
if geo:
    rh = geo["right_on_hidden"]
    GEO_HTML = f"""<h3>Books Audible's search couldn't show</h3>
<p>Audible's search only returns a book where Audible sells it, while looking a book up by its ASIN works everywhere.
Some listings are sold in only some of Audible's markets (only the UK and Commonwealth stores, only Australia and New
Zealand, only the US and Canada), so a search made outside those markets doesn't return them. Checked against Audible's
own sales-rights data, {geo["hidden"]:,} of the {geo["confirmed"]:,} books with a confirmed Audible listing were hidden from
search where these runs were made ({share(geo["hidden"], geo["books"]):.1f}% of all books). {geo["hidden_with_asin"]:,} of those
files carry their own ASIN, which a tool can look up directly.</p>
<p>That is the margin of error this adds: run where those books are sold, a tool that searches Audible could do
better on at most these {geo["hidden"]:,} books, {share(geo["hidden"], geo["books"]):.1f}% of the library. On them,
{html.escape(lf_title)} got {rh.get(opts.run_name, 0)} right, AudioSilo {rh.get("audiosilo", 0)} (it reads its own database, so
search didn't hide anything from it), Audiobookshelf {rh.get("absqm", 0)}, BookOrbit {rh.get("bo", 0)},
Grimmory {rh.get("grimmory", 0)}, ReadMeABook {rh.get("rmab", 0)} and beets {rh.get("beets", 0)}.</p>"""
reaud = audit_meta.get("reaudit", {})
va = audit_meta.get("validation", {})
scored = sum(1 for b in books.values() if b["answer"])
by_hand = sum(1 for b in books.values() if b["answer_source"] == "hand")
METHOD = f"""
<p>{len(books):,} audiobooks in their original state, before any matching: the tags LibraForge saved before it first
wrote anything to a library's books, or another library's files as they were. Each book was matched again from those
original tags, its folder path and its runtime, with no login, against the live catalog.</p>
<p>Every tool got the same books, as silent files carrying the original tags at the books' real folder paths (and,
for tools that check runtime, as long as the real book), and each was run the way its own documentation suggests.</p>
<h3>The right answers</h3>
<p>A book's right answer is the edition confirmed as that book, as its own catalog records it: Audible's listing,
read by its ASIN, when the edition is on Audible; otherwise the record of the catalog that publishes it (a
publisher's own store by ISBN, AudioSilo's community database), or the fields confirmed by hand when no catalog has
it. Each holds the title, every author, every narrator, every series with its number there, the runtime where known,
and every ID the edition has. An edition counts as confirmed when it was applied to the book in a library and
reviewed there, or, for {by_hand:,} books, confirmed by hand from the editions the tools picked, against the file
name, runtime, narrator and what the book's opening credits say. A book in several series is answered by any of
them. {len(books) - scored:,} books have no confirmed edition yet: every tool's result is shown for them, but they are
not scored.</p>
<h3>How results were judged</h3>
<div class=callout><p><b>Checked with Claude, under human supervision.</b> The book-by-book review was done with
Claude, an AI model, following one written set of rules for every tool and every book. A person supervised the
work and checked random books by hand along the way, but did not personally review every one of the
{len(books):,} books. The second audit below measures how often the review got a verdict wrong.</p></div>
<p>A tool that chose any of the confirmed edition's IDs (its ASIN, ISBN or community-database work) chose the right book. Any other choice was judged by hand, once per
book and listing: another listing of the same recording (the right book), another recording, or the wrong book. What
the tool then left on the book was rebuilt from its own way of writing and checked field by field against the
listing's record, by one script for every tool: a field is off when the book ends up with something the listing
doesn't say (written, or kept from the file) or without something it does. Two tools that leave a book the same way
always get the same verdict.</p>
{f'''<p>To check the audit, {reaud.get("books", 0)} random books were audited a second time:
{reaud.get("wrong", 0)} of {reaud.get("verdicts", 0):,} verdicts ({share(reaud.get("wrong", 0), reaud.get("verdicts", 0)):.1f}%)
were wrong, and every kind of error found was corrected for all books. A fresh {va.get("books", 0)} books audited
after that had {va.get("wrong", 0)} wrong ({share(va.get("wrong", 0), va.get("verdicts", 0)):.1f}%), also corrected.</p>''' if reaud else ""}
{GEO_HTML}
"""


def ran(t):
    spec = bench.m["runs"][t]
    bits = [b for b in (spec.get("version"), f"run {spec['date']}" if spec.get("date") else "") if b]
    return f" ({html.escape(', '.join(bits))})" if bits else ""


SETUP = f"""<ul class=setup>
<li><b>LibraForge</b>{ran("public_gr")}: Metadata Forge's matcher over the files, Audible public catalog with the Goodreads
fallback on, 5 search workers.</li>
<li><b>AudioSilo</b>{ran("audiosilo")}: "Match automatically" over the library, in mirror mode (a local copy of the community
database), and timed once more against its online service. Confident matches count as written, "to review" as held.</li>
<li><b>Audiobookshelf Quick Match</b>{ran("absqm")}: Quick Match per book with the Audible US provider, which takes the
first Audible result, or the file's ASIN when it has one. One book at a time, as Match All does.</li>
<li><b>BookOrbit</b>{ran("bo")}: a library bulk metadata fetch with its default providers.</li>
<li><b>beets</b>{ran("beets")}: <code>beet import -q</code> with the plugin's recommended settings, which applies strong
matches and skips the rest. It was given each book's real runtime, since it scores on track length.</li>
<li><b>Grimmory</b>{ran("grimmory")}: a library metadata refresh with Audible enabled and first for every field
(Goodreads, then Google behind it), applied without review.</li>
<li><b>ReadMeABook</b>{ran("rmab")}: the Bulk Import scan, which picks an Audible match per book. It groups folders by
their tags, so books it merged into another folder count as nothing written. Its scan returns no series.</li>
</ul>"""

VERDICT_OPTIONS = '<option value="">Any verdict</option>' + "".join(
    f'<option value="{c}">{html.escape(w)}</option>' for c, (_, w) in VERDICT.items() if c not in "Ss")

n_tools = len(ALL_TOOLS)
lf_s = audit_counts(opts.run_name)

CSS = """
:root{--bg:#f6f4f1;--bg2:#efebe6;--panel:#fff;--panel2:#faf8f5;--ink:#1d1a17;--soft:#4a443e;--muted:#7a736c;
--line:#e4dfd8;--line2:#d4cdc4;--accent:#1f78c8;--accent-soft:#e3effa;--ok:#2f9a5d;--warn:#d39a2a;--bad:#d2493f;
--held:#7d93b0;--none:#d9d3cb;--shadow:0 1px 2px rgba(40,30,20,.06),0 4px 16px rgba(40,30,20,.05)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#151311;--bg2:#1a1715;--panel:#1e1b18;
--panel2:#25211e;--ink:#e7e3df;--soft:#c5bdb5;--muted:#8d867f;--line:#342f2c;--line2:#4d4641;--accent:#61b8ff;
--accent-soft:#1d2f3f;--ok:#4cc27e;--warn:#e7b04a;--bad:#ef6b61;--held:#8aa3c4;--none:#3a3531;--shadow:none}}
:root[data-theme=dark]{--bg:#151311;--bg2:#1a1715;--panel:#1e1b18;--panel2:#25211e;--ink:#e7e3df;--soft:#c5bdb5;
--muted:#8d867f;--line:#342f2c;--line2:#4d4641;--accent:#61b8ff;--accent-soft:#1d2f3f;--ok:#4cc27e;--warn:#e7b04a;
--bad:#ef6b61;--held:#8aa3c4;--none:#3a3531;--shadow:none}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:15.5px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:2px}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);
border-bottom:1px solid var(--line)}
.top .wrap{display:flex;align-items:center;gap:18px;height:52px;overflow-x:auto;white-space:nowrap}
.brand{font-weight:700;letter-spacing:-.01em;color:var(--ink);text-decoration:none;margin-right:auto}
.top nav a{color:var(--soft);text-decoration:none;font-size:14px}
.top nav a:hover{color:var(--accent)}
.hero{padding:56px 0 28px}
.eyebrow{font-size:12.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin:0 0 10px}
h1{font-size:clamp(28px,4.4vw,44px);line-height:1.12;letter-spacing:-.025em;margin:0 0 16px;max-width:22ch;font-weight:750}
.lede{font-size:18px;color:var(--soft);max-width:62ch;margin:0}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:22px 0 0;padding:0;list-style:none}
.chips li{font-size:13px;color:var(--soft);background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:4px 12px}
section{padding:36px 0;border-top:1px solid var(--line)}
h2{font-size:24px;letter-spacing:-.015em;margin:0 0 6px;font-weight:700}
.sub{color:var(--muted);margin:0 0 22px;max-width:70ch}
h3{font-size:16px;margin:24px 0 6px;letter-spacing:-.005em}
p{max-width:75ch;margin:8px 0}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin:0 0 14px;font-size:13px;color:var(--soft)}
.key{display:inline-flex;align-items:center;gap:7px}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
.s-ok{background:var(--ok)}.s-warn{background:var(--warn)}.s-bad{background:var(--bad)}.s-held{background:var(--held)}.s-none{background:var(--none)}
.glance{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}
.row{display:grid;grid-template-columns:210px minmax(0,1fr) 340px;gap:20px;align-items:center;padding:16px 20px;border-top:1px solid var(--line)}
.row:first-child{border-top:0}
.row.is-lf{background:var(--accent-soft)}
.who b{display:block;font-size:15px}.who span{display:block;font-size:12.5px;color:var(--muted)}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--bg2)}
.seg{display:block;height:100%}
.seg+.seg{box-shadow:inset 1px 0 0 color-mix(in srgb,var(--panel) 70%,transparent)}
.figs{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:0}
.figs div{text-align:right}.figs dt{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
.figs dd{margin:0;font-size:18px;font-weight:650;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.explain{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:18px 0 0}
.explain div{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px 14px;font-size:14px;color:var(--soft)}
.explain b{display:block;color:var(--ink);margin-bottom:2px}
details.more{margin:18px 0 0}
details.more>summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:14px}
.scroll{overflow-x:auto;margin:12px 0 0;border:1px solid var(--line);border-radius:12px;background:var(--panel)}
table{border-collapse:collapse;width:100%}
.nums th,.nums td{padding:10px 12px;border-top:1px solid var(--line);text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;font-size:14px}
.nums thead th{border-top:0;font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.nums th:first-child{text-align:left}.nums small{display:block;color:var(--muted);font-size:12px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;box-shadow:var(--shadow);display:flex;flex-direction:column}
.card header{margin-bottom:10px}.card h3{margin:0;font-size:17px}.card header span{font-size:13px;color:var(--muted)}
.card dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:6px 14px;font-size:13.5px}
.card dt{color:var(--muted);font-weight:600}.card dd{margin:0;color:var(--soft)}
.take{margin:14px 0 0;padding-top:12px;border-top:1px solid var(--line);font-size:14px}
.callout{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;padding:16px 20px;margin:18px 0 0}
.callout h3{margin-top:0}
.findings{list-style:none;padding:0;margin:14px 0 0;display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:8px}
.findings li{display:flex;gap:12px;align-items:baseline;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;font-size:14px}
.findings b{min-width:3ch;text-align:right;font-variant-numeric:tabular-nums;color:var(--ink)}
.findings span{color:var(--soft)}
.setup{padding-left:18px;font-size:14px;color:var(--soft)}.setup li{margin:6px 0}
code{font:13px "SFMono-Regular",Consolas,monospace;background:var(--bg2);padding:1px 5px;border-radius:4px}
.controls{position:sticky;top:52px;z-index:4;display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:12px 0;background:var(--bg)}
.controls input,.controls select,.controls button{font:inherit;font-size:14px;color:var(--ink);background:var(--panel);border:1px solid var(--line2);border-radius:8px;padding:7px 11px}
.controls input[type=search]{flex:1 1 260px;min-width:0}
.controls button{cursor:pointer}.controls button:hover{border-color:var(--accent)}
.controls .lab{font-size:12.5px;color:var(--muted);font-weight:600}
#count{font-size:13px;color:var(--muted);margin-left:auto}
.book{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:6px 0}
.book>summary{list-style:none;cursor:pointer;padding:11px 14px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 14px}
.book>summary::-webkit-details-marker{display:none}
.book[open]{border-color:var(--line2)}
.book .path{font-weight:600;overflow-wrap:anywhere;font-size:14.5px}
.book .pick{color:var(--muted);font-size:13px;overflow-wrap:anywhere;grid-column:1}
.badge{font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;white-space:nowrap;align-self:start;grid-row:1/span 2;grid-column:2;
border:1px solid transparent}
.b-correct{color:var(--ok);background:color-mix(in srgb,var(--ok) 13%,transparent)}
.b-recording,.b-partial{color:var(--warn);background:color-mix(in srgb,var(--warn) 15%,transparent)}
.b-wrong{color:var(--bad);background:color-mix(in srgb,var(--bad) 13%,transparent)}
.b-correct-held,.b-wrong-held{color:var(--held);background:color-mix(in srgb,var(--held) 15%,transparent)}
.b-none,.b-not{color:var(--muted);background:var(--bg2)}
.detail{padding:6px 14px 16px;border-top:1px solid var(--line)}
.verdict{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;align-items:baseline;border-radius:10px;padding:11px 14px;margin:12px 0 4px;font-size:14px}
.verdict b{white-space:nowrap}.verdict span{color:var(--ink)}
.verdict small{grid-column:2;color:var(--soft);font-size:12.5px}
.scroll-x{overflow-x:auto}
.cmp{width:100%;table-layout:fixed;font-size:13.5px;margin:6px 0 4px;border:1px solid var(--line);border-radius:10px;border-collapse:separate;border-spacing:0;overflow:hidden}
.cmp col.c-label{width:96px}
.cmp tr.id-cell td{font-family:"SFMono-Regular",Consolas,monospace;font-size:12.5px;overflow-wrap:normal;word-break:keep-all}
.tools-list{table-layout:fixed}.tools-list col:nth-child(1){width:42%}.tools-list col:nth-child(2){width:30%}
.tools-list td:nth-child(3){white-space:nowrap;font-family:"SFMono-Regular",Consolas,monospace;font-size:12.5px}
.cmp th,.cmp td{text-align:left;padding:7px 10px;border-top:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
.cmp thead th{border-top:0;font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.03em;background:var(--panel2)}
.cmp tbody th{color:var(--muted);font-weight:600;white-space:nowrap;width:1%}
.cmp td.good{background:color-mix(in srgb,var(--ok) 9%,transparent)}
.cmp td.bad{background:color-mix(in srgb,var(--bad) 12%,transparent);font-weight:600}
.cmp td.na{color:var(--muted);font-style:italic}
.chips-row{display:flex;flex-wrap:wrap;gap:4px;grid-column:2;grid-row:1/span 2;align-self:start;justify-content:flex-end}
.chip{font-size:11px;font-weight:700;letter-spacing:.02em;padding:2px 7px;border-radius:6px;white-space:nowrap}
.c-correct,.b-correct{color:var(--ok);background:color-mix(in srgb,var(--ok) 14%,transparent)}
.c-partial,.c-recording{color:var(--warn);background:color-mix(in srgb,var(--warn) 16%,transparent)}
.c-wrong{color:var(--bad);background:color-mix(in srgb,var(--bad) 14%,transparent)}
.c-held,.c-held-wrong,.b-held,.b-held-wrong{color:var(--held);background:color-mix(in srgb,var(--held) 16%,transparent)}
.c-none,.c-unscored,.b-unscored{color:var(--muted);background:var(--bg2)}
.book-grid{table-layout:auto}.book-grid tbody th{white-space:nowrap}
.book-grid tr.src th,.book-grid tr.src td{background:var(--panel2)}
.book-grid tr.answer th{color:var(--ink)}
.book-grid td.v{white-space:nowrap}.book-grid td.v small{display:block;white-space:normal;color:var(--soft);font-size:12px;margin-top:3px;max-width:26ch}
.book-grid td.id{font-family:"SFMono-Regular",Consolas,monospace;font-size:12.5px;white-space:nowrap}
.book-grid thead th{white-space:nowrap}.subt{display:block;color:var(--muted);font-size:12px;font-family:Inter,ui-sans-serif,system-ui,sans-serif;white-space:normal}
.book-grid td.v .val{display:block}
.mk{font-weight:700}.cmp td.good .mk{color:var(--ok)}.cmp td.bad .mk{color:var(--bad)}
.key-line{color:var(--muted)}
details.more2{margin:16px 0 0;border-top:1px solid var(--line);padding-top:10px}
details.more2>summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:14px}

.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:6px 22px}
.detail h3{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:16px 0 6px}
.kv{width:100%;font-size:13.5px}.kv th{text-align:left;color:var(--muted);font-weight:600;padding:3px 12px 3px 0;vertical-align:top;white-space:nowrap;width:1%}
.kv td{padding:3px 0;overflow-wrap:anywhere}.ok{color:var(--ok)}.no{color:var(--bad)}
.list{width:100%;font-size:13px}.list th,.list td{text-align:left;padding:5px 10px 5px 0;border-top:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
.list thead th{border-top:0;color:var(--muted);font-weight:600}
.list .badge{grid-row:auto}
pre{background:var(--bg2);padding:12px;border-radius:8px;font-size:12px;overflow-x:auto;white-space:pre;margin:8px 0 0}
.muted{color:var(--muted)}.small{font-size:13px}.report{margin:14px 0 0;text-align:right}
.pager{display:flex;gap:10px;align-items:center;justify-content:center;margin:18px 0}
.pager button{font:inherit;font-size:14px;color:var(--ink);background:var(--panel);border:1px solid var(--line2);border-radius:8px;padding:7px 14px;cursor:pointer}
.pager button:disabled{opacity:.45;cursor:default}
.help{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-top:14px}
.help a{display:block;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;text-decoration:none;color:var(--ink)}
.help a:hover{border-color:var(--accent)}
.help b{display:block;margin-bottom:4px}.help span{font-size:14px;color:var(--soft)}
footer{padding:28px 0 56px;color:var(--muted);font-size:13px;border-top:1px solid var(--line)}
@media (max-width:860px){.row{grid-template-columns:1fr;gap:10px}.figs div{text-align:left}.controls{position:static}}
@media (max-width:640px){
.cmp,.cmp tbody,.cmp tr,.cmp th,.cmp td{display:block;width:auto}
.cmp colgroup,.cmp thead{display:none}
.cmp tr{border-top:1px solid var(--line);padding:8px 12px}.cmp tr:first-child{border-top:0}
.cmp tbody th{border:0;padding:0 0 4px;width:auto;color:var(--ink)}
.cmp td{border:0;padding:3px 8px;display:grid;grid-template-columns:110px 1fr;gap:8px;border-radius:6px}
.cmp td::before{content:attr(data-label);color:var(--muted);font-size:12px;font-weight:600;font-style:normal;font-family:Inter,ui-sans-serif,system-ui,sans-serif}
.tools-list colgroup,.tools-list thead{display:none}
.tools-list,.tools-list tbody{display:block}
.tools-list tr{display:grid;grid-template-columns:1fr auto;gap:4px 10px;padding:8px 0;border-top:1px solid var(--line)}
.tools-list td{border:0;padding:0}.tools-list td:nth-child(1){grid-column:1/-1;font-weight:600}
.tools-list td:nth-child(3){text-align:right}
.verdict{grid-template-columns:1fr}.verdict small{grid-column:1}}
@media (max-width:600px){.wrap{padding:0 16px}.book>summary{grid-template-columns:1fr}.badge{grid-row:auto;grid-column:1;justify-self:start}
.chips-row{grid-column:1;grid-row:auto;justify-content:flex-start}
.book-grid tr.src td.v{display:none}
.hero{padding:36px 0 20px}.controls{top:52px}}
"""

JS = r"""
const PAGE = 50;
let rows = [], view = [], page = 0;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const FIELDS = [["title", "Title"], ["author", "Author"], ["narrator", "Narrator"], ["series", "Series"], ["asin", "ASIN"]];
const RIGHT = new Set(["C", "P"]);

function kv(obj) {
  const keys = Object.keys(obj).filter((k) => obj[k] !== "" && obj[k] !== null && obj[k] !== false);
  if (!keys.length) return '<p class="muted small">none</p>';
  return '<table class=kv>' + keys.map((k) => `<tr><th>${esc(k)}</th><td>${esc(obj[k])}</td></tr>`).join("") + "</table>";
}

const badge = (code) => { const [cls, words] = V[code] || ["none", code]; return `<span class="badge b-${cls}">${esc(words)}</span>`; };
const link = (asin) => /^[A-Z0-9]{10}$/.test(asin || "") ? `<a href="https://www.audible.com/pd/${encodeURIComponent(asin)}" rel=noopener>${esc(asin)}</a>` : esc(asin);
const none = '<span class=muted>none</span>';

// One row of the grid: what a source says, or what a tool left on the book, field by field.
function line(label, values, opts = {}) {
  const cells = FIELDS.map(([k, name]) => {
    const v = values ? values[k] : "";
    let cls = "", mark = "";
    if (opts.marks && k in opts.marks) { cls = opts.marks[k] ? "good" : "bad"; mark = opts.marks[k] ? "&#10003; " : "&#10007; "; }
    const shown = (k === "asin" ? link(v) : esc(v)) + (k === "title" && values && values.subtitle ? `<small class=subt>${esc(values.subtitle)}</small>` : "")
      + (k === "asin" && opts.asinNote ? `<small class=subt>${esc(opts.asinNote)}</small>` : "");
    return `<td class="${cls}${k === "asin" ? " id" : ""}" data-label="${name}"><span class=val><span class=mk>${mark}</span>${v ? shown : none}</span></td>`;
  }).join("");
  return `<tr class="${opts.cls || ""}"><th scope=row>${label}</th>${cells}<td class=v data-label="Verdict"><span class=val>${opts.verdict || ""}</span></td></tr>`;
}

function toolLine(r, tid) {
  const [code, pickId, left, bad, why] = r.t[tid] || ["", "", null, [], []];
  const name = esc(TOOL_NAMES[tid]);
  const verdict = code ? badge(code) + (why.length ? `<small>${esc(why.join(", "))}</small>` : "") : "";
  if (!left) {
    const what = tid === "rmab" ? (pickId ? `writes nothing; picked ${link(pickId)}` : "writes nothing; no pick")
      : pickId ? `nothing written; held ${link(pickId)} for review` : "nothing written";
    return `<tr><th scope=row>${name}</th><td colspan=5 class=na data-label="Result"><span class=val>${what}</span></td><td class=v data-label="Verdict"><span class=val>${verdict}</span></td></tr>`;
  }
  let marks = null;
  if (RIGHT.has(code)) {
    marks = {};
    FIELDS.forEach(([k]) => { if (k !== "asin") marks[k] = !bad.includes(k); });
    if (left.asin) marks.asin = true;  // the confirmed listing, or another listing judged the same book
  } else if (code === "E" || code === "W" || code === "s") {
    marks = {asin: false};
  }
  const asinNote = RIGHT.has(code) && left.asin && r.a && left.asin !== r.a.asin ? "another listing of this book" : "";
  return line(name, left, {marks, verdict, asinNote});
}

function grid(r) {
  const answer = r.a;
  return `<table class="cmp book-grid"><thead><tr><th></th>${FIELDS.map(([, n]) => `<th>${n}</th>`).join("")}<th>Verdict</th></tr></thead><tbody>
    ${line("The file's tags", r.own, {cls: "src"})}
    ${answer ? line("Right answer", answer, {cls: "src answer"}) : `<tr class="src answer"><th scope=row>Right answer</th><td colspan=6 class=na>none: no confirmed edition, so this book is not scored</td></tr>`}
    ${ORDER.map((tid) => toolLine(r, tid)).join("")}
  </tbody></table>`;
}

function detail(r) {
  const q = r.q.length ? '<table class=list><thead><tr><th>Search</th><th>Query</th><th>Results</th></tr></thead><tbody>' +
    r.q.map(([k, s, n]) => `<tr><td>${esc(k)}</td><td>${esc(s)}</td><td>${esc(n ?? "")}</td></tr>`).join("") + "</tbody></table>" : '<p class="muted small">none</p>';
  const c = r.cand.length ? '<table class=list><thead><tr><th>Score</th><th>Title</th><th>ASIN</th><th>Runtime</th><th>Book</th><th>Mode</th></tr></thead><tbody>' +
    r.cand.map((x) => `<tr><td>${esc(x.score)}</td><td>${esc(x.title)}</td><td>${esc(x.asin)}</td><td>${esc(x.duration)}</td><td>${esc(x.sequence)}</td><td>${esc(x.mode)}</td></tr>`).join("") + "</tbody></table>" : '<p class="muted small">none above the cut</p>';
  const facts = {status: r.status, "why not written": r.skip, score: r.score, mode: r.mode, runtime: r.dur,
    "listing runtime (min)": r.listing_min, "other recording": r.edition ? `${r.edition.match_asin || ""} (listing narrator ${r.edition.match_narrator || "?"})` : "", "series from": r.series_asin};
  const src = r.a ? `Right answer: the confirmed edition ${[r.a.asin ? link(r.a.asin) : "", ...(r.a.ids || []).map(esc)].filter(Boolean).join(", ") || "(no catalog ID)"}, ${esc(SOURCE[r.src] || r.src)}${r.a.minutes ? `, ${r.a.minutes} min` : ""}.` : "No confirmed edition: not scored.";
  return `<div class=detail>
  <p class="muted small">${esc(r.file)} · ${r.min} min · ${src}</p>
  <div class=scroll-x>${grid(r)}</div>
  <p class="small key-line"><span class=ok>&#10003;</span> matches the right answer · <span class=no>&#10007;</span> wrong or missing · fields are checked only when the tool chose the right book</p>
  ${r.note ? `<p class=small><b>Audit note:</b> ${esc(r.note)}</p>` : ""}
  <details class=more2><summary>How ${esc(LF)} got there</summary>
    <div class=grid><section><h3>What it read</h3>${kv(r.clues)}</section><section><h3>Its decision</h3>${kv(facts)}</section></div>
    <h3>Searches</h3>${q}${r.planned.length ? `<details><summary class="muted small">All ${r.planned.length} planned keyword searches</summary><pre>${esc(r.planned.join("\n"))}</pre></details>` : ""}
    <h3>Candidates</h3>${c}
    <details><summary class="muted small">Full matcher trace</summary><pre>${esc(r.trace.join("\n"))}</pre></details>
    <h3>All of the file's tags</h3>${kv(r.tags)}
  </details>
  <p class="small report"><a href="${REPORT + new URLSearchParams({title: "Benchmark: wrong result for " + r.f, body: REPORT_BODY.replace("shown on the page):\n", "shown on the page):\n" + r.f + "\n")})}" rel=noopener>Something wrong here? Report this result</a></p></div>`;
}

function render() {
  const start = page * PAGE;
  $("list").innerHTML = view.slice(start, start + PAGE).map((r) => {
    const chips = ORDER.map((tid) => { const code = (r.t[tid] || [""])[0]; const [cls, words] = V[code] || ["none", ""];
      return `<span class="chip c-${cls}" title="${esc(TOOL_NAMES[tid])}: ${esc(words)}">${esc(SHORTS[tid])}</span>`; }).join("");
    const what = r.a ? `${r.a.title}${r.a.author ? " · " + r.a.author : ""}` : "no right answer, not scored";
    return `<details class=book data-i="${rows.indexOf(r)}"><summary><span class=path>${esc(r.f)}</span>
      <span class=chips-row>${chips}</span><span class=pick>${esc(what)}</span></summary></details>`;
  }).join("") || '<p class=muted>No books match.</p>';
  $("list").querySelectorAll("details.book").forEach((d) => d.addEventListener("toggle", () => {
    if (d.open && !d.querySelector(".detail")) d.insertAdjacentHTML("beforeend", detail(rows[+d.dataset.i]));
  }));
  const pages = Math.max(1, Math.ceil(view.length / PAGE));
  $("page").textContent = `Page ${page + 1} of ${pages}`;
  $("prev").disabled = page === 0; $("next").disabled = page >= pages - 1;
  $("count").textContent = `${view.length.toLocaleString()} of ${rows.length.toLocaleString()} books`;
}

function apply() {
  const q = $("q").value.trim().toLowerCase();
  const want = [[$("tool").value, $("v").value], [$("tool2").value, $("v2").value]];
  view = rows.filter((r) => {
    for (const [tid, code] of want) if (tid && code && (r.t[tid] || [""])[0] !== code) return false;
    if (!q) return true;
    const picks = ORDER.map((tid) => (r.t[tid] || [])[1]);
    return [r.f, r.own.title, r.own.author, r.own.asin, r.a && r.a.title, r.a && r.a.author, r.a && r.a.asin, ...picks]
      .some((v) => String(v || "").toLowerCase().includes(q));
  });
  page = 0; render();
}

(async () => {
  const bytes = Uint8Array.from(atob(DATA_GZ), (c) => c.charCodeAt(0));
  const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
  rows = JSON.parse(text);
  // Filters live in the address (#q=...&tool=...&v=...), so a filtered view can be linked to.
  const ids = ["q", "tool", "v", "tool2", "v2"];
  const saved = new URLSearchParams(location.hash.slice(1));
  ids.forEach((id) => { if (saved.has(id)) $(id).value = saved.get(id); });
  ids.forEach((id) => $(id).addEventListener("input", () => {
    const state = new URLSearchParams();
    ids.forEach((k) => { if ($(k).value) state.set(k, $(k).value); });
    history.replaceState(null, "", state.toString() ? "#" + state : location.pathname + "#books");
    apply();
  }));
  $("collapse").addEventListener("click", () => $("list").querySelectorAll("details.book").forEach((d) => { d.open = false; }));
  $("prev").addEventListener("click", () => { page--; render(); $("books").scrollIntoView(); });
  $("next").addEventListener("click", () => { page++; render(); $("books").scrollIntoView(); });
  apply();
})();
"""

tool_options = "".join(f'<option value="{html.escape(n)}">{html.escape(display(l)[0])}</option>' for n, l in ALL_TOOLS)
page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Audiobook Matching Compared</title>
<meta name="description" content="{len(books):,} real audiobooks matched by {n_tools} tools, every result checked by hand.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class=top><div class=wrap>
<a class=brand href="#">LibraForge benchmark</a>
<nav><a href="#glance">Results</a> · <a href="#tools">The tools</a> · <a href="#lf">LibraForge's misses</a> · <a href="#method">How it was tested</a> · <a href="#books">Every book</a></nav>
</div></div>
<main class=wrap>
<header class=hero>
<p class=eyebrow>Audiobook metadata matching, compared</p>
<h1>{n_tools} tools, the same {len(books):,} audiobooks, every result checked by hand</h1>
<p class=lede>Each tool was given the same real audiobooks with their original, never-edited tags and asked to find
each book's listing and write its details. Then every result was checked: was it the right book, and did the book end
up with the right title, author, narrator and series? The checking was done with Claude, an AI model, under human
supervision (<a href="#method">how</a>).</p>
<ul class=chips><li>{today}</li><li>{len(books):,} books, {scored:,} scored</li><li>{n_tools} tools</li>{f'<li>{html.escape(lf_title)} build {html.escape(opts.commit)}</li>' if opts.commit else ''}</ul>
</header>

<section id=glance>
<h2>At a glance</h2>
<p class=sub>What each tool left on the {scored:,} books with a confirmed edition, best first. Writes is how much of
them it wrote; fully correct and right book are shares of what it wrote.</p>
{glance()}
<div class=explain>
<div><b>Fully correct</b>The right book, and every field it ends up with is right.</div>
<div><b>Right book, a field off</b>The right book, but the title, an author, the narrator or the series is wrong or missing. Another recording of the book counts here too.</div>
<div><b>Wrong book</b>Another book's details were written.</div>
<div><b>Held for review</b>The tool found a candidate but waited for you to confirm it.</div>
</div>
<details class=more><summary>All the numbers</summary>{numbers_table()}
<p class="muted small">Run time is the whole run, start to finish. Searches at once is how many books the tool works on in parallel.</p></details>
</section>

<section id=tools>
<h2>The tools</h2>
<p class=sub>How each one matches and writes, which also decides what "correct" means for it, with our notes from running it.</p>
{tool_cards()}
<div class=callout>
<h3>Why AudioSilo matched every book in {took(RUNTIME.get('audiosilo'))}</h3>
<p>The other tools ask a web service for every book: each search is a round trip to Audible or Goodreads, often
several per book, and most pause between books so they aren't blocked. AudioSilo's mirror mode downloads its whole
community database once (about 320,000 recordings in one file), so matching is a query on the same disk, with no
network and nothing to wait for. The trade-off is coverage: it can only find what the community has added.</p>
{f"<p>Run against its online service instead, the same {len(books):,} books took {took(RUNTIME['audiosilo_online'])}: every book's lookup then makes the round trip to the service.</p>" if RUNTIME.get("audiosilo_online") else ""}
</div>
</section>

<section id=lf>
<h2>Where {html.escape(lf_title)} went wrong</h2>
{lf_findings()}
</section>

<section id=method>
<h2>How it was tested</h2>
{METHOD}
<details class=more><summary>Setup per tool</summary>{SETUP}</details>
</section>

<section id=books>
<h2>Every book</h2>
<p class=sub>Each book's original tags, its right answer and what every tool left on it, field by field, with
each tool's verdict. Filter by any tool's verdict, or combine two: {html.escape(lf_title)} "Wrong book" with another
tool "Fully correct" shows where that tool did better.</p>
<p class=small><a href="{DOWNLOAD_NAME}" download>Download every book as JSON</a> (the tags, the right answer and every
tool's verdict, pick and what it left on the book){f' · <a href="{html.escape(opts.mock_url)}" rel=noopener>Download the mock files</a> (each book as one second of silence carrying its original tags, at its folder path)' if opts.mock_url else ''}.</p>
<div class=controls>
  <input type=search id=q placeholder="Search a folder, title, author or ASIN" aria-label="Search books">
  <select id=tool aria-label="Tool">{tool_options}</select>
  <select id=v aria-label="Its verdict">{VERDICT_OPTIONS}</select>
  <span class=lab>and</span>
  <select id=tool2 aria-label="Another tool"><option value="">another tool</option>{tool_options}</select>
  <select id=v2 aria-label="Its verdict">{VERDICT_OPTIONS}</select>
  <button id=collapse type=button>Collapse all</button>
  <span id=count></span>
</div>
<div id=list><p class=muted>Loading…</p></div>
<div class=pager><button id=prev>Previous</button><span id=page class="muted small"></span><button id=next>Next</button></div>
</section>

<section id=help>
<h2>Help improve this comparison</h2>
<p class=sub>Every tool is scored the same way, on the same books.</p>
<div class=help>
<a href="{issue_url('Benchmark: re-run ', RERUN_BODY)}" rel=noopener><b>Ask for a re-run</b><span>A tool has a newer version, or a setting worth testing.</span></a>
<a href="{issue_url('Benchmark: add ', ADD_BODY)}" rel=noopener><b>Suggest a tool</b><span>Another matcher that should be on this page.</span></a>
<a href="{issue_url('Benchmark: wrong result for ', REPORT_BODY)}" rel=noopener><b>Report a wrong result</b><span>Think a book was judged wrongly, or its expected answer is off? Tell us which book and we'll check it again.</span></a>
<a href="https://github.com/{html.escape(opts.repo)}/issues/new?template=benchmark_add_books.yml" rel=noopener><b>Add your books</b><span>Audiobooks whose tags were never edited. It takes each file's path, length and tags (one ffprobe command), never the audio.</span></a>
</div>
</section>
</main>
<footer><div class=wrap>Built from the benchmark run of {today}. The book list loads in your browser and needs no server.</div></footer>
<script>
const DATA_GZ = "{payload}";
const ORDER = {json.dumps([n for n, _ in ALL_TOOLS])};
const TOOL_NAMES = {json.dumps({n: display(l)[0] for n, l in ALL_TOOLS}, ensure_ascii=False)};
const SHORTS = {json.dumps(SHORT)};
const V = {json.dumps(VERDICT, ensure_ascii=False)};
const SOURCE = {json.dumps({"applied": "applied to the book in a library", "hand": "confirmed by hand"})};
const LF = {json.dumps(lf_title)};
const REPORT = {json.dumps(f"https://github.com/{opts.repo}/issues/new?")};
const REPORT_BODY = {json.dumps(REPORT_BODY)};
{JS}
</script>
</body>
</html>
"""
open(opts.out, "w", encoding="utf-8").write(page)
print(f"{opts.out}: {len(rows)} books, {len(page) / 1e6:.1f} MB")
