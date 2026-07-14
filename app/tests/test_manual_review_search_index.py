"""Tests for the Manual Review filesystem search index: the shared-walker
backed entry filter, and the staleness/rebuild logic layered on top of it."""
import tempfile
import unittest
from pathlib import Path

from app.main import (
    _ManualReviewSearchIndex,
    _ensure_manual_review_search_index_fresh,
    _filter_entries_by_ignored_folders,
    _ignored_signature,
    _manual_review_search_index_is_stale,
    _run_manual_review_search_index_build,
)
import app.library_index as library_index


class IgnoredSignatureTests(unittest.TestCase):
    def test_empty_list_is_empty_signature(self):
        self.assertEqual(_ignored_signature([]), "")

    def test_order_independent(self):
        self.assertEqual(_ignored_signature(["b", "a"]), _ignored_signature(["a", "b"]))

    def test_case_and_whitespace_independent(self):
        self.assertEqual(_ignored_signature([" Recycle "]), _ignored_signature(["recycle"]))

    def test_blank_entries_dropped(self):
        self.assertEqual(_ignored_signature(["a", "", "  "]), _ignored_signature(["a"]))

    def test_different_tokens_differ(self):
        self.assertNotEqual(_ignored_signature(["a"]), _ignored_signature(["b"]))


class FilterEntriesByIgnoredFoldersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_tokens_returns_all_entries_unchanged(self):
        entries = [(str(self.root / "Author" / "Book"), False)]
        self.assertEqual(_filter_entries_by_ignored_folders(entries, self.root, []), entries)

    def test_drops_folder_whose_own_name_matches(self):
        entries = [
            (str(self.root / "Author" / "Book"), False),
            (str(self.root / "temp-imports"), False),
        ]
        kept = _filter_entries_by_ignored_folders(entries, self.root, ["temp"])
        self.assertEqual(kept, [(str(self.root / "Author" / "Book"), False)])

    def test_drops_folder_whose_ancestor_matches_even_though_shared_walk_did_not_prune_it(self):
        # The shared walker has no concept of ignored_folders (only the
        # fixed skip prefixes), so a book folder nested inside an ignored
        # ancestor still appears in the raw entries list. The post-filter
        # must catch it by checking every path component, not just the
        # entry's own leaf name.
        entries = [(str(self.root / "temp-imports" / "Nested" / "Book"), False)]
        kept = _filter_entries_by_ignored_folders(entries, self.root, ["temp"])
        self.assertEqual(kept, [])

    def test_match_is_case_insensitive(self):
        entries = [(str(self.root / "TEMP-Imports" / "Ghost"), False)]
        kept = _filter_entries_by_ignored_folders(entries, self.root, ["temp"])
        self.assertEqual(kept, [])

    def test_loose_root_file_is_never_matched_by_a_token_that_is_not_its_own_name(self):
        entries = [(str(self.root / "temp-ish.m4b"), True)]
        # A loose root file's PARENT is root itself; "temp" only matches
        # directory components, and root has none between it and the file.
        kept = _filter_entries_by_ignored_folders(entries, self.root, ["temp"])
        self.assertEqual(kept, entries)


class ManualReviewSearchIndexIsStaleTests(unittest.TestCase):
    def test_never_built_is_stale(self):
        state = _ManualReviewSearchIndex()
        self.assertTrue(_manual_review_search_index_is_stale(state, 1, "sig1"))

    def test_ready_with_matching_generation_and_signature_is_fresh(self):
        state = _ManualReviewSearchIndex(status="ready", source_generation=1, ignored_signature="sig1")
        self.assertFalse(_manual_review_search_index_is_stale(state, 1, "sig1"))

    def test_ready_with_newer_shared_generation_is_stale(self):
        state = _ManualReviewSearchIndex(status="ready", source_generation=1, ignored_signature="sig1")
        self.assertTrue(_manual_review_search_index_is_stale(state, 2, "sig1"))

    def test_ready_with_changed_ignore_signature_is_stale(self):
        state = _ManualReviewSearchIndex(status="ready", source_generation=1, ignored_signature="sig1")
        self.assertTrue(_manual_review_search_index_is_stale(state, 1, "sig2"))

    def test_error_state_is_stale_so_it_can_retry(self):
        state = _ManualReviewSearchIndex(status="error", source_generation=1, ignored_signature="sig1")
        self.assertTrue(_manual_review_search_index_is_stale(state, 1, "sig1"))

    def test_externally_seeded_ready_state_with_sentinel_generation_is_trusted(self):
        # A caller that sets status="ready" directly (bypassing
        # _run_manual_review_search_index_build, e.g. a test fixture) has no
        # way to predict or set the live shared generation. source_generation
        # stays at its -1 default in that case, which real builds never
        # produce (they always record a real non-negative generation), so
        # this combination is trusted rather than force-rebuilt against a
        # generation number the caller could never have matched.
        state = _ManualReviewSearchIndex(status="ready", source_generation=-1, ignored_signature="")
        self.assertFalse(_manual_review_search_index_is_stale(state, 7, ""))

    def test_externally_seeded_ready_state_still_honors_ignore_signature_change(self):
        state = _ManualReviewSearchIndex(status="ready", source_generation=-1, ignored_signature="")
        self.assertTrue(_manual_review_search_index_is_stale(state, 7, "temp"))


class RunManualReviewSearchIndexBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        library_index.reset_state_for_tests()

    def tearDown(self):
        library_index.reset_state_for_tests()
        self.tmp.cleanup()

    def _touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_build_reads_from_shared_index_and_reaches_ready(self):
        self._touch("Author/Book/Book.m4b")
        shared_entries, _ = library_index.build_library_index(self.root)
        library_index._state = library_index.LibraryIndexState(
            status="ready",
            entries=[(str(p), f) for p, f in shared_entries],
            signatures={},
            generation=1,
        )
        state = _ManualReviewSearchIndex()
        _run_manual_review_search_index_build(state, self.root, [])
        self.assertEqual(state.status, "ready")
        self.assertEqual(state.book_count, 1)
        self.assertEqual(state.source_generation, 1)
        self.assertEqual(state.ignored_signature, "")

    def test_rebuild_replaces_entries_from_current_shared_state(self):
        self._touch("Author/NewBook/NewBook.m4b")
        shared_entries, _ = library_index.build_library_index(self.root)
        library_index._state = library_index.LibraryIndexState(
            status="ready",
            entries=[(str(p), f) for p, f in shared_entries],
            signatures={},
            generation=1,
        )
        state = _ManualReviewSearchIndex(status="ready", entries=[("/stale/path", False)], book_count=1)
        _run_manual_review_search_index_build(state, self.root, [])
        self.assertNotIn(("/stale/path", False), state.entries)


class EnsureManualReviewSearchIndexFreshEndToEndTests(unittest.TestCase):
    """The deep-discovery staleness fix, exercised end to end through the
    public trigger function (not just the shared walker in isolation)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        library_index.reset_state_for_tests()

    def tearDown(self):
        library_index.reset_state_for_tests()
        self.tmp.cleanup()

    def _touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_new_book_under_existing_series_is_found_without_manual_intervention(self):
        import time
        import app.main as main_module

        orig_root = main_module.AUDIOBOOKS_ROOT
        orig_state = main_module._manual_review_search_index
        main_module.AUDIOBOOKS_ROOT = self.root
        main_module._manual_review_search_index = _ManualReviewSearchIndex()
        try:
            self._touch("Sanderson/Mistborn/Book 1/Book 1.m4b")
            # Mirrors real usage: the status/search endpoints call
            # _ensure_manual_review_search_index_fresh on every request, so a
            # polling client re-triggers it each time it checks in. A single
            # trigger is not enough to guarantee freshness here: the shared
            # walker's own background build (also non-blocking) can still be
            # in flight when this derive step runs off whatever shared
            # generation is currently available, so convergence to the true
            # count takes a couple of poll cycles, exactly like a real client
            # polling the endpoint would experience.
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and main_module._manual_review_search_index.book_count != 1:
                _ensure_manual_review_search_index_fresh([])
                time.sleep(0.02)
            self.assertEqual(main_module._manual_review_search_index.book_count, 1)

            self._touch("Sanderson/Mistborn/Book 2/Book 2.m4b")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and main_module._manual_review_search_index.book_count != 2:
                _ensure_manual_review_search_index_fresh([])
                time.sleep(0.02)
            self.assertEqual(main_module._manual_review_search_index.book_count, 2)
        finally:
            main_module.AUDIOBOOKS_ROOT = orig_root
            main_module._manual_review_search_index = orig_state
