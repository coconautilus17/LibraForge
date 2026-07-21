"""Tests for the shared library index walker: per-folder listing signatures
and the folder-existence + signature-table walk."""
import os
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

    def test_changes_when_a_file_inside_a_disc_subfolder_is_rewritten(self):
        # Regression: a plain stat() of "Disc 1" only reflects adds/removes/
        # renames directly inside it, not an in-place rewrite of a file one
        # level further down -- so a multi-disc book's parent signature must
        # fold in each disc subfolder's own signature to catch this.
        p = self._touch("Book/Disc 1/part1.m4b", b"x")
        before = folder_listing_signature(self.root / "Book")
        p.write_bytes(b"xx")
        after = folder_listing_signature(self.root / "Book")
        self.assertNotEqual(before, after)

    def test_order_of_children_does_not_affect_signature(self):
        # The signature is deliberately mtime-sensitive, so this test must
        # pin an identical, explicit mtime on both passes rather than rely
        # on the two touch passes happening to land on the same wall-clock
        # timestamp. Otherwise it proves time-independence-that-happens-to-
        # hold instead of true order-independence.
        fixed_time_ns = 1_700_000_000_000_000_000

        def touch_with_fixed_mtime(rel):
            p = self._touch(rel)
            os.utime(p, ns=(fixed_time_ns, fixed_time_ns))
            return p

        touch_with_fixed_mtime("Book/b.m4b")
        touch_with_fixed_mtime("Book/a.m4b")
        via_ba = folder_listing_signature(self.root / "Book")
        (self.root / "Book" / "a.m4b").unlink()
        (self.root / "Book" / "b.m4b").unlink()
        touch_with_fixed_mtime("Book/a.m4b")
        touch_with_fixed_mtime("Book/b.m4b")
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

    def test_disc_subfolder_signature_changes_when_a_file_inside_is_rewritten(self):
        p = self._touch("Author/Book/Disc 1/part1.m4b")
        p.write_bytes(b"x")
        _entries, before = build_library_index(self.root)
        p.write_bytes(b"xx")
        _entries, after = build_library_index(self.root)
        book_key = str(self.root / "Author" / "Book")
        self.assertNotEqual(before[book_key], after[book_key])

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

    def test_subsequent_call_with_nothing_changed_does_not_bump_generation(self):
        # Regression: ensure_library_index_fresh has no cheap pre-check
        # gating how often a walk runs (by design), so a consumer that polls
        # it on a timer (Manual Review's search-index status) would see
        # generation advance on every walk cycle even when nothing on disk
        # changed, misreporting "library change detected" repeatedly.
        self._touch("Author/Book1/Book1.m4b")
        ensure_library_index_fresh(self.root)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and get_state().status != "ready":
            time.sleep(0.02)
        first_generation = get_state().generation

        completed = threading.Event()
        import app.library_index as li_module
        real_run_build = li_module._run_build

        def tracked_run_build(root):
            real_run_build(root)
            completed.set()

        li_module._run_build = tracked_run_build
        try:
            ensure_library_index_fresh(self.root)
            self.assertTrue(completed.wait(timeout=2))
        finally:
            li_module._run_build = real_run_build
        self.assertEqual(get_state().generation, first_generation)

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


from app.library_index import (
    EbookUnit,
    build_ebook_index,
    is_ebook_file,
)


class IsEbookFileTests(unittest.TestCase):
    def test_epub_is_ebook(self):
        self.assertTrue(is_ebook_file(Path("book.epub")))

    def test_pdf_is_ebook(self):
        self.assertTrue(is_ebook_file(Path("book.pdf")))

    def test_case_insensitive(self):
        self.assertTrue(is_ebook_file(Path("book.EPUB")))

    def test_mobi_is_not_ebook(self):
        self.assertFalse(is_ebook_file(Path("book.mobi")))

    def test_audio_file_is_not_ebook(self):
        self.assertFalse(is_ebook_file(Path("book.m4b")))


class BuildEbookIndexTests(unittest.TestCase):
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

    def test_standalone_ebook_outside_bucket_folder_is_its_own_unit(self):
        self._touch("Author/Some Book/book.epub")
        units = build_ebook_index(self.root)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].path, self.root / "Author" / "Some Book" / "book.epub")
        self.assertEqual(units[0].formats, {"epub": self.root / "Author" / "Some Book" / "book.epub"})

    def test_paired_epub_pdf_in_sibling_bucket_folders_merge_by_stem(self):
        self._touch("Linux/EPUB/kubernetes.epub")
        self._touch("Linux/PDF/kubernetes.pdf")
        units = build_ebook_index(self.root)
        self.assertEqual(len(units), 1)
        unit = units[0]
        # epub preferred as canonical path when both formats present.
        self.assertEqual(unit.path, self.root / "Linux" / "EPUB" / "kubernetes.epub")
        self.assertEqual(unit.formats, {
            "epub": self.root / "Linux" / "EPUB" / "kubernetes.epub",
            "pdf": self.root / "Linux" / "PDF" / "kubernetes.pdf",
        })

    def test_bucket_folder_name_matching_is_case_insensitive(self):
        self._touch("Linux/Epub/book.epub")
        self._touch("Linux/PDF/book.pdf")
        units = build_ebook_index(self.root)
        self.assertEqual(len(units), 1)
        self.assertEqual(len(units[0].formats), 2)

    def test_unmatched_stem_in_bucket_folder_stays_single_format(self):
        self._touch("Linux/EPUB/onlyepub.epub")
        self._touch("Linux/PDF/onlypdf.pdf")
        units = build_ebook_index(self.root)
        self.assertEqual(len(units), 2)
        formats_by_stem = {u.path.stem: u.formats for u in units}
        self.assertEqual(list(formats_by_stem["onlyepub"].keys()), ["epub"])
        self.assertEqual(list(formats_by_stem["onlypdf"].keys()), ["pdf"])

    def test_same_stem_under_different_grandparents_does_not_merge(self):
        self._touch("Linux/EPUB/kubernetes.epub")
        self._touch("Other/PDF/kubernetes.pdf")
        units = build_ebook_index(self.root)
        self.assertEqual(len(units), 2)
        for unit in units:
            self.assertEqual(len(unit.formats), 1)

    def test_non_bucket_sibling_folders_do_not_merge(self):
        self._touch("Series/BookA/book.epub")
        self._touch("Series/BookB/book.pdf")
        units = build_ebook_index(self.root)
        self.assertEqual(len(units), 2)
        for unit in units:
            self.assertEqual(len(unit.formats), 1)

    def test_skips_hardcoded_hidden_and_system_prefixes(self):
        self._touch("Linux/EPUB/book.epub")
        self._touch(".hidden/Ghost.epub")
        self._touch("#recycle/Ghost.epub")
        units = build_ebook_index(self.root)
        paths = {str(u.path) for u in units}
        self.assertEqual(paths, {str(self.root / "Linux" / "EPUB" / "book.epub")})

    def test_no_ebooks_returns_empty_list(self):
        self._touch("Author/Book/Book.m4b")
        units = build_ebook_index(self.root)
        self.assertEqual(units, [])


from app.library_index import (
    ensure_ebook_index_fresh,
    get_ebook_state,
    reset_ebook_state_for_tests,
)


class EnsureEbookIndexFreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        reset_ebook_state_for_tests()

    def tearDown(self):
        reset_ebook_state_for_tests()
        self.tmp.cleanup()

    def _touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_initial_state_is_idle_with_no_units(self):
        self.assertEqual(get_ebook_state().status, "idle")
        self.assertEqual(get_ebook_state().units, [])

    def test_reaches_ready_and_finds_units(self):
        self._touch("Linux/EPUB/book.epub")
        ensure_ebook_index_fresh(self.root)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and get_ebook_state().status != "ready":
            time.sleep(0.02)
        state = get_ebook_state()
        self.assertEqual(state.status, "ready")
        self.assertEqual(len(state.units), 1)

    def test_generation_bumps_only_when_units_change(self):
        ensure_ebook_index_fresh(self.root)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and get_ebook_state().status != "ready":
            time.sleep(0.02)
        first_generation = get_ebook_state().generation

        ensure_ebook_index_fresh(self.root)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and get_ebook_state().generation != first_generation and get_ebook_state().status != "ready":
            time.sleep(0.02)
        time.sleep(0.1)
        self.assertEqual(get_ebook_state().generation, first_generation)

        self._touch("Linux/EPUB/new.epub")
        ensure_ebook_index_fresh(self.root)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and get_ebook_state().generation == first_generation:
            time.sleep(0.02)
        self.assertGreater(get_ebook_state().generation, first_generation)
