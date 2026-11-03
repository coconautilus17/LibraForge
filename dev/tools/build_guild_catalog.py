"""Rebuild the Audiobook Guild catalog LibraForge ships (app/data/audiobook-guild-catalog.json):
every book in the store, each with its runtime read from its page.

usage: python dev/tools/build_guild_catalog.py [--keep PATH]

Runs in the LibraForge image's venv (it needs httpx), from the repository root. Requests go
through the matcher's own pacer (one every 2 s), so a full build of ~800 books takes about
half an hour. --keep reuses the runtimes of an existing catalog for books the store hasn't
changed since (the shipped file by default), so a rebuild reads only new or changed pages.
"""
import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import audiobook_guild as guild  # noqa: E402
from app.json_files import write_json_atomic  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--keep", type=Path, default=guild.SHIPPED_CATALOG)
opts = ap.parse_args()

products = guild._read_store_catalog(guild.PACER, guild._default_http_get, 20)
if not products:
    sys.exit("the store's catalog couldn't be read")
kept = guild._load_catalog(opts.keep).get("runtimes") or {}
runtimes, read, missing = {}, 0, []
for i, product in enumerate(products, 1):
    handle = product["handle"]
    old = kept.get(handle)
    if isinstance(old, dict) and old.get("updated_at") == product["updated_at"] and old.get("minutes"):
        runtimes[handle] = old
        continue
    page = guild._fetch(guild.STORE_URL + "/products/" + urllib.parse.quote(handle), guild.PACER,
                        guild._default_http_get, 20)
    read += 1
    minutes = guild._runtime_minutes(page.decode("utf-8", "replace")) if page else None
    if minutes is None:
        missing.append(handle)
    runtimes[handle] = {"updated_at": product["updated_at"], "minutes": minutes}
    if i % 50 == 0:
        print(f"{i}/{len(products)} books, {read} pages read", flush=True)

write_json_atomic(guild.SHIPPED_CATALOG, {"read_at": time.time(), "products": products, "runtimes": runtimes})
print(f"{guild.SHIPPED_CATALOG}: {len(products)} books, {len(products) - len(missing)} with a runtime, "
      f"{read} pages read")
if missing:
    print("no runtime on the page:", ", ".join(missing[:20]) + (" ..." if len(missing) > 20 else ""))
