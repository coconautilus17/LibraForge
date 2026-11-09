"""Run the Metadata Fixer's main() on a small temporary library, for tests.

Books are short silent M4B files made with ffmpeg. A run needs no network:
either the whole per-book search is replaced (search=), or only the Audible
catalog it asks (catalog=), so everything else a search does still runs.
"""
import contextlib
import io
import subprocess
import sys
from pathlib import Path
from unittest import mock


def make_book(path: Path, title: str, seconds: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", str(seconds),
                    "-c:a", "aac", "-b:a", "8k", "-metadata", f"title={title}", "-metadata", "artist=Some Author",
                    "-f", "mp4", str(path), "-y"], check=True)
    return path


def library_listing(root: Path) -> dict[str, tuple[int, int]]:
    """Every file under root with its size and mtime: equal listings mean nothing was written."""
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def run_fixer(fixer, root: Path, *args: str, search=None, catalog=None) -> str:
    """Run main() over root with the given flags; returns everything it printed.

    search(fixer, index, file_path, total) -> ItemResult stands in for search_item.
    catalog(query, title, author) -> [product] stands in for Audible's catalog search.
    """
    patches = []
    if catalog is not None:
        def fake_audible_search(client, query, limit, api_delay_ms, cache, cache_lock, in_flight,
                                title="", author=""):
            return catalog(query, title, author)
        patches.append(mock.patch.object(fixer, "get_thread_client", return_value=object()))
        patches.append(mock.patch.object(fixer, "cached_audible_search", side_effect=fake_audible_search))
    if search is not None:
        def fake_search_item(*, index, file_path, total, **_):
            return search(fixer, index, file_path, total)
        patches.append(mock.patch.object(fixer, "search_item", side_effect=fake_search_item))
    out = io.StringIO()
    argv = ["fixer", str(root), "--audible-public-region", "us", *args]
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(mock.patch.object(sys, "argv", argv))
        stack.enter_context(contextlib.redirect_stdout(out))
        fixer.main()
    return out.getvalue()


def no_match(fixer, index, file_path, total):
    """An ItemResult for a book no source could match (sent to Manual Review)."""
    return fixer.ItemResult(
        index=index, file_path=file_path, display_path=file_path,
        log_lines=[f"[{index}/{total}] Processing: {file_path}"],
        status="skipped", skip_reason="skipped: no usable Audible match", add_to_manual_review=True,
        clues={},
    )
