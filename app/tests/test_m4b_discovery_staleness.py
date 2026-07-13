"""Staleness tests for M4B discovery: prove that a file change inside an
already-cached book folder is picked up on the next call, and that the
nothing-changed fast path does not skip a real change."""
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app.library_index as library_index
import app.main as main_module
from app.conversion_cache import CACHE_VERSION
from app.main import discover_m4b_candidates


def _ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


class M4BDiscoveryStalenessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._orig_root = main_module.AUDIOBOOKS_ROOT
        main_module.AUDIOBOOKS_ROOT = self.root
        self._orig_cache = main_module.M4B_DISCOVERY_CACHE
        main_module.M4B_DISCOVERY_CACHE = self.root / "m4b-discovery-cache.json"
        library_index.reset_state_for_tests()

    def tearDown(self):
        main_module.AUDIOBOOKS_ROOT = self._orig_root
        main_module.M4B_DISCOVERY_CACHE = self._orig_cache
        library_index.reset_state_for_tests()
        self.tmp.cleanup()

    def _touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def _settle_shared_index(self):
        """Wait for a fresh background library-index walk to finish and
        bump the shared generation past whatever it is right now.

        ensure_library_index_fresh is deliberately non-blocking (see
        library_index.py: "the correction from THIS trigger lands on the
        next call after the background walk finishes"), so two
        discover_m4b_candidates calls issued back-to-back with zero
        elapsed time between them can race the shared index's own
        background walk. Polling on status == "ready" is not sufficient
        here: _run_build reassigns _state to a new ready LibraryIndexState
        only once the walk completes, with no intermediate "building"
        status, so status can already read "ready" (from the previous
        walk) for the entire duration of a newly triggered walk. Polling
        for the generation counter to advance (the same pattern
        test_library_index.py's EnsureLibraryIndexFreshTests uses) is what
        actually detects that THIS trigger's walk has finished. This
        mimics the real wall-clock time that always separates two actual
        user actions, so these tests exercise the steady-state behavior
        discover_m4b_candidates is actually meant to provide rather than a
        sub-millisecond race that would not occur outside of two calls
        issued from the same Python statement.
        """
        starting_generation = library_index.get_state().generation
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            # Retried every iteration rather than once: if the shared lock
            # is momentarily held by an unrelated walk from another test's
            # root (a daemon thread outliving the test that started it),
            # the first trigger here is a silent no-op, so retrying is
            # what actually gets a walk scheduled for self.root once the
            # lock frees up.
            library_index.ensure_library_index_fresh(self.root)
            if library_index.get_state().generation > starting_generation:
                return
            time.sleep(0.005)
        raise AssertionError("shared library index did not settle in time")

    @unittest.skipUnless(_ffprobe_available(), "ffprobe not available on this runner")
    def test_new_non_m4b_file_added_to_an_already_cached_folder_is_detected(self):
        self._touch("Author/Book/Book.mp3")
        first = discover_m4b_candidates(path=str(self.root), mode="non_m4b", cache_action="refresh")
        self.assertEqual(first["total"], 1)
        self.assertEqual(first["items"][0]["file_count"], 1)

        # Add a second non-m4b file inside the SAME already-cached book
        # folder. Two same-extension audio files sharing a folder are
        # picked up by the fixer's multipart grouping (mp3 has no chapter
        # metadata to validate, so the group is always accepted), so the
        # existing item's file_count rises from 1 to 2 rather than the
        # item count rising from 1 to 2 -- verified directly against
        # app.main.discover_m4b_candidates before writing this assertion.
        # The old M4B path always fully re-walked so this was never
        # actually stale before; this test documents that the new
        # signature-gated fast path does not regress that: the new file
        # is reflected on the very next call, not silently missed.
        #
        # Settle AFTER touching, not before: discover_m4b_candidates's own
        # fast-path check triggers its own walk and reads get_state()
        # immediately after, which can only ever observe a walk that
        # completed strictly before this call started (see
        # _settle_shared_index's docstring). Settling before the touch
        # would only confirm the shared index caught up with the OLD
        # filesystem state, not the new file being added here.
        self._touch("Author/Book/Book Part 2.mp3")
        self._settle_shared_index()
        second = discover_m4b_candidates(path=str(self.root), mode="non_m4b", cache_action="refresh")
        self.assertEqual(second["total"], 1)
        self.assertEqual(second["items"][0]["file_count"], 2)

    @unittest.skipUnless(_ffprobe_available(), "ffprobe not available on this runner")
    def test_nothing_changed_fast_path_still_returns_correct_results(self):
        # Targets the Author/Book subfolder rather than self.root: browsing
        # AUDIOBOOKS_ROOT itself resolves its signature scope to
        # AUDIOBOOKS_ROOT (see _m4b_folder_signature_scope), which
        # _m4b_cached_search_is_still_fresh now always treats as a miss
        # (loose files living directly in AUDIOBOOKS_ROOT never get a
        # signature anywhere in the shared index, so trusting that
        # comparison could report "nothing changed" forever even when a
        # loose root file changes -- see
        # test_scope_resolving_to_audiobooks_root_is_always_a_miss and
        # test_loose_root_file_target_detects_sibling_change_at_root). A
        # real subfolder target is unaffected by that root-only carve-out
        # and still gets the fast-path speedup this test verifies.
        book_folder = self.root / "Author" / "Book"
        self._touch("Author/Book/Book.mp3")
        first = discover_m4b_candidates(path=str(book_folder), mode="non_m4b", cache_action="refresh")
        self._settle_shared_index()
        second = discover_m4b_candidates(path=str(book_folder), mode="non_m4b", cache_action="refresh")
        self.assertEqual(first["items"], second["items"])
        self.assertEqual(second["cache"]["source"], "cache")

    @unittest.skipUnless(_ffprobe_available(), "ffprobe not available on this runner")
    def test_folder_signatures_are_persisted_in_the_cache_file(self):
        self._touch("Author/Book/Book.mp3")
        discover_m4b_candidates(path=str(self.root), mode="non_m4b", cache_action="refresh")
        cache_data = json.loads(main_module.M4B_DISCOVERY_CACHE.read_text())
        entry = next(iter(cache_data["searches"].values()))
        self.assertIn("folder_signatures", entry)
        self.assertIn(str(self.root / "Author" / "Book"), entry["folder_signatures"])

    @unittest.skipUnless(_ffprobe_available(), "ffprobe not available on this runner")
    def test_file_target_path_scopes_signature_to_parent_folder_not_the_file(self):
        # discover_m4b_candidates accepts a single audio file as the
        # target_path (fixer_processing_context has a dedicated branch for
        # this, grouping it with its siblings). The shared library index
        # only carries signatures for folders, never individual files, so
        # naively filtering folder_signatures by "under target_path" when
        # target_path is itself a file always yields an empty dict on
        # both sides of the freshness comparison -- trivially "unchanged"
        # forever, even when a sibling part file is added. This proves
        # the file-target case is scoped to the parent folder instead, so
        # it is not silently and permanently treated as fresh.
        book_file = self._touch("Author/Book/Book.mp3")
        first = discover_m4b_candidates(path=str(book_file), mode="non_m4b", cache_action="refresh")
        self.assertEqual(first["total"], 1)
        self.assertEqual(first["items"][0]["file_count"], 1)

        self._touch("Author/Book/Book Part 2.mp3")
        self._settle_shared_index()
        second = discover_m4b_candidates(path=str(book_file), mode="non_m4b", cache_action="refresh")
        self.assertEqual(second["cache"]["source"], "refresh")
        self.assertEqual(second["items"][0]["file_count"], 2)

    @unittest.skipUnless(_ffprobe_available(), "ffprobe not available on this runner")
    def test_loose_root_file_target_detects_sibling_change_at_root(self):
        # target_path here is a loose file sitting directly in
        # AUDIOBOOKS_ROOT (not inside any Author/Book subfolder), a real,
        # UI-reachable browse mode. _m4b_folder_signature_scope resolves
        # this to target_path.parent == AUDIOBOOKS_ROOT, and
        # library_index.build_library_index never assigns a signature to
        # AUDIOBOOKS_ROOT or to loose root files (see its own docstring:
        # "Loose root files have no signature entry"). Without forcing a
        # miss for this scope, _m4b_folder_signatures_under would return
        # {} on both sides of the freshness comparison no matter what
        # changes among the loose root files, so a sibling being added
        # would be silently and permanently missed -- reproducing the
        # exact "reports fresh forever" bug the folder-scoped fast path
        # was meant to eliminate. This proves the second call still does
        # a full walk (source == "refresh") and reflects the new sibling.
        root_file = self._touch("Book.mp3")
        first = discover_m4b_candidates(path=str(root_file), mode="non_m4b", cache_action="refresh")
        self.assertEqual(first["items"][0]["file_count"], 1)

        self._touch("Book Part 2.mp3")
        self._settle_shared_index()
        second = discover_m4b_candidates(path=str(root_file), mode="non_m4b", cache_action="refresh")
        self.assertEqual(second["cache"]["source"], "refresh")
        self.assertEqual(second["items"][0]["file_count"], 2)

    @unittest.skipUnless(_ffprobe_available(), "ffprobe not available on this runner")
    def test_new_book_folder_under_existing_series_is_found_on_next_refresh(self):
        self._touch("Sanderson/Mistborn/Book 1/Book1.mp3")
        first = discover_m4b_candidates(path=str(self.root), mode="non_m4b", cache_action="refresh")
        self.assertEqual(first["total"], 1)

        # Settle AFTER touching, not before -- see the comment in
        # test_new_non_m4b_file_added_to_an_already_cached_folder_is_detected
        # for why the ordering matters here.
        self._touch("Sanderson/Mistborn/Book 2/Book2.mp3")
        self._settle_shared_index()
        second = discover_m4b_candidates(path=str(self.root), mode="non_m4b", cache_action="refresh")
        self.assertEqual(second["total"], 2)

    def test_pre_migration_version_cache_is_discarded_wholesale_not_partially_trusted(self):
        # A cache file written before CACHE_VERSION 3 (no folder_signatures
        # on any entry) is discarded in full by load_discovery_cache's
        # existing version-mismatch check, so _m4b_cached_search_is_still_fresh
        # never runs against it -- this is the actual migration-safety
        # mechanism, verified here at the load_discovery_cache boundary.
        main_module.M4B_DISCOVERY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        main_module.M4B_DISCOVERY_CACHE.write_text(json.dumps({
            "version": 2,
            "searches": {"somekey": {"path": str(self.root), "results": {}}},
        }))
        loaded = main_module.load_discovery_cache(main_module.M4B_DISCOVERY_CACHE)
        self.assertEqual(loaded["searches"], {})
        self.assertEqual(loaded["version"], CACHE_VERSION)


class M4BCachedSearchFreshnessTests(unittest.TestCase):
    """Direct unit tests for _m4b_cached_search_is_still_fresh's defensive
    handling of a malformed or missing folder_signatures field, isolated
    from the full discover_m4b_candidates flow."""

    def test_missing_folder_signatures_key_is_a_miss_not_a_crash(self):
        shared = library_index.LibraryIndexState(signatures={"/audiobooks/A": "sig1"})
        cached_search = {"path": "/audiobooks", "results": {}}  # no folder_signatures key
        fresh = main_module._m4b_cached_search_is_still_fresh(
            cached_search, Path("/audiobooks"), shared,
        )
        self.assertFalse(fresh)

    def test_folder_signatures_present_and_matching_is_fresh(self):
        # Uses "/audiobooks/A" rather than "/audiobooks" as target_path: the
        # latter resolves its signature scope to AUDIOBOOKS_ROOT itself
        # (default main_module.AUDIOBOOKS_ROOT, unpatched in this test
        # class), which _m4b_cached_search_is_still_fresh now always treats
        # as a miss regardless of matching signatures -- see
        # test_scope_resolving_to_audiobooks_root_is_always_a_miss. A real
        # subfolder target is unaffected by that root-only carve-out, so it
        # is what actually exercises the "signatures present and matching"
        # code path this test is about.
        shared = library_index.LibraryIndexState(signatures={"/audiobooks/A": "sig1"})
        cached_search = {
            "path": "/audiobooks/A",
            "folder_signatures": {"/audiobooks/A": "sig1"},
            "results": {},
        }
        fresh = main_module._m4b_cached_search_is_still_fresh(
            cached_search, Path("/audiobooks/A"), shared,
        )
        self.assertTrue(fresh)

    def test_folder_signatures_present_but_changed_is_a_miss(self):
        shared = library_index.LibraryIndexState(signatures={"/audiobooks/A": "sig2"})
        cached_search = {
            "path": "/audiobooks",
            "folder_signatures": {"/audiobooks/A": "sig1"},
            "results": {},
        }
        fresh = main_module._m4b_cached_search_is_still_fresh(
            cached_search, Path("/audiobooks"), shared,
        )
        self.assertFalse(fresh)

    def test_new_folder_not_in_cached_signatures_is_a_miss(self):
        shared = library_index.LibraryIndexState(
            signatures={"/audiobooks/A": "sig1", "/audiobooks/B": "sig1"}
        )
        cached_search = {
            "path": "/audiobooks",
            "folder_signatures": {"/audiobooks/A": "sig1"},
            "results": {},
        }
        fresh = main_module._m4b_cached_search_is_still_fresh(
            cached_search, Path("/audiobooks"), shared,
        )
        self.assertFalse(fresh)

    def test_file_target_path_is_scoped_to_its_parent_folder(self):
        # target_path.is_file() must be checked against a real path (Path
        # objects that don't exist on disk report is_file() == False), so
        # this uses a real temp file rather than the fabricated
        # /audiobooks paths the other tests in this class use.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            book_folder = root / "Author" / "Book"
            book_folder.mkdir(parents=True)
            book_file = book_folder / "Book.mp3"
            book_file.write_bytes(b"x")

            shared = library_index.LibraryIndexState(signatures={str(book_folder): "sig1"})
            cached_search = {
                "path": str(book_file),
                "folder_signatures": {str(book_folder): "sig1"},
                "results": {},
            }
            fresh = main_module._m4b_cached_search_is_still_fresh(
                cached_search, book_file, shared,
            )
            self.assertTrue(fresh)

            shared_changed = library_index.LibraryIndexState(
                signatures={str(book_folder): "sig2"}
            )
            fresh_after_change = main_module._m4b_cached_search_is_still_fresh(
                cached_search, book_file, shared_changed,
            )
            self.assertFalse(fresh_after_change)

    def test_scope_resolving_to_audiobooks_root_is_always_a_miss(self):
        # Loose root files (and AUDIOBOOKS_ROOT itself) never get a
        # signature entry in the shared library index (see
        # library_index.py's own docstring: "Loose root files have no
        # signature entry"), so _m4b_folder_signatures_under always
        # returns {} for this scope regardless of what actually changed
        # among the loose root files. Trusting an empty-vs-empty
        # comparison here would report "nothing changed" forever; this
        # proves the freshness check is forced to miss instead whenever
        # the resolved scope is AUDIOBOOKS_ROOT itself, whether target_path
        # IS AUDIOBOOKS_ROOT or is a loose file sitting directly in it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            orig_root = main_module.AUDIOBOOKS_ROOT
            main_module.AUDIOBOOKS_ROOT = root
            try:
                shared = library_index.LibraryIndexState(signatures={})
                cached_search = {
                    "path": str(root),
                    "folder_signatures": {},
                    "results": {},
                }
                self.assertFalse(
                    main_module._m4b_cached_search_is_still_fresh(cached_search, root, shared)
                )

                loose_file = root / "Loose.mp3"
                loose_file.write_bytes(b"x")
                self.assertFalse(
                    main_module._m4b_cached_search_is_still_fresh(
                        cached_search, loose_file, shared
                    )
                )
            finally:
                main_module.AUDIOBOOKS_ROOT = orig_root
