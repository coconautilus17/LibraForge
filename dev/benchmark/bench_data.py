"""The benchmark's one view of its data: which books, which runs, which audit.

Every script after the runs (answers.py, audit_check.py, reaudit_sample.py, geo.py,
report.py) reads the same manifest through this module, so they can't disagree on which
files make up a benchmark.

data/manifest.json (gitignored like the rest of data/; manifest.example.json shows the shape):

  books     the dataset (collect.py / dedupe.py output)
  commit    the LibraForge build its LibraForge run used
  runs      per tool: "rows" (the run's jsonl), optional "time" (its total runtime in
            seconds, default the rows file with .time), "online_time" (AudioSilo against
            its online service), "folders_from" (an older dataset whose folders the
            run reports: its books are found again by their original tags and runtime),
            "version" and "date" (the tool's version and the day of the run, shown on the page)
  audit     "verdicts" (the hand verdict files' folder), "hand" (audit.py's output),
            "judged_runs" (per tool, the run the hand verdicts were made on when its
            current run is newer), "extra" (later hand judgments: "<folder>\t<listing>\t
            right|other|wrong"), "final" (audit_check.py's output, what the page shows),
            "reaudit" (the second-audit samples and findings)
  answers   every book's right answer: its confirmed listing's catalog record (answers.py)
  rights    Audible's sales rights for every confirmed answer (geo.py rights)
  geo       the summary of answers Audible's search hid where the runs were made (geo.py summary)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# Every tool on the page, in its column order: run name, short code (verdict files,
# notes), name, and how it was run.
TOOLS = [
    ("public_gr", "LF", "LibraForge", "public catalog + Goodreads"),
    ("audiosilo", "AS", "AudioSilo", "mirror mode"),
    ("absqm", "ABS", "Audiobookshelf", "Quick Match"),
    ("grimmory", "GRM", "Grimmory", "Audible first"),
    ("rmab", "RMAB", "ReadMeABook", "Bulk Import"),
    ("bo", "BO", "BookOrbit", "default providers"),
    ("beets", "BEETS", "beets", "audible plugin"),
]
TOOL_NAMES = [t[0] for t in TOOLS]
SHORT = {t[0]: t[1] for t in TOOLS}
FIELDS = ("title", "author", "narrator", "series", "sequence")

# The tags a matcher reads. Everything else (comments, descriptions, encoder, DRM and
# store fields) says nothing about matching, can be someone's writing, and can say where
# a file came from, so nothing published carries it.
MATCHING_TAGS = {"title", "subtitle", "artist", "album_artist", "albumartists", "album", "sort_album", "composer",
                 "narratedby", "series", "series-part", "part", "mvnm", "mvin", "movement", "grouping", "track", "disc",
                 "date", "releasetime", "genre", "language", "publisher", "label", "asin", "audible_asin", "isbn"}


def public_tags(tags):
    return {k: v for k, v in (tags or {}).items() if k.lower() in MATCHING_TAGS and v not in (None, "")}


def path(name):
    """A data file: an absolute path, a path from here that exists, or a name in data/."""
    return name if os.path.isabs(name) or os.path.exists(name) and os.sep in name else os.path.join(DATA, name)


def rows_of(name):
    return {r["folder"]: r for r in map(json.loads, open(path(name), encoding="utf-8"))}


def identity(book):
    return json.dumps([book["tags"], round(book["minutes"], 3)], sort_keys=True)


def answer_fields(record):
    """A listing record as the fields a book is checked on; "series" is every series it is in."""
    return {"asin": record["asin"], "title": record["title"], "subtitle": record["subtitle"],
            "author": ", ".join(record["authors"]), "narrator": ", ".join(record["narrators"]),
            "series": record["series"], "minutes": record["minutes"]}


class Benchmark:
    def __init__(self, manifest="manifest.json", answers=True):
        """Every book gets "answer" (answer_fields of its confirmed listing, or None), "asin" (that
        listing's, or "") and "answer_source" from the manifest's answers."""
        self.manifest_path = path(manifest)
        self.m = json.load(open(self.manifest_path))
        self.books = json.load(open(path(self.m["books"])))
        self.by_folder = {b["folder"]: b for b in self.books}
        self._runs = {}
        if answers:
            known = json.load(open(self.file("answers")))
            for b in self.books:
                a = known.get(b["folder"]) or {}
                b["answer"] = answer_fields(a["record"]) if a.get("record") else None
                b["asin"] = b["answer"]["asin"] if b["answer"] else ""
                b["answer_source"] = a.get("source") if b["answer"] else "none"

    def file(self, key, *sub):
        """A data file the manifest names (audit.final, rights...)."""
        node = self.m[key]
        for k in sub:
            node = node[k]
        return path(node)

    def runs(self, tool):
        """{folder: the tool's raw row}, folders as the dataset has them now."""
        if tool not in self._runs:
            spec = self.m["runs"][tool]
            rows = rows_of(spec["rows"])
            if spec.get("folders_from"):
                now = {identity(b): b["folder"] for b in self.books}
                moved = {b["folder"]: now[identity(b)] for b in json.load(open(path(spec["folders_from"])))
                         if identity(b) in now}
                rows = {moved.get(f, f): r for f, r in rows.items()}
            self._runs[tool] = rows
        return self._runs[tool]

    def runtime(self, tool, online=False):
        spec = self.m["runs"].get(tool) or {}
        name = spec.get("online_time") if online else spec.get("time") or spec.get("rows", "").replace(".jsonl", ".time")
        if not name or not os.path.exists(path(name)):
            return None
        return float(open(path(name)).read().split()[0])


def pick(tool, row):
    """The listing the tool chose for a book, written or held: its ASIN, else (AudioSilo from 2.6)
    "isbn:..." or "work:..."; "" when it chose none."""
    row = row or {}
    if tool == "bo":
        asin = (row.get("asin") or "").upper()
        return "" if asin == "NOREALASIN" else asin
    m = row.get("match") or {}
    if tool == "public_gr":
        if row.get("status") != "matched" and "below minimum" in (row.get("skip_reason") or ""):
            return ""  # refused, not held: the row carries the closest candidate it turned down
        return (row.get("series_match_asin") or m.get("asin")
                or (row.get("different_edition") or {}).get("match_asin") or "").upper()
    asin = (m.get("asin") or "").upper()
    return asin or (f"isbn:{m['isbn']}" if m.get("isbn") else f"work:{m['work']}" if m.get("work") else "")


def result(tool, file, row):
    """(the fields the book ends up with, or None when the tool wrote nothing; the ASIN it wrote).

    file is the book's own tags as LibraForge reads them (its run's "local"). Each tool
    writes its own way:
      LibraForge  full: the listing's fields (a blank one too); another recording keeps the
                  file's narrator and ASIN; series-only: the file's details with the listing's series
      AudioSilo   confident: fills only blank fields; review and none write nothing
      ABS, Grimmory, beets: the listing's non-blank fields over the file's
      BookOrbit   its own record as fetched
      ReadMeABook writes nothing; only its pick is checked"""
    if not row:
        return None, ""
    if tool == "bo":
        if not ((row.get("asin") or "").upper() not in ("", "NOREALASIN") or row.get("goodreads")):
            return None, ""
        return {k: row.get(k) or "" for k in FIELDS}, row.get("asin") or ""
    m = row.get("match") or {}
    if tool == "public_gr":
        if row.get("status") != "matched":
            return None, ""
        if row.get("mode") == "series_only":
            # Series-only writes its own title clue, which a folder name can replace.
            return {**file, "title": m.get("title") or file["title"], "series": m.get("series") or "",
                    "sequence": m.get("sequence") or ""}, row.get("series_match_asin") or ""
        out = {k: m.get(k) or "" for k in FIELDS}
        edition = row.get("different_edition")
        if edition:  # another recording: the file keeps its own narrator and ASIN
            out["narrator"] = edition.get("local_narrator") or file["narrator"]
            return out, ""
        return out, m.get("asin") or ""
    if tool == "audiosilo":
        if row.get("outcome") not in ("auto", "own_asin"):
            return None, m.get("asin") or ""
        return {k: file[k] or m.get(k) or "" for k in FIELDS}, m.get("asin") or ""
    if row.get("status") != "matched":
        return None, ""
    return {k: m.get(k) or file[k] for k in FIELDS}, m.get("asin") or ""
