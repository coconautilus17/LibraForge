"""Run Audiobookshelf's own Quick Match over a mock library and record its picks.

Point a throwaway ABS (never your real one: Quick Match writes) at the bo_mock.py
folder mounted read-only at /audiobooks, then run this on the same docker network:

usage: abs_quickmatch.py <abs-url> <out.jsonl> [workers]

Keep workers at 1 (the default), like ABS's own Match All: two matches that create
the same new series at once crash ABS 2.35.1 on a unique constraint.

It creates the root user and a book library with the Audible provider, scans it,
then calls POST /api/items/{id}/match per book: the Quick Match button, which takes
the first result of ABS's Audible search (by the file's ASIN when it has one).
overrideDetails is on so the item's ASIN is always the one ABS picked. Rows use the
lf_bench.py shape (folder, status, match), so score.py reads them as-is.
"""
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL, OUT = sys.argv[1].rstrip("/"), sys.argv[2]
WORKERS = int(sys.argv[3]) if len(sys.argv) > 3 else 1
ROOT = "/audiobooks/"


def call(method, path, body=None, token=None, timeout=120):
    req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode()


try:
    call("POST", "/init", {"newRoot": {"username": "bench", "password": "bench"}})
except Exception:
    pass  # already initialised
token = call("POST", "/login", {"username": "bench", "password": "bench"})["user"]["token"]

libs = call("GET", "/api/libraries", token=token)["libraries"]
lib = next((l for l in libs if l["name"] == "bench"), None) or call(
    "POST", "/api/libraries", {"name": "bench", "folders": [{"fullPath": ROOT.rstrip("/")}], "mediaType": "book", "provider": "audible"},
    token=token)
call("POST", f"/api/libraries/{lib['id']}/scan", {}, token=token)
last, stable = -1, 0
while stable < 3:  # the scan runs in the background: wait until the count settles
    time.sleep(20)
    total = call("GET", f"/api/libraries/{lib['id']}/items?limit=1", token=token)["total"]
    stable = stable + 1 if total == last else 0
    last = total
    print("scanned", total, flush=True)

items = call("GET", f"/api/libraries/{lib['id']}/items?limit=0", token=token)["results"]


def names(values):
    return ", ".join(v.get("name", "") if isinstance(v, dict) else str(v) for v in values or [])


def match(item):
    folder = item["path"][len(ROOT):] if item["path"].startswith(ROOT) else item["path"]
    try:
        res = call("POST", f"/api/items/{item['id']}/match",
                   {"provider": "audible", "overrideDetails": True, "overrideCover": False}, token=token, timeout=300)
    except Exception as exc:
        return {"folder": folder, "status": "error", "error": str(exc)}
    if res.get("warning") or not res.get("updated"):
        after = call("GET", f"/api/items/{item['id']}", token=token)
        md = after["media"]["metadata"]
        # Nothing changed can still be a match that equals what the tags had.
        if res.get("warning"):
            return {"folder": folder, "status": "skipped", "skip_reason": res["warning"]}
    else:
        md = res["libraryItem"]["media"]["metadata"]
    series = (md.get("series") or [{}])[0] if md.get("series") else {}
    return {"folder": folder, "status": "matched", "match": {
        "asin": md.get("asin") or "", "title": md.get("title") or "", "subtitle": md.get("subtitle") or "",
        "author": names(md.get("authors")), "narrator": names(md.get("narrators")),
        "series": series.get("name", ""), "sequence": series.get("sequence", "") or ""}}


done = 0
with open(OUT, "w") as out, ThreadPoolExecutor(WORKERS) as pool:
    for row in pool.map(match, items):
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        done += 1
        if done % 200 == 0:
            print("matched", done, "of", len(items), flush=True)
print("done", done, flush=True)
