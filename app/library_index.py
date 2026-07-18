from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

FS_SKIP_PREFIXES = (".", "#", "@")  # skip hidden dirs and NAS system dirs
DISC_RE = re.compile(r"^(disc|disk|cd|part|vol|volume)\s*\d+$", re.IGNORECASE)


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in {
        ".m4b",
        ".m4a",
        ".mp4",
        ".mp3",
        ".flac",
        ".ogg",
        ".opus",
        ".aac",
    }


def is_ebook_file(path: Path) -> bool:
    return path.suffix.lower() in {".epub", ".pdf"}


_EBOOK_FORMAT_BUCKET_NAMES = {"epub", "pdf"}


@dataclass
class EbookUnit:
    """One logical ebook, one or more format files sharing an identity.

    `path` is this unit's canonical file -- used as its manual-review
    identity and its libraforge.json sidecar location (epub preferred over
    pdf when both are present). `formats` maps each available extension
    (without the dot) to its full file path.
    """
    path: Path
    formats: dict[str, Path]


def build_ebook_index(
    root: Path, skip_prefixes: tuple[str, ...] = FS_SKIP_PREFIXES
) -> list[EbookUnit]:
    """Walk root for .epub/.pdf files.

    A file whose immediate parent directory is literally named "epub" or
    "pdf" (case-insensitive) is grouped with any same-stem file found in a
    sibling bucket folder under the same grandparent -- this is the layout
    audiobookshelf-adjacent ebook dumps commonly use (format-first, not
    folder-per-book). Every other ebook file is its own single-format unit.

    Deliberately narrow: pairing only fires for the exact bucket-folder-name
    pattern scoped to one grandparent, so it can't misfire by matching
    unrelated same-stem files elsewhere in the library.
    """
    # bucket_files[grandparent][stem_lower][ext] = path
    bucket_files: dict[Path, dict[str, dict[str, Path]]] = {}
    standalone: list[EbookUnit] = []
    try:
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = sorted(
                d for d in dirnames
                if not any(d.startswith(s) for s in skip_prefixes)
            )
            p = Path(dirpath)
            ebook_files = [p / f for f in sorted(filenames) if is_ebook_file(p / f)]
            if not ebook_files:
                continue
            if p != root and p.name.lower() in _EBOOK_FORMAT_BUCKET_NAMES:
                bucket = bucket_files.setdefault(p.parent, {})
                for f in ebook_files:
                    ext = f.suffix.lower().lstrip(".")
                    bucket.setdefault(f.stem.lower(), {})[ext] = f
            else:
                for f in ebook_files:
                    ext = f.suffix.lower().lstrip(".")
                    standalone.append(EbookUnit(path=f, formats={ext: f}))
    except PermissionError:
        pass

    paired: list[EbookUnit] = []
    for stems in bucket_files.values():
        for formats in stems.values():
            canonical = formats.get("epub") or formats.get("pdf")
            paired.append(EbookUnit(path=canonical, formats=formats))

    units = paired + standalone
    units.sort(key=lambda u: str(u.path))
    return units


def folder_listing_signature(folder: Path) -> str:
    """Signature of a folder's direct children, one level deeper into any
    disc/part subfolder (see DISC_RE).

    Catches any add/remove/rename/resize/rewrite of a file directly inside
    `folder`, independent of whether the OS reliably bumps the folder's own
    mtime (NFS/bind-mount safe, unlike stat()-ing the folder itself). A
    missing/deleted folder returns "", distinct from any real signature
    (an empty existing folder still hashes an empty joined string, which is
    also "" -- both are legitimately "nothing here", and both correctly
    invalidate any cached probe result for a folder that no longer has
    content, which is the behavior that matters).

    build_library_index() collapses a disc/part subfolder's audio into its
    parent book folder, so the parent is the only one that gets a signature
    -- but a plain stat() of the disc subfolder's own directory entry only
    reflects adds/removes/renames directly inside it, not an in-place
    rewrite of a file one level further down. Folding each disc subfolder's
    own signature into its parent's closes that gap.
    """
    try:
        parts = []
        for entry in os.scandir(folder):
            stat = entry.stat()
            parts.append(f"{entry.name}:{stat.st_size}:{stat.st_mtime_ns}")
            if entry.is_dir() and DISC_RE.match(entry.name):
                parts.append(f"{entry.name}/:{folder_listing_signature(Path(entry.path))}")
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return ""
    return hashlib.sha256("|".join(sorted(parts)).encode("utf-8")).hexdigest()


def build_library_index(
    root: Path, skip_prefixes: tuple[str, ...] = FS_SKIP_PREFIXES
) -> tuple[list[tuple[Path, bool]], dict[str, str]]:
    """Single recursive walk producing the folder-existence inventory and
    each folder's listing signature together.

    Ported from the pre-unification _find_book_folders /
    _build_manual_review_search_index walk (same disc-subfolder collapsing,
    same loose-root-file handling), with no consumer-specific ignore-folder
    filtering: only the fixed skip_prefixes (hidden/system dirs) are
    excluded here. Each consumer applies its own ignored_folders as an
    in-memory post-filter over the returned entries.

    Returns (entries, signatures):
      entries: sorted book folders (is_file=False) followed by sorted loose
        root audio files (is_file=True).
      signatures: {str(folder_path): listing_signature} for every folder
        entry. Loose root files have no signature entry -- their own
        (name, size, mtime_ns) is already covered by each consumer's
        existing per-file probe cache.
    """
    audio_folders: set[Path] = set()
    loose_root_files: list[Path] = []
    try:
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = sorted(
                d for d in dirnames
                if not any(d.startswith(s) for s in skip_prefixes)
            )
            p = Path(dirpath)
            if p == root:
                loose_root_files.extend(
                    p / f for f in sorted(filenames) if is_audio_file(p / f)
                )
                continue
            if any(is_audio_file(p / f) for f in filenames):
                audio_folders.add(p)
    except PermissionError:
        pass

    book_folders: set[Path] = set()
    for folder in audio_folders:
        if DISC_RE.match(folder.name) and folder.parent != root:
            book_folders.add(folder.parent)
        else:
            book_folders.add(folder)

    signatures = {
        str(folder): folder_listing_signature(folder)
        for folder in book_folders
    }
    entries = [(folder, False) for folder in sorted(book_folders)]
    entries.extend((f, True) for f in sorted(loose_root_files))
    return entries, signatures


@dataclass
class LibraryIndexState:
    """In-memory state for the shared library index. One module-level
    instance -- always scoped to the whole AUDIOBOOKS_ROOT passed in by the
    caller at trigger time, matching how the pre-unification Manual Review
    index worked."""
    status: str = "idle"  # idle | ready | error
    entries: list[tuple[str, bool]] = field(default_factory=list)
    signatures: dict[str, str] = field(default_factory=dict)
    generation: int = 0
    error: str | None = None


_state = LibraryIndexState()
_lock = threading.Lock()


def get_state() -> LibraryIndexState:
    return _state


def reset_state_for_tests() -> None:
    """Test-only helper: reset shared module state between test cases. Not
    used by production code paths."""
    global _state
    _state = LibraryIndexState()


def _run_build(root: Path) -> None:
    global _state
    previous = _state
    try:
        entries, signatures = build_library_index(root)
        new_entries = [(str(p), is_file) for p, is_file in entries]
        # generation is the coarse "did the library actually change" signal
        # consumers (Manual Review search) key their own staleness off of --
        # bump it only when this walk's result differs from the previous
        # one. ensure_library_index_fresh has no cheap pre-check gating how
        # often a walk runs (by design, see its docstring), so a consumer
        # that polls this on a timer would otherwise see generation advance
        # on every walk cycle regardless of whether anything on disk
        # changed, reporting a false "library change detected" each time.
        changed = new_entries != previous.entries or signatures != previous.signatures
        _state = LibraryIndexState(
            status="ready",
            entries=new_entries,
            signatures=signatures,
            generation=previous.generation + 1 if changed else previous.generation,
        )
    except Exception as exc:
        _state = LibraryIndexState(
            status="error",
            entries=previous.entries,
            signatures=previous.signatures,
            generation=previous.generation,
            error=str(exc),
        )


def ensure_library_index_fresh(root: Path) -> None:
    """Kick a non-blocking background walk if none is already in flight.

    No cheap pre-check gates this -- the walk itself (metadata-only, no
    ffprobe) is how staleness is detected, since no coarse signal can
    safely rule out a subtree without risking a missed change. Always
    returns immediately: the caller reads get_state() for whatever the
    last-completed walk produced, and the correction from THIS trigger
    lands on the next call after the background walk finishes."""
    if not _lock.acquire(blocking=False):
        return

    def worker() -> None:
        try:
            _run_build(root)
        finally:
            _lock.release()

    threading.Thread(target=worker, daemon=True).start()


@dataclass
class EbookIndexState:
    """In-memory state for the ebook discovery index. Fully independent
    from LibraryIndexState/_state -- Folder Forge and M4B Tool only ever
    read get_state(), never this, so ebook discovery cannot affect them."""
    status: str = "idle"  # idle | ready | error
    units: list[EbookUnit] = field(default_factory=list)
    generation: int = 0
    error: str | None = None


_ebook_state = EbookIndexState()
_ebook_lock = threading.Lock()


def get_ebook_state() -> EbookIndexState:
    return _ebook_state


def reset_ebook_state_for_tests() -> None:
    """Test-only helper: reset ebook index state between test cases."""
    global _ebook_state
    _ebook_state = EbookIndexState()


def _run_ebook_build(root: Path) -> None:
    global _ebook_state
    previous = _ebook_state
    try:
        units = build_ebook_index(root)
        changed = units != previous.units
        _ebook_state = EbookIndexState(
            status="ready",
            units=units,
            generation=previous.generation + 1 if changed else previous.generation,
        )
    except Exception as exc:
        _ebook_state = EbookIndexState(
            status="error",
            units=previous.units,
            generation=previous.generation,
            error=str(exc),
        )


def ensure_ebook_index_fresh(root: Path) -> None:
    """Kick a non-blocking background ebook walk if none is already in
    flight. Mirrors ensure_library_index_fresh exactly, on its own lock."""
    if not _ebook_lock.acquire(blocking=False):
        return

    def worker() -> None:
        try:
            _run_ebook_build(root)
        finally:
            _ebook_lock.release()

    threading.Thread(target=worker, daemon=True).start()
