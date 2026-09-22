#!/usr/bin/env python3
"""One-time migration to the universal author-name scheme (dry run by default).

Phases: author folders, metadata.json / libraforge.json sidecars, and (opt-in)
embedded audio tags. Every applied change is appended to a JSONL log so it can
be undone with --revert.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from app.author_names import format_author_credit, format_person_name, scheme_enabled
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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


def revert(log_path: Path, root: Path) -> None:
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Library root, e.g. /audiobooks")
    parser.add_argument("--apply", action="store_true", help="Make the changes (default: dry run)")
    parser.add_argument("--tags", action="store_true", help="Also rewrite embedded audio tags (slow, opt-in)")
    parser.add_argument("--log", type=Path, help="JSONL change log (default: reports/author-normalize-<time>.jsonl)")
    parser.add_argument("--revert", type=Path, help="Undo the changes recorded in this log")
    parser.add_argument("--even-if-disabled", action="store_true",
                        help="Run although the universal scheme is switched off in Settings")
    args = parser.parse_args()
    if args.revert:
        revert(args.revert, args.root)
        print(f"Reverted changes from {args.revert}")
        return 0
    if not scheme_enabled() and not args.even_if_disabled:
        print("The universal author-name scheme is switched off (Settings, Author names).")
        print("Turn it on first, so the organizer and this tool agree, or pass --even-if-disabled.")
        return 2
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
