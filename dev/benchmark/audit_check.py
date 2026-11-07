"""Check the hand-audit verdicts against what each tool's write rules leave on the book.

usage: audit_check.py [--manifest manifest.json] [--out disagreements.jsonl] [--write]

The final verdict takes only the book's identity from the hand audit (right book, another recording,
wrong book, held pick right or wrong); whether the tool wrote and which fields ended up wrong come
from the checks below.

Each tool's result is rebuilt from its raw record and the file's own tags (bench_data.result: how
each tool writes). The result is then checked field by field against the reference and the file,
and every book where those mechanical checks disagree with the hand verdict is listed for a second
look. --write saves the final verdicts to the manifest's audit.final, which the page shows.
"""
import argparse
import json
import os
import re
import unicodedata
import difflib
from collections import Counter

from bench_data import FIELDS, TOOL_NAMES as TOOLS, Benchmark, result

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", default="manifest.json")
ap.add_argument("--out", default="")
ap.add_argument("--write", action="store_true", help="write the final verdicts (hand identity + checked fields)")
opts = ap.parse_args()
bench = Benchmark(opts.manifest)
books = bench.books
audit = json.load(open(bench.file("audit", "hand")))
raw = {tool: bench.runs(tool) for tool in TOOLS}


def norm(x):
    x = unicodedata.normalize("NFKD", str(x or "").replace("\u2019", "'")).encode("ascii", "ignore").decode().replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()


def people(x):
    """The credited people, without roles (a translator or an introduction writer is not an author)."""
    parts = [n for n in re.split(r",|;|&| and ", str(x or "")) if not re.search(r"\b(translator|introduction|foreword|illustrator|adaptor)\b", n, re.I)]
    return [p for p in (norm(ROLE.sub("", n)) for n in parts) if p and p not in ("translator", "editor", "phd")]


def book_number(folder):
    """The book number the folder names ("Book 4 - ...", "...; Book 04; ...", "Vol. 4"), else None."""
    m = re.search(r"(?:^|[/;] ?)(?:Book|Vol\.?|Volume) (\d+(?:\.\d+)?)(?=$|[ ;/-])", folder)
    return float(m.group(1)) if m else None


# Titles no listing or publisher gives a book: file names, track names, tag noise.
JUNK = re.compile(r"\(unabridged\)|\bunabridged\b|_|\.m4b|\.mp3|^track\b|^chapter\b|opening credits|^audiobook\b"
                  r"|\((?:author|narrator|series|[^)]*\bseries)\)|^\d{1,3}\s*-\s", re.I)
AUTHOR_JUNK = re.compile(r"[()\[\]]")
GENRE_SERIES = {"litrpg", "gamelit", "fantasy", "science fiction", "audiobook", "progression fantasy"}
ASIN_LIKE = re.compile(r"^b0[a-z0-9]{8}$")


def bare(name):
    """A person's name without initials or degrees, for comparing "James A. Hunter" with "James Hunter"."""
    return " ".join(w for w in norm(name).split() if len(w) > 1 and w not in ("phd", "ph", "md", "dr"))


def same_people(a, b):
    """Whether two sets of bare names share a person, allowing a one-letter spelling slip ("Neal"/"Neil")."""
    return any(x == y or (len(x) > 6 and difflib.SequenceMatcher(None, x, y).ratio() >= 0.85) for x in a for y in b)
PLACEHOLDER = {"misc", "unknown", "various", "various artists", "audiobook", "full cast", "uncredited"}
# Narrators that are a placeholder, never a credit: wrong whenever they end up on a book.
FAKE_NARRATOR = {"misc", "unknown", "audiobook"}
ROLE = re.compile(r"\s*-\s*(translator|introduction|foreword|illustrator|adaptor|editor|afterword)\b.*$|\s*\((aka|translator)[^)]*\)", re.I)
OMNIBUS = re.compile(r"omnibus|box ?set|boxed|collection|compendium|pack|bundle", re.I)
STOP = {"the", "a", "an", "of", "and", "book", "in", "to", "on", "for", "series", "vol", "volume", "part", "saga", "trilogy"}


def number_of(x):
    x = norm(x).replace(" ", ".")
    try:
        return float(x)
    except ValueError:
        return x


def with_numbers(x):
    return {w.rstrip("s") for w in norm(x).split() if w not in STOP}


def words(x):
    return {w.rstrip("s") for w in norm(x).split() if w not in STOP and not w.isdigit()}


def title_cut(title, want):
    """True when the title is the start of the book's title and what was cut is its range of books."""
    t, w = norm(title), norm(want)
    if not t or not w.startswith(t + " "):
        return False
    return bool(re.search(r"\d+ (to |through )?\d+", w[len(t):]))


def same_series(series, title, ref_series, folder):
    """The series the folder's book number belongs to, also when the title is tacked on ("The Grand Tour: Jupiter")."""
    folder_series = folder.split("/")[-2] if folder.count("/") > 1 else ""
    got = words(series)
    for want in (words(ref_series), words(folder_series)):
        if want and want <= got and got - want <= words(title):
            return True
    return False


def checks(res, ref, file, known, listed, confirmed, folder, invents=True):
    """What the book ends up with that does not match it: a wrong value (written or kept) or a known
    one missing. known: every narrator the book is known to have; listed: those named by a listing of
    the book (not the file). Loose (file-name) references only judge the series, since their title and
    author come from a folder name."""
    out = []
    narr = norm(res["narrator"])
    authors = {bare(a) for a in people(res["author"])}
    if not narr and known:
        out.append("narrator_missing")
    elif narr in FAKE_NARRATOR:
        out.append("narrator_placeholder")
    elif narr and bare(narr) in authors and any(bare(n) != bare(narr) for n in listed):
        out.append("narrator_is_author")
    series, seq = norm(res["series"]), str(res["sequence"] or "").strip()
    ref_series = "" if norm(ref.get("series")) in GENRE_SERIES else ref.get("series") or ""
    number = book_number(folder)
    # A file-name reference names a "series" for a standalone book too ("Treasure Island; Book 01").
    if not confirmed and number in (None, 1.0) and words(ref_series) == words(ref.get("title") or res["title"]):
        ref_series = ""
    file_series = "" if ASIN_LIKE.match(norm(file["series"]).replace(" ", "")) else file["series"]
    want_series = ref_series or file_series
    want = str(ref.get("sequence") or "").strip()
    if number is None:  # the file's own number, also when it sits in the series text ("Odd Thomas, Book #0.5")
        own_number = re.search(r"#\s*(\d+(?:\.\d+)?)\s*$", file["series"]) or re.fullmatch(r"(\d+(?:\.\d+)?)", file["sequence"].strip())
        number = float(own_number.group(1)) if own_number else None
    if not re.fullmatch(r"\d+(\.\d+)?", want) and number is not None and not re.search(r"\d\s*-\s*\d", want):
        want = f"{number:g}"
    elif number is not None and re.fullmatch(r"\d+(\.\d+)?", want) and float(want) != number:
        want = ""  # the reference and the folder disagree: no number to check against
    whole = " ".join([ref.get("title") or "", file["title"], folder.rsplit("/", 1)[-1]])
    ranged = re.search(r"\b\d+\s*-\s*\d+\b", want) or re.search(r"\bbooks \d+\s*(-|to|&|,)\s*\d+|\bbooks? \d+-\d+\b|\(\d+-\d+\)", whole, re.I)
    if ranged and confirmed and str(ref.get("sequence") or "").strip() == seq:
        ranged = None  # the library numbers this box set the same way
    if seq and not series:
        out.append("series_nameless")
    elif series in GENRE_SERIES or ASIN_LIKE.match(series.replace(" ", "")) or re.search(r"#\s*\d+(\.\d+)?\s*;", res["series"]) or len(re.findall(r"#\s*\d", res["series"])) > 1:
        out.append("series_junk")
    elif want_series and not series:
        out.append("series_missing")
    elif series and ranged and re.fullmatch(r"\d+", seq) and not OMNIBUS.search(res["series"]):
        out.append("number_for_range")
    elif series and re.fullmatch(r"\d+\.\d+", want) and number_of(seq) != number_of(want):
        out.append("number_decimal_dropped")
    elif series and not seq and re.fullmatch(r"\d+", want) and not ranged:
        out.append("number_missing")
    elif series and re.fullmatch(r"\d+(\.\d+)?", seq) and re.fullmatch(r"\d+(\.\d+)?", want) and float(seq) != float(want) \
            and not OMNIBUS.search(res["series"]) and same_series(res["series"], res["title"], ref_series, folder):
        out.append("number_wrong")
    # Only a tool that builds its series from the title invents one; a listing's own series is real data.
    if invents and series and not want_series and series == norm(res["title"]):
        out.append("series_invented")
    title = res["title"]
    sole = float(want) if re.fullmatch(r"\d+(\.\d+)?", want) else None
    suffix = re.search(r"\(([^)]*)\)\s*$", title or "")
    allowed = words(ref.get("title")) | words(res["series"]) | words(ref_series) | words(folder)
    if title and (JUNK.search(title) or re.fullmatch(r"\s*(book|vol\.?|volume|part)\s*#?\s*\d+(\.\d+)?\s*", title, re.I)
                  or re.match(r"\d{1,3}\s+[a-z]", title, re.I) and not re.match(r"\d", ref.get("title") or file["title"])
                  or re.search(r"\bby\b.*\(\d{4}\)|^\[|\bunabridged\b", title, re.I)):
        out.append("title_junk")
    # A first book often shares its series' name, so book 1 needs a confirmed title that doesn't.
    elif title and with_numbers(title) == (words(res["series"]) or words(ref_series)) \
            and (sole not in (None, 1.0) or confirmed and words(ref.get("title")) and not words(ref.get("title")) & words(title)) \
            and words(ref.get("title")) != words(ref_series):
        out.append("title_is_series")
    elif suffix and words(suffix.group(1)) & words(res["series"] or ref_series) and not re.search(r"\)\s*$", ref.get("title") or ""):
        out.append("title_series_suffix")
    elif confirmed and title_cut(title, ref.get("title")):
        out.append("title_cut")
    elif title and confirmed and not (words(ref.get("title")) <= words(title)) and not (words(title) <= allowed):
        out.append("title_differs")
    names = people(res["author"])
    if len(names) != len(set(names)) or len({bare(n) for n in names}) < len(names):
        out.append("author_doubled")
    if AUTHOR_JUNK.search(ROLE.sub("", res["author"] or "")) or norm(res["author"]) in ("unknown author", "unknown") \
            or (names and words(res["author"]) and words(res["author"]) == words(want_series)):
        out.append("author_junk")
    if confirmed and names:
        series_words = words(ref_series)
        missing = [p for p in people(ref.get("author")) if "great courses" not in p and words(p) != series_words
                   and not any(p.split()[-1] in n for n in names)]
        if missing:
            out.append("author_missing")
    return out


# What each listing is, from the tools that report a listing's own fields: its narrators and runtime.
# Grimmory and BookOrbit mix fields from several sources, so they are not used.
listing_narrators, listing_minutes = {}, {}
for tool in ("public_gr", "audiosilo", "absqm", "rmab", "beets"):
    for r in raw[tool].values():
        m, edition = r.get("match") or {}, r.get("different_edition") or {}
        for asin, narr, mins in ((edition.get("match_asin"), edition.get("match_narrator"), edition.get("match_minutes")),
                                 ("" if edition else m.get("asin"), m.get("narrator"), m.get("runtime_min") or m.get("duration_minutes"))):
            asin = (asin or "").upper()
            if not asin:
                continue
            names = {bare(n) for n in people(narr)} - {bare(n) for n in PLACEHOLDER} - {""}
            if names:
                listing_narrators.setdefault(asin, set()).update(names)
            if mins:
                listing_minutes.setdefault(asin, float(mins))


def other_recording(asin, book_narrators, ref_asin):
    """True when the pick's ASIN is a listing narrated by someone else entirely."""
    asin = (asin or "").upper()
    if not asin or not book_narrators:
        return False
    names = listing_narrators.get(asin)
    return bool(names) and not same_people(names, book_narrators)


def not_the_book(asin, minutes):
    mins = listing_minutes.get((asin or "").upper())
    return bool(mins and minutes) and not 0.5 <= mins / minutes <= 1.5


final = {}
report, tally = [], Counter()
for i, b in enumerate(books):
    lf = raw["public_gr"].get(b["folder"]) or {}
    local = lf.get("local") or {}
    file = {k: local.get(k) or "" for k in FIELDS}
    ref = (b.get("final") if b.get("asin") else b.get("expect")) or {}
    codes = audit[b["folder"]]["v"]
    confirmed = bool(b.get("asin"))
    ref_asin = (b.get("asin") or "").upper()
    author = norm(ref.get("author") or file["author"])
    # Narrators named by a listing of this book: the right-book picks, and the listing LibraForge saw
    # as another recording. Plus the reference's, and the file's unless it is just the author's name.
    listed = set()
    for tool in TOOLS:
        if codes[tool] in "CPE":
            listed.update(people(((raw[tool].get(b["folder"]) or {}).get("match") or {}).get("narrator")))
    listed.update(people((lf.get("different_edition") or {}).get("match_narrator")))
    listed = {n for n in listed if n not in PLACEHOLDER}
    known = set(listed) | {n for n in people(ref.get("narrator")) if n not in PLACEHOLDER}
    if norm(file["narrator"]) not in PLACEHOLDER and (bare(file["narrator"]) != bare(author) or listed <= {norm(file["narrator"])}):
        known |= set(people(file["narrator"]))
    # The recording the file is: its own narrator when it names one, else the reference's.
    author_names = {bare(a) for a in people(ref.get("author") or file["author"])} | {bare(a) for a in people(file["author"])}
    file_people = {bare(n) for n in people(file["narrator"])} - {bare(n) for n in PLACEHOLDER}
    own = file["narrator"] if file_people and not file_people <= author_names else ref.get("narrator")
    book_narrators = {bare(n) for n in people(own)} - {""}
    row = final[b["folder"]] = {"v": {}, "f": {}, "note": audit[b["folder"]]["note"]}
    for tool in TOOLS:
        code = codes[tool]
        rec = raw[tool].get(b["folder"])
        res, asin = result(tool, file, rec)
        problems = [] if res is None or tool == "rmab" else checks(res, ref, file, known, listed, confirmed, b["folder"],
                                                                             tool in ("grimmory", "bo") or (rec or {}).get("provider") == "goodreads")
        wrote = res is not None if tool != "rmab" else (rec or {}).get("status") == "matched"
        if not wrote:
            held = ((rec or {}).get("match") or {}).get("asin") if tool == "audiosilo" else ""
            row["v"][tool] = ("h" if code == "H" and not_the_book(held, b["minutes"]) else code) if code in "Hh" else "N"
        elif code in "CPHN" or (code == "S" and problems):
            if (asin or "").upper() == (local.get("asin") or "").upper():
                asin = ""  # the file's own ASIN tag, kept: not the tool's pick
            if not_the_book(asin, b["minutes"]):
                row["v"][tool] = "W"
            elif other_recording(asin, book_narrators, ref_asin):
                row["v"][tool] = "E"
            else:
                row["v"][tool] = "P" if problems else "C"
        else:
            row["v"][tool] = code
        if problems and wrote:
            row["f"][tool] = problems
        same_book = bool(asin and b.get("asin") and asin.upper() == b["asin"].upper())
        why = None
        if res is None and code in "CEPWSs":
            why = "verdict says written, tool wrote nothing"
        elif res is not None and code in "HhN" and tool != "rmab":
            why = "verdict says not written, tool wrote"
        elif code in "CS" and problems:
            why = "correct, but " + ", ".join(problems)
        elif code == "W" and same_book:
            why = "wrong book, but the pick is the reference ASIN"
        elif code == "P" and not problems:
            why = "damaged, but no field check fails"
        if why:
            for p_ in (problems if why.startswith("correct") else [why]):
                tally[(tool, why.split(",")[0] + (": " + p_ if why.startswith("correct") else ""))] += 1
            report.append({"i": i, "folder": b["folder"], "tool": tool, "code": code, "why": why, "problems": problems,
                           "res": res, "ref": ref, "file": file, "asin": asin, "ref_asin": b.get("asin") or "",
                           "note": audit[b["folder"]]["note"]})
for (tool, why), n in sorted(tally.items()):
    print(f"{tool:10} {n:5}  {why}")
print(len(report), "disagreements")
print("final:", {tool: dict(Counter(r["v"][tool] for r in final.values())) for tool in TOOLS})
def tally_findings(name, books_in_sample):
    """How many verdicts a second audit found wrong: data/reaudit/<name>, one 'idx TOOL a->b | why (rule|hand)' per line."""
    path = os.path.join(bench.file("audit", "reaudit"), name)
    if not os.path.exists(path):
        return {}
    lines = [l for l in open(path) if re.match(r"\d+ \w+ \w->\w", l)]
    return {"books": books_in_sample, "verdicts": books_in_sample * len(TOOLS), "wrong": len(lines),
            "rule": sum("(rule" in l for l in lines), "hand": sum("(rule" not in l for l in lines)}


if opts.write:
    validation = os.path.join(bench.file("audit", "reaudit"), "validation_sample.json")
    sample = os.path.join(bench.file("audit", "reaudit"), "sample.json")
    final["_meta"] = {
        "reaudit": tally_findings("findings.txt", len(json.load(open(sample))) if os.path.exists(sample) else 0),
        "validation": tally_findings("validation_findings.txt", len(json.load(open(validation)))
                                     if os.path.exists(validation) else 0),
    }
    json.dump(final, open(bench.file("audit", "final"), "w"), ensure_ascii=False, indent=0)
    print("wrote", bench.file("audit", "final"))
if opts.out:
    with open(opts.out, "w") as fh:
        for r in report:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
