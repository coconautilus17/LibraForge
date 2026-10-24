"""Build a standalone HTML benchmark report: every book, what its file said, how the
matcher searched, what it picked, and how that compares with the library's answer.

usage: report.py <books.json> <scores.json> <run-name> <run.jsonl> <out.html>
                 [--compare name=label ...] [--title TEXT] [--commit SHA]

  books.json   the dataset (collect.py), the reference answers included
  scores.json  score.py output holding <run-name> and any --compare runs
  run.jsonl    the LibraForge run the report lists (lf_bench.py rows, with logs)

--compare adds a summary row per other tool, scored on the books both it and
LibraForge processed. The page embeds its data gzipped and needs no server.
"""
import argparse
import base64
import datetime
import gzip
import html
import json
import re
from collections import Counter

ap = argparse.ArgumentParser()
ap.add_argument("books")
ap.add_argument("scores")
ap.add_argument("run_name")
ap.add_argument("run")
ap.add_argument("out")
ap.add_argument("--compare", action="append", default=[], help="name=label")
ap.add_argument("--title", default="LibraForge matching benchmark")
ap.add_argument("--commit", default="")
ap.add_argument("--provider", default="Audible public catalog (no login), US marketplace")
opts = ap.parse_args()

books = {b["folder"]: b for b in json.load(open(opts.books))}
scores = json.load(open(opts.scores))
runs = {}
for line in open(opts.run, encoding="utf-8"):
    row = json.loads(line)
    runs[row["folder"]] = row
mine = scores[opts.run_name]

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


def clean_tags(tags):
    out = {}
    for key, value in (tags or {}).items():
        if key.lower() in _CONTAINER_TAGS or value in (None, ""):
            continue
        text = str(value)
        out[key] = text if len(text) <= 400 else text[:400] + "\u2026"
    return out


rows = []
for folder, book in books.items():
    run = runs.get(folder) or {}
    score = mine.get(folder) or {}
    match = run.get("match") or {}
    final = book.get("final") or {}
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
        "cls": score.get("class", "not run"), "fields": score.get("fields"),
        "q": searches(run.get("log")), "cand": candidates(run.get("log")), "trace": trace(run.get("log")),
    })

ORDER = ["correct", "correct-held", "wrong", "wrong-held", "none"]


def summarize(name, folders=None):
    rows_ = scores[name]
    ref = [f for f in rows_ if books.get(f, {}).get("asin") and (folders is None or f in folders)]
    c = Counter(rows_[f]["class"] for f in ref)
    applied = c["correct"] + c["wrong"]
    ok = [rows_[f] for f in ref if rows_[f]["class"] == "correct" and rows_[f].get("fields")]
    fld = {k: (sum(1 for r in ok if r["fields"][k]) / len(ok) * 100 if ok else 0) for k in ("title", "author", "narrator")}
    with_series = [r for r in ok if r["fields"]["series"] is not None]
    fld["series"] = sum(1 for r in with_series if r["fields"]["series"]) / len(with_series) * 100 if with_series else 0
    return {"n": len(ref), **{k: c.get(k, 0) for k in ORDER},
            "precision": c["correct"] / applied * 100 if applied else 0, "fields": fld}


overall = summarize(opts.run_name)
noref = Counter(mine[f]["class"] for f in mine if not books.get(f, {}).get("asin"))
comparisons = []
for spec in opts.compare:
    name, label = spec.split("=", 1)
    both = {f for f in scores[name] if f in mine}
    comparisons.append({"label": label, "them": summarize(name, both), "us": summarize(opts.run_name, both)})

payload = base64.b64encode(gzip.compress(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode())).decode()
today = datetime.date.today().isoformat()


def pct(n, d):
    return f"{n:,} ({n / d * 100:.1f}%)" if d else "0"


def summary_row(label, s, held=True):
    cells = [s["correct"], s["correct-held"], s["wrong"], s["wrong-held"], s["none"]]
    tds = "".join(f"<td>{pct(v, s['n']) if held or i in (0, 2, 4) else 'n/a'}</td>" for i, v in enumerate(cells))
    f = s["fields"]
    return (f"<tr><th scope=row>{html.escape(label)}</th>{tds}<td>{s['precision']:.2f}%</td>"
            f"<td>{f['title']:.1f}%</td><td>{f['author']:.1f}%</td><td>{f['narrator']:.1f}%</td><td>{f['series']:.1f}%</td></tr>")


HEAD = ("<tr><th></th><th>Correct</th><th>Correct, held</th><th>Wrong, applied</th><th>Wrong, held</th><th>No match</th>"
        "<th>Precision</th><th>Title</th><th>Author</th><th>Narrator</th><th>Series</th></tr>")
comparison_html = "".join(
    f"<h3>{html.escape(c['label'])} <span class=muted>({c['us']['n']:,} books both processed)</span></h3>"
    f"<div class=scroll><table class=summary><thead>{HEAD}</thead><tbody>"
    f"{summary_row(c['label'], c['them'], held=c['them']['correct-held'] + c['them']['wrong-held'] > 0)}"
    f"{summary_row('LibraForge, public catalog', c['us'])}</tbody></table></div>"
    for c in comparisons)

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LibraForge Matching Benchmark</title>
<style>
:root {{ --bg:#fbfaf7; --panel:#ffffff; --ink:#1d1f21; --muted:#5f6670; --line:#e3e0d8; --accent:#2f6f8f;
  --ok:#1f7a45; --ok-bg:#e5f3ea; --warn:#8a5a00; --warn-bg:#fbf0d9; --bad:#a32020; --bad-bg:#fbe4e4; --none-bg:#eceae4; --code:#f3f1ec; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#15171a; --panel:#1d2024; --ink:#e7e5e0; --muted:#a0a6ad;
  --line:#33373d; --accent:#7fb7d4; --ok:#6fcf97; --ok-bg:#1d3326; --warn:#e8b75a; --warn-bg:#3a2f17; --bad:#f08a8a; --bad-bg:#3d1f1f;
  --none-bg:#2a2d31; --code:#24272c; }} }}
:root[data-theme="dark"] {{ --bg:#15171a; --panel:#1d2024; --ink:#e7e5e0; --muted:#a0a6ad; --line:#33373d; --accent:#7fb7d4;
  --ok:#6fcf97; --ok-bg:#1d3326; --warn:#e8b75a; --warn-bg:#3a2f17; --bad:#f08a8a; --bad-bg:#3d1f1f; --none-bg:#2a2d31; --code:#24272c; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:26px; margin:0 0 4px; }} h2 {{ font-size:19px; margin:32px 0 8px; }} h3 {{ font-size:15px; margin:20px 0 6px; }}
p {{ margin:6px 0; max-width:80ch; }} .muted {{ color:var(--muted); font-weight:normal; }}
a {{ color:var(--accent); }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; }}
.summary th, .summary td {{ padding:6px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
.summary th:first-child, .summary td:first-child {{ text-align:left; }}
.summary thead th {{ font-size:13px; color:var(--muted); font-weight:600; }}
.controls {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:12px 0; position:sticky; top:0; background:var(--bg); padding:8px 0; z-index:2; }}
input, select, button {{ font:inherit; color:var(--ink); background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:6px 10px; }}
input[type=search] {{ flex:1 1 260px; min-width:0; }}
button {{ cursor:pointer; }}
.book {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; margin:6px 0; }}
.book > summary {{ list-style:none; cursor:pointer; padding:8px 12px; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:4px 12px; }}
.book > summary::-webkit-details-marker {{ display:none; }}
.book .path {{ font-weight:600; overflow-wrap:anywhere; }}
.book .pick {{ color:var(--muted); font-size:13px; overflow-wrap:anywhere; grid-column:1; }}
.badge {{ font-size:12px; font-weight:600; padding:2px 8px; border-radius:999px; white-space:nowrap; align-self:start; grid-row:1 / span 2; grid-column:2; }}
.b-correct {{ background:var(--ok-bg); color:var(--ok); }} .b-correct-held, .b-noref-held {{ background:var(--warn-bg); color:var(--warn); }}
.b-wrong {{ background:var(--bad-bg); color:var(--bad); }} .b-wrong-held {{ background:var(--warn-bg); color:var(--bad); }}
.b-none, .b-noref, .b-not {{ background:var(--none-bg); color:var(--muted); }}
.detail {{ padding:4px 12px 14px; border-top:1px solid var(--line); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px 20px; }}
.kv {{ width:100%; font-size:13px; }} .kv th {{ text-align:left; color:var(--muted); font-weight:600; padding:2px 10px 2px 0; vertical-align:top; white-space:nowrap; width:1%; }}
.kv td {{ padding:2px 0; overflow-wrap:anywhere; }}
.kv .ok {{ color:var(--ok); }} .kv .no {{ color:var(--bad); }}
.list {{ width:100%; font-size:13px; }} .list th, .list td {{ text-align:left; padding:3px 8px 3px 0; border-bottom:1px solid var(--line); vertical-align:top; overflow-wrap:anywhere; }}
.list thead th {{ color:var(--muted); font-weight:600; }}
pre {{ background:var(--code); padding:10px; border-radius:6px; font-size:12px; overflow-x:auto; white-space:pre; margin:6px 0 0; }}
.pager {{ display:flex; gap:8px; align-items:center; justify-content:center; margin:16px 0; }}
.note {{ font-size:13px; color:var(--muted); }}
@media (max-width:600px) {{ .book > summary {{ grid-template-columns:minmax(0,1fr); }} .badge {{ grid-row:auto; grid-column:1; justify-self:start; }} }}
</style>
</head>
<body>
<main>
<h1>{html.escape(opts.title)}</h1>
<p class=muted>{today}{(' · LibraForge ' + html.escape(opts.commit)) if opts.commit else ''} · {html.escape(opts.provider)}</p>

<p>Every audiobook in one real library whose original tags were kept (LibraForge saves a file's tags
before it first writes anything): {len(books):,} books. Each book was matched again from those original
tags, its folder path and its runtime, with no login, against the live catalog, the same way Metadata
Forge matches a new book. {overall['n']:,} books have a confirmed answer (the match applied in the library,
reviewed by hand), and only those are scored. A pick is correct when it is that listing or another
listing of the same recording (runtime within 3% and a shared narrator). "Held" means LibraForge found
the listing but sent it to review instead of applying it.</p>

<h2>Results</h2>
<div class=scroll><table class=summary><thead>{HEAD}</thead><tbody>{summary_row('LibraForge, public catalog', overall)}</tbody></table></div>
<p class=note>Title, author, narrator and series: share of correct matches whose field agrees with the library's.
Books without a confirmed answer ({sum(noref.values()):,}): {noref.get('noref', 0):,} applied, {noref.get('noref-held', 0):,} held, {noref.get('none', 0):,} no match.</p>

<h2>Compared with other tools</h2>
<p>Each tool got the same original tags as files carrying them (1-second silent files at the books' real
folder paths) and was scored the same way. None of them holds a match for review: what they accept, they
apply, so their held columns read n/a.</p>
<ul class=note>
<li><b>Audiobookshelf Quick Match</b> (v2.35.1, Audible US provider): the Quick Match button per book, which takes
the first Audible result, looked up by the file's ASIN when it has one. Run one book at a time, as ABS's own
Match All does.</li>
<li><b>BookOrbit</b>: a library bulk metadata fetch with its default providers.</li>
<li><b>beets-audible</b> (beets 2.14, the plugin's recommended settings): <code>beet import -q</code>, which applies
strong matches and skips the rest; skipped books count as no match. beets was given each book's real runtime,
since it scores candidates on track length.</li>
<li><b>LibraForge, Audiobookshelf provider</b>: the same matcher, searching through Audiobookshelf's Audible
provider instead of the public catalog.</li>
</ul>
{comparison_html}

<h2>Every book</h2>
<div class=controls>
  <input type=search id=q placeholder="Search folder, title, author, ASIN" aria-label="Search books">
  <select id=cls aria-label="Outcome">
    <option value="">All outcomes</option><option value="correct">Correct</option><option value="correct-held">Correct, held</option>
    <option value="wrong">Wrong, applied</option><option value="wrong-held">Wrong, held</option><option value="none">No match</option>
    <option value="noref">No confirmed answer</option>
  </select>
  <select id=mode aria-label="Match mode"><option value="">Any mode</option><option value="full">Full match</option><option value="series_only">Series only</option><option value="edition">Other recording</option></select>
  <span id=count class=note></span>
</div>
<div id=list><p class=note>Loading\u2026</p></div>
<div class=pager><button id=prev>Previous</button><span id=page class=note></span><button id=next>Next</button></div>
</main>
<script>
const DATA_GZ = "{payload}";
const PAGE = 50;
let rows = [], view = [], page = 0;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]));
const LABEL = {{"correct":"Correct","correct-held":"Correct, held","wrong":"Wrong","wrong-held":"Wrong, held","none":"No match",
  "noref":"Applied, no confirmed answer","noref-held":"Held, no confirmed answer","not run":"Not run"}};

function kv(obj, check) {{
  const keys = Object.keys(obj).filter((k) => obj[k] !== "" && obj[k] !== null && obj[k] !== false);
  if (!keys.length) return '<p class=note>none</p>';
  return '<table class=kv>' + keys.map((k) => {{
    const mark = check && k in check && check[k] !== null ? (check[k] ? ' <span class=ok>&#10003;</span>' : ' <span class=no>&#10007;</span>') : "";
    return `<tr><th>${{esc(k)}}</th><td>${{esc(obj[k])}}${{mark}}</td></tr>`;
  }}).join("") + "</table>";
}}

function detail(r) {{
  const m = r.match || {{}};
  const decision = {{status: r.status, reason: r.skip, score: r.score, mode: r.mode, runtime: r.dur}};
  if (r.edition) decision["other recording"] = `${{r.edition.match_asin || ""}} (file narrator ${{r.edition.local_narrator || "?"}}, listing ${{r.edition.match_narrator || "?"}})`;
  if (r.series_asin) decision["series from"] = r.series_asin;
  const ref = Object.assign({{}}, r.ref); if (!ref.manual) delete ref.manual; else ref.manual = "set by hand";
  const q = r.q.length ? '<table class=list><thead><tr><th>Search</th><th>Query</th><th>Results</th></tr></thead><tbody>' +
    r.q.map(([k, s, n]) => `<tr><td>${{esc(k)}}</td><td>${{esc(s)}}</td><td>${{esc(n ?? "")}}</td></tr>`).join("") + "</tbody></table>" : '<p class=note>none</p>';
  const c = r.cand.length ? '<table class=list><thead><tr><th>Score</th><th>Title</th><th>ASIN</th><th>Runtime</th><th>Book</th><th>Mode</th></tr></thead><tbody>' +
    r.cand.map((x) => `<tr><td>${{esc(x.score)}}</td><td>${{esc(x.title)}}</td><td>${{esc(x.asin)}}</td><td>${{esc(x.duration)}}</td><td>${{esc(x.sequence)}}</td><td>${{esc(x.mode)}}</td></tr>`).join("") + "</tbody></table>" : '<p class=note>none above the cut</p>';
  return `<div class=detail><div class=grid>
    <section><h3>Original tags</h3><p class=note>${{esc(r.file)}} · ${{r.min}} min${{r.recycled ? " · since deleted from the library" : ""}}</p>${{kv(r.tags)}}</section>
    <section><h3>What LibraForge read</h3><p class=note>Parsed from the tags and the folder path</p>${{kv(r.clues)}}</section>
    <section><h3>Result</h3>${{kv(decision)}}${{kv(m, r.fields)}}</section>
    <section><h3>Library's answer</h3>${{kv(ref)}}</section>
  </div>
  <h3>Searches run</h3>${{q}}${{r.planned.length ? `<details><summary class=note>All ${{r.planned.length}} planned keyword queries (tried in order until one finds the book)</summary><pre>${{esc(r.planned.join("\\n"))}}</pre></details>` : ""}}
  <h3>Candidates</h3>${{c}}
  <details><summary class=note>Full matcher trace</summary><pre>${{esc(r.trace.join("\\n"))}}</pre></details></div>`;
}}

function render() {{
  const start = page * PAGE;
  $("list").innerHTML = view.slice(start, start + PAGE).map((r) => {{
    const pick = r.match && r.match.title ? `${{r.match.title}}${{r.match.author ? " · " + r.match.author : ""}}${{r.match.asin ? " · " + r.match.asin : ""}}` : (r.skip || r.status);
    return `<details class=book data-i="${{rows.indexOf(r)}}"><summary><span class=path>${{esc(r.f)}}</span>
      <span class="badge b-${{esc(r.cls.split(" ")[0])}}">${{esc(LABEL[r.cls] || r.cls)}}</span><span class=pick>${{esc(pick)}}</span></summary></details>`;
  }}).join("") || '<p class=note>No books match.</p>';
  $("list").querySelectorAll("details.book").forEach((d) => d.addEventListener("toggle", () => {{
    if (d.open && !d.querySelector(".detail")) d.insertAdjacentHTML("beforeend", detail(rows[+d.dataset.i]));
  }}, {{once: false}}));
  const pages = Math.max(1, Math.ceil(view.length / PAGE));
  $("page").textContent = `Page ${{page + 1}} of ${{pages}}`;
  $("prev").disabled = page === 0; $("next").disabled = page >= pages - 1;
  $("count").textContent = `${{view.length.toLocaleString()}} of ${{rows.length.toLocaleString()}} books`;
}}

function apply() {{
  const q = $("q").value.trim().toLowerCase(), cls = $("cls").value, mode = $("mode").value;
  view = rows.filter((r) => {{
    if (cls === "noref" ? !r.cls.startsWith("noref") : cls && r.cls !== cls) return false;
    if (mode === "edition" ? !r.edition : mode && r.mode !== mode) return false;
    if (!q) return true;
    return [r.f, r.match.title, r.match.author, r.match.asin, r.ref.asin, r.tags.title, r.tags.artist, r.tags.album].some((v) => String(v || "").toLowerCase().includes(q));
  }});
  page = 0; render();
}}

(async () => {{
  const bytes = Uint8Array.from(atob(DATA_GZ), (c) => c.charCodeAt(0));
  const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
  rows = JSON.parse(text);
  ["q", "cls", "mode"].forEach((id) => $(id).addEventListener("input", apply));
  $("prev").addEventListener("click", () => {{ page--; render(); scrollTo(0, $("list").offsetTop - 60); }});
  $("next").addEventListener("click", () => {{ page++; render(); scrollTo(0, $("list").offsetTop - 60); }});
  apply();
}})();
</script>
</body>
</html>
"""
open(opts.out, "w", encoding="utf-8").write(page)
print(f"{opts.out}: {len(rows)} books, {len(page) / 1e6:.1f} MB")
