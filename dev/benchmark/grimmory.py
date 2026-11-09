"""Run Grimmory's automatic metadata refresh over a mock library and record its picks.

Point a throwaway Grimmory (v3.5.0) at the --itunes mock (bo_mock.py, Grimmory reads
tags with jaudiotagger) mounted read-only at /books. Its refresh is automatic: per
provider it takes the top result (Audible: the file's ASIN if it has one, else one
keyword search for "title author", first result), merges the fields by provider
priority, and applies them without review.

Grimmory ships with Audible off (Goodreads, then Google). Like an audiobook user would,
this enables Audible and puts it first for every field (Goodreads, then Google behind
it), replacing a field when the provider has a value.

usage: grimmory.py setup                          admin user, Audible on
       grimmory.py library                        create the library on /books, wait for its scan
       grimmory.py refresh <out.time> [book-ids]  timed refresh (all books, or a few to test)
       grimmory.py rows <books.json> <out.jsonl>  lf_bench.py-shaped rows (bench_data.py reads them)

GRIMMORY_URL   default http://127.0.0.1:6061
GRIMMORY_CREDS JSON {"username", "password", "email", "name"}
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("GRIMMORY_URL", "http://127.0.0.1:6061").rstrip("/")
CREDS = json.load(open(os.environ["GRIMMORY_CREDS"]))
ROOT = "/books/"
FIELDS = ["title", "subtitle", "description", "authors", "publisher", "publishedDate", "seriesName", "seriesNumber",
          "seriesTotal", "isbn13", "isbn10", "language", "categories", "cover", "asin", "audibleId", "narrator"]


def call(method, path, body=None, token=None, timeout=120):
    req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:500]


def data(response):
    return response.get("data", response) if isinstance(response, dict) else response


def login():
    st, r = call("POST", "/api/v1/auth/login", {"username": CREDS["username"], "password": CREDS["password"]})
    if st != 200:
        sys.exit(f"login failed {st} {r}")
    return r["accessToken"]


def refresh_options():
    audible_first = {"p1": "Audible", "p2": "GoodReads", "p3": "Google", "p4": None}
    return {"refreshCovers": False, "mergeCategories": True, "reviewBeforeApply": False,
            "replaceMode": "REPLACE_WHEN_PROVIDED",
            "fieldOptions": {f: audible_first for f in FIELDS},
            "enabledFields": {f: True for f in FIELDS}}


def setup():
    st, r = call("GET", "/api/v1/setup/status")
    if not data(r):
        print("setup", call("POST", "/api/v1/setup", CREDS))
    tok = login()
    st, s = call("GET", "/api/v1/settings", None, tok)
    providers = data(s)["metadataProviderSettings"]
    providers["audible"] = {"enabled": True, "domain": "com"}
    print("audible on", call("PUT", "/api/v1/settings", [{"name": "METADATA_PROVIDER_SETTINGS", "value": providers}], tok)[0])


def library():
    tok = login()
    st, libs = call("GET", "/api/v1/libraries", None, tok)
    lib = next((l for l in data(libs) if l["name"] == "bench"), None)
    if not lib:
        st, lib = call("POST", "/api/v1/libraries", {"name": "bench", "icon": "headphones", "iconType": "LUCIDE",
                                                    "paths": [{"path": ROOT.rstrip("/")}], "watch": False,
                                                    "allowedFormats": ["AUDIOBOOK"], "metadataSource": "EMBEDDED",
                                                    "organizationMode": "BOOK_PER_FOLDER"}, tok, timeout=600)
        lib = data(lib)
        print("created", st, lib.get("id") if isinstance(lib, dict) else lib)
    last, stable = -1, 0
    while stable < 3:  # the scan runs in the background: wait until the count settles
        time.sleep(30)
        st, books = call("GET", "/api/v1/books?stripForListView=true", None, login(), timeout=600)
        total = len(data(books)) if st == 200 else last
        stable = stable + 1 if total == last else 0
        last = total
        print("scanned", total, flush=True)
    return lib["id"]


def refresh(out_time, book_ids=None):
    tok = login()
    st, libs = call("GET", "/api/v1/libraries", None, tok)
    lib = next(l for l in data(libs) if l["name"] == "bench")
    options = {"refreshType": "BOOKS", "bookIds": book_ids} if book_ids else {"refreshType": "LIBRARY", "libraryId": lib["id"]}
    options["refreshOptions"] = {**refresh_options(), "libraryId": lib["id"]}
    start = time.time()
    st, r = call("POST", "/api/v1/tasks/start", {"taskType": "REFRESH_METADATA_MANUAL", "options": options}, tok, timeout=3600)
    print("start", st, str(r)[:300], flush=True)
    task_id = (data(r) or {}).get("taskId") if isinstance(data(r), dict) else None
    while task_id:
        time.sleep(60)
        st, t = call("GET", f"/api/metadata/tasks/{task_id}", None, login())
        t = data(t) if st == 200 else {}
        job = t.get("task", t) if isinstance(t, dict) else {}
        print(time.strftime("%H:%M"), job.get("status"), job.get("completed"), "of", job.get("totalBooks"), flush=True)
        if str(job.get("status")) in ("COMPLETED", "ERROR", "CANCELLED", "FAILED"):
            break
    open(out_time, "w").write(f"{time.time() - start:.0f}\n")


def rows(books_path, out_path):
    tok = login()
    st, items = call("GET", "/api/v1/books?stripForListView=true", None, tok, timeout=600)
    found = {}
    for listed in data(items):  # the list view leaves fields out, so read each book in full
        st, b = call("GET", f"/api/v1/books/{listed['id']}", None, tok)
        if st == 401:
            tok = login()
            st, b = call("GET", f"/api/v1/books/{listed['id']}", None, tok)
        b = data(b)
        f = b.get("primaryFile") or {}
        path = f.get("filePath") or ""
        folder = os.path.dirname(path)[len(ROOT):] if path.startswith(ROOT) else os.path.dirname(f.get("fileSubPath") or "")
        md = b.get("metadata") or {}
        asin = md.get("audibleId") or ""
        found[folder] = {"asin": asin, "title": md.get("title") or "", "subtitle": md.get("subtitle") or "",
                         "author": ", ".join(md.get("authors") or []), "narrator": md.get("narrator") or "",
                         "series": md.get("seriesName") or "", "sequence": str(md.get("seriesNumber") or "").removesuffix(".0")}
    with open(out_path, "w", encoding="utf-8") as out:
        for book in json.load(open(books_path)):
            m = found.get(book["folder"])
            row = {"folder": book["folder"], "status": "matched" if m and m["asin"] else "skipped"}
            if m and m["asin"]:
                row["match"] = m
            else:
                row["skip_reason"] = "no Audible match" if m else "not in the Grimmory library"
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{out_path}: {sum(1 for m in found.values() if m['asin'])} with an Audible match of {len(found)} books")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "setup":
        setup()
    elif cmd == "library":
        print("library", library())
    elif cmd == "refresh":
        refresh(sys.argv[2], [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else None)
    elif cmd == "rows":
        rows(sys.argv[2], sys.argv[3])
