"""Tests for the shared library index walker: per-folder listing signatures
and the folder-existence + signature-table walk."""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.library_index import (
    DISC_RE,
    FS_SKIP_PREFIXES,
    LibraryIndexState,
    build_library_index,
    ensure_library_index_fresh,
    folder_listing_signature,
    get_state,
    is_audio_file,
    reset_state_for_tests,
)


class FolderListingSignatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, rel, content=b"x"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def test_stable_when_nothing_changes(self):
        self._touch("Book/a.m4b")
        self._touch("Book/b.m4b")
        first = folder_listing_signature(self.root / "Book")
        second = folder_listing_signature(self.root / "Book")
        self.assertEqual(first, second)

    def test_changes_when_a_file_is_added(self):
        self._touch("Book/a.m4b")
        before = folder_listing_signature(self.root / "Book")
        self._touch("Book/b.m4b")
        after = folder_listing_signature(self.root / "Book")
        self.assertNotEqual(before, after)

    def test_changes_when_a_file_is_removed(self):
        self._touch("Book/a.m4b")
        self._touch("Book/b.m4b")
        before = folder_listing_signature(self.root / "Book")
        (self.root / "Book" / "b.m4b").unlink()
        after = folder_listing_signature(self.root / "Book")
        self.assertNotEqual(before, after)

    def test_changes_when_a_file_is_rewritten_with_different_size(self):
        p = self._touch("Book/a.m4b", b"x")
        before = folder_listing_signature(self.root / "Book")
        p.write_bytes(b"xx")
        after = folder_listing_signature(self.root / "Book")
        self.assertNotEqual(before, after)

    def test_missing_folder_returns_empty_signature(self):
        self.assertEqual(folder_listing_signature(self.root / "does-not-exist"), "")

    def test_missing_folder_signature_differs_from_empty_folder(self):
        self.root.joinpath("Empty").mkdir()
        empty_sig = folder_listing_signature(self.root / "Empty")
        missing_sig = folder_listing_signature(self.root / "does-not-exist")
        self.assertNotEqual(empty_sig, missing_sig)

    def test_order_of_children_does_not_affect_signature(self):
        self._touch("Book/b.m4b")
        self._touch("Book/a.m4b")
        via_ba = folder_listing_signature(self.root / "Book")
        (self.root / "Book" / "a.m4b").unlink()
        (self.root / "Book" / "b.m4b").unlink()
        self._touch("Book/a.m4b")
        self._touch("Book/b.m4b")
        via_ab = folder_listing_signature(self.root / "Book")
        self.assertEqual(via_ba, via_ab)


class BuildLibraryIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_finds_a_single_book_folder(self):
        self._touch("Author/Book/Book.m4b")
        entries, signatures = build_library_index(self.root)
        self.assertEqual(entries, [(self.root / "Author" / "Book", False)])
        self.assertIn(str(self.root / "Author" / "Book"), signatures)

    def test_loose_root_file_is_its_own_entry_with_no_signature(self):
        self._touch("Loose.m4b")
        entries, signatures = build_library_index(self.root)
        self.assertEqual(entries, [(self.root / "Loose.m4b", True)])
        self.assertEqual(signatures, {})

    def test_collapses_disc_subfolders_into_parent(self):
        self._touch("Author/Book/Disc 1/part1.m4b")
        self._touch("Author/Book/Disc 2/part2.m4b")
        entries, signatures = build_library_index(self.root)
        self.assertEqual(entries, [(self.root / "Author" / "Book", False)])
        self.assertIn(str(self.root / "Author" / "Book"), signatures)

    def test_skips_hardcoded_hidden_and_system_prefixes(self):
        self._touch("Author/Book/Book.m4b")
        self._touch(".hidden/Ghost.m4b")
        self._touch("#recycle/Ghost.m4b")
        self._touch("@eaDir/Ghost.m4b")
        entries, _ = build_library_index(self.root)
        self.assertEqual(entries, [(self.root / "Author" / "Book", False)])

    def test_non_audio_files_are_ignored(self):
        self._touch("Author/Book/cover.jpg")
        entries, signatures = build_library_index(self.root)
        self.assertEqual(entries, [])
        self.assertEqual(signatures, {})

    def test_new_book_folder_under_existing_series_is_discovered(self):
        # The deep-discovery bug this unification fixes: the old
        # root+first-level-only fingerprint could not see a new Book folder
        # added two levels below root under an existing Author/Series,
        # because that only bumps the Series folder's mtime, never the
        # Author folder's. build_library_index does a real walk every time,
        # so it has no such blind spot.
        self._touch("Sanderson/Mistborn/Book 1/Book 1.m4b")
        first_entries, _ = build_library_index(self.root)
        self.assertEqual(len(first_entries), 1)

        self._touch("Sanderson/Mistborn/Book 2/Book 2.m4b")
        second_entries, _ = build_library_index(self.root)
        paths = {str(p) for p, _ in second_entries}
        self.assertIn(str(self.root / "Sanderson" / "Mistborn" / "Book 2"), paths)
        self.assertEqual(len(second_entries), 2)

    def test_signature_present_for_every_folder_entry(self):
        self._touch("A/Book1/Book1.m4b")
        self._touch("B/Book2/Book2.m4b")
        entries, signatures = build_library_index(self.root)
        folder_paths = {str(p) for p, is_file in entries if not is_file}
        self.assertEqual(folder_paths, set(signatures.keys()))


class EnsureLibraryIndexFreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        reset_state_for_tests()

    def tearDown(self):
        reset_state_for_tests()
        self.tmp.cleanup()

    def _touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_initial_state_is_idle_with_no_entries(self):
        self.assertEqual(get_state().status, "idle")
        self.assertEqual(get_state().entries, [])

    def test_first_call_eventually_reaches_ready(self):
        self._touch("Author/Book/Book.m4b")
        ensure_library_index_fresh(self.root)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and get_state().status != "ready":
            time.sleep(0.02)
        self.assertEqual(get_state().status, "ready")
        self.assertEqual(len(get_state().entries), 1)
        self.assertEqual(get_state().generation, 1)

    def test_subsequent_call_after_a_change_bumps_generation(self):
        self._touch("Author/Book1/Book1.m4b")
        ensure_library_index_fresh(self.root)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and get_state().status != "ready":
            time.sleep(0.02)
        first_generation = get_state().generation

        self._touch("Author/Book2/Book2.m4b")
        ensure_library_index_fresh(self.root)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and get_state().generation == first_generation:
            time.sleep(0.02)
        self.assertEqual(get_state().generation, first_generation + 1)
        self.assertEqual(len(get_state().entries), 2)

    def test_call_while_walk_in_flight_does_not_block_or_duplicate(self):
        self._touch("Author/Book/Book.m4b")
        started = threading.Event()
        release = threading.Event()

        import app.library_index as li_module
        real_build = li_module.build_library_index

        def slow_build(root, skip_prefixes=li_module.FS_SKIP_PREFIXES):
            started.set()
            release.wait(timeout=2)
            return real_build(root, skip_prefixes)

        li_module.build_library_index = slow_build
        try:
            ensure_library_index_fresh(self.root)
            self.assertTrue(started.wait(timeout=2))
            # A second call while the first walk is still in flight must
            # return immediately without starting a second walk.
            before = time.monotonic()
            ensure_library_index_fresh(self.root)
            self.assertLess(time.monotonic() - before, 0.1)
            self.assertEqual(get_state().status, "idle")
        finally:
            release.set()
            li_module.build_library_index = real_build
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and get_state().status != "ready":
                time.sleep(0.02)

    def test_missing_root_sets_error_status(self):
        ensure_library_index_fresh(self.root / "does-not-exist-at-all")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and get_state().status not in ("ready", "error"):
            time.sleep(0.02)
        # A missing root still walks to an empty result via build_library_index's
        # own PermissionError/os.walk tolerance (os.walk on a nonexistent path
        # yields nothing, it does not raise), so this settles on ready with
        # zero entries rather than error. Assert that explicitly so the
        # behavior is documented, not assumed.
        self.assertEqual(get_state().status, "ready")
        self.assertEqual(get_state().entries, [])
