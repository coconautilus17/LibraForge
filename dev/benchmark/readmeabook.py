"""Run ReadMeABook's Bulk Import scan over a mock library and record its picks.

ReadMeABook (v1.2.12) Bulk Import reads each book folder's album, album_artist and
composer tags with ffprobe and picks an Audible match automatically: a direct lookup
when the folder name holds an ASIN, else one Audible catalog keyword search (title,
author, narrator) and its first result. The review screen only lets you untick books;
the pick is made for you. The scan writes nothing, so its picks are read straight from
its event stream.

Mount the ffprobe-tag mock (bo_mock.py without --itunes) read-only at /media/audiobooks
in a throwaway ReadMeABook. Setup needs an Audiobookshelf, Prowlarr and download client
on record; a scan uses none of them, so they are unreachable placeholders here.

usage: readmeabook.py setup                       finish first-run setup, local admin
       readmeabook.py scan <books.json> <out.jsonl> [subfolder]   timed scan (writes <out>.time)

RMAB_URL   default http://127.0.0.1:3031
RMAB_CREDS JSON {"username", "password"}
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("RMAB_URL", "http://127.0.0.1:3031").rstrip("/")
CREDS = json.load(open(os.environ["RMAB_CREDS"]))
ROOT = "/media/audiobooks"


def call(method, path, body=None, token=None, timeout=120):
    req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:500]


def setup():
    unreachable = "http://placeholder.invalid"  # never contacted by a Bulk Import scan
    body = {
        "backendMode": "audiobookshelf", "audibleRegion": "us", "authMethod": "manual",
        "admin": {"username": CREDS["username"], "password": CREDS["password"]},
        "audiobookshelf": {"server_url": unreachable, "api_token": "placeholder", "library_id": "placeholder"},
        "prowlarr": {"url": unreachable, "api_key": "placeholder",
                     "indexers": [{"id": 1, "name": "placeholder", "protocol": "torrent", "priority": 10, "rssEnabled": False}]},
        "downloadClient": {"type": "qbittorrent", "url": unreachable, "username": "", "password": ""},
        "paths": {"download_dir": "/downloads", "media_dir": ROOT},
        "registration": {"enabled": False, "require_admin_approval": True},
    }
    print("setup", call("POST", "/api/setup/complete", body))


def login():
    st, r = call("POST", "/api/auth/local/login", {"username": CREDS["username"], "password": CREDS["password"]})
    if st != 200:
        sys.exit(f"login failed {st} {r}")
    return r.get("accessToken") or (r.get("tokens") or {}).get("accessToken")


def scan(books_path, out_path, sub=""):
    tok = login()
    req = urllib.request.Request(URL + "/api/admin/bulk-import/scan", method="POST",
                                 data=json.dumps({"rootPath": os.path.join(ROOT, sub) if sub else ROOT}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    picks, event, start, matching_from = {}, None, time.time(), None
    with urllib.request.urlopen(req, timeout=24 * 3600) as stream:  # one long event stream
        for raw in stream:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                d = json.loads(line[6:])
                if event == "discovery_complete":
                    matching_from = time.time()
                    print("found", d.get("totalFound"), flush=True)
                elif event == "book_matched":
                    folder = os.path.relpath(d.get("folderPath") or "", ROOT)
                    picks[folder] = d
                    if len(picks) % 200 == 0:
                        print(time.strftime("%H:%M"), "matched", len(picks), flush=True)
                elif event in ("complete", "error"):
                    print(event, str(d)[:200], flush=True)
                    break
    # Total runtime of the matching (not the folder discovery), read by score.py.
    open(out_path.removesuffix(".jsonl") + ".time", "w").write(f"{time.time() - (matching_from or start):.0f}\n")
    with open(out_path, "w", encoding="utf-8") as out:
        for book in json.load(open(books_path)):
            d = picks.get(book["folder"])
            m = (d or {}).get("match")
            row = {"folder": book["folder"], "status": "matched" if m else "skipped"}
            if m:
                # The scan sends no series: None leaves it to the field check's "unknown".
                row["match"] = {"asin": m.get("asin") or "", "title": m.get("title") or "", "author": m.get("author") or "",
                                "narrator": m.get("narrator") or "", "series": None, "sequence": ""}
                row["low_confidence"] = (d.get("metadataSource") or "tags") != "tags"
            else:
                row["skip_reason"] = "no Audible match" if d else "not found by the scan (merged or skipped)"
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    folders = {b["folder"] for b in json.load(open(books_path))}
    merged = sorted(f for f in picks if f not in folders)  # books it folded into a parent folder
    print(f"{out_path}: {sum(1 for d in picks.values() if d.get('match'))} matched of {len(picks)} scanned"
          f"; {len(merged)} entries at a merged parent folder, e.g. {merged[:3]}")


if __name__ == "__main__":
    if sys.argv[1] == "setup":
        setup()
    elif sys.argv[1] == "scan":
        scan(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
