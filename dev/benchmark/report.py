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
# A hand verdict as the class the book list shows.
AUDIT_CLASS = {"C": "correct", "S": "correct", "E": "recording", "P": "partial", "W": "wrong", "s": "wrong",
               "H": "correct-held", "h": "wrong-held", "N": "none"}

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


# What the field checks found, in words, for a book's "reviewed by hand" line.
PROBLEM = {
    "narrator_missing": "no narrator", "narrator_placeholder": "a placeholder (\"Misc\") as narrator",
    "narrator_is_author": "the author as narrator", "series_nameless": "a series number with no series name",
    "series_junk": "a junk series name", "series_missing": "no series", "number_for_range": "one number on a multi-book set",
    "number_decimal_dropped": "the decimal series number dropped", "number_missing": "no series number",
    "number_wrong": "the wrong series number", "series_invented": "a series made from the title",
    "title_junk": "a junk title", "title_is_series": "the series name as the title", "title_series_suffix": "the series tacked onto the title",
    "title_cut": "the title cut short", "title_differs": "another title", "author_doubled": "the authors doubled",
    "author_junk": "a junk author", "author_missing": "a co-author missing",
}
SHORT = {"public_gr": "LF", "audiosilo": "AS", "absqm": "ABS", "grimmory": "GRM", "rmab": "RMAB", "bo": "BO", "beets": "BEETS"}


NAMES = {"LF": "LibraForge", "AS": "AudioSilo", "ABS": "Audiobookshelf", "GRM": "Grimmory", "RMAB": "ReadMeABook",
         "BO": "BookOrbit", "BEETS": "beets"}


def readable(note):
    """A note as a reader of the page reads it: tool names in full, no tracker references."""
    note = re.sub(r"\s*\(#\d{3}\)", "", note or "")
    return re.sub(r"\b(LF|AS|ABS|GRM|RMAB|BO|BEETS)\b", lambda m: NAMES[m.group(1)], note)


def checked_note(row):
    """The hand note (the book's identity and recording) plus what the field checks found per tool."""
    found = "; ".join(f"{SHORT.get(tool, tool)} {', '.join(PROBLEM.get(p, p) for p in problems)}"
                      for tool, problems in (row.get("f") or {}).items())
    note = row.get("note") or ""
    return readable((note + (" | " if note and found else "") + ("Checked: " + found if found else "")).strip())


def verdict(name, folder):
    """[class, asin] for a tool on a book: its audited verdict and the listing it chose."""
    code = (audit.get(folder) or {}).get("v", {}).get(name)
    return [AUDIT_CLASS[code] if code else "not run", pick(name, bench.runs(name).get(folder))]


rows = []
for folder, book in books.items():
    run = runs.get(folder) or {}
    match = run.get("match") or {}
    final = book.get("final") or {}
    hand = (audit or {}).get(folder) or {}
    rows.append({
        "f": folder, "file": book.get("file", ""), "min": round(book.get("minutes") or 0, 1),
        "recycled": bool(book.get("recycled")),
        "tags": clean_tags(book.get("tags")),
        "clues": {_CLUE_LABELS.get(k, k): ", ".join(v) if isinstance(v, list) else v
                  for k, v in (run.get("clues") or {}).items() if k in _CLUE_LABELS},
        "planned": run.get("planned_queries") or [],
        "ref": {"asin": book.get("asin") or "", **{k: final.get(k, "") for k in ("title", "author", "narrator", "series", "sequence")},
                "manual": bool(book.get("manual"))},
        "status": run.get("status", "not run"), "skip": run.get("skip_reason", ""), "score": run.get("score"),
        "mode": run.get("mode", ""), "dur": run.get("duration_status", ""),
        "match": {k: match.get(k, "") for k in ("asin", "title", "subtitle", "author", "narrator", "series", "sequence",
                                                "year", "publisher", "isbn", "duration_minutes", "duration_diff_pct")} if match else {},
        "edition": run.get("different_edition") or None, "series_asin": run.get("series_match_asin", ""),
        "cls": verdict(opts.run_name, folder)[0], "fields": None,
        "cur": checked_note(hand),
        "q": searches(run.get("log")), "cand": candidates(run.get("log")), "trace": trace(run.get("log")),
        # Every other tool's outcome and pick for the same book: [class, asin].
        "o": {name: verdict(name, folder) for name, _ in others},
    })

# The downloadable book list: the same books as the page, each with every tool's verdict,
# pick and what it left on the book (bench_data.result), so anyone can recount the page.
CODE_MEANING = {"C": "the right book, every field right", "S": "series-only write, the right series",
                "E": "the right book, another recording's details", "P": "the right book, a field off",
                "W": "the wrong book", "s": "series-only write, the wrong series", "H": "held for review, the right pick",
                "h": "held for review, a wrong pick", "N": "nothing written"}
download = []
for folder, book in books.items():
    own = (runs.get(folder) or {}).get("local") or {}
    own = {k: own.get(k) or "" for k in bench_data.FIELDS}
    answer = (book.get("final") if book.get("asin") else book.get("expect")) or {}
    hand = audit.get(folder) or {"v": {}, "f": {}}
    tools = {}
    for t, _, name, _ in TOOL_ROWS:
        wrote, _ = result(t, own, bench.runs(t).get(folder))
        tools[name] = {"verdict": hand["v"].get(t, ""), "pick": pick(t, bench.runs(t).get(folder)),
                       "wrote": None if t == "rmab" else wrote, "field_problems": (hand.get("f") or {}).get(t, [])}
    download.append({
        "folder": folder, "file": book.get("file", ""), "minutes": round(book.get("minutes") or 0, 1),
        "tags": bench_data.public_tags(book.get("tags")) if opts.public else book.get("tags"),
        "answer": {"from": "confirmed listing" if book.get("asin") else "file name" if book.get("expect") else "none",
                   "asin": book.get("asin") or "", **{k: answer.get(k, "") for k in bench_data.FIELDS}},
        "note": readable(hand.get("note", "")), "tools": tools})
DOWNLOAD_NAME = "benchmark-books.json"
json.dump({"commit": opts.commit, "date": datetime.date.today().isoformat(), "verdict_codes": CODE_MEANING,
           "books": download}, open(os.path.join(os.path.dirname(os.path.abspath(opts.out)), DOWNLOAD_NAME), "w"),
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
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


# How many books each tool searches at once, and whether that can be changed, from each
# tool's source. LibraForge's is run.sh's workers argument (4 in these runs, 5 with Goodreads).
CONCURRENCY = {
    "public": ("4", "yes, Search workers 1 to 30"),
    "public_gr": ("5", "yes, Search workers 1 to 30"),
    "public_gr_old": ("5", "yes, Search workers 1 to 30"),
    "audiosilo": ("2", "no, a match run uses 2 workers"),
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
        "how": "Sends the path, the tags and the runtime together. Books whose tags carry an ASIN or ISBN are matched "
               "at scan. Applies a match only at score 90 or more, 10 ahead of the next candidate, with an ASIN or ISBN "
               "and the runtime within 10%.",
        "review": "Holds everything else for review",
        "note": "Part of its own metadata project. The whole database can be downloaded locally (mirror mode, about "
                "2 GB, refreshed daily), so matching is fast and never polls their service. Coverage is only what the "
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
    "rmab": "Picks a listing per book and writes nothing, to files or a library. Scored on whether the pick is the book.",
    "bo": "Fetches the listing into its own records (title, authors, narrators, series), not into the files.",
    "beets": "Writes the listing's fields to the files when it accepts the match; skips the rest.",
}
ISSUE_LABELS = {
    "narrator_missing": "No narrator written: the file had none and the match didn't supply one (mostly Goodreads, which lists no narrators)",
    "number_missing": "A series written without its book number, though the file or folder had it",
    "number_decimal_dropped": "A decimal book number (3.5, 14.5) dropped",
    "title_cut": "A box set's range cut off the title (\"Box Set (25-28)\" written as \"Box Set\")",
    "title_series_suffix": "The series left on the end of the title (\"9d6 (Caverns & Creatures)\")",
    "narrator_is_author": "The author's name in the narrator field taken for another recording, and kept as the narrator",
    "narrator_placeholder": "A placeholder (\"Misc\") in the narrator field taken for another recording, and kept",
    "series_nameless": "A book number written with no series name (\"#451\" from \"Fahrenheit 451\")",
    "title_junk": "A file or track name kept as the title (\"01 Monster Core\")",
    "number_for_range": "One book number written on a multi-book set",
    "series_missing": "No series written for a book in one",
    "series_junk": "A junk series name (\"Discworld, #27; Rincewind #7\")",
    "author_missing": "A co-author missing",
    "title_differs": "Another title written (a Goodreads edition, or one story of a collection)",
    "title_is_series": "The series name written as the title",
    "series_invented": "A series made up from the title",
    "number_wrong": "The wrong book number",
    "other_recording": "Another recording's narrator written on a file that had no narrator tag",
    "wrong_book": "The wrong book written",
    "wrong_series": "The wrong series written in a series-only match",
}


def audit_counts(name):
    c = Counter(audit[f]["v"][name] for f in audit if name in audit[f]["v"])
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
    <dt>Speed</dt><dd>{speed(name, s['books'], conc, editable)}</dd>
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
    items = "".join(f"<li><b>{n:,}</b><span>{html.escape(ISSUE_LABELS.get(k) or PROBLEM.get(k, k))}</span></li>"
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
own sales-rights data, {geo["hidden"]:,} of the {geo["confirmed"]:,} books with a confirmed listing were hidden from
search where these runs were made ({share(geo["hidden"], geo["books"]):.1f}% of all books). {geo["hidden_with_asin"]:,} of those
files carry their own ASIN, which a tool can look up directly.</p>
<p>That is the margin of error this adds: run where those books are sold, a tool that searches Audible could do
better on at most these {geo["hidden"]:,} books, {share(geo["hidden"], geo["books"]):.1f}% of the library. On them,
{html.escape(lf_title)} got {rh.get(opts.run_name, 0)} right, AudioSilo {rh.get("audiosilo", 0)} (it reads its own database, so
search didn't hide anything from it), Audiobookshelf {rh.get("absqm", 0)}, BookOrbit {rh.get("bo", 0)},
Grimmory {rh.get("grimmory", 0)}, ReadMeABook {rh.get("rmab", 0)} and beets {rh.get("beets", 0)}.</p>"""
reaud = audit_meta.get("reaudit", {})
va = audit_meta.get("validation", {})
METHOD = f"""
<p>{len(books):,} audiobooks in their original state, before any matching: the tags LibraForge saved before it first
wrote anything to a library's books, or another library's files as they were. Each book was matched again from those
original tags, its folder path and its runtime, with no login, against the live catalog.</p>
<p>Every tool got the same books, as silent files carrying the original tags at the books' real folder paths (and,
for tools that check runtime, as long as the real book), and each was run the way its own documentation suggests.</p>
<h3>How results were judged</h3>
<div class=callout><p><b>Checked with Claude, under human supervision.</b> The book-by-book review was done with
Claude, an AI model, following one written set of rules for every tool and every book. A person supervised the
work and checked random books by hand along the way, but did not personally review every one of the
{len(books):,} books. The second audit below measures how often the review got a verdict wrong.</p></div>
<p>Every book and every tool's result on it was audited. Whether a tool picked the right book, another recording of
it or the wrong book (and, when it held its pick, whether the held pick was right) was decided by hand, book by book.
What the tool then left on the book was checked by script against that tool's own way of writing, so one rule applies
to every tool: a field is off when the book ends up with something wrong in it (written, or kept from the file) or
without something it is known to have. A tool that keeps the file's own details is judged on the book as it ends up.</p>
{f'''<p>To check the audit, {reaud.get("books", 0)} random books were audited a second time:
{share(reaud.get("wrong", 0), reaud.get("verdicts", 0)):.1f}% of verdicts were wrong, and every kind of error found
was corrected for all books. A fresh {va.get("books", 0)} books audited after that had
{share(va.get("wrong", 0), va.get("verdicts", 0)):.1f}% wrong, also corrected.</p>''' if reaud else ""}
{GEO_HTML}
"""

SETUP = """<ul class=setup>
<li><b>LibraForge</b>: Metadata Forge's matcher over the files, Audible public catalog with the Goodreads fallback on,
5 search workers.</li>
<li><b>AudioSilo</b> (v2.5.1): "Match automatically" over the library, in mirror mode (a local copy of the community
database). Confident matches count as written, "to review" as held.</li>
<li><b>Audiobookshelf Quick Match</b> (v2.35.1, Audible US provider): Quick Match per book, which takes the first
Audible result, or the file's ASIN when it has one. One book at a time, as Match All does.</li>
<li><b>BookOrbit</b>: a library bulk metadata fetch with its default providers.</li>
<li><b>beets</b> (beets 2.14 with the beets-audible plugin, recommended settings): <code>beet import -q</code>, which
applies strong matches and skips the rest. It was given each book's real runtime, since it scores on track length.</li>
<li><b>Grimmory</b> (v3.5.0): a library metadata refresh with Audible enabled and first for every field (Goodreads,
then Google behind it), applied without review.</li>
<li><b>ReadMeABook</b> (v1.2.12): the Bulk Import scan, which picks an Audible match per book. It groups folders by
their tags, so books it merged into another folder count as nothing written. Its scan returns no series.</li>
</ul>"""

CLASS_OPTIONS = ('<option value="">Any outcome</option><option value="correct">Fully correct</option>'
                 '<option value="recording">Right book, other recording</option><option value="partial">Right book, a field off</option>'
                 '<option value="wrong">Wrong book</option><option value="correct-held">Held, right pick</option>'
                 '<option value="wrong-held">Held, wrong pick</option><option value="none">Nothing written</option>')

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
.hero{padding:36px 0 20px}.controls{top:52px}}
"""

JS = r"""
const PAGE = 50;
let rows = [], view = [], page = 0;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const LABEL = {"correct":"Fully correct","correct-held":"Held, right pick","wrong":"Wrong book","wrong-held":"Held, wrong pick",
  "none":"Nothing written","recording":"Right book, other recording","partial":"Right book, a field off","not run":"Not run"};

function kv(obj, check) {
  const keys = Object.keys(obj).filter((k) => obj[k] !== "" && obj[k] !== null && obj[k] !== false);
  if (!keys.length) return '<p class="muted small">none</p>';
  return '<table class=kv>' + keys.map((k) => {
    const mark = check && k in check && check[k] !== null ? (check[k] ? ' <span class=ok>&#10003;</span>' : ' <span class=no>&#10007;</span>') : "";
    return `<tr><th>${esc(k)}</th><td>${esc(obj[k])}${mark}</td></tr>`;
  }).join("") + "</table>";
}

function others(r) {
  const names = Object.keys(TOOLS);
  if (!names.length) return '<p class="muted small">none compared</p>';
  return '<table class="list tools-list"><colgroup><col><col><col></colgroup><thead><tr><th>Tool</th><th>Outcome</th><th>Picked</th></tr></thead><tbody>' + names.map((n) => {
    const [cls, asin] = r.o[n] || ["not run", ""];
    const same = asin && r.match && asin === r.match.asin ? ' <span class="muted">(same pick)</span>' : "";
    const pick = asin ? `<a href="https://www.audible.com/pd/${encodeURIComponent(asin)}" rel=noopener>${esc(asin)}</a>${same}` : "";
    return `<tr><td>${esc(TOOLS[n])}</td><td><span class="badge b-${esc(cls.split(" ")[0])}">${esc(LABEL[cls] || cls)}</span></td><td>${pick}</td></tr>`;
  }).join("") + "</tbody></table>";
}

const norm = (v) => String(v ?? "").toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").trim();
const head = (v) => norm(String(v ?? "").split(/[:,(\[]/)[0]);
const names = (v) => String(v ?? "").split(/,|;|&| and /).map(norm).filter(Boolean);
const num = (v) => { const m = String(v ?? "").match(/\d+(?:\.\d+)?/); return m ? parseFloat(m[0]) : null; };

// Does what LibraForge wrote agree with the right answer? true / false / null (nothing to compare).
function agrees(field, wrote, answer, fileMinutes) {
  if (field === "Runtime") return wrote && fileMinutes ? Math.abs(wrote - fileMinutes) / fileMinutes <= 0.03 : null;
  if (!norm(wrote) || !norm(answer)) return null;
  if (field === "Title") return head(wrote) === head(answer) || norm(wrote) === norm(answer);
  if (field === "Book") return num(wrote) !== null && num(wrote) === num(answer);
  if (field === "Author" || field === "Narrator") { const a = names(answer); return names(wrote).some((n) => a.includes(n)); }
  if (field === "ASIN") return norm(wrote) === norm(answer);
  return norm(wrote) === norm(answer) || norm(wrote).startsWith(norm(answer)) || norm(answer).startsWith(norm(wrote));
}

function comparison(r) {
  const t = r.tags || {}, a = r.ref || {}, m = r.match || {}, c = r.clues || {};
  const written = r.status === "matched";
  const seriesOnly = written && r.mode === "series_only";
  const edition = written && r.edition;
  const fields = [
    ["Title", t.title, a.title, m.title ? m.title + (m.subtitle ? ": " + m.subtitle : "") : ""],
    ["Author", t.artist || t.album_artist, a.author, m.author],
    ["Narrator", t.composer || t.narrator, a.narrator, m.narrator],
    ["Series", t.series || t.mvnm || t.grouping || c.series, a.series, m.series],
    ["Book", t["series-part"] || c.book, a.sequence, m.sequence],
    ["Runtime", r.min ? r.min + " min" : "", "", m.duration_minutes ? Math.round(m.duration_minutes) + " min" : ""],
    ["ASIN", t.asin || c.asin, a.asin, m.asin],
  ];
  const kept = (f) => (seriesOnly && !["Series", "Book"].includes(f)) || (edition && ["Narrator", "ASIN"].includes(f));
  const rowsHtml = fields.map(([f, file, answer, wrote]) => {
    let cell;
    const lab = `data-label="${esc(LF)} wrote"`;
    if (!written) cell = `<td class="na" ${lab}>nothing written</td>`;
    else if (kept(f)) cell = `<td class="na" ${lab}>kept the file's</td>`;
    else {
      const ok = agrees(f, f === "Runtime" ? (m.duration_minutes || 0) : wrote, answer, r.min);
      const mark = ok === true ? '<span class=ok>&#10003;</span> ' : ok === false ? '<span class=no>&#10007;</span> ' : "";
      cell = `<td class="${ok === false ? "bad" : ok === true ? "good" : ""}" ${lab}><span>${mark}${esc(wrote) || '<span class=muted>none</span>'}</span></td>`;
    }
    const id = f === "ASIN" ? " id-cell" : "";
    return `<tr class="${id}"><th>${f}</th><td data-label="File's tags">${esc(file) || '<span class=muted>none</span>'}</td><td data-label="Right answer">${esc(answer) || '<span class=muted>not known</span>'}</td>${cell}</tr>`;
  }).join("");
  const how = !written ? "" : seriesOnly ? " (series only)" : edition ? " (another recording: the file's narrator kept)" : "";
  return `<table class=cmp><colgroup><col class=c-label><col><col><col></colgroup><thead><tr><th></th><th>The file's tags</th><th>The right answer</th><th>What ${esc(LF)} wrote${how}</th></tr></thead><tbody>${rowsHtml}</tbody></table>`;
}

function detail(r) {
  const q = r.q.length ? '<table class=list><thead><tr><th>Search</th><th>Query</th><th>Results</th></tr></thead><tbody>' +
    r.q.map(([k, s, n]) => `<tr><td>${esc(k)}</td><td>${esc(s)}</td><td>${esc(n ?? "")}</td></tr>`).join("") + "</tbody></table>" : '<p class="muted small">none</p>';
  const c = r.cand.length ? '<table class=list><thead><tr><th>Score</th><th>Title</th><th>ASIN</th><th>Runtime</th><th>Book</th><th>Mode</th></tr></thead><tbody>' +
    r.cand.map((x) => `<tr><td>${esc(x.score)}</td><td>${esc(x.title)}</td><td>${esc(x.asin)}</td><td>${esc(x.duration)}</td><td>${esc(x.sequence)}</td><td>${esc(x.mode)}</td></tr>`).join("") + "</tbody></table>" : '<p class="muted small">none above the cut</p>';
  const [note, checked] = (r.cur || "").split(/\s*\|\s*Checked:\s*/);
  const why = note || r.skip || "";
  const facts = {score: r.score, mode: r.mode, runtime: r.dur, "other recording": r.edition ? `${r.edition.match_asin || ""} (listing narrator ${r.edition.match_narrator || "?"})` : "", "series from": r.series_asin};
  return `<div class=detail>
  <div class="verdict b-${esc(r.cls.split(" ")[0])}"><b>${esc(LABEL[r.cls] || r.cls)}</b>${why ? `<span>${esc(why)}</span>` : ""}${checked ? `<small>Field checks: ${esc(checked)}</small>` : ""}</div>
  <p class="muted small">${esc(r.file)} · ${r.min} min</p>
  <div class=scroll-x>${comparison(r)}</div>
  <h3>Every tool on this book</h3>${others(r)}
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
    const pick = r.match && r.match.title ? `${r.match.title}${r.match.author ? " · " + r.match.author : ""}${r.match.asin ? " · " + r.match.asin : ""}` : (r.skip || r.status);
    return `<details class=book data-i="${rows.indexOf(r)}"><summary><span class=path>${esc(r.f)}</span>
      <span class="badge b-${esc(r.cls.split(" ")[0])}">${esc(LABEL[r.cls] || r.cls)}</span><span class=pick>${esc(pick)}</span></summary></details>`;
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
  const q = $("q").value.trim().toLowerCase(), cls = $("cls").value, mode = $("mode").value;
  const tool = $("tool").value, tcls = $("tcls").value;
  view = rows.filter((r) => {
    if (cls && r.cls !== cls) return false;
    if (mode === "edition" ? !r.edition : mode && r.mode !== mode) return false;
    if (tool && tcls && (r.o[tool] || ["not run"])[0] !== tcls) return false;
    if (!q) return true;
    return [r.f, r.match.title, r.match.author, r.match.asin, r.ref.asin, r.ref.title, r.tags.title, r.tags.artist, r.tags.album]
      .some((v) => String(v || "").toLowerCase().includes(q));
  });
  page = 0; render();
}

(async () => {
  const bytes = Uint8Array.from(atob(DATA_GZ), (c) => c.charCodeAt(0));
  const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
  rows = JSON.parse(text);
  // Filters live in the address (#q=...&cls=...), so a filtered view can be linked to.
  const ids = ["q", "cls", "mode", "tool", "tcls"];
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

tool_options = "".join(f'<option value="{html.escape(n)}">{html.escape(display(l)[0])}</option>' for n, l in others)
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
<ul class=chips><li>{today}</li><li>{len(books):,} books</li><li>{n_tools} tools</li>{f'<li>{html.escape(lf_title)} build {html.escape(opts.commit)}</li>' if opts.commit else ''}</ul>
</header>

<section id=glance>
<h2>At a glance</h2>
<p class=sub>What each tool left on the whole library, best first. Writes is how much of the library it wrote;
fully correct and right book are shares of what it wrote.</p>
{glance()}
<div class=explain>
<div><b>Fully correct</b>The right book, and every field it ends up with is right.</div>
<div><b>Right book, a field off</b>The right book, but a field is wrong or missing, or another recording's narrator was written.</div>
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
<h3>Why AudioSilo matched every book in about a minute</h3>
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
<p class=sub>Each book with its original tags, the right answer, what {html.escape(lf_title)} read, searched and wrote,
and every other tool's outcome. Combine the filters, for example {html.escape(lf_title)} "Wrong book" with another
tool "Fully correct", to see where it did better.</p>
<p class=small><a href="{DOWNLOAD_NAME}" download>Download every book as JSON</a> (the tags, the right answer and every
tool's verdict, pick and what it left on the book){f' · <a href="{html.escape(opts.mock_url)}" rel=noopener>Download the mock files</a> (each book as one second of silence carrying its original tags, at its folder path)' if opts.mock_url else ''}.</p>
<div class=controls>
  <input type=search id=q placeholder="Search a folder, title, author or ASIN" aria-label="Search books">
  <span class=lab>{html.escape(lf_title)}</span>
  <select id=cls aria-label="{html.escape(lf_title)}'s outcome">{CLASS_OPTIONS}</select>
  <select id=mode aria-label="How it matched"><option value="">Any match</option><option value="full">Full match</option><option value="series_only">Series only</option><option value="edition">Other recording</option></select>
  <span class=lab>Compare with</span>
  <select id=tool><option value="">No other tool</option>{tool_options}</select>
  <select id=tcls aria-label="The other tool's outcome">{CLASS_OPTIONS}<option value="not run">Not run</option></select>
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
const TOOLS = {json.dumps({n: display(l)[0] for n, l in others}, ensure_ascii=False)};
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
