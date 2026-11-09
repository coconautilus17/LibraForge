"""Run AudioSilo's "Match automatically" over a mock library and record its picks.

Point a throwaway AudioSilo server (v2.5.1) at the --runtime mock (bo_mock.py: silence
as long as each book, since AudioSilo scores runtime and holds a match whose recording
is over 10% off) mounted read-only at /library. Run it in mirror mode with a base URL
that can't resolve (metadata.mode mirror): matching then reads the local copy of the
community database, downloaded once from the audiosilo-meta GitHub releases, and never
asks meta.audiosilo.app.

AudioSilo matches against its own community database, not Audible. A book whose tags
carry an ASIN or ISBN is matched by it at scan and left out of a run; the run sorts the
rest into confident (applied unasked: score >= 90, 10 ahead of the next, an ASIN or ISBN
to attach, runtime within 10%), to review (held) and not found.

usage: audiosilo.py library                        create the library on /library, wait for its scan
       audiosilo.py match <out.time>               timed match run over the library
       audiosilo.py rows <books.json> <out.jsonl>  lf_bench.py-shaped rows (bench_data.py reads them)

AUDIOSILO_URL   default http://127.0.0.1:8091
AUDIOSILO_CREDS JSON {"username", "password"}
AUDIOSILO_REMOTE set for a server in remote mode (metadata.mode remote): skips the mirror check
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ.get("AUDIOSILO_URL", "http://127.0.0.1:8091").rstrip("/")
CREDS = json.load(open(os.environ["AUDIOSILO_CREDS"]))
NAME, ROOT = "bench", "/library"
_TOKEN = None


def call(method, path, body=None, timeout=120):
    global _TOKEN
    for attempt in range(2):
        if _TOKEN is None:
            _TOKEN = _login()
        req = urllib.request.Request(URL + "/api/v1" + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {_TOKEN}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 401 and not attempt:
                _TOKEN = None  # expired: log in again once
                continue
            return e.code, e.read().decode(errors="replace")[:500]


def _login():
    req = urllib.request.Request(URL + "/api/v1/auth/login", method="POST", data=json.dumps(CREDS).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["token"]


def bench_library():
    st, libs = call("GET", "/admin/libraries")
    return next((l for l in libs["libraries"] if l["name"] == NAME), None)


def library():
    if not os.environ.get("AUDIOSILO_REMOTE"):  # remote mode asks the service for every book by design
        st, mirror = call("GET", "/admin/meta/mirror")
        if mirror.get("state") != "ready" or mirror.get("fallback"):
            sys.exit(f"the local copy isn't ready: {mirror}")  # a run then would ask the service
    lib = bench_library()
    if not lib:
        st, lib = call("POST", "/admin/libraries", {"name": NAME, "root": ROOT})
        print("created", st, lib)
    while True:  # the first scan starts with the library
        time.sleep(30)
        st, scan = call("GET", f"/admin/libraries/{lib['id']}/scan")
        print(time.strftime("%H:%M"), "scanned", scan.get("done"), "of", scan.get("total"), flush=True)
        if not scan.get("running"):
            return lib["id"]


def match(out_time):
    lib = bench_library()
    start = time.time()
    st, run = call("POST", "/admin/match-runs", {"library_id": lib["id"]})
    print("start", st, run.get("id") if isinstance(run, dict) else run, "books", run.get("total"), flush=True)
    while run.get("status") == "matching":
        time.sleep(15)
        st, run = call("GET", f"/admin/match-runs/{run['id']}")
        print(time.strftime("%H:%M"), run.get("status"), run.get("done"), "of", run.get("total"), run.get("counts"), flush=True)
    open(out_time, "w").write(f"{time.time() - start:.0f}\n")


def _run_items(run_id):
    items, after = [], 0
    while True:
        st, page = call("GET", f"/admin/match-runs/{run_id}/items?limit=200" + (f"&after={after}" if after else ""))
        items += page["items"]
        after = page["next_after"]
        if not after:
            return items


def rows(books_path, out_path):
    lib = bench_library()
    st, runs = call("GET", "/admin/match-runs")
    run = next(r for r in runs["runs"] if r["library_id"] == lib["id"] and r["mode"] == "match")  # newest first
    found = {}
    for it in _run_items(run["id"]):
        p = it.get("proposal") or {}
        v = p.get("values") or {}
        pick = {"asin": v.get("asin") or "", "title": v.get("title") or "", "author": v.get("author") or "",
                "narrator": v.get("narrator") or "", "series": v.get("series") or "",
                "sequence": v.get("series_index") or "",
                # Since 2.6 a match can carry only an ISBN, or only the community work it is.
                "isbn": v.get("isbn") or "", "work": p.get("work_id") or "",
                # The community's own runtime and store for the recording: an ASIN
                # from another store is the same recording under that store's id.
                "runtime_min": p.get("runtime_min"), "asin_region": p.get("asin_region") or ""} if p else None
        found[it["path"]] = {"outcome": it["outcome"], "score": it.get("score"), "pick": pick}
    with open(out_path, "w", encoding="utf-8") as out:
        for book in json.load(open(books_path)):
            m = found.get(book["folder"])
            if m is None:
                # Not in the run: matched at scan by the ASIN or ISBN its tags carry
                # (or not indexed at all).
                st, d = call("GET", f"/admin/libraries/{lib['id']}/book?path={urllib.parse.quote(book['folder'])}")
                b = (d or {}).get("book") if st == 200 else None
                if b and b.get("asin"):
                    m = {"outcome": "own_asin", "score": None,
                         "pick": {"asin": b["asin"], "title": b.get("title") or "", "author": b.get("author") or "",
                                  "narrator": b.get("narrator") or "", "series": b.get("series") or "",
                                  "sequence": str(b.get("series_index") or "").removesuffix(".0")}}
                else:
                    m = {"outcome": "not_indexed" if st == 404 else "no_asin", "score": None, "pick": None}
            row = {"folder": book["folder"], "outcome": m["outcome"], "score": m["score"]}
            if m["pick"] and (m["pick"]["asin"] or m["pick"].get("isbn") or m["pick"].get("work")):
                # Confident matches are applied unasked; "to review" waits for the admin.
                row["status"] = "matched" if m["outcome"] in ("auto", "own_asin") else "held"
                row["match"] = m["pick"]
            else:
                row["status"] = "skipped"
                row["skip_reason"] = {"none": "not found", "error": "not checked"}.get(m["outcome"], m["outcome"])
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(out_path, run["counts"])


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "library":
        print("library", library())
    elif cmd == "match":
        match(sys.argv[2])
    elif cmd == "rows":
        rows(sys.argv[2], sys.argv[3])
