"""Whether each book's opening credits name its right answer's title, authors and narrators.

Reads asr_intro.py's output. Speech-to-text spells names by ear ("Bruce Centaur" for Bruce
Sentar), so a name or title counts as heard when some run of the transcript's words is close
to it (difflib ratio), not only when it is spelled the same.

usage: asr_check.py [--intro asr_intro.jsonl] [--out asr_check.json] [--manifest manifest.json]
"""
import argparse
import difflib
import json
import re
import unicodedata

from bench_data import Benchmark, path

HEARD = 0.75
NOT_HEARD = 0.6  # below this a name is not what was said; between the two it is unclear
# Where the credits end: the story starts, or a cast list begins.
CREDITS_END = re.compile(r"\b(chapter|prologue|part one|introduction|foreword|preface|with performances|starring)\b", re.I)
NARRATOR_CREDIT = re.compile(r"\b(?:narrated|read|performed)\s+by\s+(.{3,120}?)(?=\.|,? with |,? an? [a-z]+ production|$|\b(?:chapter|prologue)\b)", re.I)


def norm(x):
    x = unicodedata.normalize("NFKD", str(x or "").replace("’", "'")).encode("ascii", "ignore").decode().replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()


def closeness(phrase, text_words):
    """The best difflib ratio between the phrase and any run of the transcript's words of about its length."""
    p = norm(phrase)
    if not p or not text_words:
        return 0.0
    n = len(p.split())
    best = 0.0
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(1, len(text_words) - size + 1)):
            best = max(best, difflib.SequenceMatcher(None, p, " ".join(text_words[i:i + size])).ratio())
    return round(best, 2)


def people(x):
    return [norm(re.sub(r"\([^)]*\)", " ", p)) for p in re.split(r",|;|&| and ", str(x or "")) if norm(p)]


def title_core(title):
    """The title proper: before a colon or a parenthesis ("Nova Terra: Catalyst" keeps both words)."""
    head = re.split(r"\(|\[", title)[0]
    return head if len(norm(head.split(":")[0]).split()) < 2 else head.split(":")[0]


NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty".split())}
NUMBER_WORDS.update({"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
                     "ninth": 9, "tenth": 10, "thirty": 30, "forty": 40, "fifty": 50})


def number_at(words, i):
    """The number words[i] says ("6", "six", "twenty one"), else None."""
    if i >= len(words):
        return None
    w = words[i]
    if i + 1 < len(words) and words[i + 1] == "edition":
        return None  # "Second Edition"
    m = re.fullmatch(r"(\d+)point(\d+)", w)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")  # "Book 3.5", kept whole by credit_words
    if w.isdigit():
        return int(w) if int(w) <= 300 else None
    if w in NUMBER_WORDS:
        n = NUMBER_WORDS[w]
        if n >= 20 and i + 1 < len(words) and words[i + 1] in NUMBER_WORDS and NUMBER_WORDS[words[i + 1]] < 10:
            n += NUMBER_WORDS[words[i + 1]]  # "twenty one"
        return n
    return None


CUES = {"book", "volume", "vol", "number"}


def said_numbers(credit_words, series_names=(), title_numbers=frozenset()):
    """The book numbers the credits say: after a cue ("Book Six", "Volume 20"), or right after the series'
    name ("Backyard Dungeon 3") unless the title itself holds that number ("Dungeon Diving 102")."""
    words, out = list(credit_words), set()
    for i, w in enumerate(words):
        if w in CUES and not (i and words[i - 1] in ("of", "in")):  # not a recap's "summary of book one"
            n = number_at(words, i + 1)
            if n is not None:
                out.add(n)
    for name in series_names:
        name_words = norm(name).split()
        k = len(name_words)
        for i in range(len(words) - k):
            if k and words[i:i + k] == name_words:
                n = number_at(words, i + k)
                if n is not None and n not in title_numbers:
                    out.add(n)
    return out


def listed_numbers(series):
    """Every number a listing's series positions cover: "6", "1-2" (1 and 2), "3.5"."""
    out = set()
    for _, seq in series or []:
        m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(seq))
        if m:
            out.update(range(int(m.group(1)), int(m.group(2)) + 1))
        else:
            try:
                out.add(float(seq) if "." in str(seq) else int(seq))
            except ValueError:
                pass
    return out


def credit_words(credits):
    """The credits' words, a decimal book number kept as one ("3.5" -> "3point5")."""
    return norm(re.sub(r"(\d)\.(\d)", r"\1point\2", credits)).split()


def judge(fields, text, book_minutes=None):
    """How the opening credits stand against a listing's fields ({title, author, narrator, series,
    minutes}): each name's closeness, whether the book number said is one the listing has, whether the
    runtime agrees, and the verdict."""
    end = CREDITS_END.search(text)
    credits = text[:end.start()] if end and end.start() > 20 else text[:400]
    w = credit_words(credits)
    c = {"title": closeness(title_core(fields.get("title", "")), w) if fields.get("title") else None,
         "authors": {p: closeness(p, w) for p in people(fields.get("author"))},
         "narrators": {p: closeness(p, w) for p in people(fields.get("narrator"))}}
    title_words = norm(f"{fields.get('title', '')} {fields.get('subtitle', '')}").split()
    in_title = {n for i in range(len(title_words)) if (n := number_at(title_words, i)) is not None}
    names = [n for n, _ in fields.get("series") or [] if n] + [title_core(fields.get("title", ""))]
    said, listed = said_numbers(w, names, in_title), listed_numbers(fields.get("series"))
    c["number"] = None if not said or not listed else bool(said & listed)
    m = fields.get("minutes")
    c["runtime"] = None if not m or not book_minutes else abs(m - book_minutes) <= max(3, 0.03 * book_minutes)
    c["verdict"] = verdict(c, [x.group(1) for x in NARRATOR_CREDIT.finditer(text)])
    return c


def verdict(c, credited_narrator):
    """'confirmed' (title, an author and every narrator heard, and neither the book number said nor the
    runtime disagrees), 'other recording' (the credits name a narrator and none of the listing's is close,
    its author heard), 'other book' (the same, author not heard), 'other number' (another book of the
    series: the credits say a number the listing doesn't have), 'partly' (some of it heard), 'not heard'."""
    t = (c["title"] or 0) >= HEARD
    a = any(v >= HEARD for v in c["authors"].values())
    heard = list(c["narrators"].values())
    # A full cast's listing names its characters' voices too; the credits name the lead.
    n = bool(heard) and (all(v >= HEARD for v in heard) or len(heard) > 3 and heard[0] >= HEARD)
    if credited_narrator and c["narrators"] and all(v < NOT_HEARD for v in c["narrators"].values()):
        return "other recording" if a else "other book"
    if c.get("number") is False and a:
        return "other number"
    if t and a and n and c.get("runtime") is not False:
        return "confirmed"
    return "partly" if t or a or n else "not heard"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intro", default="asr_intro.jsonl")
    ap.add_argument("--out", default="asr_check.json")
    ap.add_argument("--manifest", default="manifest.json")
    opts = ap.parse_args()
    bench = Benchmark(opts.manifest)
    out = {}
    for line in open(path(opts.intro), encoding="utf-8"):
        row = json.loads(line)
        b = bench.by_folder.get(row["folder"])
        if not b or row.get("error"):
            continue
        text = row.get("text", "")
        end = CREDITS_END.search(text)
        entry = {"credits": (text[:end.start()] if end and end.start() > 20 else text[:400]).strip()}
        if b["answer"]:
            entry["answer"] = judge(b["answer"], text, b["minutes"])
        out[row["folder"]] = entry
    json.dump(out, open(path(opts.out), "w"), ensure_ascii=False, indent=0)
    tally = {}
    for e in out.values():
        if "answer" in e:
            tally[e["answer"]["verdict"]] = tally.get(e["answer"]["verdict"], 0) + 1
    print(f"{len(out)} books checked; scored books' answers: {tally} -> {path(opts.out)}")


if __name__ == "__main__":
    main()
