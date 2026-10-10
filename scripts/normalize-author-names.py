#!/usr/bin/env python3
"""One-time migration to the universal author-name scheme (dry run by default).

Phases: author folders, metadata.json / libraforge.json sidecars, and (opt-in)
embedded audio tags. Every applied change is appended to a JSONL log so it can
be undone with --revert.

--abs-authors (ABS-only mode, needs ABS credentials) fixes the author names
Audiobookshelf stores itself. ABS keeps authors in its database and re-reads its
central metadata.json (/metadata/items/<itemId>/, keyed by item id) over the
embedded tags on a rescan, so files already on the scheme can still show the old
spelling in ABS. Books are fixed with PATCH /api/items/{id}/media (ABS rewrites
its metadata.json from that). An author record left with no books is deleted
when the scheme spelling already exists and holds the same kind of data (or none), renamed
when the scheme spelling does not exist yet, and ADOPTED when it carries
an image, description or ASIN the scheme-spelled twin lacks: ABS destroys the
old record on a rename-merge, data included, so the twin is parked under a
temporary name, the data-bearing record takes the scheme name, and the twin is
merged into it, leaving one record with the data and all the books.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

try:
    from app.abs_client import abs_delete_json, abs_get_json, abs_patch_json
    from app.author_names import format_author_credit, format_person_name, scheme_enabled
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.abs_client import abs_delete_json, abs_get_json, abs_patch_json
    from app.author_names import format_author_credit, format_person_name, scheme_enabled

SERVICE_PREFIXES = ("_", "#", "@", ".")


def plan_folder_changes(root: Path) -> list[dict]:
    """Top-level author folders whose name differs from the scheme."""
    existing = {e.name for e in os.scandir(root) if e.is_dir(follow_symlinks=False)}
    changes = []
    for name in sorted(existing):
        if name.startswith(SERVICE_PREFIXES):
            continue
        new = format_person_name(name)
        if new != name:
            changes.append({"phase": "folder", "old": name, "new": new,
                            "action": "merge" if new in existing else "rename"})
    return changes


def apply_folder_change(root: Path, change: dict) -> list[dict]:
    """Rename, or merge into the existing folder. A merge that would overwrite
    anything is refused whole, so nothing is ever clobbered."""
    src, dst = root / change["old"], root / change["new"]
    if change["action"] == "rename":
        os.rename(src, dst)
        return [change]
    clashes = sorted(child.name for child in src.iterdir() if (dst / child.name).exists())
    if clashes:
        raise FileExistsError(f"merge {change['old']!r} -> {change['new']!r} blocked by: {clashes}")
    logged = []
    for child in sorted(src.iterdir()):
        os.rename(child, dst / child.name)
        logged.append({"phase": "folder-child", "old": str(child), "new": str(dst / child.name)})
    src.rmdir()
    logged.append(change)
    return logged


def _json_author_edits(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    edits = []
    if path.name.endswith("metadata.json") and isinstance(data.get("authors"), list):
        for index, author in enumerate(data["authors"]):
            if isinstance(author, str) and format_person_name(author) != author:
                edits.append({"phase": "sidecar", "path": str(path), "field": f"authors[{index}]",
                              "old": author, "new": format_person_name(author)})
    audible = (data.get("marker") or {}).get("audible") if isinstance(data.get("marker"), dict) else None
    if isinstance(audible, dict) and isinstance(audible.get("author"), str):
        old = audible["author"]
        if format_author_credit(old) != old:
            edits.append({"phase": "sidecar", "path": str(path), "field": "marker.audible.author",
                          "old": old, "new": format_author_credit(old)})
    return edits


def plan_sidecar_changes(root: Path) -> list[dict]:
    edits = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(("#", "@", "."))]
        for name in sorted(files):
            if name.endswith(("metadata.json", "libraforge.json")):
                edits.extend(_json_author_edits(Path(directory) / name))
    return edits


def _set_json_field(data: dict, field: str, value: str) -> None:
    if field.startswith("authors["):
        data["authors"][int(field[8:-1])] = value
    else:
        data["marker"]["audible"]["author"] = value


def apply_sidecar_edits(edits: list[dict], reverse: bool = False) -> None:
    by_path: dict[str, list[dict]] = {}
    for edit in edits:
        by_path.setdefault(edit["path"], []).append(edit)
    for path, group in by_path.items():
        target = Path(path)
        data = json.loads(target.read_text(encoding="utf-8"))
        for edit in group:
            _set_json_field(data, edit["field"], edit["old"] if reverse else edit["new"])
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, target)


def plan_tag_changes(root: Path) -> list[dict]:
    from mutagen.id3 import ID3
    from mutagen.mp4 import MP4
    edits = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(("#", "@", "."))]
        for name in sorted(files):
            path = Path(directory) / name
            suffix = path.suffix.lower()
            try:
                if suffix in (".m4b", ".m4a"):
                    tags = MP4(path).tags or {}
                    fields = {key: (tags.get(key) or [""])[0] for key in ("\xa9ART", "aART")}
                elif suffix == ".mp3":
                    tags = ID3(path)
                    fields = {key: (str(tags[key].text[0]) if key in tags else "") for key in ("TPE1", "TPE2")}
                else:
                    continue
            except Exception:
                continue
            for field, old in fields.items():
                if old and format_author_credit(old) != old:
                    edits.append({"phase": "tag", "path": str(path), "field": field,
                                  "old": old, "new": format_author_credit(old)})
    return edits


def apply_tag_edits(edits: list[dict], reverse: bool = False) -> None:
    from mutagen.id3 import ID3, TPE1, TPE2
    from mutagen.mp4 import MP4
    by_path: dict[str, list[dict]] = {}
    for edit in edits:
        by_path.setdefault(edit["path"], []).append(edit)
    for path, group in by_path.items():
        value_of = (lambda e: e["old"]) if reverse else (lambda e: e["new"])
        if path.lower().endswith((".m4b", ".m4a")):
            audio = MP4(path)
            for edit in group:
                audio.tags[edit["field"]] = [value_of(edit)]
            audio.save()
        else:
            audio = ID3(path)
            for edit in group:
                frame = {"TPE1": TPE1, "TPE2": TPE2}[edit["field"]]
                audio.setall(edit["field"], [frame(encoding=3, text=[value_of(edit)])])
            audio.save()


def plan_abs_author_changes(authors: list[dict], get_author: Callable[[str], dict],
                            get_item: Callable[[str], dict]) -> list[dict]:
    """ABS-side plan. `authors` is /api/libraries/{id}/authors; get_author(id)
    returns the author with its items, get_item(id) the expanded item (whose
    media.metadata.authors is the structured list a PATCH must send back)."""
    by_name = {a["name"]: a for a in authors}
    changes = []
    for author in authors:
        new_name = format_person_name(author["name"])
        if new_name == author["name"]:
            continue
        detail = get_author(author["id"])
        items = detail.get("libraryItems") or []
        for brief in items:
            item = get_item(brief["id"])
            old = [str(a.get("name") or "") for a in (item.get("media") or {}).get("metadata", {}).get("authors") or []]
            new = list(dict.fromkeys(format_person_name(n) for n in old))
            if new != old and not any(c.get("item_id") == brief["id"] for c in changes):
                changes.append({"phase": "abs-item", "item_id": brief["id"], "path": str(item.get("path") or ""),
                                "old": old, "new": new, "status": "CLEAN"})
        if items:
            continue
        data = [k for k in ("imagePath", "description", "asin") if detail.get(k)]
        twin = by_name.get(new_name)
        if twin is None:
            changes.append({"phase": "abs-author-rename", "author_id": author["id"], "old": author["name"],
                            "new": new_name, "status": "CLEAN"})
            continue
        twin_has_data = any(get_author(twin["id"]).get(k) for k in ("imagePath", "description", "asin"))
        if data and not twin_has_data:
            changes.append({"phase": "abs-author-adopt", "author_id": author["id"], "twin_id": twin["id"],
                            "old": author["name"], "new": new_name, "keeps": data, "status": "CLEAN"})
        else:
            changes.append({"phase": "abs-author-delete", "author_id": author["id"], "old": author["name"],
                            "new": new_name, "status": "CLEAN"})
    return changes


def plan_abs_changes(abs_url: str, abs_api_key: str) -> list[dict]:
    def request(path: str, params: dict[str, str]):
        return abs_get_json(path, params, abs_url, abs_api_key)

    libs = request("/api/libraries", {})
    libraries = libs.get("libraries", []) if isinstance(libs, dict) else (libs or [])
    changes: list[dict] = []
    for lib in [l for l in libraries if l.get("mediaType") == "book"]:
        authors = request(f"/api/libraries/{lib['id']}/authors", {}).get("authors", [])
        changes += plan_abs_author_changes(
            authors,
            lambda author_id: request(f"/api/authors/{author_id}", {"include": "items"}),
            lambda item_id: request(f"/api/items/{item_id}", {"expanded": "1"}),
        )
    return changes


def _adopt_author(change: dict, abs_url: str, abs_api_key: str) -> bool:
    """Swap the data-bearing empty record in for its scheme-spelled twin (see the
    module docstring). Re-checks both records first; if a step fails the twin is
    put back under its scheme name so nothing is left under a temporary name."""
    try:
        orphan = abs_get_json(f"/api/authors/{change['author_id']}", {"include": "items"}, abs_url, abs_api_key)
        abs_get_json(f"/api/authors/{change['twin_id']}", {}, abs_url, abs_api_key)
    except Exception:
        return False  # one of them is already gone
    if orphan.get("libraryItems"):
        return False
    temp = f"{change['new']} (merging {change['twin_id'][:8]})"
    abs_patch_json(f"/api/authors/{change['twin_id']}", {"name": temp}, abs_url, abs_api_key)
    try:
        abs_patch_json(f"/api/authors/{change['author_id']}", {"name": change["new"]}, abs_url, abs_api_key)
    except Exception:
        abs_patch_json(f"/api/authors/{change['twin_id']}", {"name": change["new"]}, abs_url, abs_api_key)
        raise
    abs_patch_json(f"/api/authors/{change['twin_id']}", {"name": change["new"]}, abs_url, abs_api_key)
    return True


def apply_abs_changes(changes: list[dict], abs_url: str, abs_api_key: str, reverse: bool = False) -> list[dict]:
    """Books first, then author records (re-checked: ABS may already have dropped
    an author once its last book moved). Returns the entries actually applied;
    a delete cannot be reverted, so it is applied and logged but skipped on reverse."""
    applied = []
    ordered = sorted(changes, key=lambda c: c["phase"] != "abs-item")
    for change in ordered:
        if change["status"] != "CLEAN":
            continue
        phase = change["phase"]
        if phase == "abs-item":
            names = change["old"] if reverse else change["new"]
            abs_patch_json(f"/api/items/{change['item_id']}/media",
                           {"metadata": {"authors": [{"name": n} for n in names]}}, abs_url, abs_api_key)
        elif phase == "abs-author-rename":
            abs_patch_json(f"/api/authors/{change['author_id']}",
                           {"name": change["old"] if reverse else change["new"]}, abs_url, abs_api_key)
        elif phase == "abs-author-adopt":
            if reverse or not _adopt_author(change, abs_url, abs_api_key):
                continue
        elif phase == "abs-author-delete":
            if reverse:
                continue
            try:
                detail = abs_get_json(f"/api/authors/{change['author_id']}", {"include": "items"}, abs_url, abs_api_key)
            except Exception:
                continue  # already gone
            if detail.get("libraryItems"):
                continue
            abs_delete_json(f"/api/authors/{change['author_id']}", abs_url, abs_api_key)
        applied.append(change)
    return applied


def revert(log_path: Path, root: Path, abs_url: str = "", abs_api_key: str = "") -> None:
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    abs_entries = [e for e in entries if e["phase"].startswith("abs-")]
    if abs_entries:
        apply_abs_changes(list(reversed(abs_entries)), abs_url, abs_api_key, reverse=True)
        skipped = [e["old"] for e in abs_entries if e["phase"] in ("abs-author-delete", "abs-author-adopt")]
        if skipped:
            print(f"  NOT restored (ABS cannot split or recreate those author records): {skipped}")
    for entry in reversed(entries):
        if entry["phase"] == "folder-child":
            os.rename(entry["new"], entry["old"])
        elif entry["phase"] == "folder":
            if entry["action"] == "rename":
                os.rename(root / entry["new"], root / entry["old"])
            else:
                (root / entry["old"]).mkdir(exist_ok=True)
    apply_sidecar_edits([e for e in entries if e["phase"] == "sidecar"], reverse=True)
    apply_tag_edits([e for e in entries if e["phase"] == "tag"], reverse=True)


def run_abs_authors(args, abs_url: str, abs_api_key: str) -> int:
    if not abs_api_key:
        print("--abs-authors needs --abs-config-file, or --abs-url and --abs-api-key (or the ABS_API_KEY env var)")
        return 1
    changes = plan_abs_changes(abs_url, abs_api_key)
    for phase, label in (("abs-item", "Books whose ABS author list changes"),
                         ("abs-author-rename", "Author records renamed"),
                         ("abs-author-adopt", "Empty records that keep their photo/bio/ASIN and absorb the scheme-spelled twin"),
                         ("abs-author-delete", "Empty author records deleted")):
        rows = [c for c in changes if c["phase"] == phase]
        print(f"{label}: {len(rows)}")
        for c in rows:
            old, new = (c["old"], c["new"])
            where = f"  ({c['path']})" if c.get("path") else ""
            print(f"  {c['status']:9} {old!r} -> {new!r}{where}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to make the CLEAN changes.")
        return 0
    log_path = args.log or Path("reports") / f"author-normalize-abs-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    applied = apply_abs_changes(changes, abs_url, abs_api_key)
    with log_path.open("a", encoding="utf-8") as log:
        for entry in applied:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"Done. {len(applied)} ABS changes applied. Change log: {log_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path("/audiobooks"), help="Library root, e.g. /audiobooks")
    parser.add_argument("--apply", action="store_true", help="Make the changes (default: dry run)")
    parser.add_argument("--tags", action="store_true", help="Also rewrite embedded audio tags (slow, opt-in)")
    parser.add_argument("--log", type=Path, help="JSONL change log (default: reports/author-normalize-<time>.jsonl)")
    parser.add_argument("--revert", type=Path, help="Undo the changes recorded in this log")
    parser.add_argument("--abs-authors", action="store_true",
                        help="Fix the author names stored in Audiobookshelf itself (see the module docstring). "
                             "ABS-only mode: root is ignored. Needs --abs-config-file, or --abs-url and --abs-api-key.")
    parser.add_argument("--abs-config-file", type=Path,
                        help='JSON file shaped like {"url": ..., "api_key": ...} (config/abs.json); keeps the key off the command line')
    parser.add_argument("--abs-url", default=os.environ.get("ABS_URL", ""))
    parser.add_argument("--abs-api-key", default=os.environ.get("ABS_API_KEY", ""))
    parser.add_argument("--even-if-disabled", action="store_true",
                        help="Run although the universal scheme is switched off in Settings")
    args = parser.parse_args()
    abs_url, abs_api_key = args.abs_url, args.abs_api_key
    if args.abs_config_file:
        abs_config = json.loads(args.abs_config_file.read_text(encoding="utf-8"))
        abs_url = abs_config.get("url") or abs_url
        abs_api_key = abs_config.get("api_key") or abs_api_key
    if args.revert:
        revert(args.revert, args.root, abs_url, abs_api_key)
        print(f"Reverted changes from {args.revert}")
        return 0
    if not scheme_enabled() and not args.even_if_disabled:
        print("The universal author-name scheme is switched off (Settings, Author names).")
        print("Turn it on first, so the organizer and this tool agree, or pass --even-if-disabled.")
        return 2
    if args.abs_authors:
        return run_abs_authors(args, abs_url, abs_api_key)
    folders = plan_folder_changes(args.root)
    sidecars = plan_sidecar_changes(args.root)
    tags = plan_tag_changes(args.root) if args.tags else []
    print(f"Author folders to change: {len(folders)} ({sum(c['action'] == 'merge' for c in folders)} merges)")
    for change in folders:
        print(f"  {change['action'].upper():6} {change['old']!r} -> {change['new']!r}")
    print(f"Sidecar author fields to change: {len(sidecars)}")
    print(f"Embedded tag fields to change: {len(tags)}{'' if args.tags else ' (not scanned, pass --tags)'}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to make these changes.")
        return 0
    log_path = args.log or Path("reports") / f"author-normalize-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        def record(entries):
            for entry in entries:
                log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            log.flush()
        # Files first, folders last: sidecar and tag paths were planned against the
        # current folder names, so they must be edited before any folder moves.
        apply_sidecar_edits(sidecars)
        record(sidecars)
        if args.tags:
            apply_tag_edits(tags)
            record(tags)
        for change in folders:
            try:
                record(apply_folder_change(args.root, change))
            except FileExistsError as error:
                print(f"  SKIPPED: {error}")
    print(f"Done. Change log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
