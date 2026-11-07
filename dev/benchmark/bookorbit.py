"""Tiny BookOrbit API client, for comparing against a throwaway BookOrbit stack.

BOOKORBIT_URL   API base (default http://127.0.0.1:5057/api/v1)
BOOKORBIT_CREDS JSON file with {"username", "password"} (default data/bookorbit-admin.json)

usage: bookorbit.py METHOD PATH [json-body]
       bookorbit.py fetch <library-id> <out.time>
       bookorbit.py rows <library-id> <out.jsonl>

fetch starts a metadata fetch for every book in the library (ignoring BookOrbit's
provider cache), waits for its queue to empty, and writes the total runtime in
seconds to out.time. rows then reads every book's record as fetched into the run's
rows: its folder (the mock's path under the library root), the Audible ASIN and
Goodreads id BookOrbit found, and the title, author, narrator, series and number it
keeps, which is what it shows (bench_data.result).
"""
import re
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BOOKORBIT_URL", "http://127.0.0.1:5057/api/v1")
HERE = os.path.dirname(os.path.abspath(__file__))
CREDS = os.environ.get("BOOKORBIT_CREDS", os.path.join(HERE, "data", "bookorbit-admin.json"))


def call(method, path, body=None, token=None, headers=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")


def login():
    c = json.load(open(CREDS))
    st, r = call("POST", "/auth/login", {"username": c["username"], "password": c["password"]})
    if st != 200:
        sys.exit(f"login failed {st} {r}")
    return r.get("accessToken") or r.get("access_token") or r["tokens"]["accessToken"]


def fetch(library_id, out_time):
    tok = login()
    start = time.time()
    st, r = call("POST", f"/book-metadata-fetch/run/{library_id}", {"ignoreCache": True}, tok)
    if st >= 300:
        sys.exit(f"run failed {st} {r}")
    while True:
        time.sleep(60)
        try:
            st, s = call("GET", "/book-metadata-fetch/status", None, tok)
        except Exception:  # BookOrbit busy or restarting: try again
            continue
        if st == 401:
            tok = login()
            continue
        print(time.strftime("%H:%M"), s.get("sessionDone"), "of", s.get("sessionTotal"), "failed", s.get("failed"), flush=True)
        if st == 200 and not s.get("queued") and not s.get("processing"):
            break
    open(out_time, "w").write(f"{time.time() - start:.0f}\n")


def rows(library_id, out_jsonl):
    tok = login()
    page, items = 0, []  # BookQuery: 0-based page, size per page
    while True:
        st, r = call("POST", f"/libraries/{library_id}/books", {"pagination": {"page": page, "size": 100}}, tok)
        items += r["items"]
        if len(items) >= r["total"] or not r["items"]:
            break
        page += 1
    with open(out_jsonl, "w", encoding="utf-8") as out:
        for b in items:
            st, d = call("GET", f"/books/{b['id']}", None, tok)
            ids = d.get("providerIds") or {}
            out.write(json.dumps({
                "folder": re.sub(r"^/[^/]+-books/", "", d["folderPath"]),
                "asin": ids.get("audible") or "", "goodreads": ids.get("goodreads") or "",
                "title": d.get("title") or "", "subtitle": d.get("subtitle") or "",
                "author": ", ".join(a["name"] for a in d.get("authors", [])),
                "narrator": ", ".join(n["name"] for n in (d.get("audioMetadata") or {}).get("narrators", [])),
                "series": d.get("seriesName") or "", "sequence": d.get("seriesIndex") or "",
            }, ensure_ascii=False) + "\n")
    print(f"{len(items)} books -> {out_jsonl}")


if __name__ == "__main__":
    if sys.argv[1] == "rows":
        rows(int(sys.argv[2]), sys.argv[3])
        sys.exit()
    if sys.argv[1] == "fetch":
        fetch(int(sys.argv[2]), sys.argv[3])
        sys.exit()
    tok = login()
    body = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    st, r = call(sys.argv[1], sys.argv[2], body, tok)
    print(st)
    print(json.dumps(r, indent=1, ensure_ascii=False))
