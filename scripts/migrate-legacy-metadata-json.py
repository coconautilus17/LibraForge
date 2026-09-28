#!/usr/bin/env python3
"""Migrate legacy metadata.json files into Audiobookshelf via its API, then delete them.

metadata.json is retired in LibraForge (writes go straight to ABS through its
API), but older versions left one in most book folders. ABS re-reads that file
on every rescan of the folder and prefers it over its own database, so it
silently reverts API edits (LibraForge #298).

For every book whose own folder holds a metadata.json, this compares the file
with the ABS record:
  - identical            -> delete the file
  - different, ABS newer -> ABS wins, delete the file
  - different, file newer (file mtime > item updatedAt)
                         -> push the file's differing, non-blank values to ABS,
                            then delete the file
  - unreadable           -> left alone and reported

Default is a DRY RUN: nothing is written, deleted or PATCHed; a JSON report of
what would happen is written. Pass --apply to perform it (each book is
re-fetched right before it is reconciled, and each file is first copied in full
to --backup-dir). Run it where the library is mounted
at the same path ABS uses (e.g. inside the LibraForge container, /audiobooks).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.abs_client import (  # noqa: E402
    abs_get_json,
    apply_legacy_metadata_json_migration,
    plan_legacy_metadata_json_migration,
    reconcile_legacy_metadata_json,
)
from app.enrichment import fetch_all_abs_book_items  # noqa: E402

ABS_REQUEST_GAP_S = 0.2  # at most 5 ABS requests/second


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually reconcile and delete (default: dry run).")
    parser.add_argument(
        "--abs-config-file", type=Path,
        help='JSON file shaped like {"url": ..., "api_key": ...} (the same shape as config/abs.json). '
             "Prefer this: the key never appears on the command line.",
    )
    parser.add_argument("--abs-url", default=os.environ.get("ABS_URL", "http://audiobookshelf"))
    parser.add_argument("--abs-api-key", default=os.environ.get("ABS_API_KEY", ""))
    parser.add_argument("--report", type=Path, default=Path("legacy-metadata-json-migration.json"),
                        help="Where to write the JSON report (default: ./legacy-metadata-json-migration.json).")
    parser.add_argument("--backup-dir", type=Path, default=Path("legacy-metadata-json-backup"),
                        help="--apply copies every file here (<item id>.json) before it can be deleted "
                             "(default: ./legacy-metadata-json-backup).")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N candidate books (testing).")
    args = parser.parse_args()

    abs_url, abs_api_key = args.abs_url, args.abs_api_key
    if args.abs_config_file:
        config = json.loads(args.abs_config_file.read_text(encoding="utf-8"))
        abs_url = config.get("url") or abs_url
        abs_api_key = config.get("api_key") or abs_api_key
    if not abs_api_key:
        print("Needs --abs-config-file, --abs-api-key, or the ABS_API_KEY env var.")
        return 1

    last = [0.0]

    def paced_get(path: str, params: dict[str, str]):
        gap = last[0] + ABS_REQUEST_GAP_S - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        last[0] = time.monotonic()
        return abs_get_json(path, params, abs_url, abs_api_key)

    def get_item(item_id: str):
        return paced_get(f"/api/items/{item_id}", {"expanded": "1"})

    items = fetch_all_abs_book_items(paced_get)
    print(f"{len(items)} ABS items; checking their folders for a legacy metadata.json...")
    rows = plan_legacy_metadata_json_migration(
        items, get_item=get_item,
        on_progress=lambda n, total: print(f"  {n}/{total}", end="\r", flush=True) if n % 25 == 0 or n == total else None,
    )
    if args.limit:
        rows = rows[: args.limit]
    print()
    planned = Counter(r["action"] for r in rows)
    print(f"{len(rows)} legacy metadata.json file(s): " + ", ".join(f"{k}={v}" for k, v in sorted(planned.items())))

    outcome: dict[str, int] = {}
    try:
        if args.apply:
            outcome = apply_legacy_metadata_json_migration(
                rows, get_item=get_item, backup_dir=args.backup_dir,
                reconcile=lambda path, item: reconcile_legacy_metadata_json(
                    path, item, abs_url=abs_url, abs_api_key=abs_api_key),
                on_progress=lambda n, total: print(f"  applied {n}/{total}", end="\r", flush=True)
                if n % 25 == 0 or n == total else None,
            )
            print()
            print("Applied: " + ", ".join(f"{k}={v}" for k, v in sorted(outcome.items())))
            print(f"Backups of every processed file: {args.backup_dir}")
        else:
            print("Dry run: nothing changed. Re-run with --apply to perform it.")
    finally:
        # Written even if the run is interrupted: rows carry "result" for
        # everything that was already processed.
        args.report.write_text(json.dumps({
            "mode": "apply" if args.apply else "dry-run",
            "planned": dict(planned),
            "applied": dict(outcome),
            "rows": rows,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
