"""Reading every new book before the search, spread over processes: the same search
contexts as threads build, the files' facts left in the shared store for the parent,
and threads whenever forking would not be safe or worth it."""
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app import media_probe
from app.media_facts_store import MediaFactsStore
from app.tests.script_loader import load_script
from app.tests.test_media_probe import make_m4b

FIXER = load_script("fixer_prefill_processes", "audible-metadata-fixer-v5.py")


class PrefillProcessesTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        media_probe.reset()
        self.addCleanup(media_probe.reset)
        self.addCleanup(media_probe.configure_store, None)
        self.root = self.dir / "library"
        for folder in [*(f"Author {i}" for i in range(3)), "Author 9/Long Book"]:
            (self.root / folder).mkdir(parents=True)
        books = [make_m4b(self.root / f"Author {i}" / f"Book {i}.m4b", title=f"Book {i}") for i in range(3)]
        parts = [make_m4b(self.root / "Author 9" / "Long Book" / f"{n:02d}.m4b", title=f"Long Book {n}")
                 for n in range(1, 6)]
        for leftover in self.root.rglob("*.ffmeta"):
            leftover.unlink()
        self.files = books + parts
        self.groups = {parts[0].parent: parts}
        self.items = FIXER.build_processing_items(self.files, self.groups, {})

    def prefill(self, *, processes: bool) -> dict:
        media_probe.reset()
        media_probe.configure_store(self.dir / f"facts-{processes}.sqlite")
        args = mock.Mock(workers=2, force_original=False, reprobe=False, backup=False)
        cache = {}
        with mock.patch.object(FIXER, "PREFILL_PROCESS_MIN_BOOKS", 1 if processes else 10 ** 9), \
                mock.patch.object(FIXER, "load_marker", return_value={}), \
                mock.patch.object(os, "cpu_count", return_value=4), \
                mock.patch("builtins.print"):
            FIXER.prefill_search_contexts(self.items, self.groups, args, cache, threading.Lock())
        return cache

    def test_processes_build_the_same_contexts_as_threads(self):
        threads = self.prefill(processes=False)
        processes = self.prefill(processes=True)
        self.assertEqual(len(processes), 4)  # three books and one book of five parts
        self.assertEqual(processes, threads)
        self.assertEqual(processes[FIXER.get_search_context_cache_key(self.files[3], self.groups)][1]["group_search"]
                         ["file_count"], 5)

    def test_the_parent_finds_what_the_processes_read_in_the_store(self):
        self.prefill(processes=True)
        self.assertEqual(media_probe.stats().get("requests", 0), 0)  # nothing read in the parent
        for path in self.files:
            media_probe.inspect(path, {"tags", "duration"})
        self.assertEqual(media_probe.stats().get("store_hits"), len(self.files))

    def test_threads_while_another_thread_runs_or_for_few_books(self):
        with mock.patch.object(os, "cpu_count", return_value=4):
            self.assertEqual(FIXER.prefill_process_count(500, 8), 4)
        self.assertEqual(FIXER.prefill_process_count(FIXER.PREFILL_PROCESS_MIN_BOOKS - 1, 8), 0)
        self.assertEqual(FIXER.prefill_process_count(500, 1), 0)
        stop = threading.Event()
        other = threading.Thread(target=stop.wait)
        other.start()
        try:
            self.assertEqual(FIXER.prefill_process_count(500, 8), 0)
        finally:
            stop.set()
            other.join()

    def test_a_book_of_many_parts_keeps_its_parts_in_order(self):
        parts = self.groups[self.files[3].parent]
        with mock.patch.object(FIXER, "GROUP_READ_MIN_FILES", 10 ** 9):
            one_by_one = FIXER.build_multi_file_search_context(parts)
        side_by_side = FIXER.build_multi_file_search_context(parts)
        self.assertEqual(side_by_side, one_by_one)


class StoreAcrossForkTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "fork"), "needs fork")
    def test_a_forked_process_opens_its_own_connection(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        store = MediaFactsStore(folder / "facts.sqlite", "1:test")
        store.put("/a", 1, 1, {"fields": ["tags"]})
        parent_db = store._connect()
        pid = os.fork()
        if pid == 0:
            ok = store._connect() is not parent_db and store.get("/a", 1, 1) is not None
            store.put("/b", 2, 2, {"fields": ["tags"]})
            os._exit(0 if ok else 1)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        self.assertIs(store._connect(), parent_db)
        self.assertEqual(store.get("/b", 2, 2), {"fields": ["tags"]})


if __name__ == "__main__":
    unittest.main()
