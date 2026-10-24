"""Tiny BookOrbit API client, for comparing against a throwaway BookOrbit stack.

BOOKORBIT_URL   API base (default http://127.0.0.1:5057/api/v1)
BOOKORBIT_CREDS JSON file with {"username", "password"} (default data/bookorbit-admin.json)

usage: bookorbit.py METHOD PATH [json-body]
"""
import json
import os
import sys
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


if __name__ == "__main__":
    tok = login()
    body = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    st, r = call(sys.argv[1], sys.argv[2], body, tok)
    print(st)
    print(json.dumps(r, indent=1, ensure_ascii=False))
