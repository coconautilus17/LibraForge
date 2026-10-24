"""Run LibraForge's real matcher on mock books: original tags + duration, no files.

Runs inside a LibraForge image with this checkout's app/ and scripts/ mounted
at /app (run.sh does that). Each book's search context is built the way
build_search_context builds it (build_search_queries_from_metadata on the
backup tags, the backup duration, the raw tags and the "current" snapshot),
placed in the context cache, and search_item() runs normally against the real
providers. Report items come from the fixer's own _build_report_item, so they
match a real dry run's REPORT_ITEM_JSON; each also carries its log lines.

usage: lf_bench.py <books.json> <out.jsonl> <audible|abs> [workers] [--abs-config PATH]
"""
import argparse
import importlib.util
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "/app")
MOCK_ROOT = Path("/mock")

ap = argparse.ArgumentParser()
ap.add_argument("books")
ap.add_argument("out")
ap.add_argument("provider", choices=["audible", "abs"])
ap.add_argument("workers", nargs="?", type=int, default=4)
ap.add_argument("--abs-config", default="/app/config/abs.json")
opts = ap.parse_args()

spec = importlib.util.spec_from_file_location("fixer", "/app/scripts/audible-metadata-fixer-v5.py")
fixer = importlib.util.module_from_spec(spec)
sys.modules["fixer"] = fixer
spec.loader.exec_module(fixer)

argv = [str(MOCK_ROOT), "--min-score", "0.70", "--limit", "50",
        "--abs-agg-url", "http://abs-agg:3000", "--abs-tract-url", "http://abs-tract:5555",
        "--abs-tract-kindle-region", "uk"]
if opts.provider == "abs":
    cfg = json.load(open(opts.abs_config))
    argv += ["--provider", "abs", "--abs-provider", "audible", "--abs-url", cfg["url"], "--abs-api-key", cfg["api_key"]]
else:
    argv += ["--auth-file", "/nonexistent/audible.json"]  # no login: the public catalog


# Take the fixer's own argument defaults: parse argv with its parser, then stop.
class _Captured(Exception):
    pass


_orig_parse = argparse.ArgumentParser.parse_args


def _capture(self, args=None, namespace=None):
    raise _Captured(_orig_parse(self, argv))


argparse.ArgumentParser.parse_args = _capture
try:
    fixer.main()
except _Captured as cap:
    args = cap.args[0]
argparse.ArgumentParser.parse_args = _orig_parse

if hasattr(fixer, "LIBRARY_ROOTS"):
    fixer.LIBRARY_ROOTS[:] = [MOCK_ROOT]

books = json.load(open(opts.books))
locks = {name: threading.Lock() for name in ("ctx", "match", "search", "out")}
search_context_cache, match_cache, search_cache, in_flight = {}, {}, {}, {}

for book in books:
    path = MOCK_ROOT / book["folder"] / book["file"]
    tags = book["tags"]
    queries, clues = fixer.build_search_queries_from_metadata(path, tags=tags)
    clues["local_duration_minutes"] = book["minutes"]
    clues["_raw_tags"] = tags
    current = fixer.read_current_book_metadata(tags)
    current["duration_minutes"] = book["minutes"]
    clues["current"] = current
    search_context_cache[fixer.get_search_context_cache_key(path, {})] = (queries, clues)

out = open(opts.out, "w", encoding="utf-8")


def run(index_book):
    index, book = index_book
    path = MOCK_ROOT / book["folder"] / book["file"]
    try:
        result = fixer.search_item(
            index=index, file_path=path, total=len(books), multi_part_group_map={},
            args=args, auth_file=args.auth_file, auth_password=None,
            search_context_cache=search_context_cache, search_context_lock=locks["ctx"],
            match_cache=match_cache, match_cache_lock=locks["match"],
            search_cache=search_cache, search_cache_lock=locks["search"],
            search_in_flight=in_flight, folder_audio_counts=None, abs_index=None,
        )
        item = fixer._build_report_item(result)
        item["log"] = result.log_lines
    except Exception as exc:  # keep going; record the failure
        item = {"path": str(path), "status": "error", "error": repr(exc)}
    item["folder"] = book["folder"]
    with locks["out"]:
        out.write(json.dumps(item, ensure_ascii=False) + "\n")
        out.flush()


with ThreadPoolExecutor(max_workers=opts.workers) as pool:
    list(pool.map(run, enumerate(books, start=1)))
out.close()
print("done", len(books))
