"""Rebuild the Audiobook Guild catalog LibraForge ships (app/data/audiobook-guild-catalog.json):
every book in the store, each with its runtime read from its page.

usage: python dev/tools/build_guild_catalog.py [--keep PATH]

Runs in the LibraForge image's venv (it needs httpx), from the repository root. Requests go
through the matcher's own pacer (one every 2 s), so a full build of ~800 books takes about
half an hour. --keep reuses the runtimes of an existing catalog (the shipped file by
default), so a rebuild reads only the pages of books without one.
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
# A published book's runtime doesn't change (the store touches updated_at constantly), so a
# known runtime is kept; only a book with none has its page read. A failed read never
# replaces a runtime, and the books whose read failed are tried again once, more slowly.
runtimes, read, failed = {}, 0, []
# The matcher's pacer pauses for minutes after two failures, which in a long build turns every
# read during the pause into a failure: same gap, no pause.
pacer = guild.GoodreadsPacer(gap_s=guild.GAP_S, fail_threshold=10**9)


def read_runtime(product, pacer):
    page = guild._fetch(guild.STORE_URL + "/products/" + urllib.parse.quote(product["handle"]), pacer,
                        guild._default_http_get, 20)
    return guild._runtime_minutes(page.decode("utf-8", "replace")) if page else None


for i, product in enumerate(products, 1):
    handle = product["handle"]
    old = kept.get(handle)
    if isinstance(old, dict) and old.get("minutes"):
        runtimes[handle] = {"updated_at": product["updated_at"], "minutes": old["minutes"]}
        continue
    read += 1
    minutes = read_runtime(product, pacer)
    runtimes[handle] = {"updated_at": product["updated_at"], "minutes": minutes}
    if minutes is None:
        failed.append(product)
    if i % 50 == 0:
        print(f"{i}/{len(products)} books, {read} pages read", flush=True)
slow = guild.GoodreadsPacer(gap_s=5.0, fail_threshold=10**9)
for product in failed:
    time.sleep(1)
    runtimes[product["handle"]]["minutes"] = read_runtime(product, slow)
missing = [h for h, r in runtimes.items() if r["minutes"] is None]

write_json_atomic(guild.SHIPPED_CATALOG, {"read_at": time.time(), "products": products, "runtimes": runtimes})
print(f"{guild.SHIPPED_CATALOG}: {len(products)} books, {len(products) - len(missing)} with a runtime, "
      f"{read} pages read")
if missing:
    print("no runtime on the page:", ", ".join(missing[:20]) + (" ..." if len(missing) > 20 else ""))
